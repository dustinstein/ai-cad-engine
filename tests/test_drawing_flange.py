from dataclasses import replace
from math import hypot

import ezdxf
import pytest
from ezdxf import bbox

from ai_cad_engine.drawing.annotate import DIMSTYLE, annotate_flange
from ai_cad_engine.drawing.dxf_writer import INSUNITS_INCH
from ai_cad_engine.drawing.make import make_drawing
from ai_cad_engine.parts.weld_neck_flange import build_weld_neck_flange
from ai_cad_engine.standards.asme_b16_5 import IN, WN_4_150 as F, flange_title_block

TOL = 0.0005  # inch (~0.013 mm); geometry is exact, this absorbs float noise
VIEW_NAMES = ("FRONT", "TOP", "RIGHT")


def inch(mm: float) -> float:
    return mm / IN


@pytest.fixture(scope="module")
def drawing(tmp_path_factory):
    path = tmp_path_factory.mktemp("dxf") / "f.dxf"
    res = make_drawing(build_weld_neck_flange(F), annotate_flange, flange_title_block(F), path)
    return res, ezdxf.readfile(path)


@pytest.fixture(scope="module")
def doc(drawing):
    return drawing[1]


@pytest.fixture(scope="module")
def sheet(drawing):
    return drawing[0].sheet


def group(doc, name):
    return list(doc.groups.get(name))


def view(doc, name):
    return group(doc, f"VIEW_{name}")


def view_entities(doc):
    return [e for n in VIEW_NAMES for e in view(doc, n)]


def size(entities):
    b = bbox.extents(entities)
    return b.size.x, b.size.y


def dims(doc):
    return list(doc.modelspace().query("DIMENSION"))


def dia_dim_by_text(doc, text):
    found = [d for d in dims(doc) if d.dimtype & 0xF == 3 and d.dxf.text == text]
    assert len(found) == 1, text
    return found[0]


# ---- units, entities, linetypes ------------------------------------------------


def test_units_inch(doc):
    assert doc.header["$INSUNITS"] == INSUNITS_INCH
    assert doc.header["$MEASUREMENT"] == 0


def test_only_exact_entity_types(doc):
    # Dimensioning relies on real lines/circles/arcs, not approximations.
    assert {e.dxftype() for e in view_entities(doc)} <= {"LINE", "CIRCLE", "ARC"}


def test_no_duplicate_view_entities(doc):
    seen = set()
    for e in view_entities(doc):
        if e.dxftype() == "LINE":
            a, b = sorted([tuple(round(v, 5) for v in e.dxf.start), tuple(round(v, 5) for v in e.dxf.end)])
            key = ("L", a, b)
        else:
            key = (e.dxftype(), tuple(round(v, 5) for v in e.dxf.center), round(e.dxf.radius, 5))
        assert key not in seen, key
        seen.add(key)


def test_all_referenced_linetypes_defined(doc):
    for layer in doc.layers:
        assert layer.dxf.linetype in doc.linetypes, layer.dxf.name


def test_only_standard_linetype_names(doc):
    # Alibre maps linetypes by name; a custom name imports as solid.
    standard = {"CONTINUOUS", "BYLAYER", "BYBLOCK", "HIDDEN", "CENTER"}
    for layer in doc.layers:
        assert layer.dxf.linetype.upper() in standard, (layer.dxf.name, layer.dxf.linetype)


@pytest.mark.parametrize("name,paper_dash", [("HIDDEN", 0.125), ("CENTER", 0.75)])
def test_linetype_dashes_baked_at_scale(doc, sheet, name, paper_dash):
    dashes = [t.value for t in doc.linetypes.get(name).pattern_tags.tags if t.code == 49]
    assert max(dashes) == pytest.approx(paper_dash * sheet.scale)


# ---- views ---------------------------------------------------------------------


@pytest.mark.parametrize("name", ["FRONT", "RIGHT"])
def test_profile_view_extents(doc, name):
    w, h = size(view(doc, name))
    assert w == pytest.approx(inch(F.od), abs=TOL)
    assert h == pytest.approx(inch(F.length_through_hub), abs=TOL)


def test_top_view_extents(doc):
    w, h = size(view(doc, "TOP"))
    assert w == pytest.approx(inch(F.od), abs=TOL)
    assert h == pytest.approx(inch(F.od), abs=TOL)


