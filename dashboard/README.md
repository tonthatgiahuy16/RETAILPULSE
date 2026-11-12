# Portfolio Dashboard Brief

Compiles a standalone, single-file HTML portfolio brief from verified execution artifacts.

- **Input artifacts**:
  - `data/processed/orchestration/last_run.json` (pipeline execution & SQL gates evidence)
  - `data/processed/repurchase_model_evaluation.json` (model evaluation & fixed-capacity ranking)
  - `dashboard/templates/index.html.template` (HTML/CSS design and data tokens)
- **Build command**: `python scripts/build_dashboard.py`
- **Output**: `dashboard/dist/index.html`

In CI, the separate `model-evaluation` job builds this brief from the run record
and model report produced by the synthetic fixture workflow, so the
pipeline-to-model-to-dashboard wiring is exercised end to end. The checked-in
fixtures remain for unit tests and static compilation.

> **Note**: The generated HTML is a static, frozen snapshot representing specific historical execution runs. It does not update automatically without running the build script, nor does it connect to live streaming databases or guarantee active customer forecasts.
