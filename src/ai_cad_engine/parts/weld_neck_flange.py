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

from ai_cad_engine.standards.asme_b16_5 import WeldNeckFlange

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
