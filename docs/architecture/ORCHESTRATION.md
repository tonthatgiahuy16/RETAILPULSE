# Orchestration — in-repo DAG runner

`scripts/run_dag.py` runs the batch pipeline as a dependency graph. It is not a
scheduler service: it executes one run (or a fixed interval loop) and records
JSON evidence. An external scheduler such as Task Scheduler, cron, or a CI job
calls it. Airflow is intentionally not part of this slice.

## Graph

```
validate_inputs
      |
   migrate
      |
   ingest            (optional: skipped when no workbook is supplied)
      |
  sql_gates
   /       \
dbt_build  train_model   (both optional, enabled by flags)
   \       /
powerbi_refresh          (manual gate; never claims a refresh)
```

Every database task opens its own connection, so a retry does not reuse a
connection left in a failed transaction. `migrate` calls the same
`apply_migrations` ledger; `ingest` reuses `ingest_workbook` and the
materialized-view refresh; `sql_gates` runs `tests/sql/*.sql`.

## Run one pipeline

```powershell
$env:PYTHONPATH = 'src'
# DATABASE_URL must be set in the environment.
python scripts/run_dag.py `
  --workbook data/raw/online_retail_ii/online_retail_II.xlsx `
  --source-uri 'https://archive.ics.uci.edu/dataset/502/online+retail+ii' `
  --source-retrieved-at '<actual-retrieval-time-with-timezone>'
