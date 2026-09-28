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
    assert rows["PIPE-4-S40-42.000"]["qty"] == 1


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
    asm.connect(pipe_component("P1", p.nps, p.od, p.wall, SPEC.pipe_length, p.schedule), "end1", "F1.weld")
    asm.connect(flange_component("F2", F), "weld", "P1.end2", clock_deg=10)
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
    asm.connect(pipe_component("P1", p.nps, p.od, p.wall, SPEC.pipe_length, p.schedule), "end1", "F1.weld")
    asm.connect(flange_component("F2", F), "weld", "P1.end2", clock_deg=360 / F.bolt_hole_count)
    assert report(asm).passed
