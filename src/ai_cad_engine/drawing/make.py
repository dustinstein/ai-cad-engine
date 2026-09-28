"""Projected views (mm) -> dimensioned third-angle ANSI drawing in inches, written to DXF."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import ezdxf.document

from ai_cad_engine.drawing.dxf_writer import (
    PlacedView,
    add_views,
    layout_bbox,
    layout_third_angle,
    new_doc,
    translate,
)
from ai_cad_engine.drawing.sheet import ANNOT_ALLOWANCE, Sheet, TitleBlock, choose_sheet, draw_sheet
from ai_cad_engine.drawing.views import View, scale_view

MM_TO_IN = 1 / 25.4

Annotator = Callable[[ezdxf.document.Drawing, list[PlacedView], float], None]


@dataclass(frozen=True)
class DrawingResult:
    sheet: Sheet
    placed: list[PlacedView]


def make_drawing(
    views: dict[str, View],
    annotate: Annotator,
    tb: TitleBlock,
    path: Path,
    view_gap: float = 1.0,
    allowance: tuple[float, float, float, float] = ANNOT_ALLOWANCE,
) -> DrawingResult:
    """`views` (mm, keyed FRONT/TOP/RIGHT) are converted to inches, laid out third-angle,
    placed on the smallest suitable ANSI sheet, annotated and saved.
    `view_gap` and `allowance` are paper inches."""
    v = {k: scale_view(view, MM_TO_IN) for k, view in views.items()}

    def layout(S: float) -> list[PlacedView]:
        return layout_third_angle(v["FRONT"], v.get("TOP"), v.get("RIGHT"), gap=view_gap * S)

    def size_at(S: float) -> tuple[float, float]:
        x0, y0, x1, y1 = layout_bbox(layout(S))
        return x1 - x0, y1 - y0

    sheet = choose_sheet(size_at, allowance=allowance)
    S = sheet.scale
    placed = layout(S)
    # Center the view block plus its annotation allowance in the content area.
    al, ab, ar, at = allowance
    lx0, ly0, lx1, ly1 = layout_bbox(placed)
    lx0, ly0, lx1, ly1 = lx0 - al * S, ly0 - ab * S, lx1 + ar * S, ly1 + at * S
    cx0, cy0, cx1, cy1 = sheet.content_area()
    placed = translate(
        placed,
        (cx0 + cx1) / 2 * S - (lx0 + lx1) / 2,
        (cy0 + cy1) / 2 * S - (ly0 + ly1) / 2,
    )

    doc = new_doc(S)
    draw_sheet(doc, sheet, tb)
    add_views(doc, placed, S)
    annotate(doc, placed, S)
    doc.saveas(path)
    return DrawingResult(sheet, placed)
