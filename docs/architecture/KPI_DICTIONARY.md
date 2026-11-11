# RetailPulse KPI dictionary

This is the published definition for metrics exposed in RetailPulse analytics,
dashboard, or decision-support work. Every metric is scoped by immutable
`source_file_id`; use `source_sha256` and `ops.source_file.source_retrieved_at`
to identify the exact source snapshot. Do not add different snapshots together
unless a consumer documents why that comparison is valid.

## Policy and interpretation

- Revenue KPIs are **event-date transaction amounts**, not accounting revenue.
  A cancellation candidate is never a confirmed return and is never netted as
  an extra accounting adjustment.
- Missing Customer ID remains in revenue. It is excluded upstream from the
  customer-event eligibility contract and therefore from RFM, cohort, label,
  and baseline consumers.
- Data-derived dates take precedence over the machine date: RFM as-of date,
  cohort snapshot end, and label windows come from eligible purchase events.
- Candidate statuses are diagnostic heuristic outcomes, not financial facts.

## Revenue

**Relation:** `mart.revenue_daily`
**Grain:** one `(source_file_id, event_date)` row.
**Input:** published `stg.online_retail_transaction` rows where
`transaction_class in ('SALE', 'CANCELLATION')`.

Parse-valid non-`C` negative-quantity rows are `ADJUSTMENT` and are excluded
from all revenue KPIs; see the [snapshot-scoped adjustment contract](../data/REVENUE_ADJUSTMENT_CONTRACT.md).

| KPI | SQL definition | Missing-data treatment | Limit / label rule |
|---|---|---|---|
| Gross Sales | `sum(case when transaction_class = 'SALE' then quantity * unit_price else 0 end)` | Invalid required fields are `QUARANTINE` and excluded; missing Customer ID stays included. | Gross event-date sales, not invoiced, paid, or accounting revenue. |
| Signed Cancellation Amount | `sum(case when transaction_class = 'CANCELLATION' then quantity * unit_price else 0 end)` | Same published staging boundary. | Preserves the source sign; not a matched-return amount. |
| Net Transaction Amount | `sum(quantity * unit_price)`; equivalently gross sales plus signed cancellation amount. | Same published staging boundary. | Must not be relabelled as accounting net revenue. |
| Transaction Row Count | `count(*)` of included staging rows. | Includes rows with missing Customer ID; excludes `ADJUSTMENT`. | Counts source rows, not invoices or customers. |
| Missing Customer ID Row Count | `count(*) filter (where is_missing_customer_id)` | Counted, never discarded from revenue. | Coverage diagnostic, not a customer count. |
| Missing Customer ID Share | `missing_customer_id_row_count::numeric / nullif(transaction_row_count, 0)` | `NULL` with a zero denominator. | Derived ratio at the same grain; do not average daily shares without weighting. |

## Cancellation diagnostics

**Relations:** `int.cancellation_match_resolution`,
`int.cancellation_sale_candidate`, and
`mart.customer_purchase_event_cancellation_diagnostic`.
**Resolution grain:** one cancellation source row:
`(source_file_id, cancellation_sheet_name, cancellation_source_row_number)`.

| Diagnostic | SQL definition | Missing-data treatment | Limit |
|---|---|---|---|
| Candidate Count | `count(*)` candidate edges per cancellation row. | Missing Customer ID/Stock Code and invalid quantity remain explicit in `candidate_reason`. | Heuristic evidence only. |
| Matched Candidate Count | `count(*) filter (where candidate_status = 'MATCHED_CANDIDATE')` | Exactly one candidate edge. | Does not establish an accounting return. |
| Ambiguous Count | `count(*) filter (where candidate_status = 'AMBIGUOUS')` | More than one candidate edge. | Must not be attributed to one sale. |
| Unmatched Count | `count(*) filter (where candidate_status = 'UNMATCHED')` | Zero candidate edges. | Does not prove that no real-world return relation exists. |
| Event Candidate Diagnostics | Counts of matched/ambiguous resolution rows at customer-event grain. | Event can have zero diagnostic rows. | Informational only; never subtract from `gross_purchase_amount`. |

The candidate heuristic requires the same source snapshot, customer, stock
code, exact absolute quantity, and sale timestamp no later than cancellation
timestamp. See [cancellation candidates](CANCELLATION_MATCH_CANDIDATES.md).

## Customer purchase events

**Relation:** `mart.customer_purchase_event`
**Grain:** one `(source_file_id, customer_id, invoice_no)` row.
**Eligibility:** `SALE`, non-null Customer ID, positive quantity, and positive
unit price, as recorded by `int.customer_analytics_row_eligibility`.

