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

## Scheduling and limits

- For recurring runs, schedule `python scripts/run_dag.py` (it runs once by
  default) from Task Scheduler or cron. `--interval-seconds` with `--max-runs`
  is available for a short local loop, not for production scheduling.
- One process, one host: there is no worker pool, queue, distributed lock
  beyond the migration advisory lock, run-history table, or SLA/alerting
  integration beyond the webhook.
- The runner does not schedule itself, retry across process restarts, or
  refresh Power BI.
