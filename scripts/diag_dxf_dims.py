"""Diagnostic: which difference makes Alibre import our DIMENSIONs as text?

Known (Alibre V28, double-click open):
  - minimal file, 1 horizontal linear dim, layer 0, R2000 -> DIMENSION  (baseline, works)
  - full flange drawing, R2000/R2010/R2018               -> text

Each file below changes ONE factor from the working baseline.
Temporary; remove once the Alibre dimension-import question is settled.
"""

from pathlib import Path

import ezdxf

from ai_cad_engine.drawing.annotate import DIMSTYLE, annotate_flange, setup
from ai_cad_engine.drawing.dxf_writer import INSUNITS_MM, add_views, layout_third_angle, new_doc
from ai_cad_engine.drawing.views import FRONT, RIGHT, TOP, project
from ai_cad_engine.parts.weld_neck_flange import build_weld_neck_flange
from ai_cad_engine.standards.asme_b16_5 import WN_4_150

OUT = Path(__file__).resolve().parents[1] / "out" / "diag"


def base():
    doc = ezdxf.new("R2000", setup=True, units=INSUNITS_MM)
    setup(doc)
    return doc, doc.modelspace()


def lin(msp, angle=0, **kw):
    if angle == 0:
        msp.add_line((0, 0), (100, 0))
        d = msp.add_linear_dim(base=(0, 15), p1=(0, 0), p2=(100, 0), dimstyle=DIMSTYLE, **kw)
    else:
        msp.add_line((0, 0), (0, 100))
        d = msp.add_linear_dim(
            base=(-15, 0), p1=(0, 0), p2=(0, 100), angle=90, dimstyle=DIMSTYLE, **kw
        )
    d.render()
    return d.dimension


def dia(msp, text="<>", location=None):
    msp.add_circle((0, 0), 50)
    d = msp.add_diameter_dim(
        center=(0, 0), radius=50, angle=45, location=location, text=text, dimstyle=DIMSTYLE
    )
    d.render()
    return d.dimension


def case_a(msp, doc):  # baseline, should import as dimension
    lin(msp)


def case_b(msp, doc):  # vertical linear dim
    lin(msp, angle=90)


def case_c(msp, doc):  # dim on layer DIM
    lin(msp, dxfattribs={"layer": "DIM"})


def case_d(msp, doc):  # dim + line inside a DXF GROUP
    d = lin(msp)
    doc.groups.new("G1").set_data([d, *msp.query("LINE")])


def case_e(msp, doc):  # diameter dim, default placement, plain text
    dia(msp)


def case_f(msp, doc):  # diameter dim, text placed by us outside the circle
    dia(msp, location=(60, 60))


def case_g(msp, doc):  # diameter dim with prefix/suffix text
    dia(msp, text="8X <> THRU")


CASES = {
    "A_baseline_horizontal": case_a,
    "B_vertical_linear": case_b,
    "C_layer_DIM": case_c,
    "D_in_group": case_d,
    "E_diameter_default": case_e,
    "F_diameter_text_outside": case_f,
    "G_diameter_custom_text": case_g,
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in CASES.items():
        doc, msp = base()
        fn(msp, doc)
        doc.saveas(OUT / f"{name}.dxf")

    # H: the full flange drawing with every GROUP removed.
    part = build_weld_neck_flange(WN_4_150)
    placed = layout_third_angle(*(project(part, s) for s in (FRONT, TOP, RIGHT)))
    doc = new_doc("R2000")
    add_views(doc, placed)
    annotate_flange(doc, placed)
    for gname in [n for n, _ in doc.groups]:
        doc.groups.delete(gname)
    doc.saveas(OUT / "H_flange_no_groups.dxf")

    for f in sorted(OUT.glob("*.dxf")):
        d = ezdxf.readfile(f)
        print(f.name, "dims:", len(d.modelspace().query("DIMENSION")), "audit errors:", len(d.audit().errors))


if __name__ == "__main__":
    main()
