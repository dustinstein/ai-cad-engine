"""Centerlines and DIMENSION entities.

Dimension defpoints are snapped to features found in the projected geometry
by *role* (largest circle, off-axis circles, view extents, full-width faces),
never to table values. The DXF DIMENSION therefore reports what was actually
drawn, and tests compare those measurements against the standard.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, hypot, radians, sin

import ezdxf.document

from ai_cad_engine.drawing.dxf_writer import PlacedView
from ai_cad_engine.drawing.views import TOL, Circle, Line, View

DIMSTYLE = "ENGINE_MM"
# Centerline at 1:1 mm: long 12, gap 3, short 3, gap 3.
CENTER_PATTERN = (21.0, 12.0, -3.0, 3.0, -3.0)
CL_OVERSHOOT = 6.0  # centerline extension past the feature, mm


def setup(doc: ezdxf.document.Drawing) -> None:
    doc.linetypes.add("CENTER_MM", pattern=list(CENTER_PATTERN), description="Center ____ _ ____")
    doc.layers.add("CENTER", color=1, linetype="CENTER_MM", lineweight=25)
    doc.layers.add("DIM", color=3, lineweight=25)
    # Own style: ezdxf's EZ_* styles are scaled for other units (e.g. EZ_RADIUS shows 20 mm as 2000).
    style = doc.dimstyles.new(DIMSTYLE)
    style.dxf.dimtxt = 3.5  # text height
    style.dxf.dimasz = 3.0  # arrow size
    style.dxf.dimexo = 1.5  # extension line offset from geometry
    style.dxf.dimexe = 2.0  # extension past dimension line
    style.dxf.dimgap = 1.0
    style.dxf.dimdec = 2
    style.dxf.dimzin = 0  # keep trailing zeros; checking to 0.01 mm
    style.dxf.dimlfac = 1.0
    style.dxf.dimtad = 1  # text above dimension line
    style.dxf.dimtih = 1  # horizontal text inside (ASME unidirectional)
    style.dxf.dimtoh = 1  # horizontal text outside
    style.dxf.dimtofl = 0  # diameter dims with text outside: leader only, no line through center
    style.dxf.dimdsep = ord(".")
    style.dxf.dimblk = ""  # closed filled arrows


# ---- feature finding (by role) -------------------------------------------------


@dataclass(frozen=True)
class BoltPattern:
    center: tuple[float, float]
    od_radius: float
    hole_radius: float
    hole_centers: list[tuple[float, float]]
    bc_radius: float


def find_bolt_pattern(view: View) -> BoltPattern:
    circles = [p for p in view.visible if isinstance(p, Circle)]
    od = max(circles, key=lambda c: c.radius)
    cx, cy = od.center
    holes = [c for c in circles if hypot(c.center[0] - cx, c.center[1] - cy) > TOL]
    radii = {round(c.radius, 4) for c in holes}
    if len(radii) != 1:
        raise ValueError(f"expected one off-axis hole size, found radii {sorted(radii)}")
    dists = [hypot(c.center[0] - cx, c.center[1] - cy) for c in holes]
    if max(dists) - min(dists) > TOL:
        raise ValueError(f"hole centers not on one circle: {min(dists)}..{max(dists)}")
    return BoltPattern(
        center=od.center,
        od_radius=od.radius,
        hole_radius=holes[0].radius,
        hole_centers=[c.center for c in holes],
        bc_radius=sum(dists) / len(dists),
    )


@dataclass(frozen=True)
class AxialProfile:
    axis_x: float
    y_min: float
    y_max: float
    bottom_pt: tuple[float, float]  # leftmost point on the contact face (y_min)
    top_pt: tuple[float, float]  # leftmost point on the far end (y_max)
    back_face_pt: tuple[float, float]  # leftmost point on the flange back face


def find_axial_profile(view: View) -> AxialProfile:
    x0, y0, x1, y1 = view.bbox
    horiz = [
        ln for ln in view.visible if isinstance(ln, Line) and abs(ln.p1[1] - ln.p2[1]) < TOL
    ]

    def left(ln: Line) -> tuple[float, float]:
        return min(ln.p1, ln.p2)

    bottom = min((ln for ln in horiz if abs(ln.p1[1] - y0) < TOL), key=lambda ln: left(ln)[0])
    top = min((ln for ln in horiz if abs(ln.p1[1] - y1) < TOL), key=lambda ln: left(ln)[0])
    full = [ln for ln in horiz if abs(abs(ln.p2[0] - ln.p1[0]) - (x1 - x0)) < TOL]
    if not full:
        raise ValueError("no full-width face found for flange thickness")
    back = max(full, key=lambda ln: ln.p1[1])
    return AxialProfile(
        axis_x=(x0 + x1) / 2,
        y_min=y0,
        y_max=y1,
        bottom_pt=left(bottom),
        top_pt=left(top),
        back_face_pt=left(back),
    )


# ---- annotation ----------------------------------------------------------------


def _off(pt: tuple[float, float], o: tuple[float, float]) -> tuple[float, float]:
    return (pt[0] + o[0], pt[1] + o[1])


def annotate_flange(doc: ezdxf.document.Drawing, placed: list[PlacedView]) -> None:
    setup(doc)
    msp = doc.modelspace()
    by_name = {pv.view.spec.name: pv for pv in placed}
    dim_attrs = {"layer": "DIM"}
    cl_attrs = {"layer": "CENTER"}

    # TOP: bolt pattern
    top = by_name["TOP"]
    bp = find_bolt_pattern(top.view)
    c = _off(bp.center, top.offset)
    ents = []
    ext = bp.od_radius + CL_OVERSHOOT
    ents.append(msp.add_line((c[0] - ext, c[1]), (c[0] + ext, c[1]), dxfattribs=cl_attrs))
    ents.append(msp.add_line((c[0], c[1] - ext), (c[0], c[1] + ext), dxfattribs=cl_attrs))
    ents.append(msp.add_circle(c, bp.bc_radius, dxfattribs=cl_attrs))
    for hc in bp.hole_centers:
        h = _off(hc, top.offset)
        ux, uy = (h[0] - c[0]) / bp.bc_radius, (h[1] - c[1]) / bp.bc_radius
        e = bp.hole_radius + CL_OVERSHOOT / 2
        ents.append(
            msp.add_line(
                (h[0] - ux * e, h[1] - uy * e), (h[0] + ux * e, h[1] + uy * e), dxfattribs=cl_attrs
            )
        )

    def dia(center, r, angle_deg, text, out):
        a = radians(angle_deg)
        loc = (center[0] + (r + out) * cos(a), center[1] + (r + out) * sin(a))
        d = msp.add_diameter_dim(
            center=center, radius=r, location=loc, text=text, dimstyle=DIMSTYLE, dxfattribs=dim_attrs
        )
        d.render()
        return d.dimension

    ents.append(dia(c, bp.od_radius, 135, "<>", 20))
    ents.append(dia(c, bp.bc_radius, 45, "<> B.C.", bp.od_radius - bp.bc_radius + 30))
    # Hole callout on the hole nearest 67.5 deg (upper right), leader pointing outward.
    h = max(bp.hole_centers, key=lambda p: p[1] + 0.4 * p[0])
    hs = _off(h, top.offset)
    ang = _deg(hs[0] - c[0], hs[1] - c[1])
    ents.append(
        dia(hs, bp.hole_radius, ang, f"{len(bp.hole_centers)}X <> THRU", bp.od_radius - bp.bc_radius + 12)
    )
    doc.groups.new("ANNOT_TOP").set_data(ents)

    # FRONT / RIGHT: axis centerline
    for name in ("FRONT", "RIGHT"):
        pv = by_name[name]
        prof = find_axial_profile(pv.view)
        x = prof.axis_x + pv.offset[0]
        ents = [
            msp.add_line(
                (x, prof.y_min + pv.offset[1] - CL_OVERSHOOT),
                (x, prof.y_max + pv.offset[1] + CL_OVERSHOOT),
                dxfattribs=cl_attrs,
            )
        ]
        if name == "FRONT":
            x0 = pv.view.bbox[0] + pv.offset[0]

            def vdim(p1, p2, dx):
                d = msp.add_linear_dim(
                    base=(x0 - dx, p1[1]),
                    p1=p1,
                    p2=p2,
                    angle=90,
                    dimstyle=DIMSTYLE,
                    dxfattribs=dim_attrs,
                )
                d.render()
                return d.dimension

            b = _off(prof.bottom_pt, pv.offset)
            ents.append(vdim(b, _off(prof.back_face_pt, pv.offset), 12))
            ents.append(vdim(b, _off(prof.top_pt, pv.offset), 26))
        doc.groups.new(f"ANNOT_{name}").set_data(ents)


def _deg(dx: float, dy: float) -> float:
    from math import atan2, degrees

    return degrees(atan2(dy, dx))
