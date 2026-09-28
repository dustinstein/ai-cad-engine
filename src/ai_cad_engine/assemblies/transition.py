"""Barrel transition: large pipe -> B16.9 eccentric reducer -> small pipe.

The pig-launcher break between the oversize barrel and the line-size barrel.
Assembly frame: axis along +X from the large pipe's free end at the origin, Z up.
The reducer is flat-on-bottom (FOB) by default, so both barrels share a bottom
elevation (outside) — measured on geometry, not assumed.
"""

from __future__ import annotations

from dataclasses import dataclass

from build123d import Plane, Vector

from ai_cad_engine.assembly import Assembly, validate_ports
from ai_cad_engine.assemblies.spool import DEFAULT_ROOT_GAP
from ai_cad_engine.parts.pipe import pipe_component
from ai_cad_engine.parts.reducer import reducer_component
from ai_cad_engine.standards.asme_b16_9 import Reducer
from ai_cad_engine.verify import CriticalDim

DOWN = (0, 0, -1)
UP = (0, 0, 1)


@dataclass(frozen=True)
class TransitionSpec:
    reducer: Reducer
    large_length: float  # mm, large pipe cut length
    small_length: float  # mm, small pipe cut length
    flat: str = "bottom"  # "bottom" (FOB) or "top" (FOT)
    root_gap: float = DEFAULT_ROOT_GAP

    @property
    def overall(self) -> float:
        return self.large_length + self.reducer.length + self.small_length + 2 * self.root_gap


def build_transition(spec: TransitionSpec, name: str = "TRANSITION") -> Assembly:
    r, g = spec.reducer, spec.root_gap
    L, S = r.large, r.small
    asm = Assembly(name)
    asm.add_root(
        pipe_component("P1", L.nps, L.od, L.wall, spec.large_length, L.schedule, L.verified),
        "end1",
        Plane(origin=(0, 0, 0), x_dir=UP, z_dir=(-1, 0, 0)),
    )
    flat = DOWN if spec.flat == "bottom" else UP
    asm.connect(reducer_component("R1", r), "large", "P1.end2", gap=g, align_x=flat)
    asm.connect(
        pipe_component("P2", S.nps, S.od, S.wall, spec.small_length, S.schedule, S.verified), "end1", "R1.small", gap=g
    )
    return asm


def critical_dims(spec: TransitionSpec) -> list[CriticalDim]:
    return [
        CriticalDim("overall", "Overall length (pipe + reducer + pipe + gaps)", spec.overall),
        CriticalDim("flat", f"Flat on {spec.flat}: barrels share the {spec.flat} (outside) elevation", 1, "check"),
        CriticalDim("root_gaps", f"Both root gaps = {spec.root_gap / 25.4:.4f} in", 1, "check"),
        CriticalDim("ports_valid", "Every port sits on a matching planar face", 1, "check"),
        CriticalDim("connections", "Mated ports coaxial, face to face, gap apart, ends match", 1, "check"),
        CriticalDim("no_interference", "No overlapping material between components", 1, "check"),
        CriticalDim("table_data_verified", "All table data verified", 1, "check"),
    ]


def measure(asm: Assembly, spec: TransitionSpec) -> tuple[dict[str, float], dict[str, str]]:
    notes: dict[str, str] = {}
    b1 = asm.placed["P1"].solid.bounding_box()
    b2 = asm.placed["P2"].solid.bounding_box()
    if spec.flat == "bottom":
        flat_err = abs(b1.min.Z - b2.min.Z)
    else:
        flat_err = abs(b1.max.Z - b2.max.Z)
    gaps = asm.gaps()
    gap_probs = [f"{a}/{b}: {g:.4f} mm" for a, b, g in gaps if abs(g - spec.root_gap) > 1e-4]
    checks = {
        "flat": [f"P1 vs P2 {spec.flat} elevations differ by {flat_err:.4f} mm"] if flat_err > 1e-4 else [],
        "root_gaps": gap_probs,
        "ports_valid": [p for pl in asm.placed.values() for p in validate_ports(pl.comp)],
        "connections": asm.connection_errors(),
        "no_interference": asm.interferences(),
        "table_data_verified": [f"unverified table data: {', '.join(asm.unverified())}"] if asm.unverified() else [],
    }
    for k, v in checks.items():
        if v:
            notes[k] = "; ".join(v)
    model = {k: float(not v) for k, v in checks.items()}
    model["overall"] = asm.compound().bounding_box().size.X
    return model, notes
