"""Shared drawing checks (readability, containment) used by drawing tests."""

from math import hypot

from ezdxf import bbox

# Conservative glyph advance / text height, shared with the layout code. 0.9 missed a
# real touch of two hub diameter texts on the NPS 2 CL600 drawing; fonts run ~1.0.
from ai_cad_engine.drawing.annotate import CHAR_W_EST  # noqa: E402


def text_box(d):
    """Conservative box of a dimension's text: from char height and character count."""
    m = [e for e in d.get_geometry_block() if e.dxftype() == "MTEXT"][0]
    h = m.dxf.char_height
    n = len(m.text.replace("%%c", "X"))
    w = n * h * CHAR_W_EST
    x, y = m.dxf.insert.x, m.dxf.insert.y
    assert m.dxf.attachment_point == 5  # middle center
    return (x - w / 2, y - h / 2, x + w / 2, y + h / 2)


def _seg_hits_box(p, q, box):
    """Liang-Barsky segment/rect intersection."""
    x0, y0, x1, y1 = box
    t0, t1 = 0.0, 1.0
    dx, dy = q[0] - p[0], q[1] - p[1]
    for pp, qq in ((-dx, p[0] - x0), (dx, x1 - p[0]), (-dy, p[1] - y0), (dy, y1 - p[1])):
        if pp == 0:
            if qq < 0:
                return False
        else:
            t = qq / pp
            if pp < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
    return t0 <= t1


def _circle_hits_box(c, r, box):
    x0, y0, x1, y1 = box
    near = hypot(max(x0 - c[0], 0, c[0] - x1), max(y0 - c[1], 0, c[1] - y1))
    far = max(hypot(x - c[0], y - c[1]) for x in (x0, x1) for y in (y0, y1))
    return near <= r <= far


def assert_dimension_text_clear(doc, view_names=("FRONT", "RIGHT")):
    """No dimension text box touches other dims' lines, other text, part geometry or centerlines."""
    ds = list(doc.modelspace().query("DIMENSION"))
    boxes = {d.dxf.handle: text_box(d) for d in ds}
    obstacles = []  # (owner handle or None, entity)
    for d in ds:
        for e in d.get_geometry_block():
            if e.dxftype() == "LINE":
                obstacles.append((d.dxf.handle, e))
    for n in view_names:
        for e in doc.groups.get(f"VIEW_{n}"):
            if e.dxftype() in ("LINE", "CIRCLE", "ARC"):
                obstacles.append((None, e))
    for n in view_names:
        for e in doc.groups.get(f"ANNOT_{n}"):
            if e.dxftype() in ("LINE", "CIRCLE"):
                obstacles.append((None, e))
    for h, box in boxes.items():
        for owner, e in obstacles:
            if owner == h:
                continue
            if e.dxftype() == "LINE":
                hit = _seg_hits_box(e.dxf.start, e.dxf.end, box)
            else:
                hit = _circle_hits_box(e.dxf.center, e.dxf.radius, box)
            assert not hit, (doc.entitydb[h].dxf.text, e.dxftype(), e.dxf.layer)
        for h2, box2 in boxes.items():
            if h2 != h:
                overlap = box[0] < box2[2] and box2[0] < box[2] and box[1] < box2[3] and box2[1] < box[3]
                assert not overlap, (doc.entitydb[h].dxf.text, doc.entitydb[h2].dxf.text)


def assert_inside_content_area(doc, sheet, view_names=("FRONT", "RIGHT")):
    S = sheet.scale
    cx0, cy0, cx1, cy1 = (v * S for v in sheet.content_area())
    ents = [e for n in view_names for g in ("VIEW", "ANNOT") for e in doc.groups.get(f"{g}_{n}")]
    b = bbox.extents(ents)
    assert b.extmin.x >= cx0 and b.extmin.y >= cy0, (b.extmin, (cx0, cy0))
    assert b.extmax.x <= cx1 and b.extmax.y <= cy1, (b.extmax, (cx1, cy1))
    for d in doc.modelspace().query("DIMENSION"):
        x0, y0, x1, y1 = text_box(d)
        assert cx0 <= x0 and x1 <= cx1 and cy0 <= y0 and y1 <= cy1, d.dxf.text