| KPI | SQL definition | Missing-data treatment | Limit |
|---|---|---|---|
| Eligible Customer Purchase Events | `count(*)` from the relation. | Missing Customer ID and non-eligible sales are excluded. | One event is customer × invoice, not a raw line key. |
| Eligible Sale Row Count | `count(*)` eligible sale rows within the event. | Only eligible sale rows. | Supporting metric; not total invoices across snapshots. |
| Gross Purchase Amount | `sum(sale_quantity * sale_unit_price)` within the event. | Positive eligible sales only. | No candidate cancellation net-off; not accounting customer revenue. |
| Active Customer Count | `count(distinct customer_id)` at an explicitly stated consuming time grain. | Missing Customer ID excluded upstream. | Never aggregate across snapshots without a snapshot policy. |

## RFM snapshot

**Relation:** `mart.customer_rfm_snapshot`
**Grain:** one `(source_file_id, as_of_date, customer_id)` row.
**Input:** `int.customer_purchase_event_snapshot`.

| KPI | SQL definition | Missing-data treatment | Limit |
|---|---|---|---|
| RFM As-of Date | `max(event_at)::date + 1` per source snapshot. | No row for a snapshot with no eligible events. | Data-derived; never replace with today. |
| Recency Days | `as_of_date - max(event_at)::date` per customer. | Eligible events only. | Historical snapshot recency, not live recency. |
| Frequency | `count(*)` eligible customer purchase events. | Missing Customer ID excluded upstream. | Counts invoice events, not raw rows or units. |
| Monetary Amount | `sum(gross_purchase_amount)` eligible events. | Positive eligible sales only. | No candidate cancellation net-off; not LTV/accounting revenue. |
| Last Purchase At | `max(event_at)`. | Eligible events only. | Source timestamp has no timezone. |

## Cohort retention

**Relation:** `mart.customer_cohort_retention`
**Grain:** one `(source_file_id, cohort_month, activity_month)` row.
**Input:** `mart.customer_purchase_event`.
**Calendar:** migration 017 emits every calendar month from a cohort month
through that source snapshot's final event month, including zero-retention
months.

| KPI | SQL definition | Missing-data treatment | Limit |
|---|---|---|---|
| Cohort Month | `date_trunc('month', min(event_at))::date` per customer/snapshot. | Missing Customer ID excluded upstream. | Each customer has one cohort per snapshot. |
| Activity Month | Calendar series through `date_trunc('month', max(event_at))::date`. | Months with no source-wide activity get zero counts. | Keep zero rows in heatmaps. |
| Months Since Cohort | Calendar-month difference between activity/cohort months. | Never negative. | Month index, not elapsed-day duration. |
| Cohort Customer Count | `count(*)` customers first active in cohort month. | Missing Customer ID excluded upstream. | Retention denominator; constant within a cohort. |
| Active Customer Count | `count(distinct customer_id)` for all eligible customers in the source/activity month. | `0` when no eligible activity exists. | Contextual and repeated across cohorts; **do not sum across cohorts**. |
| Retained Customer Count | Cohort customers active in activity month; `coalesce(..., 0)`. | Explicit zero is valid. | Cohort-specific retention numerator. |
| Retention Rate | `retained_customer_count::numeric / cohort_customer_count`. | Cohort size is positive. | Month zero is 100%; zero later retention is valid and descriptive, not causal. |

## Repurchase labels and baseline

**Relations:** `mart.customer_repurchase_label_dataset` and
`mart.customer_repurchase_baseline_evaluation`.
**Label grain:** one `(source_file_id, customer_id)` row for customers active
in the observation window.
**Evaluation grain:** source snapshot × its data-derived temporal windows.

| KPI | SQL definition | Missing-data treatment | Limit |
|---|---|---|---|
| Observation Window | `[prediction_end_date - 270 days, prediction_end_date - 90 days)` (180 days). | Only eligible events contribute features. | Data-derived; not a current-date window. |
| Prediction Window | `[prediction_end_date - 90 days, prediction_end_date)` (90 days), where `prediction_end_date = max(event_at)::date + 1`. | A customer need not purchase in this window. | Label never looks past snapshot end. |
| Repurchase Label | `exists` an eligible purchase event in the prediction window. | Missing Customer ID excluded upstream. | Historical descriptive label, not campaign response/uplift. |
| Observation Recency | `prediction_start_date - max(observation event_at)::date`. | Label requires an observation event. | No prediction-window feature leakage. |
| Observation Frequency | `count(*)` observation purchase events. | Eligible customer events only. | Invoice-event count, not raw rows. |
| Observation Monetary Amount | `sum(gross_purchase_amount)` observation events. | Positive eligible sales only. | No candidate cancellation net-off. |
| Baseline Prediction | `observation_frequency >= 2`. | Evaluated only for labeled customers. | Transparent benchmark, not deployed prediction or recommendation. |
| Labeled / Actual / Predicted Counts | `count(*)`; `count(*) filter (where repurchased_in_prediction_window)`; `count(*) filter (where baseline_predicts_repurchase)`. | Zero-capable. | Scoped to one snapshot/window. |
| True Positives | `count(*) filter (where baseline_predicts_repurchase and repurchased_in_prediction_window)`. | Labeled customers only. | Not campaign conversions. |
| Accuracy | `correct_prediction_count::numeric / labeled_customer_count`. | `NULL` when no labeled customers. | Retrospective and threshold-specific. |
| Precision | `true_positive_count::numeric / predicted_repurchase_customer_count`. | `NULL` when no predicted positives. | Retrospective and threshold-specific. |
| Recall | `true_positive_count::numeric / actual_repurchase_customer_count`. | `NULL` when no actual positives. | Retrospective and threshold-specific. |

