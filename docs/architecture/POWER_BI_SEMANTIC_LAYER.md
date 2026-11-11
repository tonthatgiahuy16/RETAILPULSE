# Power BI semantic layer — Slice 15

## Purpose and boundary

Schema `bi` is the only PostgreSQL schema intended for the Power BI data
source. Its views are thin projections of published `mart`, `dw`, `decision`,
and candidate-diagnostic contracts; they never read the workbook or `raw`
tables directly. Every analytical relation retains `source_file_id` and, where
available, `source_sha256`. A report must filter or visibly label its source
snapshot and must not silently add different snapshots together.

This migration creates semantic contracts only. It does not create a database
login, store a password, publish a Power BI report, configure gateway refresh,
or write model propensity scores to PostgreSQL.

## Relations and grains

| Power BI relation | Grain | Published source | Intended use |
|---|---|---|---|
| `bi.source_snapshot` | One successfully ingested source file | `ops.source_file` + successful batch | Snapshot filter/label. |
| `bi.sales_daily` | Source snapshot × event date | `mart.revenue_daily` | Revenue and Customer-ID coverage KPIs. |
| `bi.sales_line` | One `SALE` staging source row | `dw.fct_sales_line` + dimensions | Product, country, and time analysis. |
| `bi.customer_lifecycle_snapshot` | Source snapshot × RFM as-of date × customer | `decision.customer_priority_snapshot` | RFM and descriptive priority segmentation. |
| `bi.customer_cohort_retention` | Source snapshot × cohort month × activity month | `mart.customer_cohort_retention` | Cohort heatmap/retention curve. |
| `bi.cancellation_diagnostic` | Source snapshot × candidate status × candidate_reason | `int.cancellation_match_resolution` | Candidate diagnostic counts only; includes candidate_reason since 2026-11-10. |
| `bi.repurchase_baseline_evaluation` | Source snapshot × label windows | `mart.customer_repurchase_baseline_evaluation` | Historical baseline evaluation. |
| `bi.repurchase_model_evaluation` | Source snapshot × model name | `mart.repurchase_model_evaluation` | Logistic regression vs rule baseline backtest. |

The SQL gate `tests/sql/020_powerbi_semantic_layer.sql` reconciles all eight
Power BI views to their published source contracts:
- `bi.source_snapshot` matches successfully ingested `ops.source_file` records;
- `bi.sales_daily` reconciles with `mart.revenue_daily`;
- `bi.sales_line` matches `dw.fct_sales_line` row counts and lineage;
- `bi.customer_lifecycle_snapshot` matches `decision.customer_priority_snapshot`;
- `bi.customer_cohort_retention` matches `mart.customer_cohort_retention`;
- `bi.cancellation_diagnostic` asserts candidate diagnostic categories and interpretation labels;
- `bi.repurchase_baseline_evaluation` reconciles with `mart.customer_repurchase_baseline_evaluation`;
- `bi.repurchase_model_evaluation` reconciles with `mart.repurchase_model_evaluation` and asserts the backtest interpretation disclaimer.

## Interpretation rules carried into reports

- `gross_sales_amount` and `net_transaction_amount` are event-date transaction
  amounts, **not accounting revenue**.
- Cancellation candidate statuses are heuristic diagnostics, **not confirmed
  returns**, and must not be netted as an additional revenue adjustment.
- Rows with missing Customer ID remain in revenue; customer analytics excludes
  them through its separate eligibility contract.
- Customer lifecycle priority is a descriptive RFM rule, not a propensity
  score. The repurchase baseline is a historical label evaluation, not a
  campaign response, uplift, or ROI result.

## Provision a least-privilege Power BI login

Run the migration/publish gates first. Then a PostgreSQL administrator creates
a dedicated login with a password supplied outside this repository and runs
the following after replacing `retailpulse_powerbi_reader` with the chosen
role name:

```sql
create role retailpulse_powerbi_reader login password '<store outside Git>';
grant connect on database retailpulse to retailpulse_powerbi_reader;
grant usage on schema bi to retailpulse_powerbi_reader;
grant select on all tables in schema bi to retailpulse_powerbi_reader;
grant usage on schema stg to retailpulse_powerbi_reader;
```

The migration owner should also grant future `bi` views when a later migration
adds them:

```sql
alter default privileges in schema bi
grant select on tables to retailpulse_powerbi_reader;
```

PostgreSQL can inline the typed conversion functions used by
`mart.revenue_daily`; therefore the role needs `USAGE` (but **not** `SELECT`)
on `stg` for `bi.sales_daily` to execute. This technical schema lookup does not
allow browsing or reading staging relations. Do not grant this role `CREATE`,
`INSERT`, `UPDATE`, `DELETE`, membership in the pipeline owner role, or
`SELECT` on `raw`, `stg`, `int`, `ops`, `mart`, `dw`, or `decision` schemas.

## Connect Power BI Desktop

1. Choose **Get data → PostgreSQL database** and enter the PostgreSQL server
   and database name. Use the dedicated read-only login; keep its password in
   Power BI's credential store, not a `.pbix` note, script, or this repository.
2. Start with **Import** mode. The current sales-line fact is about one million
   rows; Import keeps the model predictable for this learning project. Use
   DirectQuery only after measuring the target database and documenting the
   reason.
3. Select only `bi.*` relations. In the model, relate
   `bi.sales_line[date_key]` to a copy of the date dimension if a separate
   report calendar is needed; do not join snapshots by invoice number.
4. Add `bi.source_snapshot[source_file_id]` as a report-level filter or a
   visible snapshot label. For the current known dataset there is one published
   source snapshot, but the contract does not assume that forever.
5. Reconcile displayed totals to `bi.sales_daily` for the selected snapshot
   before publishing. Keep the interpretation warnings visible on revenue,
   cancellation, and decision pages.

## Static PBIP checks and TMDL defaults

Run `python scripts/validate_powerbi_project.py` (optionally with
`--root <pbip-folder>`) to gate the PBIP metadata. CI runs the same command and
`tests/test_powerbi_project_validation.py`, which validates the repository's
actual Power BI-saved files.

Power BI Desktop rewrites TMDL on save and omits properties that equal their
model default. A relationship is **many-to-one** unless it declares otherwise,
so a saved relationship with only `fromColumn`/`toColumn` is still
`many` to `one`; do not re-add `fromCardinality`/`toCardinality` just to make a
check pass. The validator resolves those defaults and separately asserts that
each `Snapshot_*` relationship joins the expected `bi.*` table to
`bi source_snapshot`, so an omitted default cannot hide a mis-wired relation.
Each visible `source_snapshot_slicer` must not persist a filter, because a
saved filter literal would pin the report to one snapshot id.

When adding a snapshot consumer, add a `Snapshot_<table>` relationship with
`<table>.source_file_id` as `fromColumn` and
`bi source_snapshot.source_file_id` as `toColumn`. Explicit cardinality is
optional and is only needed when a relation is not many-to-one.

Desktop also adds a trailing blank line to every TMDL file it saves. That is
whitespace only, but `git diff --check` reports it as `new blank line at EOF`;
strip the extra line before committing instead of treating it as drift.
`powerbi/**` is pinned to CRLF in `.gitattributes`, and the cosmetic
`diagramLayout.json` canvas file is ignored.

## Refresh and evidence

`bi` views update when their upstream published relations update. The
warehouse materialized views still refresh through the normal pipeline runner;
Power BI refresh does not run ingestion, migrations, or SQL gates. Record the
runner output, selected source snapshot, Power BI refresh timestamp, and the
reconciled KPI totals as separate runtime evidence.
