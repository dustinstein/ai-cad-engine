"""ASME B16.5 weld-neck flanges.

Data: data/asme_b16_5_wn.csv (published inch values). Stored here in mm.

Raised-face convention is per row (`rf_in_C_Y`): for Class 150/300 the 0.06 in RF
is INCLUDED in C (thickness) and Y (length through hub) — confirmed by the user
against their edition. For Class 400 and up the 0.25 in RF is NOT included:
C and Y are measured from the flange front face, and the RF is added in front.

The weld-neck bore is not a B16.5 table value; it matches the pipe schedule, so a
flange entry is built from a B16.5 row plus a B36.10 pipe. The table's A (hub at
weld point) is the pipe OD rounded to 2 decimals; the solid uses the pipe OD, and
the loader checks they agree to within that rounding.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_cad_engine.standards.asme_b36_10 import pipe
from ai_cad_engine.standards.tables import TableSanityError, find, load, yes

IN = 25.4
TABLE = "asme_b16_5_wn.csv"
A_ROUNDING_IN = 0.005 + 1e-9


@dataclass(frozen=True)
class WeldNeckFlange:
    nps: str
    pressure_class: int
    od: float  # O, flange outside diameter
    thickness: float  # C, min flange thickness (per rf_in_cy)
    raised_face_dia: float  # R
    raised_face_height: float
    bolt_circle_dia: float  # W
    bolt_hole_count: int
    bolt_hole_dia: float
    hub_dia_base: float  # X, hub diameter at base
    hub_dia_weld: float  # A, hub diameter at weld point (= pipe OD)
    length_through_hub: float  # Y (per rf_in_cy)
    bore: float  # B, matches pipe ID for the specified schedule
    bore_schedule: str
    rf_in_cy: bool = True  # raised face included in C and Y

    @property
    def face_to_back(self) -> float:
        """RF contact face to flange back face."""
        return self.thickness if self.rf_in_cy else self.thickness + self.raised_face_height

    @property
    def overall_length(self) -> float:
        """RF contact face to weld end."""
        return self.length_through_hub if self.rf_in_cy else self.length_through_hub + self.raised_face_height


def check_row(r: dict) -> None:
    """Geometric sanity of a published row (inch). Catches typos, not wrong-but-plausible values."""
    v = {k: float(r[k]) for k in ("O", "C", "R", "rf_height", "W", "hole_dia", "X", "A", "Y")}
    tag = f"B16.5 NPS {r['nps']} CL{r['class']}"
    rules = [
        (v["W"] / 2 + v["hole_dia"] / 2 < v["O"] / 2, "bolt holes break out of the OD"),
        (v["R"] / 2 < v["W"] / 2 - v["hole_dia"] / 2, "raised face runs into the bolt holes"),
        (v["X"] / 2 < v["W"] / 2 - v["hole_dia"] / 2, "hub base runs into the bolt holes"),
        (v["A"] <= v["X"], "hub at weld point larger than hub base"),
        (v["Y"] > v["C"], "length through hub not longer than flange thickness"),
        (v["C"] > v["rf_height"] > 0, "raised face height vs thickness"),
        (int(r["bolt_holes"]) % 4 == 0, "bolt hole count not a multiple of 4"),
    ]
    bad = [msg for ok, msg in rules if not ok]
    if bad:
        raise TableSanityError(f"{tag}: " + "; ".join(bad))


def wn_flange(nps: str, pressure_class: int, schedule: str, allow_unverified: bool = False) -> WeldNeckFlange:
    r = find(TABLE, allow_unverified, nps=nps, **{"class": str(pressure_class)})
    check_row(r)
    p = pipe(nps, schedule, allow_unverified)
    a_table = float(r["A"])
    if abs(a_table - p.od / IN) > A_ROUNDING_IN:
        raise TableSanityError(
            f"B16.5 NPS {nps} CL{pressure_class}: A={a_table} vs pipe OD {p.od / IN:.3f} (beyond rounding)"
        )
    return WeldNeckFlange(
        nps=nps,
        pressure_class=pressure_class,
        od=float(r["O"]) * IN,
        thickness=float(r["C"]) * IN,
        raised_face_dia=float(r["R"]) * IN,
        raised_face_height=float(r["rf_height"]) * IN,
        bolt_circle_dia=float(r["W"]) * IN,
        bolt_hole_count=int(r["bolt_holes"]),
        bolt_hole_dia=float(r["hole_dia"]) * IN,
        hub_dia_base=float(r["X"]) * IN,
        hub_dia_weld=p.od,
        length_through_hub=float(r["Y"]) * IN,
        bore=p.id,
        bore_schedule=schedule,
        rf_in_cy=yes(r["rf_in_C_Y"]),
    )


def all_rows() -> tuple[dict, ...]:
    return load(TABLE)


# NPS 4, Class 150, bore for Sch 40 — the user-confirmed reference part.
WN_4_150 = wn_flange("4", 150, "40")


def flange_title_block(f: WeldNeckFlange, date: str = ""):
    """Title block text for a B16.5 weld-neck flange drawing."""
    from ai_cad_engine.drawing.sheet import TitleBlock

    h = f"{f.raised_face_height / IN:.2f}".lstrip("0")
    rf_note = (
        f"RAISED FACE {h} INCLUDED IN FLANGE THICKNESS AND LENGTH THRU HUB."
        if f.rf_in_cy
        else f"RAISED FACE {h} NOT INCLUDED IN FLANGE THICKNESS AND LENGTH THRU HUB."
    )
    return TitleBlock(
        title=f"FLANGE, WELD NECK, RF, NPS {f.nps} CL{f.pressure_class}, SCH {f.bore_schedule} BORE",
        dwg_no=f"WN-{f.nps}-{f.pressure_class}-RF",
        date=date,
        notes=(
            "DIMENSIONS ARE IN INCHES.",
            "DIMENSIONS AND TOLERANCES PER ASME B16.5.",
            rf_note,
            "MACHINE-GENERATED DRAWING. VERIFY BEFORE RELEASE.",
        ),
    )