## Publication checks

KPI relations are publishable only after the checksum-backed migration ledger
and their SQL gates complete successfully. The main checks are revenue
reconciliation (`mart_revenue_daily.sql`), candidate resolution (`007`),
customer-event reconciliation (`008`), RFM (`009`), label/leakage and baseline
validity (`010`), and cohort/dense-calendar reconciliation (`016`, `017`).

## Dimensional and decision-support measures

**Relations:** `dw.fct_sales_line`, `decision.customer_priority_snapshot`, and
`decision.customer_priority_backtest`.

| Measure | Grain and definition | Limit |
|---|---|---|
| Sales Line Amount | One published `SALE` source row; `quantity * unit_price` in `dw.fct_sales_line`. | Event-date transaction amount, not accounting revenue; null Customer ID remains present with a null dimension key. |
| Customer First Seen | Source snapshot × customer; `min(staging.invoice_at)` in `dw.dim_customer`. | Includes any typed staging transaction with a valid Customer ID/date; it is not the first eligible purchase-event date. |
| Primary Country | Source snapshot × customer; most frequent non-null staging country, with deterministic tie-breaks. | Convenience dimension attribute, not a verified domicile. |
| Current Priority Segment | Source snapshot × RFM as-of date × customer; percentile rule in `decision.customer_priority_snapshot`. | Descriptive segmentation only; no future label or response prediction. |
| Backtest Priority Segment | Source snapshot × customer active in observation window; same rule using observation-only recency/frequency/monetary values. | The label is a historical repurchase outcome, not campaign response or causal uplift. |
| Illustrative Budget Capacity | One fixed scenario: 1,000 campaign units / 2 units per contact / 500 ranks eligible. | No currency, actual cost, response rate, revenue, profit, ROI, or uplift is asserted. |

Gates `018` and `019` validate warehouse lineage/dimensions and decision
grains/disclosures respectively. See [Dimensional warehouse](DIMENSIONAL_WAREHOUSE.md)
and [Customer priority decision](CUSTOMER_PRIORITY_DECISION.md).

## Repurchase model evaluation

**Artifacts:** local ignored JSON output from `scripts/train_repurchase_model.py`
and the versioned [retention-priority decision report](../decision/RETENTION_PRIORITY_DECISION.md).
**Evaluation grain:** one customer at the final data-derived prediction cutoff.

| Measure | Definition | Limit |
|---|---|---|
| PR-AUC | `average_precision_score(label, ranking_score)` on the final temporal holdout. | Ranking quality on one source snapshot; not campaign response. |
| ROC-AUC | `roc_auc_score(label, ranking_score)` on the final temporal holdout. | Does not select an operating threshold. |
| Precision / Recall at 0.5 | Classification metrics using probability `>= 0.5`; baseline remains `observation_frequency >= 2`. | Threshold choice has a recall/precision trade-off. |
| Lift at top 20% | Positive rate among top 20% ranked customers divided by holdout positive rate. | Historical ranking diagnostic; not incremental lift/uplift. |
| Brier Score / Calibration Bins | Mean squared probability error and observed rate in five probability ranges. | Reported for probability model only; calibration needs more snapshots before operational use. |

## Fixed-capacity retention selection

**Cohort:** source snapshot `1`, SHA-256
`bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980`;
temporal holdout window `[2011-09-11, 2011-12-10)` with 2,784 customers.
The positive label is at least one eligible purchase in that historical
90-day window; it is not a campaign response.

For a selected set of size `K = ceil(N * fraction)`:

| Metric | Definition | Limit |
|---|---|---|
| Precision@K | Selected customers with a positive holdout label / selected customer count. | Observed historical purchase rate in the selected group. |
| Recall@K | Selected customers with a positive holdout label / all positive holdout customers. | Coverage of holdout purchasers; not campaign impact. |
| Lift@K | Precision@K / positive rate over the full holdout. | Ranking diagnostic; not incremental lift or uplift. |

