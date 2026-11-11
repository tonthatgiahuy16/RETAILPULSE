# dbt contract adapters — Slice 6

The project lives in [`dbt/`](../../dbt/). It intentionally does **not** restate transaction classification or revenue arithmetic: migrations `002` and `022` own classification, migration `003` owns revenue arithmetic, and migrations `004`, `006`, and `023` own reconciliation. The dbt staging and mart models are view adapters over those verified contracts, placed in `analytics_staging` and `analytics_marts` under the example profile. They add model documentation, schema tests, lineage in dbt, a no-auto-match cancellation test, and a mart-to-staging reconciliation test without creating another competing definition of revenue.

`tests/test_dbt_adapters.py` enforces that boundary without needing a database or dbt installed: each model must be exactly `select * from {{ source(...) }}`, declare a distinct alias, stay materialized as a view, and be documented in `models.yml`. See [`dbt/README.md`](../../dbt/README.md) for the adapter contract and how to extend it.

Copy `dbt/profiles.example.yml` outside the repository as `profiles.yml`; credentials remain environment variables. Install the optional `transform` extra (which supplies the PostgreSQL dbt adapter) and, after the database has been migrated, run:

```powershell
$env:PYTHONPATH = 'src'
python -m pip install -e '.[transform]'
python scripts/run_pipeline.py
$env:DBT_PROFILES_DIR = '<directory containing profiles.yml>'
dbt build --project-dir dbt
```

On 2026-10-29, a local `dbt build` created both adapter views and passed all 14 tests against the local PostgreSQL snapshot. It needs a PostgreSQL connection and `dbt-postgres` installed in the active environment; no credential belongs in the repository.
