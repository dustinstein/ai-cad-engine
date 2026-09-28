"""Diagnostic: does Alibre import our DIMENSION entities as dimensions?

Writes the flange drawing at several DXF versions, plus a minimal file with one
line and one linear dimension, so import behaviour can be isolated.
Temporary; remove once the Alibre dimension-import question is settled.
"""

from pathlib import Path

import ezdxf

from ai_cad_engine.drawing.annotate import DIMSTYLE, annotate_flange, setup
from ai_cad_engine.drawing.dxf_writer import INSUNITS_MM, layout_third_angle, write_dxf
from ai_cad_engine.drawing.views import FRONT, RIGHT, TOP, project
from ai_cad_engine.parts.weld_neck_flange import build_weld_neck_flange
from ai_cad_engine.standards.asme_b16_5 import WN_4_150

OUT = Path(__file__).resolve().parents[1] / "out"


def main() -> None:
    part = build_weld_neck_flange(WN_4_150)
    placed = layout_third_angle(*(project(part, s) for s in (FRONT, TOP, RIGHT)))
    for ver in ("R2000", "R2010"):
        path = OUT / f"diag_flange_{ver}.dxf"
        write_dxf(placed, path, annotate=annotate_flange, version=ver)
        print(f"wrote {path}")

    doc = ezdxf.new("R2000", setup=True, units=INSUNITS_MM)
    setup(doc)
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 0))
    msp.add_linear_dim(base=(0, 15), p1=(0, 0), p2=(100, 0), dimstyle=DIMSTYLE).render()
    path = OUT / "diag_min_R2000.dxf"
    doc.saveas(path)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
