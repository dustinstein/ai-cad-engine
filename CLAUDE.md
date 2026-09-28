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
- `src/ai_cad_engine/standards/data/*.csv` — standards tables as published (inch), with `verified` +
  `source` columns. `tables.py` loads them and REFUSES rows not verified=yes (UnverifiedDataError)
  unless allow_unverified=True (tests/previews only). Every row passes geometric sanity checks.
- `src/ai_cad_engine/standards/asme_b16_5.py` — `wn_flange(nps, class, schedule)`: B16.5 row + B36.10
  pipe → WeldNeckFlange (mm). `asme_b36_10.py` — `pipe(nps, schedule)`.
- `src/ai_cad_engine/parts/` — per family: builder from a table entry, `critical_dims(entry)`,
  `measure(solid)` (by role).
- `src/ai_cad_engine/measure.py` — generic solid measurement helpers (Z-axis cylinders, planes, cones).
- `src/ai_cad_engine/verify.py` — CriticalDim (length/count/angle/check), verification report (model +
  drawing), DIMENSION tagging.
- `src/ai_cad_engine/assembly.py` — Port / Component / Assembly: connect ports, port-vs-geometry
  validation, connection + interference checks, bolt-hole angles, named STEP assembly, BOM.
- `src/ai_cad_engine/assemblies/` — assembly builders (`spool.py`: flange + pipe + flange;
  `transition.py`: large pipe + ecc reducer + small pipe, FOB/FOT).
- `src/ai_cad_engine/standards/asme_b16_9.py` + `data/asme_b16_9_reducers.csv` — reducer H; ends from
  B36.10 by schedule. `parts/reducer.py` — eccentric reducer builder/ports/critical dims/measure.
- `src/ai_cad_engine/standards/asme_b36_10.py` — pipe OD/wall by NPS + schedule.
- `src/ai_cad_engine/drawing/views.py` — HLR orthographic projection → clean 2D prims (Line/Circle/Arc).
- `src/ai_cad_engine/drawing/dxf_writer.py` — doc setup (units, linetypes), third-angle layout, view writer.
- `src/ai_cad_engine/drawing/sheet.py` — ANSI sizes, scale/sheet choice, border, title block, notes.
- `src/ai_cad_engine/drawing/annotate.py` — generic: dimstyle, `Annotator` (centerlines, tagged linear /
  diameter / half dims), `find_bolt_pattern`.
- `src/ai_cad_engine/drawing/flange_drawing.py` — flange views (half section + face), section profile
  finder, flange dimension layout, per-family `ALLOWANCE` / `VIEW_GAP`.
- `src/ai_cad_engine/drawing/make.py` — `make_drawing(views_mm, annotate, title_block, path, view_gap,
  allowance)` pipeline: inch conversion, third-angle layout, sheet choice, DXF.
- `scripts/build_flange.py` → `out/flange_4in_150.{step,dxf,verify.json}`; prints the report table and
  exits 1 on verification failure. `out/*.step|dxf|verify.json` committed for Alibre checks.
- `scripts/build_spool.py` → `out/spool_4in_150_48in.{step,bom.csv,verify.json}`.
- `scripts/build_transition.py [--preview]` → `out/transition_12x8_fob[_PRELIM].{step,bom.csv,verify.json}`.
  `--preview` allows unverified rows; outputs get `_PRELIM` and the report FAILS `table_data_verified`.
- Commands: `uv sync`, `uv run pytest`, `uv run python scripts/build_flange.py`, `.../build_spool.py`.

## Decisions / conventions
- Internal units: mm. STEP exported in mm (AP214 schema by default from OCP).
- Flange coords: axis = Z, RF contact face at Z=0, weld end at +Z. Bolt holes straddle centerlines.
- B16.5 RF convention is per row (`rf_in_C_Y`): Class 150/300 0.06" RF INCLUDED in C and Y
  (**confirmed by user**); Class 400+ 0.25" RF NOT included — C and Y are from the flange front face and
  the RF is added in front. `face_to_back` / `overall_length` properties give RF-face-based lengths;
  measure() and the drawing use the matching datum (drawing C/Y dims start at the front face for 600).
