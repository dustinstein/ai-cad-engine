"""Build a 4" Class 150 flanged spool (48" face to face): assembly STEP, BOM, verification.
Exits non-zero if verification fails."""

import json
import sys
from pathlib import Path

from ai_cad_engine.assemblies.spool import SpoolSpec, build_spool, critical_dims, measure
from ai_cad_engine.standards.asme_b16_5 import IN, WN_4_150
from ai_cad_engine.standards.asme_b36_10 import pipe
from ai_cad_engine.verify import build_report

OUT = Path(__file__).resolve().parents[1] / "out"
NAME = "spool_4in_150_48in"


def main() -> int:
    OUT.mkdir(exist_ok=True)
    spec = SpoolSpec(WN_4_150, pipe("4", "40"), 48 * IN)
    asm = build_spool(spec, name=NAME.upper())

    step = OUT / f"{NAME}.step"
    asm.export_step(step)
    bom = OUT / f"{NAME}.bom.csv"
    asm.write_bom_csv(bom)
    print(f"wrote {step}\nwrote {bom}")

    model, notes = measure(asm, spec.root_gap)
    report = build_report(
        part=f'Spool, NPS 4 CL150 RF, 48" F-F, {spec.root_gap / IN:.4f}" root gaps',
        standard="ASME B16.5 / B36.10",
        crit=critical_dims(spec),
        model=model,
        notes=notes,
    )
    rpt = OUT / f"{NAME}.verify.json"
    rpt.write_text(report.to_json() + "\n")
    print(f"wrote {rpt}\n")
    print(report.table())
    print("\nBOM:")
    for r in asm.bom():
        print(f"  {r['item']}  {r['qty']} x {r['part_no']:<22} {r['description']}  [{r['tags']}]")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
