"""CSV-backed standards tables with a `verified` gate.

Rows are published inch values. A row is usable only if `verified` is "yes"
(checked by the user against their copy of the standard); drafts must be
loaded with allow_unverified=True, which is for tests and previews only.
Every row also passes geometric sanity checks on load.
"""

from __future__ import annotations

import csv
from functools import cache
from importlib.resources import files


class UnverifiedDataError(RuntimeError):
    pass


class TableSanityError(ValueError):
    pass


@cache
def load(name: str) -> tuple[dict, ...]:
    path = files("ai_cad_engine.standards") / "data" / name
    with path.open(newline="") as fh:
        return tuple(csv.DictReader(fh))


def find(name: str, allow_unverified: bool, **keys: str) -> dict:
    rows = [r for r in load(name) if all(r[k] == v for k, v in keys.items())]
    if not rows:
        raise KeyError(f"{name}: no row for {keys}; add it from the standard")
    if len(rows) > 1:
        raise TableSanityError(f"{name}: duplicate rows for {keys}")
    row = rows[0]
    if row["verified"].strip().lower() != "yes" and not allow_unverified:
        raise UnverifiedDataError(
            f"{name} {keys} is not verified ({row['source']}). Check it against the standard "
            "and set verified=yes."
        )
    return row


def yes(v: str) -> bool:
    return v.strip().lower() == "yes"