- WN bore is not a B16.5 value: it comes from the pipe schedule. Hub-at-weld A in the table is the pipe
  OD rounded to 2 decimals (6.63 vs 6.625); the solid uses the pipe OD and the loader checks agreement
  within 0.005".
- Weld-neck v0 simplifications: straight hub taper, no r1 fillet, no weld bevel, no RF serration.
- Drawing: third-angle projection (ASME Y14.3). Views are FRONT / optional TOP / optional RIGHT; each
  family picks its ViewSpecs. View 2D coords = model coords projected (camera looks at model origin;
  view x = up × toward, y = up) → view↔model is a pure axis map; layout only translates views.
- Flange drawing = 2 views (the 3rd added nothing for a revolved part and cost sheet space):
  FRONT = half-section profile, axis horizontal, RF face left, hub right, upper half sectioned;
  RIGHT = face view from the hub end, true orientation. The sectioned copy is rotated so a MEASURED
  bolt hole lies in the cutting plane (Y14.3 aligned-section convention: revolve features into the
  plane). No cutting-plane line: Y14.3 allows omitting it when the plane is the obvious symmetry axis.
- Section views: `views.section()` cuts with a quarter-space box, projects without hidden lines
  (ASME practice), hatches the planar faces lying in the view plane through the origin (ANSI31, layer
  HATCH, scale S), and drops object lines on the half-section boundary (y=0) — Y14.3 shows that
  boundary as a centerline. Test: hatch area equals the section area computed by hand from table values.
- Half dimensions (bore in a half section): `HALF_DIM` override = dimsd2/dimse2 + dimblk2 "NONE"
  (ezdxf still draws arrow 2 unless its block is NONE). Measurement stays the full diameter; the
  mirrored defpoint uses the axis found from the view's OD extents.
- HLR cleanup is mandatory: OCC returns straight silhouettes as B-splines, splits edges at cylinder
  seams, and emits hidden edges under visible ones. We normalise to exact LINE/CIRCLE/ARC, merge
  collinear lines, and drop covered hidden prims (in mm, before unit conversion). Tests assert views
  contain only LINE/CIRCLE/ARC.
- **Drawing units: INCH** (user decision). Model/solid/STEP stay mm; views are scaled by 1/25.4 after
  HLR. DXF $INSUNITS=1, $MEASUREMENT=0, so measuring in CAD matches dimension text.
- **Sheets: ANSI (Y14.1)**, single model space (no paper-space viewports; importers handle model space
  best). Geometry at true size; border/title block/notes drawn ×S (S = scale denominator, 1:S).
  Paper-sized things (text, dash lengths, offsets) are defined in paper inches ×S. Linetype patterns
  are baked at S (not via $LTSCALE, which importers may ignore). Sheet choice: smallest of B→C→D whose
  largest fitting standard scale (1,2,4,8,16) is ≥ 1:4. Fit uses a per-side annotation allowance
  (left, bottom, right, top); a test asserts everything lands inside the content area.
- DXF: R2018. Layers VISIBLE / HIDDEN / CENTER / DIM / BORDER / TITLE. Groups: `VIEW_<NAME>`,
  `ANNOT_<NAME>`, `SHEET`. Only standard linetype names (HIDDEN, CENTER) — Alibre maps linetypes by
  name and imports unknown names solid; ezdxf's stock HIDDEN doesn't exist and its patterns are tiny.
- Dimensions: real DIMENSION entities, rendered (geometry block present), dimstyle `ENGINE_IN`:
  .125 text (Y14.2 min), 3 decimals, no leading zero (.750), dimscale=S, horizontal text,
  leader-style diameters (dimtofl=0). Don't use ezdxf's EZ_* dimstyles (scaled for other units).
  ezdxf can't render DIMALT (dual units) — irrelevant now that we're inch-only.
