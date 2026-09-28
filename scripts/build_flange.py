"""Build the NPS 4 Class 150 weld-neck flange; export STEP, a dimensioned ANSI drawing (DXF),
and a verification report. Exits non-zero if verification fails."""

import sys
from datetime import date
from pathlib import Path

from build123d import Unit, export_step

from ai_cad_engine.drawing.annotate import annotate_flange
from ai_cad_engine.drawing.make import make_drawing
from ai_cad_engine.parts.weld_neck_flange import build_weld_neck_flange, critical_dims, measure
from ai_cad_engine.standards.asme_b16_5 import WN_4_150, flange_title_block
from ai_cad_engine.verify import build_report

OUT = Path(__file__).resolve().parents[1] / "out"
NAME = "flange_4in_150"


def main() -> int:
    OUT.mkdir(exist_ok=True)
    f = WN_4_150
    flange = build_weld_neck_flange(f)

    step = OUT / f"{NAME}.step"
    export_step(flange, step, unit=Unit.MM)
    print(f"wrote {step}")

    dxf = OUT / f"{NAME}.dxf"
    res = make_drawing(flange, annotate_flange, flange_title_block(f, date=date.today().isoformat()), dxf)
    print(f"wrote {dxf}  (ANSI {res.sheet.size}, {res.sheet.scale_text})")

    report = build_report(
        part=f"Weld neck flange NPS {f.nps} Class {f.pressure_class} RF",
        standard="ASME B16.5",
        crit=critical_dims(f),
        model=measure(flange),
        drawing_path=dxf,
    )
    rpt = OUT / f"{NAME}.verify.json"
    rpt.write_text(report.to_json() + "\n")
    print(f"wrote {rpt}\n")
    print(report.table())
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
