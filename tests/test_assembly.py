from dataclasses import replace

import pytest
from build123d import Plane, import_step

from ai_cad_engine.assemblies.spool import SpoolSpec, build_spool, critical_dims, measure
from ai_cad_engine.assembly import Assembly, Component, Port, validate_ports
from ai_cad_engine.parts.pipe import pipe_component
from ai_cad_engine.parts.weld_neck_flange import flange_component
from ai_cad_engine.standards.asme_b16_5 import IN, WN_4_150 as F
from ai_cad_engine.standards.asme_b36_10 import PipeSize, pipe
from ai_cad_engine.verify import build_report

SPEC = SpoolSpec(F, pipe("4", "40"), 48 * IN)


@pytest.fixture(scope="module")
def spool():
    return build_spool(SPEC)


def report(asm, spec=SPEC):
    model, notes = measure(asm)
    return build_report("t", "t", critical_dims(spec), model, notes=notes)


def failed(rep):
    return {i.key for i in rep.items if not i.passed}


# ---- components ----------------------------------------------------------------


def test_component_ports_match_geometry():
    assert validate_ports(flange_component("F", F)) == []
    assert validate_ports(pipe_component("P", "4", 114.3, 6.0198, 500, "40")) == []


def test_port_validation_catches_misplaced_port():
    c = flange_component("F", F)
    bad = Component(c.tag, c.part_no, c.description, c.solid, dict(c.ports, weld=replace(c.ports["weld"], origin=(0, 0, 70))))
    assert validate_ports(bad) and "F.weld" in validate_ports(bad)[0]


def test_pipe_and_flange_tables_agree():
    # Independent tables: B36.10 pipe and B16.5 flange hub/bore must match at the weld.
    p = pipe("4", "40")
    assert p.od == pytest.approx(F.hub_dia_weld)
    assert p.id == pytest.approx(F.bore, abs=1e-3)


# ---- spool ---------------------------------------------------------------------


def test_spool_passes(spool):
    rep = report(spool)
    assert rep.passed, rep.table()


def test_face_to_face(spool):
    bb = spool.compound().bounding_box()
    assert bb.size.X == pytest.approx(48 * IN, abs=1e-3)
    assert bb.min.X == pytest.approx(0, abs=1e-6)  # F1 raised face at the origin


def test_bom(spool):
    rows = {r["part_no"]: r for r in spool.bom()}
    assert rows["WN-4-150-RF-S40"]["qty"] == 2
    assert rows["PIPE-4-S40-41.875"]["qty"] == 1  # 48 - 2 x 3.000 - 2 x 1/16 root gap


def test_step_is_named_assembly(spool, tmp_path):
    path = tmp_path / "s.step"
    spool.export_step(path)
    back = import_step(path)
    assert sorted(c.label for c in back.children) == ["F1", "F2", "P1"]
    assert sum(c.volume for c in back.children) == pytest.approx(spool.compound().volume, rel=1e-6)
    assert "NEXT_ASSEMBLY_USAGE_OCCURRENCE" in path.read_text()


# ---- negative cases: the checks must fail ---------------------------------------


def test_wrong_pipe_schedule_fails_weld_match():
    sch80 = PipeSize("4", "80", 4.5 * IN, 0.337 * IN)  # heavier wall than the Sch 40 flange bore
    rep = report(build_spool(replace(SPEC, pipe=sch80)), replace(SPEC, pipe=sch80))
    assert failed(rep) == {"connections"}
    assert "ID mismatch" in next(i.note for i in rep.items if i.key == "connections")


def test_misclocked_flange_fails_two_holing():
    asm = Assembly("X")
    asm.add_root(flange_component("F1", F), "face", Plane(origin=(0, 0, 0), x_dir=(0, 0, 1), z_dir=(-1, 0, 0)))
    p = SPEC.pipe
    g = SPEC.root_gap
    asm.connect(pipe_component("P1", p.nps, p.od, p.wall, SPEC.pipe_length, p.schedule), "end1", "F1.weld", gap=g)
    asm.connect(flange_component("F2", F), "weld", "P1.end2", clock_deg=10, gap=g)
    rep = report(asm)
    assert failed(rep) == {"two_holed"}
    assert "F2" in next(i.note for i in rep.items if i.key == "two_holed")


