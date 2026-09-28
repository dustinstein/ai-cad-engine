"""Build the NPS 4 Class 150 weld-neck flange; export STEP and a dimensioned ANSI drawing (DXF)."""

from datetime import date
from pathlib import Path

from build123d import Unit, export_step

from ai_cad_engine.drawing.annotate import annotate_flange
from ai_cad_engine.drawing.make import make_drawing
from ai_cad_engine.drawing.sheet import TitleBlock
from ai_cad_engine.parts.weld_neck_flange import build_weld_neck_flange
from ai_cad_engine.standards.asme_b16_5 import WN_4_150, flange_title_block

OUT = Path(__file__).resolve().parents[1] / "out"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    flange = build_weld_neck_flange(WN_4_150)

    step = OUT / "flange_4in_150.step"
    export_step(flange, step, unit=Unit.MM)
    bb = flange.bounding_box()
    print(f"wrote {step}")
    print(f"  bbox mm: {bb.size.X:.3f} x {bb.size.Y:.3f} x {bb.size.Z:.3f}")
    print(f"  volume mm^3: {flange.volume:.1f}")

    dxf = OUT / "flange_4in_150.dxf"
    tb: TitleBlock = flange_title_block(WN_4_150, date=date.today().isoformat())
    res = make_drawing(flange, annotate_flange, tb, dxf)
    print(f"wrote {dxf}  (ANSI {res.sheet.size}, {res.sheet.scale_text})")


if __name__ == "__main__":
    main()
