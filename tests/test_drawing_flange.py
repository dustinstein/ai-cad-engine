from math import hypot

import ezdxf
import pytest

from ai_cad_engine.drawing.annotate import DIMSTYLE, annotate_flange
from ai_cad_engine.drawing.dxf_writer import (
    INSUNITS_MM,
    layout_third_angle,
    write_dxf,
)
from ai_cad_engine.drawing.views import FRONT, RIGHT, TOP, project
from ai_cad_engine.parts.weld_neck_flange import build_weld_neck_flange
from ai_cad_engine.standards.asme_b16_5 import WN_4_150 as F

TOL = 0.01


@pytest.fixture(scope="module")
def doc(tmp_path_factory):
    part = build_weld_neck_flange(F)
    views = [project(part, s) for s in (FRONT, TOP, RIGHT)]
    path = tmp_path_factory.mktemp("dxf") / "f.dxf"
    write_dxf(layout_third_angle(*views), path, annotate=annotate_flange)
    return ezdxf.readfile(path)


def group(doc, name):
    return list(doc.groups.get(f"VIEW_{name}"))


def extents(entities):
    from ezdxf import bbox

    b = bbox.extents(entities)
    return b.size.x, b.size.y


def test_units_mm(doc):
    assert doc.header["$INSUNITS"] == INSUNITS_MM


VIEW_NAMES = ("FRONT", "TOP", "RIGHT")


def view_entities(doc):
    return [e for n in VIEW_NAMES for e in group(doc, n)]


def test_only_exact_entity_types(doc):
    # Dimensioning relies on real lines/circles/arcs, not approximations.
    assert {e.dxftype() for e in view_entities(doc)} <= {"LINE", "CIRCLE", "ARC"}
    assert {e.dxftype() for e in doc.modelspace()} <= {"LINE", "CIRCLE", "ARC", "DIMENSION"}


def test_hidden_layer_uses_hidden_linetype(doc):
    assert doc.layers.get("HIDDEN").dxf.linetype == "HIDDEN"
    lt = doc.linetypes.get("HIDDEN")  # raises if the linetype isn't defined
    dashes = [t.value for t in lt.pattern_tags.tags if t.code == 49]
    assert max(dashes) >= 2.0  # readable at 1:1 in mm


@pytest.mark.parametrize("name", ["FRONT", "RIGHT"])
def test_profile_view_extents(doc, name):
    w, h = extents(group(doc, name))
    assert w == pytest.approx(F.od, abs=TOL)
    assert h == pytest.approx(F.length_through_hub, abs=TOL)


def test_top_view_extents(doc):
    w, h = extents(group(doc, "TOP"))
    assert w == pytest.approx(F.od, abs=TOL)
    assert h == pytest.approx(F.od, abs=TOL)


def test_top_view_bolt_holes(doc):
    circles = [e for e in group(doc, "TOP") if e.dxftype() == "CIRCLE"]
    od = [c for c in circles if abs(c.dxf.radius - F.od / 2) < TOL]
    assert len(od) == 1
    cx, cy = od[0].dxf.center.x, od[0].dxf.center.y
    holes = [
        c
        for c in circles
        if abs(c.dxf.radius - F.bolt_hole_dia / 2) < TOL and c.dxf.layer == "VISIBLE"
    ]
    assert len(holes) == F.bolt_hole_count
    for h in holes:
        r = hypot(h.dxf.center.x - cx, h.dxf.center.y - cy)
        assert 2 * r == pytest.approx(F.bolt_circle_dia, abs=TOL)


def test_front_view_hidden_bore(doc):
    hidden = [e for e in group(doc, "FRONT") if e.dxf.layer == "HIDDEN"]
    xs = sorted({round(e.dxf.start.x, 3) for e in hidden})
    # Outermost hidden lines in FRONT are bolt hole edges; bore lines are full length.
    full = [e for e in hidden if abs(abs(e.dxf.end.y - e.dxf.start.y) - F.length_through_hub) < TOL]
    assert len(full) == 2
    assert abs(full[0].dxf.start.x - full[1].dxf.start.x) == pytest.approx(F.bore, abs=TOL)
    assert len(xs) == 10


