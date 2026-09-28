# AI CAD Engine

Text prompt or structured spec → (1) dimensionally accurate 3D solid exported as STEP (AP214/AP242),
(2) 2D manufacturing drawing (projected views, dimensions, title block) as DXF, then DWG.

**Dimensional accuracy is requirement #1.** A good-looking part that's off by 0.5 mm is a failure.

## User / context
- Windows; CAD = Alibre Design Expert V28. Every STEP output gets checked in Alibre.
- Domain: oilfield/industrial — flanges, subs, crossovers, brackets, lifting lugs, skids, thread protectors.
  Codes: ASME B16.5, API 6A, ASME/API piping. Use these as test parts.
- Background: React, Firebase, Node, Claude API; comfortable in Python for the engine.

## Working style
- ONE small step at a time, with a time estimate. Wait for the user to say "done" before the next.
- Direct, concise, peer-level.
- Keep this file updated as decisions are made.

## Principles
- Standard dimensions come from lookup tables (`src/ai_cad_engine/standards/`), never LLM memory.
- Every generated part ships with a verification report.
- CAD kernel is deterministic Python (build123d / OpenCascade). The LLM writes code, never geometry.
- Eval set of 10–20 reference parts with known dimensions; run on every change.
- LLM = Claude API, model configurable.

## Architecture (planned)
1. Spec extraction: prompt → LLM → JSON spec (features, critical dims, tolerances, units, must-verify list).
2. Codegen: spec → LLM writes build123d. AST check (whitelisted imports, no eval/exec/file/network),
   run in subprocess with time/memory limits.
3. Verification loop: measure solid (bbox, volume, hole dia/positions, face/edge queries) vs must-verify
   dims; on mismatch feed diff back, retry ≤ N; per-dimension pass/fail report.
4. 3D export: STEP (build123d/OCP); STL/GLB for previews.
5. 2D drawing: HLR projected views (front/top/side/iso; sections later), sheet layout, dimensions from
   spec critical dims; DXF via ezdxf with real DIMENSION entities (not exploded lines).
6. DWG: DXF→DWG via ODA File Converter (license TBD) or LibreDWG (GPL, limited). Behind an interface.
7. Later: React + three.js UI, API, part-family templates (e.g. B16.5 from tables), GD&T, assemblies.

## Prior art (2026-09-28)
- earthtojake/text-to-cad (MIT, ~12.8k★): most complete; STEP/STL/3MF/DXF profiles. Evaluate before building parallel pieces.
- Cadless (MIT): prompt→build123d→AST validate→sandbox→STEP. Reference for validate/sandbox.
- CADAM (GPL-3, OpenSCAD, mesh only) — not a base.
- Zoo/KittyCAD — commercial benchmark to beat, not a dependency.
- build123d-mcp — agent runs/inspects build123d.
- Benchmarks: CAD Arena (runs-only), Text2CAD-Bench, MUSE, BenchCAD.
- Unfilled gap / our value: auto readable dimensioned 2D drawings → DXF/DWG from the same model.

## Repo layout / tooling
- uv, Python 3.12 (`.python-version`), src layout, pytest. build123d 0.13.
- `src/ai_cad_engine/standards/asme_b16_5.py` — B16.5 tables (inch values ×25.4, stored in mm).
- `src/ai_cad_engine/parts/` — deterministic part builders from table entries.
- `src/ai_cad_engine/measure.py` — solid measurement helpers (seed of the verification loop).
- `src/ai_cad_engine/drawing/views.py` — HLR orthographic projection → clean 2D prims (Line/Circle/Arc).
- `src/ai_cad_engine/drawing/dxf_writer.py` — third-angle layout + ezdxf DXF writer.
- `scripts/build_flange.py` → `out/flange_4in_150.{step,dxf}`. `out/*.step|dxf` committed for Alibre checks.
- Commands: `uv sync`, `uv run pytest`, `uv run python scripts/build_flange.py`.

## Decisions / conventions
- Internal units: mm. STEP exported in mm (AP214 schema by default from OCP).
- Flange coords: axis = Z, RF contact face at Z=0, weld end at +Z. Bolt holes straddle centerlines.
- B16.5 Class 150/300: 0.06" RF treated as INCLUDED in C (thickness) and Y (length through hub),
  per the commonly published tables. **Open item:** confirm against the user's B16.5 edition.
- Weld-neck v0 simplifications: straight hub taper, no r1 fillet, no weld bevel, no RF serration.
- Drawing: third-angle projection (ASME Y14.3). Z-up model; FRONT = viewer at -Y, TOP = +Z, RIGHT = +X.
  View 2D coords = model coords projected (camera looks at model origin) → view↔model is a pure axis
  map; layout applies only a translation per view. Drawn 1:1 in mm in model space (sheet/paperspace later).
- HLR cleanup is mandatory: OCC returns straight silhouettes as B-splines, splits edges at cylinder
  seams, and emits hidden edges under visible ones. We normalise to exact LINE/CIRCLE/ARC, merge
  collinear lines, and drop covered hidden prims. Tests assert DXF contains only LINE/CIRCLE/ARC.
- DXF: R2018, $INSUNITS=4 (mm). Layers VISIBLE / HIDDEN. Own HIDDEN linetype (3 mm dash, 1.5 mm gap);
  ezdxf's stock patterns are inch-sized and have no HIDDEN. Each view is a DXF GROUP `VIEW_<NAME>`.

## Status
- [x] Step 1: scaffold + 4" Cl150 WN flange → STEP + pytest. Confirmed in Alibre V28 (mm, holes, BC, length, solid).
- [x] Step 2: 3-view HLR drawing (FRONT/TOP/RIGHT) → DXF, no dimensions yet. Awaiting Alibre check.
- [ ] Next candidates: centerlines + real DIMENSION entities; sheet/title block; verification report.
