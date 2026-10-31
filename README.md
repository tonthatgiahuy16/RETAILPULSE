# RetailPulse

RetailPulse is a learning project for a reproducible retail-data pipeline.

The project purpose, scope, decision guardrails, and evidence policy are in
the [Project Charter](docs/project/PROJECT_CHARTER.md). Technical contracts
remain under [`docs/data/`](docs/data/) and [`docs/architecture/`](docs/architecture/).

## Current status

Slice 1 has a hash-recorded UCI source snapshot, its initial profile, source-snapshot metadata, a PostgreSQL raw-layer migration, and a streaming raw-loader implementation with unit tests. On 2026-10-29 the migration and full raw ingestion were exercised against the local development database. The hash-recorded source manifest and raw table both contain 1,067,371 rows (525,461 for `Year 2009-2010`; 541,910 for `Year 2010-2011`). One same-hash rerun was recorded as `SKIPPED_ALREADY_LOADED` with no new raw rows; an intentionally failed insert was rolled back and recorded as `FAILED`.

Slice 2's staging migration was applied to the same local development database on 2026-10-29 and its SQL gate passed. `stg.online_retail_transaction` contains 1,067,371 source-row-grain rows: 1,047,877 `SALE` and 19,494 `CANCELLATION`; no row is `QUARANTINE` for this snapshot. Every cancellation remains `NOT_EVALUATED` for return matching.

Slice 3's event-date revenue mart was applied and reconciled against staging on the same local database. `mart.revenue_daily` has 604 snapshot-day rows with gross sales `20,813,918.428`, cancellation signed amount `-1,526,667.86`, and net transaction amount `19,287,250.568`; it includes 1,067,371 transaction rows, of which 243,007 have missing Customer ID. This is not accounting revenue and cancellations are not return-matched.

Slice 4's reconciliation/data-quality report and fail-fast SQL gate were applied locally on 2026-10-29. The gate reconciles expected manifest rows to raw and staging counts, checks unique staging lineage and class coverage, and requires at least one mart day per published source snapshot.

Slices 5 and 6 added a checksum-backed migration ledger, serialized migration runner, PostgreSQL integration CI, and dbt adapters. The ledger was bootstrapped through migration 006 on the local database; a rerun left every ledger application timestamp unchanged. A local dbt build created its two adapter views and passed all 14 tests without committing a credential.

Slices 7–10 add candidate-only cancellation diagnostics, customer purchase events, data-derived RFM snapshots, and a leakage-safe repurchase-label baseline. They do not turn a cancellation candidate into an accounting return, net candidate cancellations from revenue, or claim campaign uplift/ROI.

Slice 15 adds a snapshot-aware, read-only `bi` semantic layer for Power BI.
Migration 020 was applied to the local development database on 2026-10-31;
direct PostgreSQL queries returned 604 daily revenue rows, 1,047,877 sales-line
rows, 5,878 customer-lifecycle rows, and 325 cohort-retention rows. A dedicated
Power BI login, report, gateway, and refresh evidence are deliberately separate
administrator/report-author steps and are not stored in this repository.

## Slice 1 contract

The input is an immutable source file. Its SHA-256 hash identifies its content. The same hash must not create a second raw copy. Raw rows retain their source sheet and row number; business-level duplicates are not removed at raw ingestion.

Read [`docs/data/LINEAGE_AND_BATCHING.md`](docs/data/LINEAGE_AND_BATCHING.md) before implementing the database loader.

## Run the available tests

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
```

GitHub Actions starts an isolated PostgreSQL service, exercises migration bootstrap/rerun and concurrent runners, then runs `dbt build`. The PostgreSQL integration tests are intentionally skipped on a developer machine unless both `RETAILPULSE_INTEGRATION_TEST=1` and a dedicated `RETAILPULSE_INTEGRATION_DSN` are supplied; they reset schemas and must never point at a shared database.

## Run migrations, ingestion, and publish gates

Set `DATABASE_URL` outside the repository, then run the migration and one ingestion attempt. `--source-retrieved-at` is the actual retrieval time of this local snapshot and must include its timezone.

```powershell
$env:PYTHONPATH = 'src'
$env:DATABASE_URL = 'postgresql://...'
python scripts/run_pipeline.py `
  --workbook data/raw/online_retail_ii/online_retail_II.xlsx `
  --source-uri 'https://archive.ics.uci.edu/dataset/502/online+retail+ii' `
  --source-retrieved-at '<actual-retrieval-time-with-timezone>'
```

The runner records each applied migration and its SHA-256 in `ops.schema_migration`, refuses migration drift, then runs SQL publish gates after ingestion. The loader first materializes a private copy of the workbook and hashes that exact copy; it serializes same-hash attempts with a PostgreSQL advisory lock, then inserts the source manifest, raw rows, and `SUCCEEDED` state in one transaction. A repeat of the same SHA-256 creates a `SKIPPED_ALREADY_LOADED` audit batch and no new raw rows. The command output is evidence for one run only; inspect the reported count and database reconciliation before treating the raw snapshot as published.

## Repurchase model evaluation

The optional model command builds rolling temporal examples from published
customer events, evaluates Logistic Regression against the frequency rule, and
writes a local JSON report. It does not publish scores or claim uplift/ROI.
See [Repurchase model evaluation](docs/architecture/REPURCHASE_MODEL_EVALUATION.md).

## Power BI semantic layer

After the pipeline has published a source snapshot, connect Power BI only to
the read-only `bi` schema. It provides snapshot-aware sales, customer
lifecycle, cohort, cancellation-diagnostic, and baseline-evaluation views;
it does not expose raw data or create a Power BI login automatically. See
[Power BI semantic layer](docs/architecture/POWER_BI_SEMANTIC_LAYER.md) for
least-privilege provisioning, Import-mode connection steps, KPI reconciliation,
and reporting limits.

## Not yet implemented

- production scoring service and Airflow

## dbt contract checks

The dbt project in [`dbt/`](dbt/) exposes the already-verified PostgreSQL staging and mart contracts as analytics views without restating their business logic. See [`docs/architecture/DBT_CONTRACTS.md`](docs/architecture/DBT_CONTRACTS.md) for the environment-only profile and `dbt build` command.