```

Optional tasks:

```powershell
# include dbt build and model training
python scripts/run_dag.py --workbook <path> --source-uri <uri> --source-retrieved-at <ts> --with-dbt --train-model
```

Use `--model-output` and `--model-markdown-output` to keep generated model
artifacts outside the tracked default paths, for example in a CI artifact
directory. The `model-evaluation` CI job uses a synthetic fixture to exercise
training, persistence, BI validation, and dashboard compilation.

Without `--workbook`, `ingest` is skipped and the run applies migrations and
SQL gates only. Use `--dry-run` to print the topological order without a
database or credentials:

```powershell
python scripts/run_dag.py --dry-run
```

## Retry, skip, and alert behavior

- Each task is retried up to `--max-attempts` (default 2) with exponential
  backoff `--backoff-seconds * 2^(attempt-1)`.
- A failed task blocks only its downstream tasks; independent branches still
  run. A blocked task is recorded as `skipped` with `blocked: true`.
- Optional tasks that are disabled return `skipped` without blocking
  downstream tasks.
- On a failed run, if `RETAILPULSE_ALERT_WEBHOOK` is set, the runner POSTs a
  JSON summary. Delivery failure is printed but never hides the run result.

## Power BI refresh boundary

A local PBIP report in Import mode cannot be refreshed by this runner. The
`powerbi_refresh` task therefore either:

- returns a `manual_action` telling the operator to refresh in Power BI Desktop
  and record evidence; or
- verifies a JSON evidence file passed with `--powerbi-evidence` containing
  `refreshed_at` and `source_file_id`.

Verifying evidence is not a refresh. The run record keeps that distinction in
`manual_actions` and in the task detail.

## Run record

`--output` (default `data/processed/orchestration/last_run.json`) receives:

```json
{
  "run_id": "…",
  "started_at": "…",
  "finished_at": "…",
  "status": "succeeded | failed",
  "tasks": [
    {"name": "sql_gates", "status": "succeeded", "attempts": 1, "elapsed_seconds": 0.4, "detail": {}, "error": null, "blocked": false, "skipped_reason": null}
  ],
  "manual_actions": []
}
```

The same JSON is printed to stdout. CI uploads its run record as an artifact.
`sql_gates.detail.timings` records one `{name, elapsed_seconds}` entry per SQL
gate, and `ingest.detail.materialized_view_timings` records one per refreshed
view. These detail fields are what make latency attribution possible.

## Run history and latency summaries

Every normal run also appends one compact JSON line to
`data/processed/orchestration/run_history.jsonl` (local and gitignored). Each
line records the run total, per-task status and elapsed time, the slowest tasks,
and the slowest SQL gates and materialized views. Use
`--history-output` to redirect it and `--no-history` to disable it.

```powershell
python scripts/report_pipeline_runs.py --last 10
python scripts/report_pipeline_runs.py --last 10 --json
```

The report prints per-task median, max and latest elapsed seconds plus the
slowest gates and views from the latest run. It reads only the JSONL history; it
does not query PostgreSQL. With fewer than two runs the medians equal the single
observed value, so do not over-interpret them.

## Latency and materialized-view refresh

- The runner prints `[dag] <task> started` and `[dag] <task> <status> <seconds>`
  to stderr while it works; the JSON record is printed at the end.
- `ingest` refreshes eight materialized views after every ingestion attempt,
  including a same-hash `SKIPPED_ALREADY_LOADED`. `refresh materialized view
  dw.fct_sales_line` is the expensive step: it evaluates
  `stg.try_invoice_timestamp` per row over the full sales fact, and the refresh
  sets `max_parallel_workers_per_gather = 0`.
- `--skip-refresh` skips that step. Use it only when the raw snapshot is
  unchanged and the views are already known fresh; otherwise the views can
  remain stale. The refresh is transactional, so canceling leaves the previous
  view contents in place.

### Local latency baseline

A single local measurement on 2026-11-12 (source snapshot `1`, 13 SQL gates,
run through `run_sql_checks` with per-gate timings) took `1073.9s`. The slowest
gates were `020_powerbi_semantic_layer.sql` (`347.4s`),
`mart_revenue_daily.sql` (`238.0s`),
`staging_transaction_classification.sql` (`196.8s`), and
`022_revenue_adjustment_contract.sql` (`137.8s`). All 13 gates are read-only
reconciliation checks, so the cost is full-table scanning, not writes.

This is one local observation, not a benchmark or CI evidence. The gate set and
database state differ from the earlier 2026-11-10 run, which had 12 gates and
took `549.7s`; do not compare the totals as if only code changed. Use
`report_pipeline_runs.py` after several runs before choosing an optimization.

### Measured optimization (2026-11-12)

Two gates were rewritten without changing their assertions:

- `020_powerbi_semantic_layer.sql`: the daily comparison now materializes
  `bi.sales_daily` and `mart.revenue_daily` once and compares them with a
  symmetric full join, instead of scanning both relations in both EXCEPT
  directions. A row-count equality check plus an explicit duplicate-key check on
  both sides keeps the comparison equivalent when a key is duplicated, including
  the case where both contracts duplicate the same key identically.
- `staging_transaction_classification.sql`: raw coverage uses one windowed scan
  of `raw.online_retail_line`, and the class/quarantine/match-status checks share
  one scan of `stg.online_retail_transaction`.

Both gates passed before and after. On the same local database and gate set as
the baseline above:

| Gate | Before | After | Change |
|---|---:|---:|---:|
| `020_powerbi_semantic_layer.sql` | 347.4s | 147.5-191.6s | -45% to -58% |
| `staging_transaction_classification.sql` | 196.8s | 74.5-76.2s | -61% to -62% |
| All 13 gates | 1073.9s | 765.8-887.4s | -17% to -29% |

The ranges are separate local runs, not a single before/after pair. One run
exceeded a 1500s timeout while an orphaned session held the mart gate; after
terminating that backend, the full set completed in 887.4s. Treat the slower end
as machine/IO variance rather than a code regression.

A single-scan rewrite of `022_revenue_adjustment_contract.sql` was tried and
reverted: it measured `141.3s` against the `137.8s` baseline, so it added
complexity without a measurable gain. `mart_revenue_daily.sql` (`~240-267s`) was
not optimized; it still needs one scan to derive expected rows and one to read
the mart view, so it remains the largest single gate.

Timings vary between runs on this machine (for example `020` measured 147-192s
across runs, `022` 130-184s), so treat the percentages as directional and compare
medians from several runs before claiming a stable improvement. These are
single-run local observations, not CI evidence.

## Scheduling and limits

- For recurring runs, schedule `python scripts/run_dag.py` (it runs once by
  default) from Task Scheduler or cron. `--interval-seconds` with `--max-runs`
  is available for a short local loop, not for production scheduling.
- One process, one host: there is no worker pool, queue, or distributed lock
  beyond the migration advisory lock. Run history is a local JSONL file, not a
  shared database table, and alerting is limited to the optional webhook.
- The runner does not schedule itself, retry across process restarts, or
  refresh Power BI.
