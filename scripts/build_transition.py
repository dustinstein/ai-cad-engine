"""Build the pig-launcher barrel transition: 12" Sch 80 x 24" -> 12x8 ecc reducer (FOB) ->
8" Sch 80 x 24". Assembly STEP, BOM, verification report; exits 1 if verification fails.

--preview allows table rows not yet verified; outputs are suffixed _PRELIM and the report
fails on `table_data_verified` until the rows are verified.
"""

import argparse
import sys
from pathlib import Path

from ai_cad_engine.assemblies.transition import TransitionSpec, build_transition, critical_dims, measure
from ai_cad_engine.standards.asme_b16_9 import IN, reducer
from ai_cad_engine.verify import build_report

OUT = Path(__file__).resolve().parents[1] / "out"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true", help="allow unverified table rows")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)

    red = reducer("12", "8", "80", "80", allow_unverified=args.preview)
    spec = TransitionSpec(red, large_length=24 * IN, small_length=24 * IN, flat="bottom")
    name = "transition_12x8_fob" + ("" if red.verified else "_PRELIM")
    asm = build_transition(spec, name=name.upper())

    step = OUT / f"{name}.step"
    asm.export_step(step)
    asm.write_bom_csv(OUT / f"{name}.bom.csv")
    model, notes = measure(asm, spec)
    report = build_report(
        part='Barrel transition 12" SCH 80 x 12x8 ECC RED (FOB) x 8" SCH 80',
        standard="ASME B16.9 / B36.10",
        crit=critical_dims(spec),
        model=model,
        notes=notes,
    )
    (OUT / f"{name}.verify.json").write_text(report.to_json() + "\n")
    print(f"wrote {step}\n")
    print(report.table())
    print("\nBOM:")
    for r in asm.bom():
        print(f"  {r['item']}  {r['qty']} x {r['part_no']:<24} {r['description']}  [{r['tags']}]")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
