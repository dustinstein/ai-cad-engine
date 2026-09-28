from dataclasses import replace
from math import hypot

import ezdxf
import pytest
from ezdxf import bbox

from ai_cad_engine.drawing import flange_drawing as fd
from ai_cad_engine.drawing.annotate import DIMSTYLE
from ai_cad_engine.drawing.dxf_writer import INSUNITS_INCH
from ai_cad_engine.drawing.make import make_drawing
from ai_cad_engine.drawing.views import loop_area
from ai_cad_engine.parts.weld_neck_flange import build_weld_neck_flange
from ai_cad_engine.standards.asme_b16_5 import IN, WN_4_150 as F, flange_title_block

TOL = 0.0005  # inch (~0.013 mm); geometry is exact, this absorbs float noise
VIEW_NAMES = ("FRONT", "RIGHT")


def inch(mm: float) -> float:
    return mm / IN


def draw(f, path):
    return make_drawing(
        fd.flange_views(build_weld_neck_flange(f)),
        fd.annotate_flange,
        flange_title_block(f),
        path,
        view_gap=fd.VIEW_GAP,
        allowance=fd.ALLOWANCE,
    )


@pytest.fixture(scope="module")
def drawing(tmp_path_factory):
    path = tmp_path_factory.mktemp("dxf") / "f.dxf"
    res = draw(F, path)
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


def view_entities(doc, types=("LINE", "CIRCLE", "ARC")):
    return [e for n in VIEW_NAMES for e in view(doc, n) if e.dxftype() in types]


def size(entities):
    b = bbox.extents(entities)
    return b.size.x, b.size.y


def dims(doc):
    return list(doc.modelspace().query("DIMENSION"))


def dim_by_key(doc, key):
    from ai_cad_engine.verify import APPID

    found = [d for d in dims(doc) if d.has_xdata(APPID) and d.get_xdata(APPID)[0].value == key]
    assert len(found) == 1, key
    return found[0]


def shown(d):
    return [e.text for e in d.get_geometry_block() if e.dxftype() == "MTEXT"][0]


# ---- units, entities, linetypes ------------------------------------------------


def test_units_inch(doc):
    assert doc.header["$INSUNITS"] == INSUNITS_INCH
    assert doc.header["$MEASUREMENT"] == 0


def test_only_exact_entity_types(doc):
    # Dimensioning relies on real lines/circles/arcs, not approximations.
    types = {e.dxftype() for n in VIEW_NAMES for e in view(doc, n)}
    assert types <= {"LINE", "CIRCLE", "ARC", "HATCH"}


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


def test_profile_view_extents(doc):
    w, h = size(view_entities(doc) and [e for e in view(doc, "FRONT") if e.dxftype() != "HATCH"])
    assert w == pytest.approx(inch(F.length_through_hub), abs=TOL)
    assert h == pytest.approx(inch(F.od), abs=TOL)


def test_face_view_extents(doc):
    w, h = size(view(doc, "RIGHT"))
    assert w == pytest.approx(inch(F.od), abs=TOL)
    assert h == pytest.approx(inch(F.od), abs=TOL)


def test_face_view_bolt_holes(doc):
    circles = [e for e in view(doc, "RIGHT") if e.dxftype() == "CIRCLE"]
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


def test_views_aligned_third_angle(doc):
    f = bbox.extents(e for e in view(doc, "FRONT") if e.dxftype() != "HATCH")
    r = bbox.extents(view(doc, "RIGHT"))
    assert r.extmin.y == pytest.approx(f.extmin.y, abs=TOL)  # RIGHT beside FRONT
    assert r.extmax.y == pytest.approx(f.extmax.y, abs=TOL)
    assert r.extmin.x > f.extmax.x


# ---- half section ----------------------------------------------------------------


def test_section_has_no_hidden_lines(doc):
    assert not [e for e in view(doc, "FRONT") if e.dxf.layer == "HIDDEN"]


def test_section_hatch_area_matches_table(doc):
    # Independent check: half-section area through a bolt hole, from B16.5 values.
    b = F.bore / 2
    rf = (F.raised_face_dia / 2 - b) * F.raised_face_height
    ring = (F.od / 2 - b - F.bolt_hole_dia) * (F.thickness - F.raised_face_height)
    hub = ((F.hub_dia_base + F.hub_dia_weld) / 4 - b) * (F.length_through_hub - F.thickness)
    expected_in2 = (rf + ring + hub) / IN**2
    hatches = [e for e in view(doc, "FRONT") if e.dxftype() == "HATCH"]
    assert hatches and all(h.dxf.layer == "HATCH" and h.dxf.pattern_name == "ANSI31" for h in hatches)
    area = sum(
        loop_area([(v[0], v[1]) for v in p.vertices]) * (1 if p.path_type_flags & 1 else -1)
        for h in hatches
        for p in h.paths
    )
    assert area == pytest.approx(expected_in2, rel=1e-6)


def test_section_cuts_a_bolt_hole(doc):
    # Two hatch regions: inner (RF + ring + hub) and the ring outboard of the bolt hole.
    assert len([e for e in view(doc, "FRONT") if e.dxftype() == "HATCH"]) == 2


