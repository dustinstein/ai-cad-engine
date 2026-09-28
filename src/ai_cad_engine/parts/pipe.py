"""Straight pipe, butt-weld ends. Axis Z, end1 at Z=0, end2 at Z=length."""

from __future__ import annotations

from build123d import Align, BuildPart, Cylinder, Mode, Solid

from ai_cad_engine.assembly import Component, Port

_BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)


def build_pipe(od: float, wall: float, length: float) -> Solid:
    with BuildPart() as p:
        Cylinder(od / 2, length, align=_BOTTOM)
        Cylinder(od / 2 - wall, length, align=_BOTTOM, mode=Mode.SUBTRACT)
    return p.part


def pipe_component(
    tag: str, nps: str, od: float, wall: float, length: float, schedule: str, verified: bool = True
) -> Component:
    ends = {"od": od, "id": od - 2 * wall, "nps": nps}
    return Component(
        tag=tag,
        part_no=f"PIPE-{nps}-S{schedule}-{length / 25.4:.3f}",
        description=f'PIPE, NPS {nps}, SCH {schedule}, BE, CUT LENGTH {length / 25.4:.3f}"',
        solid=build_pipe(od, wall, length),
        ports={
            "end1": Port((0, 0, 0), (0, 0, -1), end="BW", attrs=ends),
            "end2": Port((0, 0, length), (0, 0, 1), end="BW", attrs=ends),
        },
        meta={"length": length, "od": od, "wall": wall, "verified": verified},
    )
