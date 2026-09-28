"""ASME B36.10M welded and seamless wrought steel pipe: OD and wall by NPS/schedule.

Data: data/asme_b36_10.csv (inch). Stored here in mm.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_cad_engine.standards.tables import TableSanityError, find, load, yes

IN = 25.4
TABLE = "asme_b36_10.csv"


@dataclass(frozen=True)
class PipeSize:
    nps: str
    schedule: str
    od: float
    wall: float
    verified: bool = True

    @property
    def id(self) -> float:
        return self.od - 2 * self.wall


def check_row(r: dict) -> None:
    od, wall = float(r["od"]), float(r["wall"])
    if not 0 < wall < od / 2:
        raise TableSanityError(f"B36.10 NPS {r['nps']} SCH {r['schedule']}: wall {wall} vs OD {od}")


def pipe(nps: str, schedule: str, allow_unverified: bool = False) -> PipeSize:
    r = find(TABLE, allow_unverified, nps=nps, schedule=schedule)
    check_row(r)
    return PipeSize(nps, schedule, float(r["od"]) * IN, float(r["wall"]) * IN, yes(r["verified"]))


def all_rows() -> tuple[dict, ...]:
    return load(TABLE)
