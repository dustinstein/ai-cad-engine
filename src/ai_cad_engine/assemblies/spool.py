"""Flanged pipe spool: WN flange + pipe + WN flange, face-to-face length given.

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


@dataclass(frozen=True)
class SpoolSpec:
    flange: WeldNeckFlange
    pipe: PipeSize
    face_to_face: float  # mm

    @property
    def pipe_length(self) -> float:
        return self.face_to_face - 2 * self.flange.length_through_hub


def build_spool(spec: SpoolSpec, name: str = "SPOOL") -> Assembly:
    if spec.pipe_length <= 0:
        raise ValueError("face-to-face shorter than two flanges")
    p = spec.pipe
    asm = Assembly(name)
    # F1 face at origin looking -X, its straddled centerline vertical.
    asm.add_root(flange_component("F1", spec.flange), "face", Plane(origin=(0, 0, 0), x_dir=UP, z_dir=(-1, 0, 0)))
    asm.connect(pipe_component("P1", p.nps, p.od, p.wall, spec.pipe_length, p.schedule), "end1", "F1.weld")
    asm.connect(flange_component("F2", spec.flange), "weld", "P1.end2")
    return asm


def critical_dims(spec: SpoolSpec) -> list[CriticalDim]:
    return [
        CriticalDim("face_to_face", "Overall face-to-face length", spec.face_to_face),
        CriticalDim("component_count", "Components", 3, "count"),
        CriticalDim("ports_valid", "Every port sits on a matching planar face", 1, "check"),
        CriticalDim("connections", "Mated ports coincide, face each other, ends match", 1, "check"),
        CriticalDim("no_interference", "No overlapping material between components", 1, "check"),
        CriticalDim("two_holed", "Bolt holes of every flange straddle the vertical centerline", 1, "check"),
    ]


def measure(asm: Assembly) -> tuple[dict[str, float], dict[str, str]]:
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
    for key, probs in (("ports_valid", port_probs), ("connections", conn), ("no_interference", intf), ("two_holed", straddle)):
        if probs:
            notes[key] = "; ".join(probs)
    return (
        {
            "face_to_face": bb.size.X,
            "component_count": len(asm.placed),
            "ports_valid": float(not port_probs),
            "connections": float(not conn),
            "no_interference": float(not intf),
            "two_holed": float(not straddle),
        },
        notes,
    )
