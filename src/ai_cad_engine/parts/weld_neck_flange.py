"""Weld-neck flange solid from an ASME B16.5 table entry.

Coordinate system (mm): axis = Z, raised-face contact surface at Z=0,
weld end at Z = +length_through_hub. Bolt holes straddle the X/Y centerlines.

Simplifications (v0): straight-taper hub (no hub-to-flange fillet r1, no weld
bevel), no RF serration.
"""

from build123d import (
    Align,
    BuildPart,
    Cone,
    Cylinder,
    Locations,
    Mode,
    PolarLocations,
    Solid,
)

from ai_cad_engine.measure import z_axis_cylinders, z_cones, z_planes
from ai_cad_engine.standards.asme_b16_5 import WeldNeckFlange
from ai_cad_engine.verify import CriticalDim

_BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)


def build_weld_neck_flange(f: WeldNeckFlange) -> Solid:
    rf_h = f.raised_face_height
    body_h = f.thickness - rf_h
    hub_h = f.length_through_hub - f.thickness

    with BuildPart() as part:
        # Raised face
        Cylinder(f.raised_face_dia / 2, rf_h, align=_BOTTOM)
        # Flange ring
        with Locations((0, 0, rf_h)):
            Cylinder(f.od / 2, body_h, align=_BOTTOM)
        # Tapered hub
        with Locations((0, 0, f.thickness)):
            Cone(f.hub_dia_base / 2, f.hub_dia_weld / 2, hub_h, align=_BOTTOM)
        # Bore
        Cylinder(
            f.bore / 2, f.length_through_hub, align=_BOTTOM, mode=Mode.SUBTRACT
        )
        # Bolt holes, offset half a pitch so they straddle the centerlines
        pitch = 360 / f.bolt_hole_count
        with PolarLocations(
            f.bolt_circle_dia / 2, f.bolt_hole_count, start_angle=pitch / 2
        ):
            Cylinder(f.bolt_hole_dia / 2, f.thickness, align=_BOTTOM, mode=Mode.SUBTRACT)

    return part.part


def critical_dims(f: WeldNeckFlange) -> list[CriticalDim]:
    """Must-verify dimensions; nominals straight from the standards table."""
    return [
        CriticalDim("od", "Flange outside diameter (O)", f.od),
        CriticalDim("bolt_circle", "Bolt circle diameter (W)", f.bolt_circle_dia),
        CriticalDim("bolt_hole_dia", "Bolt hole diameter", f.bolt_hole_dia),
        CriticalDim("bolt_hole_count", "Number of bolt holes", f.bolt_hole_count, "count"),
        CriticalDim(
            "bolt_hole_offset",
            "Bolt holes straddle centerlines (first hole angle)",
            180 / f.bolt_hole_count,
            "angle",
        ),
        CriticalDim("bore", f"Bore (B), Sch {f.bore_schedule}", f.bore),
        CriticalDim("raised_face_dia", "Raised face diameter (R)", f.raised_face_dia),
        CriticalDim("raised_face_height", "Raised face height", f.raised_face_height),
        CriticalDim("thickness", "Flange thickness incl. RF (C)", f.thickness),
        CriticalDim("length_through_hub", "Length through hub incl. RF (Y)", f.length_through_hub),
        CriticalDim("hub_dia_base", "Hub diameter at base (X)", f.hub_dia_base),
        CriticalDim("hub_dia_weld", "Hub diameter at weld point (A)", f.hub_dia_weld),
    ]


def measure(solid: Solid) -> dict[str, float]:
    """Measure the critical dimensions on the solid, by role (never from the table)."""
    bb = solid.bounding_box()
    z0 = bb.min.Z
    cyl = z_axis_cylinders(solid)
    on_axis = [c for c in cyl if c.radial_pos < 1e-6]
    holes = [c for c in cyl if c.radial_pos >= 1e-6]
    planes = z_planes(solid)
    cones = z_cones(solid)
    if len(cones) != 1:
        raise ValueError(f"expected one hub cone, found {len(cones)}")
    (hz0, hd0), (hz1, hd1) = cones[0].ends

    rf = [c for c in on_axis if abs(c.z_min - z0) < 1e-6 and c is not min(on_axis, key=lambda c: c.dia)]
    od_faces = [p for p in planes if abs(p.outer_dia - bb.size.X) < 1e-6]
    hole_dias = {round(h.dia, 6) for h in holes}
    bc = {round(2 * h.radial_pos, 6) for h in holes}
    return {
        "od": bb.size.X,
        "length_through_hub": bb.size.Z,
        "bolt_hole_count": len(holes),
        "bolt_hole_dia": hole_dias.pop() if len(hole_dias) == 1 else float("nan"),
        "bolt_circle": bc.pop() if len(bc) == 1 else float("nan"),
        "bolt_hole_offset": min(h.angle_deg for h in holes) if holes else float("nan"),
        "bore": min(on_axis, key=lambda c: c.dia).dia,
        "raised_face_dia": rf[0].dia if len(rf) == 1 else float("nan"),
        "raised_face_height": (min(p.z for p in od_faces) - z0) if od_faces else float("nan"),
        "thickness": (max(p.z for p in od_faces) - z0) if od_faces else float("nan"),
        "hub_dia_base": hd0,
        "hub_dia_weld": hd1,
    }
