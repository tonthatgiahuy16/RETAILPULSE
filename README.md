# RetailPulse

RetailPulse is a learning project for a reproducible retail-data pipeline.

## Current status

Slice 1 has a hash-recorded UCI source snapshot, its initial profile, source-snapshot metadata, a PostgreSQL raw-layer migration, and a streaming raw-loader implementation with unit tests. On 2026-10-29 the migration and full raw ingestion were exercised against the local development database. The hash-recorded source manifest and raw table both contain 1,067,371 rows (525,461 for `Year 2009-2010`; 541,910 for `Year 2010-2011`). One same-hash rerun was recorded as `SKIPPED_ALREADY_LOADED` with no new raw rows; an intentionally failed insert was rolled back and recorded as `FAILED`.

Slice 2's staging migration was applied to the same local development database on 2026-10-29 and its SQL gate passed. `stg.online_retail_transaction` contains 1,067,371 source-row-grain rows: 1,047,877 `SALE` and 19,494 `CANCELLATION`; no row is `QUARANTINE` for this snapshot. Every cancellation remains `NOT_EVALUATED` for return matching.

## Slice 1 contract

The input is an immutable source file. Its SHA-256 hash identifies its content. The same hash must not create a second raw copy. Raw rows retain their source sheet and row number; business-level duplicates are not removed at raw ingestion.

Read [`docs/data/LINEAGE_AND_BATCHING.md`](docs/data/LINEAGE_AND_BATCHING.md) before implementing the database loader.

## Run the available tests

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
```

## Run Slice 1 against PostgreSQL

Set `DATABASE_URL` outside the repository, then run the migration and one ingestion attempt. `--source-retrieved-at` is the actual retrieval time of this local snapshot and must include its timezone.

```powershell
$env:PYTHONPATH = 'src'
$env:DATABASE_URL = 'postgresql://...'
python scripts/ingest_raw.py data/raw/online_retail_ii/online_retail_II.xlsx `
  --source-uri 'https://archive.ics.uci.edu/dataset/502/online+retail+ii' `
  --source-retrieved-at '<actual-retrieval-time-with-timezone>' `
  --apply-migration
```

The loader streams rows, records each attempt in `ops.ingestion_batch`, serializes same-hash attempts with a PostgreSQL advisory lock, and inserts the source manifest, raw rows, and `SUCCEEDED` state in one transaction. A repeat of the same SHA-256 creates a `SKIPPED_ALREADY_LOADED` audit batch and no new raw rows. The command output is evidence for one run only; inspect the reported count and database reconciliation before treating the raw snapshot as published.

## Not yet implemented

- marts, reconciliation/data-quality report, customer analytics, model, dbt, and Airflow