def test_no_object_line_on_half_section_boundary(doc):
    axis = [e for e in doc.modelspace() if e.dxf.layer == "CENTER" and e in group(doc, "ANNOT_FRONT")]
    ys = {round(e.dxf.start.y, 5) for e in axis if abs(e.dxf.start.y - e.dxf.end.y) < 1e-9}
    for e in view_entities(doc):
        if e.dxftype() == "LINE" and e in view(doc, "FRONT"):
            on_axis = abs(e.dxf.start.y - e.dxf.end.y) < 1e-9 and round(e.dxf.start.y, 5) in ys
            assert not (on_axis and abs(e.dxf.end.x - e.dxf.start.x) > inch(F.thickness)), e


# ---- dimensions ----------------------------------------------------------------

EXPECTED = {
    "od": (F.od, "%%c9.000"),
    "bolt_circle": (F.bolt_circle_dia, "%%c7.500 B.C."),
    "bolt_hole_dia": (F.bolt_hole_dia, "8X %%c.750 THRU"),
    "thickness": (F.thickness, ".940"),
    "length_through_hub": (F.length_through_hub, "3.000"),
    "raised_face_height": (F.raised_face_height, ".060"),
    "bore": (F.bore, "%%c4.026"),
    "raised_face_dia": (F.raised_face_dia, "%%c6.190"),
    "hub_dia_weld": (F.hub_dia_weld, "%%c4.500"),
    "hub_dia_base": (F.hub_dia_base, "%%c5.310"),
}


def test_dimensions_are_real_dimension_entities(doc):
    ds = dims(doc)
    assert len(ds) == len(EXPECTED)
    for d in ds:
        assert d.dxf.dimstyle == DIMSTYLE
        assert d.dxf.layer == "DIM"
        assert d.get_geometry_block() is not None  # rendered, displays without regen


# Measurements come from DIMENSION defpoints, which were snapped to drawn
# geometry, so these compare what the drawing shows against the standard.
@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_dimension_values_and_text(doc, key):
    nominal_mm, text = EXPECTED[key]
    d = dim_by_key(doc, key)
    assert d.get_measurement() == pytest.approx(inch(nominal_mm), abs=TOL)
    assert shown(d) == text


def test_bore_is_half_dimension(doc):
    # Only the sectioned half shows the bore: one arrowhead, one extension line.
    blk = dim_by_key(doc, "bore").get_geometry_block()
    arrows = [e.dxf.name for e in blk if e.dxftype() == "INSERT"]
    assert sorted(arrows) == ["_CLOSEDFILLED", "_NONE"]


def test_dimstyle(doc, sheet):
    st = doc.dimstyles.get(DIMSTYLE)
    assert st.dxf.dimlfac == 1.0
    assert st.dxf.dimdec == 3
    assert st.dxf.dimscale == sheet.scale
    assert st.dxf.dimtxt == 0.125  # paper inches, Y14.2 minimum


def test_centerlines(doc):
    front = [e for e in group(doc, "ANNOT_FRONT") if e.dxf.layer == "CENTER"]
    right = [e for e in group(doc, "ANNOT_RIGHT") if e.dxf.layer == "CENTER"]
    assert len(front) == 2  # axis + bolt hole in section
    circles = [e for e in right if e.dxftype() == "CIRCLE"]
    assert len(circles) == 1
    assert 2 * circles[0].dxf.radius == pytest.approx(inch(F.bolt_circle_dia), abs=TOL)
    assert len([e for e in right if e.dxftype() == "LINE"]) == 2 + F.bolt_hole_count


def test_dimensions_report_drawn_geometry_not_table(tmp_path):
    # A flange built 0.5 mm off must show the wrong value, not the table value.
    path = tmp_path / "bad.dxf"
    draw(replace(F, bolt_circle_dia=F.bolt_circle_dia + 0.5), path)
    d = dim_by_key(ezdxf.readfile(path), "bolt_circle")
    assert d.get_measurement() == pytest.approx(inch(F.bolt_circle_dia + 0.5), abs=TOL)


# ---- sheet ---------------------------------------------------------------------


def test_sheet_choice(sheet):
    assert (sheet.size, sheet.scale) == ("B", 2)


def test_everything_inside_content_area(doc, sheet):
    S = sheet.scale
    cx0, cy0, cx1, cy1 = (v * S for v in sheet.content_area())
    ents = [e for n in VIEW_NAMES for e in view(doc, n) + group(doc, f"ANNOT_{n}")]
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


def test_title_block_text_fits_cells(doc, sheet):
    from ai_cad_engine.drawing.sheet import CHAR_W

    S = sheet.scale
    bx0, by0, bx1, by1 = (v * S for v in sheet.title_block_rect())
    for t in doc.modelspace().query("TEXT"):
        x, y = t.dxf.insert.x, t.dxf.insert.y
        if not (bx0 <= x <= bx1 and by0 <= y <= by1):
            continue  # notes
        assert x + len(t.dxf.text) * t.dxf.height * CHAR_W <= bx1 + 1e-9, t.dxf.text


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
    """No dimension text box touches other dims' lines, other text, part geometry or centerlines."""
    ds = dims(doc)
    boxes = {d.dxf.handle: text_box(d) for d in ds}
    obstacles = []  # (owner handle or None, entity)
    for d in ds:
        for e in d.get_geometry_block():
            if e.dxftype() == "LINE":
                obstacles.append((d.dxf.handle, e))
    for e in view_entities(doc):
        obstacles.append((None, e))
    for n in VIEW_NAMES:
        for e in group(doc, f"ANNOT_{n}"):
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
