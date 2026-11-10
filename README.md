# RetailPulse

RetailPulse is a learning and portfolio project for reproducible data
engineering, analytics, and decision support using the UCI Online Retail II
dataset. It demonstrates a batch pipeline from an immutable source snapshot to
PostgreSQL analytical contracts, dbt checks, and a Power BI report project.

The project is not a production retail service. Its customer and revenue
metrics describe the historical source snapshot; they do not represent a live
retailer, accounting revenue, campaign results, or causal uplift.

## What is in the repository

- Immutable source tracking and PostgreSQL raw, staging, warehouse, mart, and
  decision contracts, with lineage and reconciliation gates.
- A migration runner, automated tests, and GitHub Actions checks using an
  isolated PostgreSQL service.
- An in-repo DAG runner with dependencies, retries, downstream skipping, a JSON
  run record, and an optional failure webhook. See
  [`docs/architecture/ORCHESTRATION.md`](docs/architecture/ORCHESTRATION.md).
- dbt adapter views and contract tests over the existing PostgreSQL contracts.
  dbt is a verification and lineage layer; migrations remain the source of
  truth for transformation logic. See [`dbt/README.md`](dbt/README.md).
- A read-only PostgreSQL `bi` semantic layer and a Power BI Project (PBIP)
  report with Overview, Customer lifecycle, and Data quality pages.
- Architecture, data-contract, KPI, and source-attribution documentation under
  [`docs/`](docs/).

The original workbook and local database are not included. Runtime numbers
below are historical, local evidence and should not be interpreted as a
current hosted service or refresh status.

## Data source and attribution

