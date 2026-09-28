"""ASME B16.9 butt-welding fittings: reducers (end-to-end H).

Data: data/asme_b16_9_reducers.csv (inch). B16.9 gives H; the ends match the
connecting pipe (OD and wall from B36.10 by schedule). The body shape between the
ends is not specified by B16.9.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_cad_engine.standards.asme_b36_10 import PipeSize, pipe
from ai_cad_engine.standards.tables import TableSanityError, find, load, yes

IN = 25.4
TABLE = "asme_b16_9_reducers.csv"


@dataclass(frozen=True)
class Reducer:
    large: PipeSize
    small: PipeSize
    length: float  # H, end to end, mm
    verified: bool

    @property
    def offset(self) -> float:
        """Eccentric offset between end centers (outside flat), mm."""
        return (self.large.od - self.small.od) / 2


def check_row(r: dict, large: PipeSize, small: PipeSize) -> None:
    h = float(r["H"])
    if not h > 0:
        raise TableSanityError(f"B16.9 {r['large_nps']}x{r['small_nps']}: H={h}")
    if not small.od < large.od:
        raise TableSanityError(f"B16.9 {r['large_nps']}x{r['small_nps']}: small end not smaller")


def reducer(
    large_nps: str, small_nps: str, large_sch: str, small_sch: str, allow_unverified: bool = False
) -> Reducer:
    r = find(TABLE, allow_unverified, large_nps=large_nps, small_nps=small_nps)
    large = pipe(large_nps, large_sch, allow_unverified)
    small = pipe(small_nps, small_sch, allow_unverified)
    check_row(r, large, small)
    verified = yes(r["verified"]) and large.verified and small.verified
    return Reducer(large, small, float(r["H"]) * IN, verified)


def all_rows() -> tuple[dict, ...]:
    return load(TABLE)
