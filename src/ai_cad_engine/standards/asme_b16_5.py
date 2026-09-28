"""ASME B16.5 flange dimension tables.

Values are the published inch dimensions, converted to mm exactly (x 25.4).
Standard dimensions come from here, never from an LLM.

Convention (VERIFY against your edition): for Class 150/300, the 0.06 in
raised face is INCLUDED in `thickness` (C / tf) and `length_through_hub` (Y),
as stated in the widely published B16.5 tables. Some editions list tf
excluding the raised face; if yours does, the flange body grows by 0.06 in.
"""

from dataclasses import dataclass

IN = 25.4


@dataclass(frozen=True)
class WeldNeckFlange:
    nps: str
    pressure_class: int
    od: float  # O, flange outside diameter
    thickness: float  # C, min flange thickness incl. raised face
    raised_face_dia: float  # R
    raised_face_height: float
    bolt_circle_dia: float  # W
    bolt_hole_count: int
    bolt_hole_dia: float
    hub_dia_base: float  # X, hub diameter at base
    hub_dia_weld: float  # A, hub diameter at weld point (pipe OD)
    length_through_hub: float  # Y, overall length incl. raised face
    bore: float  # B, matches pipe ID for the specified schedule
    bore_schedule: str


# NPS 4, Class 150, bore for STD/Sch 40 (4.026 in ID).
WN_4_150 = WeldNeckFlange(
    nps="4",
    pressure_class=150,
    od=9.00 * IN,
    thickness=0.94 * IN,
    raised_face_dia=6.19 * IN,
    raised_face_height=0.06 * IN,
    bolt_circle_dia=7.50 * IN,
    bolt_hole_count=8,
    bolt_hole_dia=0.75 * IN,
    hub_dia_base=5.31 * IN,
    hub_dia_weld=4.50 * IN,
    length_through_hub=3.00 * IN,
    bore=4.026 * IN,
    bore_schedule="40",
)
