# dbt contract adapters — Slice 6

The project lives in [`dbt/`](../../dbt/). It intentionally does **not** restate transaction classification or revenue arithmetic: those PostgreSQL views have already been applied and reconciled by migrations 002–004. The dbt staging and mart models are view adapters over those verified contracts, placed in `analytics_staging` and `analytics_marts` under the example profile. They add model documentation, schema tests, lineage in dbt, a no-auto-match cancellation test, and a mart-to-staging reconciliation test without creating another competing definition of revenue.

Copy `dbt/profiles.example.yml` outside the repository as `profiles.yml`; credentials remain environment variables. Install the optional `transform` extra (which supplies the PostgreSQL dbt adapter) and, after the database has been migrated, run:

```powershell
$env:PYTHONPATH = 'src'
python -m pip install -e '.[transform]'
python scripts/run_pipeline.py
$env:DBT_PROFILES_DIR = '<directory containing profiles.yml>'
dbt build --project-dir dbt
```

On 2026-10-29, a local `dbt build` created both adapter views and passed all 14 tests against the local PostgreSQL snapshot. It needs a PostgreSQL connection and `dbt-postgres` installed in the active environment; no credential belongs in the repository.
