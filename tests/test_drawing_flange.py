from dataclasses import replace
from math import hypot

import ezdxf
import pytest
from ezdxf import bbox

from ai_cad_engine.drawing import flange_drawing as fd
from tests.drawing_checks import assert_dimension_text_clear, assert_inside_content_area
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
    assert_inside_content_area(doc, sheet)


def test_dimension_text_is_clear(doc):
    assert_dimension_text_clear(doc)


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


