"""Weld-neck flange drawing: half-section profile (FRONT) + face view (RIGHT).

Conventional flange layout: axis horizontal, raised face on the left, hub to the
right. FRONT is a half section (upper half cut, hidden lines omitted), rotated so
the cutting plane passes through a bolt hole: ASME Y14.3 aligned-section
convention of revolving features into the cutting plane. RIGHT is the face view
seen from the hub end, in true orientation.
"""

from __future__ import annotations

from dataclasses import dataclass

import ezdxf.document
from build123d import Axis, Solid

from ai_cad_engine.drawing.annotate import CL_OVERSHOOT, HALF_DIM, Annotator, Pt, find_bolt_pattern
from ai_cad_engine.drawing.dxf_writer import PlacedView
from ai_cad_engine.drawing.views import TOL, Line, View, ViewSpec, half_section_cutter, project, section
from ai_cad_engine.measure import z_axis_cylinders

# Model axis Z maps to view +x; model -X maps to view +y (section half on top).
PROFILE = ViewSpec("FRONT", (0, -1, 0), (-1, 0, 0))
FACE = ViewSpec("RIGHT", (0, 0, 1), (-1, 0, 0))

# Paper inches reserved around the view block: (left, bottom, right, top).
ALLOWANCE = (1.8, 1.7, 1.7, 0.9)
VIEW_GAP = 2.2  # between profile and face view; hub diameter dims live here

# Dimension line offsets from the view, paper inches.
NEAR, FAR = 0.5, 1.3  # FAR clears NEAR's horizontal text (~.7 in wide)
OD_LEADER_OUT, BC_LEADER_OUT, HOLE_LEADER_OUT = 0.5, 0.75, 0.4


def flange_views(part: Solid) -> dict[str, View]:
    holes = [c for c in z_axis_cylinders(part) if c.radial_pos > 1e-6]
    if not holes:
        raise ValueError("no bolt holes found")
    # Rotate so a measured hole sits at 180 deg (model -X) = on the section plane, upper half.
    rot = 180 - holes[0].angle_deg
    sectioned = part.rotate(Axis.Z, rot)
    size = 4 * max(part.bounding_box().size)
    return {
        "FRONT": section(sectioned, PROFILE, half_section_cutter(PROFILE, size)),
        "RIGHT": project(part, FACE),
    }


@dataclass(frozen=True)
class SectionProfile:
    """Features of the half-section profile, found by role (view coordinates)."""

    axis_y: float
    a_min: float  # raised face contact surface
    a_max: float  # weld end
    a_front: float  # flange front face (behind the raised face)
    a_back: float  # flange back face / hub base
    r_od: float
    r_rf: float
    r_bore: float
    r_hub_base: float
    r_hub_weld: float
    hole_y: float | None  # bolt hole axis in the section half


def find_section_profile(view: View) -> SectionProfile:
    x0, y0, x1, y1 = view.bbox
    ax = (y0 + y1) / 2
    lines = [p for p in view.visible if isinstance(p, Line)]
    vert = [ln for ln in lines if abs(ln.p1[0] - ln.p2[0]) < TOL]
    horiz = [ln for ln in lines if abs(ln.p1[1] - ln.p2[1]) < TOL]
    sloped = [ln for ln in lines if ln not in vert and ln not in horiz]

    def reach(ln: Line) -> float:
        return max(abs(ln.p1[1] - ax), abs(ln.p2[1] - ax))

    def at_x(x: float) -> list[Line]:
        return [ln for ln in vert if abs(ln.p1[0] - x) < TOL]

    r_rf = max(reach(ln) for ln in at_x(x0))
    r_hub_weld = max(reach(ln) for ln in at_x(x1))
    od_faces = sorted({round(ln.p1[0], 9) for ln in vert if abs(reach(ln) - (y1 - ax)) < TOL})
    if len(od_faces) != 2:
        raise ValueError(f"expected flange front/back faces reaching OD, found x={od_faces}")
    a_front, a_back = od_faces
    base_pts = [p for ln in sloped for p in (ln.p1, ln.p2) if abs(p[0] - a_back) < TOL]
    if not base_pts:
        raise ValueError("hub taper not found")
    r_hub_base = max(abs(p[1] - ax) for p in base_pts)
    bore = [
        ln
        for ln in horiz
        if ln.p1[1] > ax + TOL and abs(abs(ln.p2[0] - ln.p1[0]) - (x1 - x0)) < TOL
    ]
    if not bore:
        raise ValueError("bore line not found in section half")
    r_bore = min(ln.p1[1] for ln in bore) - ax
    walls = [
        ln.p1[1]
        for ln in horiz
        if ax + TOL < ln.p1[1] < y1 - TOL  # between axis and OD edge
        and {round(min(ln.p1[0], ln.p2[0]), 9), round(max(ln.p1[0], ln.p2[0]), 9)}
        == {round(a_front, 9), round(a_back, 9)}
    ]
    hole_y = sum(walls) / len(walls) if len(walls) == 2 else None
    return SectionProfile(ax, x0, x1, a_front, a_back, y1 - ax, r_rf, r_bore, r_hub_base, r_hub_weld, hole_y)