def test_top_view_bolt_holes(doc):
    circles = [e for e in view(doc, "TOP") if e.dxftype() == "CIRCLE"]
    od = [c for c in circles if abs(c.dxf.radius - inch(F.od) / 2) < TOL]
    assert len(od) == 1
    cx, cy = od[0].dxf.center.x, od[0].dxf.center.y
    holes = [
        c
        for c in circles
        if abs(c.dxf.radius - inch(F.bolt_hole_dia) / 2) < TOL and c.dxf.layer == "VISIBLE"
    ]
    assert len(holes) == F.bolt_hole_count
    for h in holes:
        r = hypot(h.dxf.center.x - cx, h.dxf.center.y - cy)
        assert 2 * r == pytest.approx(inch(F.bolt_circle_dia), abs=TOL)


def test_front_view_hidden_bore(doc):
    hidden = [e for e in view(doc, "FRONT") if e.dxf.layer == "HIDDEN"]
    full = [
        e
        for e in hidden
        if abs(abs(e.dxf.end.y - e.dxf.start.y) - inch(F.length_through_hub)) < TOL
    ]
    assert len(full) == 2
    assert abs(full[0].dxf.start.x - full[1].dxf.start.x) == pytest.approx(inch(F.bore), abs=TOL)
    assert len({round(e.dxf.start.x, 4) for e in hidden}) == 10


def test_views_aligned_third_angle(doc):
    f, t, r = (bbox.extents(view(doc, n)) for n in ("FRONT", "TOP", "RIGHT"))
    assert t.extmin.x == pytest.approx(f.extmin.x, abs=TOL)  # TOP above FRONT
    assert t.extmin.y > f.extmax.y
    assert r.extmin.y == pytest.approx(f.extmin.y, abs=TOL)  # RIGHT beside FRONT
    assert r.extmin.x > f.extmax.x


# ---- dimensions ----------------------------------------------------------------


def test_dimensions_are_real_dimension_entities(doc):
    ds = dims(doc)
    assert len(ds) == 5
    for d in ds:
        assert d.dxf.dimstyle == DIMSTYLE
        assert d.dxf.layer == "DIM"
        assert d.get_geometry_block() is not None  # rendered, displays without regen


# Measurements come from DIMENSION defpoints, which were snapped to drawn
# geometry, so these compare what the drawing shows against the standard.
@pytest.mark.parametrize(
    "text,expected_mm",
    [("<>", F.od), ("<> B.C.", F.bolt_circle_dia), ("8X <> THRU", F.bolt_hole_dia)],
)
def test_diameter_dimensions(doc, text, expected_mm):
    assert dia_dim_by_text(doc, text).get_measurement() == pytest.approx(inch(expected_mm), abs=TOL)


def test_linear_dimensions(doc):
    lin = sorted((d for d in dims(doc) if d.dimtype & 0xF in (0, 1)), key=lambda d: d.get_measurement())
    assert [d.get_measurement() for d in lin] == pytest.approx(
        [inch(F.thickness), inch(F.length_through_hub)], abs=TOL
    )


def test_displayed_text_inch_format(doc):
    # ASME Y14.5 inch: 3 decimals, no leading zero.
    shown = {
        d.dxf.text: [e.text for e in d.get_geometry_block() if e.dxftype() == "MTEXT"][0]
        for d in dims(doc)
        if d.dxf.text != "<>"
    }
    assert shown["<> B.C."] == "%%c7.500 B.C."
    assert shown["8X <> THRU"] == "8X %%c.750 THRU"
    texts = sorted(
        e.text for d in dims(doc) for e in d.get_geometry_block() if e.dxftype() == "MTEXT"
    )
    assert ".940" in texts and "3.000" in texts and "%%c9.000" in texts


def test_dimstyle(doc, sheet):
    st = doc.dimstyles.get(DIMSTYLE)
    assert st.dxf.dimlfac == 1.0
    assert st.dxf.dimdec == 3
    assert st.dxf.dimscale == sheet.scale
    assert st.dxf.dimtxt == 0.125  # paper inches, Y14.2 minimum


