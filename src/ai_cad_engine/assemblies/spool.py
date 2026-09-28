"""Flanged pipe spool: WN flange + pipe + WN flange, face-to-face length given.

Face-to-face is over the raised faces and includes both butt-weld root gaps, so the
pipe cut length = face-to-face - 2 x flange length - 2 x root gap.

Assembly frame: spool axis along +X from the F1 raised face at the origin; Z up.
Flanges are placed "two-holed": bolt holes straddle the vertical centerline.
"""

from __future__ import annotations

from dataclasses import dataclass

from build123d import Plane, Vector

from ai_cad_engine.assembly import Assembly, bolt_hole_angles, validate_ports
from ai_cad_engine.parts.pipe import pipe_component
from ai_cad_engine.parts.weld_neck_flange import WeldNeckFlange, flange_component
from ai_cad_engine.standards.asme_b36_10 import PipeSize
from ai_cad_engine.verify import CriticalDim

UP = Vector(0, 0, 1)
ANGLE_TOL = 0.01  # deg
DEFAULT_ROOT_GAP = 25.4 / 16  # 1/16"; typical 1/16"-1/8", set per weld procedure


@dataclass(frozen=True)
class SpoolSpec:
    flange: WeldNeckFlange
    pipe: PipeSize
    face_to_face: float  # mm, over the raised faces
    root_gap: float = DEFAULT_ROOT_GAP  # mm, at each butt weld

    @property
    def pipe_length(self) -> float:
        """Pipe cut length."""
        return self.face_to_face - 2 * self.flange.overall_length - 2 * self.root_gap


def build_spool(spec: SpoolSpec, name: str = "SPOOL") -> Assembly:
    if spec.pipe_length <= 0:
        raise ValueError("face-to-face shorter than two flanges")
    p = spec.pipe
    asm = Assembly(name)
    # F1 face at origin looking -X, its straddled centerline vertical.
    asm.add_root(flange_component("F1", spec.flange), "face", Plane(origin=(0, 0, 0), x_dir=UP, z_dir=(-1, 0, 0)))
    g = spec.root_gap
    asm.connect(pipe_component("P1", p.nps, p.od, p.wall, spec.pipe_length, p.schedule), "end1", "F1.weld", gap=g)
    asm.connect(flange_component("F2", spec.flange), "weld", "P1.end2", gap=g)
    return asm


def critical_dims(spec: SpoolSpec) -> list[CriticalDim]:
    return [
        CriticalDim("face_to_face", "Overall face-to-face length", spec.face_to_face),
        CriticalDim("component_count", "Components", 3, "count"),
        CriticalDim("pipe_cut_length", "Pipe cut length (F-F - 2 flanges - 2 root gaps)", spec.pipe_length),
        CriticalDim("root_gaps", f"Both butt-weld root gaps = {spec.root_gap / 25.4:.4f} in", 1, "check"),
        CriticalDim("ports_valid", "Every port sits on a matching planar face", 1, "check"),
        CriticalDim("connections", "Mated ports coincide, face each other, ends match", 1, "check"),
        CriticalDim("no_interference", "No overlapping material between components", 1, "check"),
        CriticalDim("two_holed", "Bolt holes of every flange straddle the vertical centerline", 1, "check"),
    ]


def measure(asm: Assembly, root_gap: float = DEFAULT_ROOT_GAP) -> tuple[dict[str, float], dict[str, str]]:
    """Measured values and failure notes. Length from geometry (extent along the spool axis)."""
    notes: dict[str, str] = {}
    bb = asm.compound().bounding_box()
    port_probs = [p for pl in asm.placed.values() for p in validate_ports(pl.comp)]
    conn = asm.connection_errors()
    intf = asm.interferences()
    straddle = []
    for tag, pl in asm.placed.items():
        n = pl.comp.ports.get("face", None)
        if n is None or "bolt_holes" not in n.attrs:
            continue
        pitch = 360 / n.attrs["bolt_holes"]
        angles = bolt_hole_angles(pl, "face", UP)
        off = [a % pitch for a in angles]
        if len(angles) != n.attrs["bolt_holes"] or any(abs(o - pitch / 2) > ANGLE_TOL for o in off):
            straddle.append(f"{tag}: hole angles from vertical {angles}")
    gaps = asm.gaps()
    gap_probs = [f"{a}/{b}: {g:.4f} mm" for a, b, g in gaps if abs(g - root_gap) > 1e-4]
    if len(gaps) != 2:
        gap_probs.append(f"expected 2 butt welds, found {len(gaps)}")
    pipe_solid = asm.placed["P1"].solid.bounding_box()
    for key, probs in (("root_gaps", gap_probs), ("ports_valid", port_probs), ("connections", conn), ("no_interference", intf), ("two_holed", straddle)):
        if probs:
            notes[key] = "; ".join(probs)
    return (
        {
            "face_to_face": bb.size.X,
            "component_count": len(asm.placed),
            "pipe_cut_length": pipe_solid.size.X,
            "root_gaps": float(not gap_probs),
            "ports_valid": float(not port_probs),
            "connections": float(not conn),
            "no_interference": float(not intf),
            "two_holed": float(not straddle),
        },
        notes,
    )
