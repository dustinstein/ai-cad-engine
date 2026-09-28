import json
from dataclasses import replace

import ezdxf
import pytest

from ai_cad_engine.drawing.annotate import annotate_flange
from ai_cad_engine.drawing.make import make_drawing
from ai_cad_engine.parts.weld_neck_flange import build_weld_neck_flange, critical_dims, measure
from ai_cad_engine.standards.asme_b16_5 import WN_4_150 as F, flange_title_block
from ai_cad_engine.verify import APPID, _fmt_inch, _number_in, build_report

DRAWN = {"od", "bolt_circle", "bolt_hole_dia", "bolt_hole_count", "thickness", "length_through_hub"}


def run(f, tmp_path, name="f"):
    """Build part + drawing for table entry f, verify against the TRUE table (F)."""
    part = build_weld_neck_flange(f)
    path = tmp_path / f"{name}.dxf"
    make_drawing(part, annotate_flange, flange_title_block(f), path)
    return build_report("test", "ASME B16.5", critical_dims(F), measure(part), path), path


@pytest.fixture(scope="module")
def good(tmp_path_factory):
    return run(F, tmp_path_factory.mktemp("good"))


def by_key(rep):
    return {i.key: i for i in rep.items}


def test_good_flange_passes(good):
    rep, _ = good
    assert rep.passed, rep.table()
    assert len(rep.items) == 12
    assert {k for k, i in by_key(rep).items() if i.drawing_pass is not None} == DRAWN


def test_json_report(good):
    d = json.loads(good[0].to_json())
    assert d["passed"] is True
    assert d["standard"] == "ASME B16.5"
    assert set(d["not_on_drawing"]) == {i.key for i in critical_dims(F)} - DRAWN
    thk = next(i for i in d["items"] if i["key"] == "thickness")
    assert thk["drawing_text"] == ".940" and thk["expected_text"] == ".940"


def test_wrong_bolt_circle_fails_model_and_drawing(tmp_path):
    rep, _ = run(replace(F, bolt_circle_dia=F.bolt_circle_dia + 0.5), tmp_path)
    items = by_key(rep)
    assert not rep.passed
    assert not items["bolt_circle"].model_pass
    assert items["bolt_circle"].drawing_pass is False
    failed = {k for k, i in items.items() if not i.passed}
    assert failed == {"bolt_circle"}


def test_wrong_hole_count_fails_model_and_callout(tmp_path):
    rep, _ = run(replace(F, bolt_hole_count=4), tmp_path)
    items = by_key(rep)
    assert not items["bolt_hole_count"].model_pass
    assert items["bolt_hole_count"].drawing == 4
    assert items["bolt_hole_count"].drawing_pass is False


def test_small_error_below_display_precision_still_caught(tmp_path):
    # +0.01 mm (0.0004 in) still displays "3.000", but the 0.005 mm measurement check catches it.
    rep, _ = run(replace(F, length_through_hub=F.length_through_hub + 0.01), tmp_path)
    i = by_key(rep)["length_through_hub"]
    assert i.drawing_text == "3.000"
    assert i.drawing_pass is False and not i.model_pass


def test_tampered_display_text_fails(good, tmp_path):
    # Geometry right but the drawing SHOWS the wrong number -> drawing check fails.
    _, path = good
    doc = ezdxf.readfile(path)
    for d in doc.modelspace().query("DIMENSION"):
        if d.has_xdata(APPID) and d.get_xdata(APPID)[0].value == "thickness":
            for e in d.get_geometry_block():
                if e.dxftype() == "MTEXT":
                    e.text = ".950"
    bad = tmp_path / "tampered.dxf"
    doc.saveas(bad)
    part = build_weld_neck_flange(F)
    rep = build_report("t", "ASME B16.5", critical_dims(F), measure(part), bad)
    i = by_key(rep)["thickness"]
    assert i.model_pass and i.drawing is not None
    assert i.drawing_pass is False


def test_hub_and_rf_errors_caught_on_model(tmp_path):
    rep, _ = run(replace(F, hub_dia_base=F.hub_dia_base + 0.5, raised_face_height=F.raised_face_height + 0.5), tmp_path)
    failed = {i.key for i in rep.items if not i.passed}
    # RF height change also moves the flange body; thickness and length are fixed in the builder.
    assert {"hub_dia_base", "raised_face_height"} <= failed


@pytest.mark.parametrize(
    "v,dec,s", [(0.94, 3, ".940"), (9.0, 3, "9.000"), (0.75, 3, ".750"), (7.5, 3, "7.500")]
)
def test_fmt_inch(v, dec, s):
    assert _fmt_inch(v, dec) == s


@pytest.mark.parametrize(
    "text,num", [("8X %%c.750 THRU", ".750"), ("%%c9.000", "9.000"), (".940", ".940"), ("%%c7.500 B.C.", "7.500")]
)
def test_number_in(text, num):
    assert _number_in(text) == num