def annotate_flange(doc: ezdxf.document.Drawing, placed: list[PlacedView], scale: float) -> None:
    S = scale
    an = Annotator(doc, S)
    pv = {p.view.spec.name: p for p in placed}

    # ---- FRONT: half-section profile ----
    front = pv["FRONT"]
    sp = find_section_profile(front.view)
    ox, oy = front.offset

    def P(a: float, r: float) -> Pt:  # (axial, radial from axis) -> model space
        return (a + ox, sp.axis_y + r + oy)

    over = CL_OVERSHOOT * S
    an.centerline("FRONT", P(sp.a_min - over, 0), P(sp.a_max + over, 0))
    if sp.hole_y is not None:
        hy = sp.hole_y - sp.axis_y
        an.centerline("FRONT", P(sp.a_front - over, hy), P(sp.a_back + over, hy))

    bottom = sp.axis_y - sp.r_od + oy
    top = sp.axis_y + sp.r_od + oy
    left = sp.a_min + ox
    right = sp.a_max + ox
    # Axial lengths below the (exterior) lower half.
    an.linear("FRONT", "thickness", P(sp.a_min, -sp.r_rf), P(sp.a_back, -sp.r_od), (left, bottom - NEAR * S), 0)
    an.linear(
        "FRONT", "length_through_hub", P(sp.a_min, -sp.r_rf), P(sp.a_max, -sp.r_hub_weld), (left, bottom - FAR * S), 0
    )
    # Raised face height above the section half; too small for inside text, so text sits left.
    an.linear(
        "FRONT",
        "raised_face_height",
        P(sp.a_min, sp.r_rf),
        P(sp.a_front, sp.r_od),
        (left, top + NEAR * S),
        0,
        location=(left - 0.5 * S, top + NEAR * S),
    )
    # Diameters on the left: bore as a half dimension (only the section half shows it).
    an.linear(
        "FRONT",
        "bore",
        P(sp.a_min, sp.r_bore),
        P(sp.a_min, -sp.r_bore),
        (left - NEAR * S, 0),
        90,
        text="%%c<>",
        location=(left - NEAR * S, sp.axis_y + oy + sp.r_bore / 2),
        override=HALF_DIM,
    )
    an.linear("FRONT", "raised_face_dia", P(sp.a_min, sp.r_rf), P(sp.a_min, -sp.r_rf), (left - FAR * S, 0), 90, text="%%c<>")
    # Hub diameters on the right.
    an.linear("FRONT", "hub_dia_weld", P(sp.a_max, sp.r_hub_weld), P(sp.a_max, -sp.r_hub_weld), (right + NEAR * S, 0), 90, text="%%c<>")
    an.linear("FRONT", "hub_dia_base", P(sp.a_back, sp.r_hub_base), P(sp.a_back, -sp.r_hub_base), (right + FAR * S, 0), 90, text="%%c<>")

    # ---- RIGHT: face view ----
    face = pv["RIGHT"]
    bp = find_bolt_pattern(face.view)
    c = (bp.center[0] + face.offset[0], bp.center[1] + face.offset[1])
    ext = bp.od_radius + over
    an.centerline("RIGHT", (c[0] - ext, c[1]), (c[0] + ext, c[1]))
    an.centerline("RIGHT", (c[0], c[1] - ext), (c[0], c[1] + ext))
    an.circle_centerline("RIGHT", c, bp.bc_radius)
    for hc in bp.hole_centers:
        h = (hc[0] + face.offset[0], hc[1] + face.offset[1])
        ux, uy = (h[0] - c[0]) / bp.bc_radius, (h[1] - c[1]) / bp.bc_radius
        e = bp.hole_radius + over / 2
        an.centerline("RIGHT", (h[0] - ux * e, h[1] - uy * e), (h[0] + ux * e, h[1] + uy * e))

    an.diameter("RIGHT", "od", c, bp.od_radius, 135, OD_LEADER_OUT)
    an.diameter("RIGHT", "bolt_circle", c, bp.bc_radius, 45, bp_out(bp, BC_LEADER_OUT, S), text="<> B.C.")
    # Hole callout on the upper-right hole, leader pointing outward.
    from math import atan2, degrees

    hc = max(bp.hole_centers, key=lambda p: (p[1] - bp.center[1]) + 0.4 * (p[0] - bp.center[0]))
    h = (hc[0] + face.offset[0], hc[1] + face.offset[1])
    ang = degrees(atan2(h[1] - c[1], h[0] - c[0]))
    an.diameter(
        "RIGHT",
        "bolt_hole_dia",
        h,
        bp.hole_radius,
        ang,
        bp_out(bp, HOLE_LEADER_OUT, S),
        text=f"{len(bp.hole_centers)}X <> THRU",
        count_key="bolt_hole_count",
    )
    an.finish()


def bp_out(bp, paper_out: float, S: float) -> float:
    """Leader length (paper inches) that puts the text paper_out beyond the OD."""
    return (bp.od_radius - bp.bc_radius) / S + paper_out
