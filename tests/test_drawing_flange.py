from math import hypot

import ezdxf
import pytest

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
    write_dxf(layout_third_angle(*views), path)
    return ezdxf.readfile(path)


def group(doc, name):
    return list(doc.groups.get(f"VIEW_{name}"))


def extents(entities):
    from ezdxf import bbox

    b = bbox.extents(entities)
    return b.size.x, b.size.y


def test_units_mm(doc):
    assert doc.header["$INSUNITS"] == INSUNITS_MM


def test_only_exact_entity_types(doc):
    # Dimensioning relies on real lines/circles/arcs, not approximations.
    types = {e.dxftype() for e in doc.modelspace()}
    assert types <= {"LINE", "CIRCLE", "ARC"}


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


def test_no_duplicate_entities(doc):
    seen = set()
    for e in doc.modelspace():
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