def test_all_referenced_linetypes_defined(doc):
    for layer in doc.layers:
        assert layer.dxf.linetype in doc.linetypes, layer.dxf.name


def test_only_standard_linetype_names(doc):
    # Alibre maps linetypes by name; a custom name imports as solid.
    standard = {"CONTINUOUS", "BYLAYER", "BYBLOCK", "HIDDEN", "CENTER"}
    for layer in doc.layers:
        assert layer.dxf.linetype.upper() in standard, (layer.dxf.name, layer.dxf.linetype)


@pytest.mark.parametrize("name", ["HIDDEN", "CENTER"])
def test_linetype_dashes_readable_in_mm(doc, name):
    dashes = [t.value for t in doc.linetypes.get(name).pattern_tags.tags if t.code == 49]
    assert max(dashes) >= 2.0


def test_no_duplicate_entities(doc):
    seen = set()
    for e in view_entities(doc):
        if e.dxftype() == "LINE":
            a, b = sorted([tuple(round(v, 4) for v in e.dxf.start), tuple(round(v, 4) for v in e.dxf.end)])
            key = ("L", a, b)
        else:
            key = (e.dxftype(), tuple(round(v, 4) for v in e.dxf.center), round(e.dxf.radius, 4))
        assert key not in seen, key
        seen.add(key)


def test_views_aligned_third_angle(doc):
    from ezdxf import bbox

    f, t, r = (bbox.extents(group(doc, n)) for n in ("FRONT", "TOP", "RIGHT"))
    assert t.extmin.x == pytest.approx(f.extmin.x, abs=TOL)  # TOP above FRONT
    assert t.extmin.y > f.extmax.y
    assert r.extmin.y == pytest.approx(f.extmin.y, abs=TOL)  # RIGHT beside FRONT
    assert r.extmin.x > f.extmax.x


def dims(doc):
    return list(doc.modelspace().query("DIMENSION"))


def dia_dim_by_text(doc, text):
    found = [d for d in dims(doc) if d.dimtype & 0xF == 3 and d.dxf.text == text]
    assert len(found) == 1, text
    return found[0]


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
    "text,expected",
    [
        ("<>", F.od),
        ("<> B.C.", F.bolt_circle_dia),
        ("8X <> THRU", F.bolt_hole_dia),
    ],
)
def test_diameter_dimensions(doc, text, expected):
    d = dia_dim_by_text(doc, text)
    assert d.get_measurement() == pytest.approx(expected, abs=TOL)


def test_linear_dimensions(doc):
    lin = sorted((d for d in dims(doc) if d.dimtype & 0xF in (0, 1)), key=lambda d: d.get_measurement())
    assert [d.get_measurement() for d in lin] == pytest.approx(
        [F.thickness, F.length_through_hub], abs=TOL
    )


def test_dimstyle_is_unscaled_mm(doc):
    st = doc.dimstyles.get(DIMSTYLE)
    assert st.dxf.dimlfac == 1.0
    assert st.dxf.dimdec == 2


def test_centerlines(doc):
    cl = [e for e in doc.modelspace() if e.dxf.layer == "CENTER"]
    circles = [e for e in cl if e.dxftype() == "CIRCLE"]
    assert len(circles) == 1
    assert 2 * circles[0].dxf.radius == pytest.approx(F.bolt_circle_dia, abs=TOL)
    # 2 cross lines + 8 hole marks in TOP, 1 axis line each in FRONT and RIGHT
    assert len([e for e in cl if e.dxftype() == "LINE"]) == 2 + F.bolt_hole_count + 2


def test_dimensions_report_drawn_geometry_not_table(tmp_path):
    # A flange built 0.5 mm off must show the wrong value, not the table value.
    from dataclasses import replace

    bad = replace(F, bolt_circle_dia=F.bolt_circle_dia + 0.5)
    part = build_weld_neck_flange(bad)
    path = tmp_path / "bad.dxf"
    write_dxf(layout_third_angle(*(project(part, s) for s in (FRONT, TOP, RIGHT))), path, annotate=annotate_flange)
    d = dia_dim_by_text(ezdxf.readfile(path), "<> B.C.")
    assert d.get_measurement() == pytest.approx(F.bolt_circle_dia + 0.5, abs=TOL)
