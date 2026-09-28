"""Build the NPS 4 Class 150 weld-neck flange and export STEP."""

from pathlib import Path

from build123d import Unit, export_step

from ai_cad_engine.parts.weld_neck_flange import build_weld_neck_flange
from ai_cad_engine.standards.asme_b16_5 import WN_4_150

OUT = Path(__file__).resolve().parents[1] / "out"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    flange = build_weld_neck_flange(WN_4_150)
    path = OUT / "flange_4in_150.step"
    export_step(flange, path, unit=Unit.MM)
    bb = flange.bounding_box()
    print(f"wrote {path}")
    print(f"bbox mm: {bb.size.X:.3f} x {bb.size.Y:.3f} x {bb.size.Z:.3f}")
    print(f"volume mm^3: {flange.volume:.1f}")


if __name__ == "__main__":
    main()