The temporal backtest run on 2026-11-11 reports:

| Ranking | Precision@10% / Recall@10% | Precision@20% / Recall@20% | Precision@30% / Recall@30% |
|---|---:|---:|---:|
| RFM priority, contract 019 | 95.0% / 15.4% | 86.5% / 28.0% | 83.5% / 40.5% |
| Frequency naive (`frequency DESC, customer_id ASC`) | 94.6% / 15.3% | 89.8% / 29.0% | 85.4% / 41.5% |
| Frequency business (`frequency DESC, monetary DESC, recency ASC, customer_id ASC`) | 95.0% / 15.4% | 91.0% / 29.4% | 86.1% / 41.8% |
| Logistic Regression | 95.0% / 15.4% | 90.5% / 29.3% | 85.5% / 41.5% |

Frequency business is the simpler operational candidate on this holdout: it
ties LR at 10% and has observed precision differences of +0.539 and +0.598
percentage points at 20% and 30%. Its paired-customer bootstrap 95% confidence
intervals contain zero at all three capacities: 10% `[-0.151, +0.151]` pp,
20% `[-1.015, +2.000]` pp, and 30% `[-0.578, +1.784]` pp. The run therefore
does not establish a precision difference from LR. Frequency naive cuts through
ties at every capacity: 61 of 72, 156 of 209, and 226 of 312 customers in the
respective boundary-frequency groups are selected by its ID tie-breaker.
Repeated customers across rolling cutoffs make those cutoff rows dependent;
neither this one holdout nor an unadjusted average across its cutoffs can claim
stable superiority or campaign effectiveness.

Calibration diagnostics for the same run show pooled training-example positive
rate 46.9%, holdout positive rate 61.9%, and LR mean predicted probability
46.7%. The model uses `class_weight=None`; weighting is not the source of this
run's gap. A log1p sensitivity on frequency and monetary does not reduce it.
The 0.2-0.4 probability bin has 31.8% mean prediction and 46.0% observed rate;
these are bin rates, not the full holdout rate. The observed prevalence shift
is a plausible explanation, but the cutoffs do not establish seasonality as a
cause.

No campaign cost, incremental revenue, profit, ROI or causal uplift is
estimated. Any later economic scenario must be labeled **simulation based on
assumptions**.

The model's rolling examples use 180 observation days and 90 prediction days.
Earlier non-overlapping cutoffs train; the final cutoff must exactly match
`mart.customer_repurchase_label_dataset`. See [Repurchase model evaluation](REPURCHASE_MODEL_EVALUATION.md).

## Power BI consumption boundary

**Schema:** `bi`. Power BI consumers use the semantic views in this schema,
not `raw`, `stg`, `int`, `ops`, `mart`, `dw`, or `decision`. Each BI relation
keeps its source snapshot identifier; report-level totals must be scoped to
one `source_file_id` unless a documented comparison requires otherwise.

| BI relation | KPI family | Grain | Limit |
|---|---|---|---|
| `bi.source_snapshot` | Snapshot filter/label | Successfully ingested source snapshot | One selected `source_file_id` per report; not a time series. |
| `bi.sales_daily` | Revenue and Customer-ID coverage | Source snapshot × event date | Same definitions and event-date/accounting limitation as `mart.revenue_daily`. |
| `bi.sales_line` | Product, country, time sales analysis | One `SALE` source row | Missing Customer ID stays present; cancellation rows are excluded. |
| `bi.customer_lifecycle_snapshot` | RFM and current priority segment | Source snapshot × as-of date × customer | Descriptive rule, not a propensity score; capacity is illustrative only. |
| `bi.customer_cohort_retention` | Cohort retention | Source snapshot × cohort month × activity month | Customer-event eligibility only; zero-retention months are retained. |
| `bi.cancellation_diagnostic` | Cancellation candidate counts | Source snapshot × candidate status × candidate_reason | Candidate diagnostics are not return-accounting facts. |
| `bi.repurchase_baseline_evaluation` | Label-baseline evaluation | Source snapshot × observation/prediction windows | Historical label result, not campaign response, uplift, or ROI. |
| `bi.repurchase_model_evaluation` | Model backtest evaluation | Source snapshot × model name | Written only by the opt-in training step; not campaign response, uplift, or ROI. |

See [Power BI semantic layer](POWER_BI_SEMANTIC_LAYER.md) for the view
contracts, role provisioning, and refresh evidence boundary.

Inspect `ops.schema_migration`, `ops.ingestion_batch`, and the exact runner
output for runtime status. This dictionary defines semantics; it is not itself
evidence that a database refresh has run.
