import pytest
from build123d import import_step

from ai_cad_engine.measure import z_axis_cylinders
from ai_cad_engine.parts.weld_neck_flange import build_weld_neck_flange
from ai_cad_engine.standards.asme_b16_5 import IN, WN_4_150

TOL = 0.01  # mm; geometry is exact, so this only absorbs float noise


@pytest.fixture(scope="module")
def flange():
    return build_weld_neck_flange(WN_4_150)


@pytest.fixture(scope="module")
def bolt_holes(flange):
    holes = z_axis_cylinders(flange)
    return [h for h in holes if h.radial_pos > TOL]  # exclude the bore


def test_table_values_are_b16_5():
    # Guard against someone editing the table: published inch values.
    f = WN_4_150
    assert f.od == pytest.approx(9.00 * IN)
    assert f.bolt_circle_dia == pytest.approx(7.50 * IN)
    assert f.bolt_hole_dia == pytest.approx(0.75 * IN)
    assert f.bolt_hole_count == 8
    assert f.length_through_hub == pytest.approx(3.00 * IN)


def test_od(flange):
    bb = flange.bounding_box()
    assert bb.size.X == pytest.approx(WN_4_150.od, abs=TOL)
    assert bb.size.Y == pytest.approx(WN_4_150.od, abs=TOL)


def test_overall_length(flange):
    assert flange.bounding_box().size.Z == pytest.approx(
        WN_4_150.length_through_hub, abs=TOL
    )


def test_bolt_hole_count_and_dia(bolt_holes):
    assert len(bolt_holes) == WN_4_150.bolt_hole_count
    for h in bolt_holes:
        assert h.dia == pytest.approx(WN_4_150.bolt_hole_dia, abs=TOL)


def test_bolt_circle(bolt_holes):
    for h in bolt_holes:
        assert 2 * h.radial_pos == pytest.approx(WN_4_150.bolt_circle_dia, abs=TOL)


def test_bolt_holes_straddle_centerlines(bolt_holes):
    for h in bolt_holes:
        assert abs(h.x) > 1 and abs(h.y) > 1


def test_step_roundtrip(flange, tmp_path):
    from build123d import Unit, export_step

    p = tmp_path / "f.step"
    export_step(flange, p, unit=Unit.MM)
    back = import_step(p)
    bb = back.bounding_box()
    assert bb.size.X == pytest.approx(WN_4_150.od, abs=TOL)
    assert bb.size.Z == pytest.approx(WN_4_150.length_through_hub, abs=TOL)
    assert back.volume == pytest.approx(flange.volume, rel=1e-6)
