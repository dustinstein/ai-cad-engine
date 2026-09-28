"""Verification report: critical dimensions vs the solid and vs the drawing.

For each critical dimension (nominal from a standards table) the report records:
  - model:   value measured on the B-rep solid, by role
  - drawing: value of the tagged DIMENSION entity read back from the DXF on disk,
             plus the text the drawing actually displays
Tolerance is a MODELLING tolerance (does the CAD equal the nominal?), not a
manufacturing tolerance. Manufacturing tolerances belong in standards tables.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import ezdxf

APPID = "AI_CAD_ENGINE"
MODEL_TOL_MM = 0.005
ANGLE_TOL_DEG = 0.01
MM_PER_IN = 25.4


@dataclass(frozen=True)
class CriticalDim:
    key: str
    description: str
    nominal: float  # mm for "length", count for "count", degrees for "angle"
    kind: str = "length"  # length | count | angle


@dataclass
class Item:
    key: str
    description: str
    kind: str
    nominal: float
    model: float | None
    model_pass: bool
    drawing: float | None = None  # same units as nominal
    drawing_text: str | None = None
    expected_text: str | None = None
    drawing_pass: bool | None = None  # None = not dimensioned on the drawing

    @property
    def passed(self) -> bool:
        return self.model_pass and self.drawing_pass is not False


@dataclass
class Report:
    part: str
    standard: str
    drawing_file: str | None
    items: list[Item] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(i.passed for i in self.items)

    def to_json(self) -> str:
        d = {
            "part": self.part,
            "standard": self.standard,
            "drawing_file": self.drawing_file,
            "model_tolerance_mm": MODEL_TOL_MM,
            "passed": self.passed,
            "not_on_drawing": [i.key for i in self.items if i.drawing_pass is None],
            "items": [asdict(i) | {"passed": i.passed} for i in self.items],
        }
        return json.dumps(d, indent=2)

    def table(self) -> str:
        rows = [
            f"{'KEY':<22}{'NOMINAL':>11}{'MODEL':>11}  {'M':<4}{'DRAWING':>11}  {'TEXT':<18}{'D':<4}"
        ]
        for i in self.items:
            unit = {"length": "", "count": "", "angle": "°"}[i.kind]
            fmt = (lambda v: "-" if v is None else f"{v:.3f}{unit}") if i.kind != "count" else (
                lambda v: "-" if v is None else f"{v:g}"
            )
            d = "-" if i.drawing_pass is None else ("ok" if i.drawing_pass else "FAIL")
            rows.append(
                f"{i.key:<22}{fmt(i.nominal):>11}{fmt(i.model):>11}  {'ok' if i.model_pass else 'FAIL':<4}"
                f"{fmt(i.drawing):>11}  {(i.drawing_text or '-').replace('%%c', 'Ø'):<18}{d:<4}"
            )
        rows.append(f"RESULT: {'PASS' if self.passed else 'FAIL'}  (lengths in mm, model tol {MODEL_TOL_MM} mm)")
        return "\n".join(rows)


def tag_dimension(dim_entity, key: str, count_key: str | None = None) -> None:
    """Attach a critical-dimension key to a DIMENSION so the report can find it in the DXF.

    `count_key` marks a count stated in the text as an "NX" prefix (e.g. "8X Ø.750 THRU").
    """
    doc = dim_entity.doc
    if APPID not in doc.appids:
        doc.appids.add(APPID)
    tags = [(1000, key)] + ([(1000, count_key)] if count_key else [])
    dim_entity.set_xdata(APPID, tags)


@dataclass(frozen=True)
class DrawnDim:
    measurement: float  # drawing units
    text: str  # as displayed
    dimdec: int
    count_key: str | None


def read_drawing_dims(path: Path) -> dict[str, DrawnDim]:
    """key -> DrawnDim for DIMENSIONs tagged with a critical-dimension key."""
    doc = ezdxf.readfile(path)
    out: dict[str, DrawnDim] = {}
    for d in doc.modelspace().query("DIMENSION"):
        if not d.has_xdata(APPID):
            continue
        tags = [t.value for t in d.get_xdata(APPID)]
        key = tags[0]
        if key in out:
            raise ValueError(f"duplicate drawing dimension for {key!r}")
        texts = [e.text for e in d.get_geometry_block() if e.dxftype() == "MTEXT"]
        dimdec = doc.dimstyles.get(d.dxf.dimstyle).dxf.dimdec
        out[key] = DrawnDim(
            d.get_measurement(), texts[0] if texts else "", dimdec, tags[1] if len(tags) > 1 else None
        )
    return out


def _fmt_inch(v_in: float, dec: int) -> str:
    s = f"{v_in:.{dec}f}"
    return s[1:] if s.startswith("0.") else s  # ASME inch: no leading zero


def _number_in(text: str) -> str | None:
    # First decimal number; skips count prefixes like "8X".
    m = re.search(r"\d*\.\d+", text)
    return m.group(0) if m else None


def build_report(
    part: str,
    standard: str,
    crit: list[CriticalDim],
    model: dict[str, float],
    drawing_path: Path | None = None,
) -> Report:
    rep = Report(part, standard, str(drawing_path) if drawing_path else None)
    drawn = read_drawing_dims(drawing_path) if drawing_path else {}
    counts = {dd.count_key: dd for dd in drawn.values() if dd.count_key}
    unknown = (set(drawn) | set(counts)) - {c.key for c in crit}
    if unknown:
        raise ValueError(f"drawing has tagged dims with no critical dim: {sorted(unknown)}")
    for c in crit:
        m = model.get(c.key)
        tol = {"length": MODEL_TOL_MM, "count": 0, "angle": ANGLE_TOL_DEG}[c.kind]
        m_ok = m is not None and abs(m - c.nominal) <= tol
        item = Item(c.key, c.description, c.kind, c.nominal, m, m_ok)
        if c.key in drawn:
            if c.kind != "length":
                raise ValueError(f"only length dims are measured on drawings, got {c.key}")
            dd = drawn[c.key]
            item.drawing = dd.measurement * MM_PER_IN
            item.drawing_text = dd.text
            item.expected_text = _fmt_inch(c.nominal / MM_PER_IN, dd.dimdec)
            item.drawing_pass = (
                abs(item.drawing - c.nominal) <= MODEL_TOL_MM
                and _number_in(dd.text) == item.expected_text
            )
        elif c.key in counts:
            dd = counts[c.key]
            m_count = re.match(r"\s*(\d+)X\b", dd.text)
            item.drawing = float(m_count.group(1)) if m_count else None
            item.drawing_text = dd.text
            item.expected_text = f"{int(c.nominal)}X"
            item.drawing_pass = item.drawing == c.nominal
        rep.items.append(item)
    return rep
