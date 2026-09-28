from dataclasses import replace
from math import pi

import pytest
from build123d import Plane

from ai_cad_engine.assemblies.transition import TransitionSpec, build_transition, critical_dims, measure
from ai_cad_engine.assembly import Assembly, validate_ports
from ai_cad_engine.parts import reducer as red_mod
from ai_cad_engine.parts.pipe import pipe_component
from ai_cad_engine.parts.reducer import build_ecc_reducer, reducer_component
from ai_cad_engine.standards.asme_b16_9 import IN, reducer
from ai_cad_engine.standards.asme_b36_10 import PipeSize
from ai_cad_engine.standards.tables import UnverifiedDataError
from ai_cad_engine.verify import build_report

R = reducer("12", "8", "80", "80", allow_unverified=True)


def failed(rep):
    return {i.key for i in rep.items if not i.passed}


def test_unverified_row_refused_without_flag():
    if R.verified:
        pytest.skip("row verified")
    with pytest.raises(UnverifiedDataError):
        reducer("12", "8", "80", "80")


def test_reducer_dims_on_solid():
    s = build_ecc_reducer(R)
    rep = build_report("t", "t", red_mod.critical_dims(R), red_mod.measure(s, True))
    assert rep.passed, rep.table()
    assert red_mod.measure(s, R.verified)["table_data_verified"] == float(R.verified)


def test_reducer_volume_matches_frustum_formula():
    # An oblique cone frustum has the right-frustum volume (Cavalieri): independent check.
    def frustum(r0, r1, h):
        return pi * h / 3 * (r0**2 + r0 * r1 + r1**2)

    h = R.length
    expected = frustum(R.large.od / 2, R.small.od / 2, h) - frustum(R.large.id / 2, R.small.id / 2, h)
    assert build_ecc_reducer(R).volume == pytest.approx(expected, rel=1e-6)


def test_reducer_ports_valid():
    assert validate_ports(reducer_component("R", R)) == []


@pytest.mark.parametrize("flat", ["bottom", "top"])
def test_transition_geometry_passes(flat):
    spec = TransitionSpec(R, 24 * IN, 24 * IN, flat)
    m, n = measure(build_transition(spec), spec)
    rep = build_report("t", "t", critical_dims(spec), m, notes=n)
    expect = set() if R.verified else {"table_data_verified"}
    assert failed(rep) == expect, rep.table()
    assert m["overall"] == pytest.approx(48 * IN + R.length + 2 * IN / 16, abs=1e-3)


def test_flat_on_wrong_side_detected():
    built = TransitionSpec(R, 24 * IN, 24 * IN, "top")
    wanted = replace(built, flat="bottom")
    m, n = measure(build_transition(built), wanted)
    assert m["flat"] == 0.0 and "bottom" in n["flat"]


def test_reducer_small_end_mismatch_with_pipe():
    thin = PipeSize("8", "40", R.small.od, 0.322 * IN)  # Sch 40 wall on the Sch 80 reducer end
    asm = Assembly("X")
    asm.add_root(reducer_component("R1", R), "large", Plane(origin=(0, 0, 0), x_dir=(0, 0, -1), z_dir=(-1, 0, 0)))
    asm.connect(pipe_component("P2", "8", thin.od, thin.wall, 500, "40"), "end1", "R1.small", gap=IN / 16)
    assert any("ID mismatch" in e for e in asm.connection_errors())


def test_align_x_parallel_to_axis_rejected():
    spec = TransitionSpec(R, 24 * IN, 24 * IN)
    asm = build_transition(spec)
    with pytest.raises(ValueError, match="parallel"):
        asm.connect(reducer_component("R9", R), "large", "P2.end2", gap=IN / 16, align_x=(1, 0, 0))
