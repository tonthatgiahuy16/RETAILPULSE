# RetailPulse

RetailPulse is a learning project for a reproducible retail-data pipeline.

## Current status

Slice 1 foundations are present: a hash-recorded UCI source snapshot, its initial profile, source-snapshot metadata, a PostgreSQL raw-layer migration, and unit tests for file identity. No database migration has run and no data has been loaded.

## Slice 1 contract

The input is an immutable source file. Its SHA-256 hash identifies its content. The same hash must not create a second raw copy. Raw rows retain their source sheet and row number; business-level duplicates are not removed at raw ingestion.

Read [`docs/data/LINEAGE_AND_BATCHING.md`](docs/data/LINEAGE_AND_BATCHING.md) before implementing the database loader.

## Run the available tests

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
```

## Not yet implemented

- PostgreSQL connection and migration execution
- Raw loader
- dbt staging, marts, dashboard, customer analytics, model, and Airflow