The source is [Online Retail II from the UCI Machine Learning
Repository](https://archive.ics.uci.edu/dataset/502/online+retail+ii), DOI
[10.24432/C5CG6D](https://doi.org/10.24432/C5CG6D), licensed under [Creative
Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).

Citation: Chen, D. (2012). *Online Retail II* [Dataset]. UCI Machine Learning
Repository. The original workbook is intentionally excluded from Git. See
[`docs/data/SOURCE_AND_LICENSE.md`](docs/data/SOURCE_AND_LICENSE.md) for the
recorded snapshot hashes and attribution details.

## Local setup

Requirements: Python 3.13 or later, PostgreSQL, and (for the optional
transform checks) dbt Core with the PostgreSQL adapter. The CI workflow
provides an isolated PostgreSQL service for integration checks.

From PowerShell, create a virtual environment and install the project with the
optional dbt and model dependencies:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e '.[transform,model]'
```

Set `PYTHONPATH` for the test suite and run the available tests:

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
```

PostgreSQL integration tests are skipped unless both
`RETAILPULSE_INTEGRATION_TEST=1` and a dedicated
`RETAILPULSE_INTEGRATION_DSN` are configured. They reset project schemas; use
an isolated disposable database only, never a shared or production database.
The GitHub Actions workflow runs these checks against its isolated service.

## Run the pipeline locally

First obtain the source workbook from UCI under the ignored
`data/raw/online_retail_ii/` directory. Its SHA-256 and source lineage are
documented in `docs/data/`. Configure `DATABASE_URL` in the shell or another
local secret store; do not put credentials in command history, tracked files,
Power BI project files, or screenshots.

```powershell
$env:PYTHONPATH = 'src'
# Set DATABASE_URL securely in your local environment before running this step.
python scripts/run_pipeline.py `
  --workbook data/raw/online_retail_ii/online_retail_II.xlsx `
  --source-uri 'https://archive.ics.uci.edu/dataset/502/online+retail+ii' `
  --source-retrieved-at '<actual-retrieval-time-with-timezone>'
```

Use the actual retrieval timestamp, including timezone. The command applies
migrations, attempts ingestion, and runs publish gates; inspect its output and
database reconciliation for the specific run. The recorded local run on
2026-10-29 loaded 1,067,371 source rows and exercised same-hash skip and
transaction rollback behavior. Those results are historical evidence, not a
claim that the database is available or current in another environment.

Local verification reported on 2026-11-10 (developer shell, not a hosted CI
run): the four opt-in PostgreSQL integration tests passed, and
`dbt build --project-dir dbt --profiles-dir dbt` finished with
`PASS=16 WARN=0 ERROR=0 SKIP=0`, covering 2 models, 12 generic tests, and 2
singular tests. These results are date-scoped to that environment.

The same operations are available as a governed DAG with dependency order,
retries, downstream skipping, and a JSON run record:

```powershell
python scripts/run_dag.py --output data/processed/orchestration/last_run.json
```

Add `--with-dbt` and `--train-model` to enable those optional tasks. The Power
BI task records a manual refresh action, or verifies evidence passed with
`--powerbi-evidence`; it never claims to refresh the report. See
[`docs/architecture/ORCHESTRATION.md`](docs/architecture/ORCHESTRATION.md).

Two local DAG runs on 2026-11-10 are recorded here; both are date-scoped to that
machine and are not CI evidence.

- `run_id 0d4bfd59b9c4`: no workbook. All 20 migrations were already applied,
  ingestion was skipped, 12 SQL gates executed, dbt and model training were
  disabled, and Power BI was recorded as a manual action. This proves dependency
  wiring, skip semantics, and the run record only.
- `run_id 8c0fc3c3e9ca`: full chain in 17 minutes. Migrations were already
  applied; ingestion reported `SKIPPED_ALREADY_LOADED` for the same source hash
  but still refreshed 8 materialized views (321s, dominated by
  `dw.fct_sales_line`); 12 SQL gates took 550s; `dbt build` finished with
  `PASS=16 WARN=0 ERROR=0 SKIP=0` in 108s; model training wrote
  `data/processed/repurchase_model_evaluation.json` in 44s. Power BI remained a
  manual action with no refresh evidence. Ingestion here re-used an existing
  snapshot, so this run does not prove loading a new snapshot.

Most of the wall clock is PostgreSQL work, not Python: the CLI only printed at
the end of that run. The runner now logs `[dag] <task> started|finished` to
stderr, and `--skip-refresh` skips the materialized-view refresh when the raw
snapshot is unchanged. See
[`docs/architecture/ORCHESTRATION.md`](docs/architecture/ORCHESTRATION.md).

Power BI report verification on 2026-11-10 (developer screenshots, not CI):
all three pages render with data and the source snapshot slicer is unpinned,
confirming the PBIP metadata fix. Migration 021 repaired a self-referential
materialized view in the cancellation candidate path, so matched and ambiguous
candidates are now non-zero; the diagnostic chart now shows the candidate reason.
The training step now persists model and rule-baseline metrics to
`bi.repurchase_model_evaluation`.

## Power BI

Open [`powerbi/RetailPulse.pbip`](powerbi/RetailPulse.pbip) in Power BI Desktop.
The report connects to the PostgreSQL `bi` schema in Import mode. Configure
the endpoint through the model parameters and provide credentials through
Power BI's credential store; no database password is included in this repo.
The model is designed around one selected source snapshot. See
[`docs/architecture/POWER_BI_SEMANTIC_LAYER.md`](docs/architecture/POWER_BI_SEMANTIC_LAYER.md)
for least-privilege setup, metric reconciliation, and interpretation limits.

The report was opened locally and its three pages were manually confirmed to
show data on 2026-11-07. This is a local Desktop check only; no Power BI Service
publication, gateway configuration, scheduled refresh, or hosted availability
is claimed.

Static project checks:

```powershell
python scripts/validate_powerbi_project.py
python -m py_compile scripts/build_powerbi_report.py scripts/validate_powerbi_project.py
git diff --check
```

On 2026-11-10 these checks passed locally on the Power BI-saved files
(`POWERBI_PROJECT=PASS`, 7 BI tables, 3 report pages), and the PBIP regression
tests in `tests/test_powerbi_project_validation.py` passed. That is local
static evidence; it does not claim a GitHub Actions run.

## Interpretation guardrails

- Revenue measures are event-date transaction amounts, not accounting
  revenue. Cancellation rows remain signed source events; candidate matches
  are diagnostics, not verified returns.
- Missing Customer ID rows remain in revenue totals and are excluded only by
  customer-level eligibility contracts.
- RFM priority is descriptive. Repurchase evaluation uses historical labels;
  there is no campaign treatment data to establish causal uplift or ROI.
- Every metric must retain its source snapshot, grain, time window, and
  denominator. Do not add separate source snapshots unless a comparison
  contract explicitly permits it.

Read the [Project Charter](docs/project/PROJECT_CHARTER.md),
[KPI Dictionary](docs/architecture/KPI_DICTIONARY.md), and data contracts
before extending the analytical outputs.

## Project status

Implemented pipeline and analytics contracts are documented alongside their
code and tests. Historical local runtime evidence is explicitly date-scoped.
Production scoring service, hosted Power BI refresh, and an external scheduler
such as Airflow remain out of scope; the in-repo DAG runner is implemented and
tested. The [Project Charter](docs/project/PROJECT_CHARTER.md)
is the source for the current scope and roadmap.