- Dimension defpoints are snapped to features found in the drawn views **by role** (largest circle,
  off-axis circles, view extents, full-width face), never to table values, and text uses `<>` so the
  DXF shows the measured value. Tests compare DIMENSION measurements to the standard, and a negative
  test proves a 0.5 mm error shows up on the drawing.
- Linear-dim text is always placed explicitly by `Annotator.linear` (ezdxf's own placement shifted some
  vertical-dim texts 0.5" off the line): centered on the dim line when it fits between the extension
  lines, else outside before p1. Text-width estimate `CHAR_W_EST` = 1.05 × height, shared with tests
  (0.9 missed a real touch on the NPS 2 CL600 drawing).
- `tests/test_flange_family.py` runs build + verification (model and drawing) + readability +
  containment + hand-computed section area for EVERY B16.5 row, drafts included.
- Known cosmetic limit: at 1:2 the .060 RF-height extension line sits 0.03" from the flange front face.
- Readability test: dimension text boxes (estimated from char height × count, ezdxf's MTEXT bbox is
  unreliable) must not touch other dims' lines, other dim text, or part geometry. Verified it catches
  a real overlap (.940 text crossing the 3.000 dim line). Dimension placement is still hand-tuned per
  part family; general placement/collision avoidance is future work.
- Title block: TITLE / DWG NO / REV / SIZE / SHEET / SCALE / UNITS / PROJECTION / DRAWN / DATE /
  MATERIAL. Material left blank on purpose (user: a material query will be built into the tool later). Notes cite ASME B16.5 for dims+tolerances and flag the
  drawing as machine-generated. Values shrink to fit their cell (tested).
- Alibre V28's DXF **and DWG** import converts ALL dimensions to notes/text, including its own
  exported dims (verified by round-trip of both formats). DWG does not help for Alibre. Not a defect in our DXF. So: Alibre is a valid check for geometry,
  scale, layers, linetypes, and dimension VALUES, but not for DIMENSION entity fidelity. Use a
  second viewer that preserves dims (LibreCAD for DXF; DWG TrueView after DWG conversion).

- Verification report (`verify.py`): each family lists critical dims with nominals from the table.
  MODEL = measured on the solid by role. DRAWING = tagged DIMENSION read back from the DXF on disk
  (XDATA appid `AI_CAD_ENGINE`: [key, optional count_key]); passes only if the measurement matches
  AND the displayed text equals the nominal formatted at the dimstyle precision. "NX" callout prefixes
  verify counts. Tolerance is a MODELLING tolerance (0.005 mm, 0.01°), not a manufacturing tolerance —
  B16.5 manufacturing tolerances must come from a table filled from the user's copy, never from memory.
  Report lists dims not shown on the drawing (`not_on_drawing`) rather than hiding them.
  Negative tests: wrong BC, wrong hole count, +0.01 mm error below display precision, tampered
  display text, hub/RF errors.

- **Assemblies (target: custom oilfield items like the 12x8 pig launcher GA the user shared — barrels
  of Sch 80 pipe, B16.9 eccentric reducer, Cl600 RF WN flanges, nozzles/branches, lateral pull port,
  equalizer line with ball valve, hinged closure).** Nearly everything is standard components joined at
  ports, so: component library (table-driven builders with named Ports) + assembly by connecting ports.
  For assemblies the LLM should emit a component/connection graph (JSON), NOT build123d code; the
  engine builds geometry. Free-form codegen only for truly custom parts (brackets, lugs). Vendor items
  (valves, closures) = imported vendor STEP with hand-defined ports. Outputs: named assembly STEP →
  GA drawing with overall dims/callouts/BOM → per-spool fabrication drawings.
- Port = frame at the connecting face center, `direction` OUT of the part, `x_dir` reference in the face
  (flanges: a centerline the bolt holes straddle), `end` type (BW, RF) + attrs (od/id, nps, class).
  Connecting mates frames face to face; clocking rotates about the shared axis (explicit Rodrigues —
  build123d `Plane.rotated` did NOT do this; a test caught it). Ports are declarations, so
  `validate_ports` checks each against geometry (center of a planar face with matching normal).
- Assembly checks (all measured on placed geometry): mated ports coincide + face each other + same end
  type; BW ends match OD and ID (catches Sch 80 pipe on a Sch 40 flange bore); pairwise interference
  (intersection volume); flanges two-holed (bolt holes straddle vertical, measured from hole
  cylinders). Assembly frame: axis along +X, Z up.
- **Butt-weld root gap** (user catch: 2 × Y + 42.000" pipe = 48.000" only with zero gap). BW
  connections carry a real gap between mating faces (`connect(..., gap=)`, rejected on non-BW ends);
  connection check requires faces exactly `gap` apart on axis. Face-to-face is over the raised faces
  INCLUDING gaps; pipe cut length = F-F − 2 × flange overall length − 2 × gap. Default 1/16"
  (`DEFAULT_ROOT_GAP`), typical 1/16"–1/8", set per weld procedure. BOM shows CUT LENGTH.
- Job decisions (pig launcher): root gap 1/16"; 12" barrel wall .688" (B36.10 Sch 80, not the GA's
  .687); nozzles Sch 80.
