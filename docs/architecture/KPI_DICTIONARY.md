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

| KPI | SQL definition | Missing-data treatment | Limit / label rule |
|---|---|---|---|
| Gross Sales | `sum(case when transaction_class = 'SALE' then quantity * unit_price else 0 end)` | Invalid required fields are `QUARANTINE` and excluded; missing Customer ID stays included. | Gross event-date sales, not invoiced, paid, or accounting revenue. |
| Signed Cancellation Amount | `sum(case when transaction_class = 'CANCELLATION' then quantity * unit_price else 0 end)` | Same published staging boundary. | Preserves the source sign; not a matched-return amount. |
| Net Transaction Amount | `sum(quantity * unit_price)`; equivalently gross sales plus signed cancellation amount. | Same published staging boundary. | Must not be relabelled as accounting net revenue. |
| Transaction Row Count | `count(*)` of included staging rows. | Includes rows with missing Customer ID. | Counts source rows, not invoices or customers. |
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

Inspect `ops.schema_migration`, `ops.ingestion_batch`, and the exact runner
output for runtime status. This dictionary defines semantics; it is not itself
evidence that a database refresh has run.
