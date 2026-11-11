# dbt adapters — role and boundary

dbt in this repository is a **verification and lineage layer**, not the
transformation engine. PostgreSQL migrations `002` and `022` own transaction
classification, migration `003` owns revenue arithmetic, and migrations
`004`, `006`, and `023` own reconciliation. The dbt models are view adapters over
those published contracts, created in `analytics_staging` and
`analytics_marts` by the example profile.

What the adapter layer provides:

- discoverable model documentation in `models/models.yml`;
- 12 generic schema tests (uniqueness, null, accepted values) and 2 singular
  reconciliation tests in `tests/`;
- dbt lineage over the existing PostgreSQL relations;
- no second stored copy: both layers materialize as **views**.

The role is enforced by [`tests/test_dbt_adapters.py`](../tests/test_dbt_adapters.py):
every model must be exactly `select * from {{ source(...) }}`, declare a
distinct `config(alias='...')`, stay a view, and be documented in
`models/models.yml`; singular tests may only `ref` declared models.

## Add a new adapter

1. Add or change the contract in `migrations/` first (immutable once released),
   then run `python scripts/run_pipeline.py`.
2. Register the source table in `models/sources.yml`.
3. Add `models/<layer>/<name>.sql`:

   ```sql
   {{ config(alias='<published_relation>') }}

   select *
   from {{ source('<source_name>', '<published_relation>') }}
   ```

4. Document it in `models/models.yml` and add tests.
5. Run `dbt build --project-dir dbt --profiles-dir <dir>` locally; it needs
   PostgreSQL and the optional `transform` extra.

## Do not

- reimplement joins, aggregation, or business logic in dbt before the migration
  contract exists;
- change adapters to `table`/`incremental` materializations;
- add a second source snapshot to make a dbt test pass;
- put credentials or `profiles.yml` in the repository.

Local evidence: on 2026-10-29 the adapter build passed 14 tests; on 2026-11-10
a reported local `dbt build` finished `PASS=16 WARN=0 ERROR=0 SKIP=0`
(2 models + 14 tests). These are date-scoped local results, not a hosted CI
claim.
