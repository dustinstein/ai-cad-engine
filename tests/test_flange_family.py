"""Every B16.5 weld-neck row (verified and DRAFT) builds, verifies on model and drawing,
and produces a readable drawing. Drafts are allowed here only to exercise geometry and
layout; production scripts refuse unverified rows."""

from functools import partial

import ezdxf
import pytest

from ai_cad_engine.drawing import flange_drawing as fd
from ai_cad_engine.drawing.make import make_drawing
from ai_cad_engine.drawing.views import loop_area
from ai_cad_engine.parts.weld_neck_flange import build_weld_neck_flange, critical_dims, measure
from ai_cad_engine.standards.asme_b16_5 import IN, all_rows, check_row, flange_title_block, wn_flange
from ai_cad_engine.standards.asme_b36_10 import all_rows as pipe_rows
from ai_cad_engine.standards.asme_b36_10 import check_row as check_pipe_row
from ai_cad_engine.standards.tables import TableSanityError, UnverifiedDataError
from ai_cad_engine.verify import build_report
from tests.drawing_checks import assert_dimension_text_clear, assert_inside_content_area

# Bore schedule used for each class in the family tests.
SCHEDULE = {"150": "40", "600": "80"}
ROWS = [(r["nps"], int(r["class"])) for r in all_rows()]


def test_all_rows_sane():
    for r in all_rows():
        check_row(r)
    for r in pipe_rows():
        check_pipe_row(r)


def test_unverified_rows_are_refused():
    drafts = [r for r in all_rows() if r["verified"] != "yes"]
    assert drafts, "no draft rows left; drop this test or keep one"
    r = drafts[0]
    with pytest.raises(UnverifiedDataError):
        wn_flange(r["nps"], int(r["class"]), SCHEDULE[r["class"]])


def test_sanity_catches_typo():
    r = dict(all_rows()[0], R="8.19")  # raised face bigger than the bolt circle allows
    with pytest.raises(TableSanityError, match="raised face"):
        check_row(r)


@pytest.fixture(scope="module", params=ROWS, ids=[f"{n}-{c}" for n, c in ROWS])
def built(request, tmp_path_factory):
    nps, cls = request.param
    f = wn_flange(nps, cls, SCHEDULE[str(cls)], allow_unverified=True)
    part = build_weld_neck_flange(f)
    path = tmp_path_factory.mktemp("fam") / f"{nps}_{cls}.dxf"
    res = make_drawing(
        fd.flange_views(part),
        partial(fd.annotate_flange, rf_in_cy=f.rf_in_cy),
        flange_title_block(f),
        path,
        view_gap=fd.VIEW_GAP,
        allowance=fd.ALLOWANCE,
    )
    return f, part, path, res, ezdxf.readfile(path)


def test_verification_passes(built):
    f, part, path, _, _ = built
    rep = build_report("t", "t", critical_dims(f), measure(part, f.rf_in_cy), path)
    assert rep.passed, rep.table()
    assert {i.key for i in rep.items if i.drawing_pass is None} == {"bolt_hole_offset"}


def test_rf_convention(built):
    f, part, *_ = built
    bb = part.bounding_box()
    expected = f.length_through_hub + (0 if f.rf_in_cy else f.raised_face_height)
    assert bb.size.Z == pytest.approx(expected, abs=1e-6)


def test_readable_and_inside_sheet(built):
    *_, res, doc = built
    assert_dimension_text_clear(doc)
    assert_inside_content_area(doc, res.sheet)


def test_section_area(built):
    f, *_, doc = built
    b = f.bore / 2
    rf = (f.raised_face_dia / 2 - b) * f.raised_face_height
    ring = (f.od / 2 - b - f.bolt_hole_dia) * (f.face_to_back - f.raised_face_height)
    hub = ((f.hub_dia_base + f.hub_dia_weld) / 4 - b) * (f.overall_length - f.face_to_back)
    hatches = [e for e in doc.groups.get("VIEW_FRONT") if e.dxftype() == "HATCH"]
    area = sum(
        loop_area([(v[0], v[1]) for v in p.vertices]) * (1 if p.path_type_flags & 1 else -1)
        for h in hatches
        for p in h.paths
    )
    assert area == pytest.approx((rf + ring + hub) / IN**2, rel=1e-6)
