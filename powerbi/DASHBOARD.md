# RetailPulse Power BI dashboard

The PBIP project exposes only the PostgreSQL `bi` semantic layer. Open
`RetailPulse.pbip` in Power BI Desktop, refresh the imported model, and apply
external changes when prompted after regenerating the report files.

The model deliberately uses `bi source_snapshot` as the one-side snapshot
dimension for every consumer view. It does not retain Power BI's inferred
many-to-many relationships or duplicate cancellation-diagnostic query, because
both can fan out filters and make cross-view totals misleading.

## Connection parameters and local state

`RetailPulsePostgresServer` and `RetailPulsePostgresDatabase` are Power Query
parameters in `RetailPulse.SemanticModel/definition/expressions.tmdl`. Change
them through **Transform data â†’ Manage parameters** for a different local or
gateway endpoint, then refresh. They contain only endpoint names; the
read-only PostgreSQL password remains in Power BI's credential store.

The `.pbi/` folders are ignored because they hold machine-local editor state
and an imported-model cache. The checked-in PBIP definition is sufficient to
open the report and configure a local connection.

## Pages and metric contract

| Page | Decision support | Primary source | Grain / interpretation |
|---|---|---|---|
| Overview | Monitor sales volume and Customer ID coverage | `bi.sales_daily` | One source snapshot × event date. Net transaction amount is event-date transaction amount, not accounting revenue. |
| Customer lifecycle | Prioritise descriptive RFM segments and inspect retention | `bi.customer_lifecycle_snapshot`, `bi.customer_cohort_retention` | Customer snapshot and cohort-month activity. Priority is descriptive, not a propensity score; capacity is illustrative. |
| Data quality & diagnostics | Inspect incomplete customer identity, cancellation candidates, and historical baseline outputs | `bi.sales_daily`, `bi.cancellation_diagnostic`, `bi.repurchase_baseline_evaluation`, `bi.source_snapshot` | Candidate cancellation matches are diagnostic only. Baseline labels are historical, not campaign response or causal uplift. |

`Missing customer ID share` is a measure defined as total missing-Customer-ID
rows divided by total transaction rows; it deliberately does not sum daily
shares. `Weighted retention rate` is total retained customers divided by total
cohort customers in the visual filter context.

## Regenerate

```powershell
python scripts/build_powerbi_report.py
```

The generator creates PBIR visual files only; it does not refresh PostgreSQL,
publish a report, change credentials, or create a Power BI Service artifact.

## Verify after opening in Power BI Desktop

1. Select **Apply external changes** if Power BI prompts for it.
2. Refresh the model and resolve any PostgreSQL credential prompt locally.
3. Use the visible **Source snapshot** slicer on each page when more than one
   snapshot exists; do not compare totals across snapshots without an explicit
   comparison contract.
4. Compare Overview totals with `mart.revenue_daily` through the existing SQL
   gate before treating the report as published evidence.
