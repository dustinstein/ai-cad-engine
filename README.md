# ai-cad-engine

Prompt/spec → dimensionally verified CAD: STEP solid (mm) + dimensioned ANSI drawing (inch) as DXF/DWG.

```
uv sync
uv run python scripts/build_flange.py   # -> out/flange_4in_150.step
uv run pytest
```