- Unverified table data is visible, never silent: table entries / components carry `verified`;
  `Assembly.unverified()` lists them; assembly reports include a `table_data_verified` check.
- Eccentric reducer: oblique-cone loft between end circles, end centers offset e = (D_L − D_S)/2 so the
  OUTSIDE is flat along one line; with unequal walls the inside is not exactly flat. Port x_dir points to
  the flat side; `connect(..., align_x=world_dir)` orients it (FOB = align_x down). FOB/FOT verified on
  geometry: both barrels' outside bottoms (tops) at the same elevation. Volume test vs frustum formula
  (Cavalieri). B16.9 doesn't fix the body shape (real fittings may have short straight ends).
- STEP assemblies: build123d `Compound(children=[labeled solids])` → XCAF assembly with named products
  (NEXT_ASSEMBLY_USAGE_OCCURRENCE), names survive re-import.

## Status
- [x] Step 1: scaffold + 4" Cl150 WN flange → STEP + pytest. Confirmed in Alibre V28 (mm, holes, BC, length, solid).
- [x] Step 2: 3-view HLR drawing (FRONT/TOP/RIGHT) → DXF. Confirmed in Alibre (1:1 mm, dashed hidden, BC, layers).
- [x] Step 3: centerlines + DIMENSION entities (OD, BC, 8X hole, thickness, overall length).
      Alibre: values + Ø correct; dims → notes is Alibre's importer (see above); centerlines fixed.
- [x] Step 4: inch units + ANSI B sheet, auto scale (1:2 for the flange), border, title block, notes,
      readability + containment tests. Confirmed in Alibre (inch, values, title block, dashed lines).
- [x] Step 5: verification report (12 critical dims; 6 checked on the drawing), JSON + table, exit code.
- [x] Step 6: half-section profile + face view; all 11 length/count critical dims on the drawing
      (only bolt-hole orientation remains model-only). Confirmed in Alibre.
- [x] Step 7: assembly core (ports, connect, checks, named STEP assembly, BOM) proved on a 4" Cl150
      48" F-F spool. Confirmed in Alibre (assembly F1/P1/F2, 1219.2 mm, two-holed).
- [x] Step 8: CSV standards tables with verified gate + sanity checks; RF convention per row; Cl600
      NPS 2/3/6/8/12 and Sch 80/160 pipe rows — user-verified 2026-09-28 (12" Sch 80 wall .688;
      GA's 11.376 ID implies .687 — user chose .688).
- [x] Step 9: butt-weld root gap in assemblies; spool pipe cut 41.875" for 48" F-F at 1/16" gaps.
- [x] Step 10: B16.9 eccentric reducer 12x8 (H = 7.00" DRAFT, awaiting user verification) +
      barrel transition assembly with FOB/FOT, preview mode for unverified data.
- [ ] Toward the pig launcher: B16.9 tee / lateral
      (ecc reducer, tee/lateral) → branch connections (nozzle on barrel) → GA drawing + BOM table →
      JSON assembly spec → LLM spec extraction.