def test_overlap_fails_interference_and_connection():
    asm = Assembly("X")
    asm.add_root(flange_component("F1", F), "face", Plane(origin=(0, 0, 0), x_dir=(0, 0, 1), z_dir=(-1, 0, 0)))
    p = SPEC.pipe
    pc = pipe_component("P1", p.nps, p.od, p.wall, SPEC.pipe_length, p.schedule)
    # Pipe pushed 10 mm into the flange hub instead of connected.
    asm.add_root(pc, "end1", Plane(origin=(F.length_through_hub - 10, 0, 0), x_dir=(0, 0, 1), z_dir=(-1, 0, 0)))
    assert asm.interferences()


def test_short_face_to_face_rejected():
    with pytest.raises(ValueError):
        build_spool(replace(SPEC, face_to_face=5 * IN))


def test_clock_by_one_hole_pitch_keeps_two_holing():
    asm = Assembly("X")
    asm.add_root(flange_component("F1", F), "face", Plane(origin=(0, 0, 0), x_dir=(0, 0, 1), z_dir=(-1, 0, 0)))
    p = SPEC.pipe
    g = SPEC.root_gap
    asm.connect(pipe_component("P1", p.nps, p.od, p.wall, SPEC.pipe_length, p.schedule), "end1", "F1.weld", gap=g)
    asm.connect(flange_component("F2", F), "weld", "P1.end2", clock_deg=360 / F.bolt_hole_count, gap=g)
    assert report(asm).passed


# ---- root gap ------------------------------------------------------------------


def test_default_root_gap_is_sixteenth():
    assert SPEC.root_gap == pytest.approx(IN / 16)
    assert SPEC.pipe_length == pytest.approx((48 - 2 * 3.0 - 2 / 16) * IN)


def test_gaps_measured_on_placed_parts(spool):
    gaps = spool.gaps()
    assert len(gaps) == 2
    assert all(g == pytest.approx(IN / 16, abs=1e-6) for *_, g in gaps)


@pytest.mark.parametrize("gap_in", [0, 3 / 32, 1 / 8])
def test_face_to_face_holds_for_any_gap(gap_in):
    spec = replace(SPEC, root_gap=gap_in * IN)
    asm = build_spool(spec)
    model, notes = measure(asm, spec.root_gap)
    rep = build_report("t", "t", critical_dims(spec), model, notes=notes)
    assert rep.passed, rep.table()
    assert asm.compound().bounding_box().size.X == pytest.approx(48 * IN, abs=1e-3)


def test_pipe_cut_to_zero_gap_length_fails_with_gap():
    # The user's catch: 42.000" of pipe with 1/16" gaps makes the spool 48.125" long.
    spec = replace(SPEC, root_gap=IN / 16)
    asm = Assembly("X")
    asm.add_root(flange_component("F1", F), "face", Plane(origin=(0, 0, 0), x_dir=(0, 0, 1), z_dir=(-1, 0, 0)))
    p = SPEC.pipe
    asm.connect(pipe_component("P1", p.nps, p.od, p.wall, 42 * IN, p.schedule), "end1", "F1.weld", gap=spec.root_gap)
    asm.connect(flange_component("F2", F), "weld", "P1.end2", gap=spec.root_gap)
    model, notes = measure(asm, spec.root_gap)
    assert model["face_to_face"] == pytest.approx(48.125 * IN, abs=1e-3)
    rep = build_report("t", "t", critical_dims(spec), model, notes=notes)
    assert failed(rep) == {"face_to_face", "pipe_cut_length"}


def test_wrong_gap_detected():
    asm = build_spool(SPEC)
    model, notes = measure(asm, root_gap=IN / 8)  # procedure says 1/8", built with 1/16"
    assert model["root_gaps"] == 0.0 and "P1" in notes["root_gaps"]


def test_gap_rejected_on_flanged_joint():
    asm = Assembly("X")
    asm.add_root(flange_component("F1", F), "face", Plane(origin=(0, 0, 0), x_dir=(0, 0, 1), z_dir=(-1, 0, 0)))
    with pytest.raises(ValueError, match="butt-weld"):
        asm.connect(flange_component("F2", F), "face", "F1.face", gap=1.0)


def test_connection_check_catches_moved_part(spool):
    import copy

    from build123d import Location

    asm = copy.copy(spool)
    asm.placed = dict(spool.placed)
    pl = asm.placed["P1"]
    asm.placed["P1"] = type(pl)(pl.comp, Location((0.5, 0, 0)) * pl.loc)  # slid 0.5 mm
    assert any("P1" in e for e in asm.connection_errors())
