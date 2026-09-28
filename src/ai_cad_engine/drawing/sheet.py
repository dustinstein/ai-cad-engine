"""ANSI sheets (ASME Y14.1), scale selection, border, title block, notes.

All sizes here are paper inches. Model-space positions are paper * S, where
S is the scale denominator (S=2 means the drawing is 1:2).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import ezdxf.document

ANSI_SIZES = {"A": (11.0, 8.5), "B": (17.0, 11.0), "C": (22.0, 17.0), "D": (34.0, 22.0)}
STANDARD_SCALES = (1, 2, 4, 8, 16)  # reductions; enlargements (2:1) later if needed
BORDER_MARGIN = 0.5
TB_W, TB_H = 6.25, 1.5  # title block
ROW_H = TB_H / 4
LABEL_H, VALUE_H, TITLE_H = 0.07, 0.125, 0.14
CHAR_W = 0.9  # conservative glyph advance / text height, for fit checks
NOTE_H = 0.125
# Paper inches reserved around the view block for dims/leaders: (left, bottom, right, top).
# Linear dims sit left of FRONT; diameter leaders go above/right of TOP. Tests assert the
# finished drawing stays inside the content area, so an optimistic estimate fails loudly.
ANNOT_ALLOWANCE = (1.6, 0.25, 0.5, 0.75)
MAX_PREFERRED_REDUCTION = 4  # go to a bigger sheet rather than below 1:4


@dataclass(frozen=True)
class TitleBlock:
    title: str
    dwg_no: str
    rev: str = "-"
    material: str = ""
    drawn_by: str = "AI-CAD-ENGINE"
    date: str = ""
    units: str = "INCHES"
    projection: str = "THIRD ANGLE"
    notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Sheet:
    size: str
    scale: int  # S; drawing is 1:S

    @property
    def paper(self) -> tuple[float, float]:
        return ANSI_SIZES[self.size]

    @property
    def scale_text(self) -> str:
        return f"1:{self.scale}"

    def content_area(self) -> tuple[float, float, float, float]:
        """Paper rect for views + annotations: inside border, above the title-block strip."""
        w, h = self.paper
        m = BORDER_MARGIN
        return (m, m + TB_H, w - m, h - m)

    def title_block_rect(self) -> tuple[float, float, float, float]:
        w, _ = self.paper
        m = BORDER_MARGIN
        return (w - m - TB_W, m, w - m, m + TB_H)


def fits(sheet: Sheet, model_w: float, model_h: float, allowance=ANNOT_ALLOWANCE) -> bool:
    x0, y0, x1, y1 = sheet.content_area()
    al, ab, ar, at = allowance
    need_w = model_w / sheet.scale + al + ar
    need_h = model_h / sheet.scale + ab + at
    return need_w <= x1 - x0 and need_h <= y1 - y0


def choose_sheet(
    layout_size_at, sizes: tuple[str, ...] = ("B", "C", "D"), allowance=ANNOT_ALLOWANCE
) -> Sheet:
    """Smallest sheet whose largest fitting standard scale is no smaller than 1:4.

    `layout_size_at(S)` returns the model (w, h) of the view layout for scale S
    (view gaps are paper-sized, so the layout depends on S).
    """
    fallback = None
    for size in sizes:
        for s in STANDARD_SCALES:
            sheet = Sheet(size, s)
            if fits(sheet, *layout_size_at(s), allowance):
                if s <= MAX_PREFERRED_REDUCTION:
                    return sheet
                fallback = fallback or sheet
                break
    if fallback is None:
        raise ValueError("part does not fit any sheet at supported scales")
    return fallback


def draw_sheet(doc: ezdxf.document.Drawing, sheet: Sheet, tb: TitleBlock) -> None:
    doc.layers.add("BORDER", color=7, lineweight=70)
    doc.layers.add("TITLE", color=7, lineweight=25)
    msp = doc.modelspace()
    S = sheet.scale
    w, h = sheet.paper
    m = BORDER_MARGIN
    ents = []

    def rect(x0, y0, x1, y1, layer):
        return msp.add_lwpolyline(
            [(x0 * S, y0 * S), (x1 * S, y0 * S), (x1 * S, y1 * S), (x0 * S, y1 * S)],
            close=True,
            dxfattribs={"layer": layer},
        )

    def line(x0, y0, x1, y1):
        return msp.add_line((x0 * S, y0 * S), (x1 * S, y1 * S), dxfattribs={"layer": "TITLE"})

    def text(s, x, y, height):
        return msp.add_text(
            s, height=height * S, dxfattribs={"layer": "TITLE", "insert": (x * S, y * S)}
        )

    ents.append(rect(m, m, w - m, h - m, "BORDER"))

    bx0, by0, bx1, by1 = sheet.title_block_rect()
    ents.append(rect(bx0, by0, bx1, by1, "BORDER"))
    # rows, bottom to top; each cell: (x_from, x_to, label, value)
    rows = [
        [(0, 2.5, "DRAWN", tb.drawn_by), (2.5, 4.0, "DATE", tb.date), (4.0, 6.25, "MATERIAL", tb.material)],
        [(0, 1.5, "SCALE", sheet.scale_text), (1.5, 3.0, "UNITS", tb.units), (3.0, 6.25, "PROJECTION", tb.projection)],
        [(0, 3.75, "DWG NO", tb.dwg_no), (3.75, 4.5, "REV", tb.rev), (4.5, 5.25, "SIZE", sheet.size), (5.25, 6.25, "SHEET", "1 OF 1")],
        [(0, 6.25, "TITLE", tb.title)],
    ]
    for i, row in enumerate(rows):
        y = by0 + i * ROW_H
        if i:
            ents.append(line(bx0, y, bx1, y))
        for x_from, x_to, label, value in row:
            if x_from:
                ents.append(line(bx0 + x_from, y, bx0 + x_from, y + ROW_H))
            ents.append(text(label, bx0 + x_from + 0.05, y + ROW_H - LABEL_H - 0.04, LABEL_H))
            vh = TITLE_H if label == "TITLE" else VALUE_H
            # Shrink long values to fit the cell rather than overrun the grid.
            vh = min(vh, (x_to - x_from - 0.16) / (CHAR_W * max(len(value), 1)))
            if value:
                ents.append(text(value, bx0 + x_from + 0.08, y + 0.06, vh))

    # Notes, bottom-left strip beside the title block.
    lines = ["NOTES:", *(f"{i}. {n}" for i, n in enumerate(tb.notes, 1))]
    y = m + TB_H - 0.3
    for ln in lines:
        ents.append(text(ln, m + 0.2, y, NOTE_H))
        y -= NOTE_H * 1.8
    doc.groups.new("SHEET").set_data(ents)
