"""B16.9 eccentric reducer.

Local frame (mm): axis Z, large end at Z=0 centered on the origin, small end at
Z=H centered at (-e, 0) with e = (D_large - D_small)/2, so the OUTSIDE is flat
along the line x = -D_large/2 ("flat side" = -X). Body: oblique cone (ruled loft)
between the end circles, outside and inside; ends match the pipe schedules, so
with unequal walls the inside is not exactly flat. Simplification: B16.9 does not
fix the body shape; real fittings may have short straight ends.

Ports `large` / `small` point out of the fitting; their x_dir points to the flat
side, so an assembly makes it flat-on-bottom by aligning x_dir with world down.
"""

from __future__ import annotations

from math import hypot

from build123d import Circle, GeomType, Plane, Solid, loft

from ai_cad_engine.assembly import Component, Port
from ai_cad_engine.standards.asme_b16_9 import Reducer
from ai_cad_engine.verify import CriticalDim

FLAT = (-1, 0, 0)


def _cone(r0: float, r1: float, h: float, dx: float) -> Solid:
    a = Plane.XY * Circle(r0)
    b = Plane(origin=(dx, 0, h)) * Circle(r1)
    return loft([a, b])


def build_ecc_reducer(r: Reducer) -> Solid:
    e = r.offset
    outer = _cone(r.large.od / 2, r.small.od / 2, r.length, -e)
    inner = _cone(r.large.id / 2, r.small.id / 2, r.length, -e)
    return outer - inner


def reducer_component(tag: str, r: Reducer) -> Component:
    L, S = r.large, r.small
    return Component(
        tag=tag,
        part_no=f"RED-ECC-{L.nps}x{S.nps}-S{L.schedule}x{S.schedule}",
        description=(
            f"REDUCER, ECCENTRIC, BW, NPS {L.nps} x {S.nps}, SCH {L.schedule} x {S.schedule}, ASME B16.9"
        ),
        solid=build_ecc_reducer(r),
        ports={
            "large": Port((0, 0, 0), (0, 0, -1), FLAT, end="BW", attrs={"od": L.od, "id": L.id, "nps": L.nps}),
            "small": Port(
                (-r.offset, 0, r.length), (0, 0, 1), FLAT, end="BW", attrs={"od": S.od, "id": S.id, "nps": S.nps}
            ),
        },
        meta={"table": r, "verified": r.verified},
    )


def critical_dims(r: Reducer) -> list[CriticalDim]:
    return [
        CriticalDim("length", "End to end (H)", r.length),
        CriticalDim("large_od", "Large end OD", r.large.od),
        CriticalDim("large_id", "Large end ID", r.large.id),
        CriticalDim("small_od", "Small end OD", r.small.od),
        CriticalDim("small_id", "Small end ID", r.small.id),
        CriticalDim("offset", "Eccentric offset between end centers", r.offset),
        CriticalDim("flat_outside", "Outside flat: both end ODs tangent to one line", 1, "check"),
        CriticalDim("table_data_verified", "All table data verified", 1, "check"),
    ]


def measure(solid: Solid, verified: bool) -> dict[str, float]:
    """End faces found by role: the two planar annuli normal to Z at min/max Z."""
    bb = solid.bounding_box()
    ends = {}
    for f in solid.faces().filter_by(GeomType.PLANE):
        fb = f.bounding_box()
        if fb.size.Z > 1e-6:
            continue
        circles = sorted(
            (e for e in f.edges() if e.geom_type == GeomType.CIRCLE), key=lambda e: e.radius
        )
        if len(circles) != 2:
            continue
        which = "large" if abs(fb.min.Z - bb.min.Z) < 1e-6 else "small"
        ends[which] = (circles[1], circles[0])  # (outer, inner)
    (lo, li), (so, si) = ends["large"], ends["small"]
    cl, cs = lo.arc_center, so.arc_center
    # Outside flat along -X: leftmost points of both outer circles on one line x = const.
    flat_err = abs((cl.X - lo.radius) - (cs.X - so.radius)) + abs(cl.Y - cs.Y)
    return {
        "length": bb.size.Z,
        "large_od": 2 * lo.radius,
        "large_id": 2 * li.radius,
        "small_od": 2 * so.radius,
        "small_id": 2 * si.radius,
        "offset": hypot(cl.X - cs.X, cl.Y - cs.Y),
        "flat_outside": float(flat_err < 1e-4),
        "table_data_verified": float(verified),
    }