def test_centerlines(doc):
    cl = [e for e in doc.modelspace() if e.dxf.layer == "CENTER"]
    circles = [e for e in cl if e.dxftype() == "CIRCLE"]
    assert len(circles) == 1
    assert 2 * circles[0].dxf.radius == pytest.approx(inch(F.bolt_circle_dia), abs=TOL)
    # 2 cross lines + 8 hole marks in TOP, 1 axis line each in FRONT and RIGHT
    assert len([e for e in cl if e.dxftype() == "LINE"]) == 2 + F.bolt_hole_count + 2


def test_dimensions_report_drawn_geometry_not_table(tmp_path):
    # A flange built 0.5 mm off must show the wrong value, not the table value.
    bad = replace(F, bolt_circle_dia=F.bolt_circle_dia + 0.5)
    path = tmp_path / "bad.dxf"
    make_drawing(build_weld_neck_flange(bad), annotate_flange, flange_title_block(bad), path)
    d = dia_dim_by_text(ezdxf.readfile(path), "<> B.C.")
    assert d.get_measurement() == pytest.approx(inch(F.bolt_circle_dia + 0.5), abs=TOL)


# ---- sheet ---------------------------------------------------------------------


def test_sheet_choice(sheet):
    assert (sheet.size, sheet.scale) == ("B", 2)


def test_everything_inside_content_area(doc, sheet):
    S = sheet.scale
    cx0, cy0, cx1, cy1 = (v * S for v in sheet.content_area())
    ents = view_entities(doc) + [e for n in VIEW_NAMES for e in group(doc, f"ANNOT_{n}")]
    b = bbox.extents(ents)
    assert b.extmin.x >= cx0 and b.extmin.y >= cy0, (b.extmin, (cx0, cy0))
    assert b.extmax.x <= cx1 and b.extmax.y <= cy1, (b.extmax, (cx1, cy1))
    for d in dims(doc):  # dimension text boxes too
        x0, y0, x1, y1 = text_box(d)
        assert cx0 <= x0 and x1 <= cx1 and cy0 <= y0 and y1 <= cy1, d.dxf.text


def test_border_and_title_block(doc, sheet):
    S = sheet.scale
    w, h = sheet.paper
    b = bbox.extents(e for e in doc.modelspace() if e.dxf.layer == "BORDER")
    assert (b.extmin.x, b.extmin.y) == pytest.approx((0.5 * S, 0.5 * S))
    assert (b.extmax.x, b.extmax.y) == pytest.approx(((w - 0.5) * S, (h - 0.5) * S))
    texts = {e.dxf.text for e in doc.modelspace().query("TEXT")}
    for expected in ("B", "1:2", "INCHES", "THIRD ANGLE", "WN-4-150-RF", "1 OF 1"):
        assert expected in texts, expected
    assert any("NPS 4 CL150" in t for t in texts)
    assert any("ASME B16.5" in t for t in texts)


# ---- readability ---------------------------------------------------------------


def text_box(d):
    """Conservative box of a dimension's text: from char height and character count."""
    m = [e for e in d.get_geometry_block() if e.dxftype() == "MTEXT"][0]
    h = m.dxf.char_height
    n = len(m.text.replace("%%c", "X"))
    w = n * h * 0.9
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


def test_dimension_text_is_clear(doc):
    """No dimension text box touches other dims' lines, other text, or part geometry."""
    ds = dims(doc)
    boxes = {d.dxf.handle: text_box(d) for d in ds}
    obstacles = []  # (owner handle or None, entity)
    for d in ds:
        for e in d.get_geometry_block():
            if e.dxftype() == "LINE":
                obstacles.append((d.dxf.handle, e))
    for e in view_entities(doc):
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


def test_title_block_text_fits_cells(doc, sheet):
    from ai_cad_engine.drawing.sheet import CHAR_W

    S = sheet.scale
    bx0, by0, bx1, by1 = (v * S for v in sheet.title_block_rect())
    for t in doc.modelspace().query("TEXT"):
        x, y = t.dxf.insert.x, t.dxf.insert.y
        if not (bx0 <= x <= bx1 and by0 <= y <= by1):
            continue  # notes
        assert x + len(t.dxf.text) * t.dxf.height * CHAR_W <= bx1 + 1e-9, t.dxf.text
