"""Low-level DXF writing: document setup, view layout, view geometry.

Drawings are old-school single-space DXF: everything lives in model space at
true size in drawing units (inches), and the sheet border/title block are drawn
scaled up by the drawing scale S. Paper-space viewports are avoided on purpose;
importers (Alibre, LibreCAD, ...) handle plain model space most reliably.

Paper-sized quantities (text, linetype dashes, offsets) are given in paper
inches and multiplied by S. Linetype patterns are baked at S rather than
relying on $LTSCALE, which some importers ignore.

Layers: VISIBLE, HIDDEN. Each view's entities are collected in a DXF GROUP
named VIEW_<NAME> so tools/tests can find them.
"""

from __future__ import annotations

from dataclasses import dataclass

import ezdxf
import ezdxf.document

from ai_cad_engine.drawing.views import Arc, Circle, Line, Polyline, Prim, View

DXF_VERSION = "R2018"
INSUNITS_INCH = 1
MEASUREMENT_IMPERIAL = 0

# ASME Y14.2 line patterns in paper inches: (dash, gap, ...). Standard NAMES are required:
# Alibre maps linetypes by name and imports unknown names as solid.
HIDDEN_PAPER = (0.125, -0.0625)
CENTER_PAPER = (0.75, -0.0625, 0.125, -0.0625)


@dataclass(frozen=True)
class PlacedView:
    view: View
    offset: tuple[float, float]  # model-space position of the view's origin


def layout_third_angle(front: View, top: View, right: View, gap: float) -> list[PlacedView]:
    """FRONT at origin, TOP above, RIGHT to the right, aligned per Y14.3."""
    _, _, fx1, fy1 = front.bbox
    _, ty0, _, _ = top.bbox
    rx0, _, _, _ = right.bbox
    return [
        PlacedView(front, (0.0, 0.0)),
        PlacedView(top, (0.0, fy1 + gap - ty0)),
        PlacedView(right, (fx1 + gap - rx0, 0.0)),
    ]


def layout_bbox(placed: list[PlacedView]) -> tuple[float, float, float, float]:
    boxes = [
        (x0 + pv.offset[0], y0 + pv.offset[1], x1 + pv.offset[0], y1 + pv.offset[1])
        for pv in placed
        for x0, y0, x1, y1 in [pv.view.bbox]
    ]
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def translate(placed: list[PlacedView], dx: float, dy: float) -> list[PlacedView]:
    return [PlacedView(pv.view, (pv.offset[0] + dx, pv.offset[1] + dy)) for pv in placed]


def new_doc(scale: float) -> ezdxf.document.Drawing:
    doc = ezdxf.new(DXF_VERSION, setup=True, units=INSUNITS_INCH)
    doc.header["$MEASUREMENT"] = MEASUREMENT_IMPERIAL
    for name, paper, desc in (
        ("HIDDEN", HIDDEN_PAPER, "Hidden __ __ __"),
        ("CENTER", CENTER_PAPER, "Center ____ _ ____"),
    ):
        if name in doc.linetypes:
            doc.linetypes.remove(name)
        pattern = [v * scale for v in paper]
        doc.linetypes.add(name, pattern=[sum(abs(v) for v in pattern), *pattern], description=desc)
    doc.layers.add("VISIBLE", color=7, lineweight=50)
    doc.layers.add("HIDDEN", color=8, linetype="HIDDEN", lineweight=25)
    return doc


def add_views(doc: ezdxf.document.Drawing, placed: list[PlacedView]) -> None:
    msp = doc.modelspace()
    for pv in placed:
        entities = []
        for layer, prims in (("VISIBLE", pv.view.visible), ("HIDDEN", pv.view.hidden)):
            for p in prims:
                entities.append(_add(msp, p, pv.offset, layer))
        doc.groups.new(f"VIEW_{pv.view.spec.name}").set_data(entities)


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
