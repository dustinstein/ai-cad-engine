"""Write projected views to DXF (mm, 1:1 in model space) with ezdxf.

Layers: VISIBLE (continuous), HIDDEN (HIDDEN linetype). Each view's entities
are collected in a DXF GROUP named VIEW_<NAME> so tools/tests can find them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import ezdxf

from ai_cad_engine.drawing.views import Arc, Circle, Line, Polyline, Prim, View

DXF_VERSION = "R2018"
INSUNITS_MM = 4
# ASME Y14.2-style hidden line at 1:1 in mm. ezdxf's stock patterns are too fine for mm.
HIDDEN_PATTERN = (4.5, 3.0, -1.5)  # total, dash, gap


@dataclass(frozen=True)
class PlacedView:
    view: View
    offset: tuple[float, float]  # sheet position of the view's model origin


def layout_third_angle(
    front: View, top: View, right: View, gap: float = 40.0
) -> list[PlacedView]:
    """FRONT at origin, TOP above, RIGHT to the right, aligned per Y14.3."""
    fx0, fy0, fx1, fy1 = front.bbox
    tx0, ty0, tx1, ty1 = top.bbox
    rx0, ry0, rx1, ry1 = right.bbox
    return [
        PlacedView(front, (0.0, 0.0)),
        PlacedView(top, (0.0, fy1 + gap - ty0)),
        PlacedView(right, (fx1 + gap - rx0, 0.0)),
    ]


def write_dxf(placed: list[PlacedView], path: Path) -> None:
    doc = ezdxf.new(DXF_VERSION, setup=True, units=INSUNITS_MM)
    doc.header["$MEASUREMENT"] = 1  # metric
    doc.linetypes.add("HIDDEN", pattern=list(HIDDEN_PATTERN), description="Hidden __ __ __")
    doc.layers.add("VISIBLE", color=7, lineweight=50)
    doc.layers.add("HIDDEN", color=8, linetype="HIDDEN", lineweight=25)
    msp = doc.modelspace()
    for pv in placed:
        entities = []
        for layer, prims in (("VISIBLE", pv.view.visible), ("HIDDEN", pv.view.hidden)):
            for p in prims:
                entities.append(_add(msp, p, pv.offset, layer))
        doc.groups.new(f"VIEW_{pv.view.spec.name}").set_data(entities)
    doc.saveas(path)


def _add(msp, p: Prim, off: tuple[float, float], layer: str):
    ox, oy = off
    attrs = {"layer": layer}
    if isinstance(p, Line):
        return msp.add_line(
            (p.p1[0] + ox, p.p1[1] + oy), (p.p2[0] + ox, p.p2[1] + oy), dxfattribs=attrs
        )
    if isinstance(p, Circle):
        return msp.add_circle((p.center[0] + ox, p.center[1] + oy), p.radius, dxfattribs=attrs)
    if isinstance(p, Arc):
        return msp.add_arc(
            (p.center[0] + ox, p.center[1] + oy),
            p.radius,
            p.start_angle,
            p.end_angle,
            dxfattribs=attrs,
        )
    if isinstance(p, Polyline):
        return msp.add_lwpolyline([(x + ox, y + oy) for x, y in p.points], dxfattribs=attrs)
    raise TypeError(p)
