"""ASME B36.10M welded and seamless wrought steel pipe: OD and wall by NPS/schedule.

Inch values x 25.4, stored in mm. Entries must be checked against the user's copy
of the standard before use (same rule as every other table here).
"""

from dataclasses import dataclass

IN = 25.4


@dataclass(frozen=True)
class PipeSize:
    nps: str
    schedule: str
    od: float
    wall: float

    @property
    def id(self) -> float:
        return self.od - 2 * self.wall


PIPE = {
    ("4", "40"): PipeSize("4", "40", 4.500 * IN, 0.237 * IN),
}


def pipe(nps: str, schedule: str) -> PipeSize:
    try:
        return PIPE[(nps, schedule)]
    except KeyError:
        raise KeyError(f"no B36.10 entry for NPS {nps} SCH {schedule}; add it from the standard") from None
