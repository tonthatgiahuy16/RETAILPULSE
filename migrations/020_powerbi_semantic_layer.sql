-- Slice 15: a deliberately narrow, read-only semantic layer for Power BI.
-- Consumers must connect to these views, not to raw, staging, or intermediate
-- schemas. Every fact retains its immutable source snapshot identifier.

create schema if not exists bi;

create or replace view bi.source_snapshot as
select
    source.source_file_id,
    source.sha256 as source_sha256,
    source.source_retrieved_at,
    source.source_uri,
    source.original_filename,
    source.byte_size,
    source.expected_row_count
from ops.source_file as source
where exists (
    select 1
    from ops.ingestion_batch as batch
    where batch.source_file_id = source.source_file_id
      and batch.status = 'SUCCEEDED'
);

create or replace view bi.sales_daily as
select
    revenue.source_file_id,
    revenue.source_sha256,
    revenue.event_date,
    revenue.gross_sales_amount,
    revenue.cancellation_signed_amount,
    revenue.net_transaction_amount,
    revenue.transaction_row_count,
    revenue.missing_customer_id_row_count,
    revenue.missing_customer_id_row_count::numeric
        / nullif(revenue.transaction_row_count, 0) as missing_customer_id_share,
    'EVENT_DATE_TRANSACTION_AMOUNT_NOT_ACCOUNTING_REVENUE'::text
        as revenue_interpretation,
    'CANCELLATION_CANDIDATES_ARE_NOT_CONFIRMED_RETURNS'::text
        as cancellation_interpretation
from mart.revenue_daily as revenue;

create or replace view bi.sales_line as
select
    fact.source_file_id,
    fact.sheet_name,
    fact.source_row_number,
    fact.invoice_no,
    fact.date_key,
    date.calendar_date,
    date.calendar_year,
    date.calendar_quarter,
    date.calendar_month,
    date.iso_day_of_week,
    fact.customer_key,
    customer.customer_id,
    customer.primary_country,
    fact.product_key,
    product.stock_code,
    product.latest_normalized_description,
    product.special_item_class,
    fact.has_customer_key,
    fact.has_product_key,
    fact.quantity,
    fact.unit_price,
    fact.sales_amount,
    'SALE_SOURCE_ROW_EVENT_DATE_AMOUNT_NOT_ACCOUNTING_REVENUE'::text
        as sales_interpretation
from dw.fct_sales_line as fact
join dw.dim_date as date
  on date.date_key = fact.date_key
left join dw.dim_customer as customer
  on customer.customer_key = fact.customer_key
left join dw.dim_product as product
  on product.product_key = fact.product_key;

create or replace view bi.customer_lifecycle_snapshot as
select
    priority.source_file_id,
    priority.source_sha256,
    priority.as_of_date,
    priority.customer_id,
    priority.primary_country,
    priority.recency_days,
    priority.frequency,
    priority.monetary_amount,
    priority.last_purchase_at,
    priority.priority_segment,
    priority.priority_rank,
    priority.is_within_illustrative_budget,
    priority.scenario_id,
    priority.budget_campaign_units,
    priority.cost_per_contact_units,
    priority.contact_capacity,
    priority.decision_interpretation,
    'DESCRIPTIVE_RFM_SEGMENT_NOT_A_PROPENSITY_SCORE'::text as model_interpretation
from decision.customer_priority_snapshot as priority;

create or replace view bi.customer_cohort_retention as
select
    cohort.source_file_id,
    cohort.source_sha256,
    cohort.cohort_month,
    cohort.activity_month,
    cohort.months_since_cohort,
    cohort.cohort_customer_count,
    cohort.active_customer_count,
    cohort.retained_customer_count,
    cohort.retention_rate,
    'ELIGIBLE_CUSTOMER_PURCHASE_EVENTS_ONLY'::text as customer_eligibility_interpretation
from mart.customer_cohort_retention as cohort;

create or replace view bi.cancellation_diagnostic as
select
    resolution.source_file_id,
    resolution.candidate_status,
    count(*) as cancellation_row_count,
    'SAME_SNAPSHOT_CUSTOMER_STOCK_EXACT_QUANTITY_PRIOR_SALE'::text as heuristic_name,
    'DIAGNOSTIC_CANDIDATE_NOT_CONFIRMED_RETURN'::text as interpretation
from int.cancellation_match_resolution as resolution
group by resolution.source_file_id, resolution.candidate_status;

create or replace view bi.repurchase_baseline_evaluation as
select
    evaluation.source_file_id,
    evaluation.observation_start_date,
    evaluation.prediction_start_date,
    evaluation.prediction_end_date,
    evaluation.labeled_customer_count,
    evaluation.actual_repurchase_customer_count,
    evaluation.predicted_repurchase_customer_count,
    evaluation.true_positive_count,
    evaluation.correct_prediction_count,
    evaluation.accuracy,
    evaluation.precision,
    evaluation.recall,
    'HISTORICAL_LABEL_NOT_CAMPAIGN_RESPONSE_OR_CAUSAL_UPLIFT'::text as label_interpretation
from mart.customer_repurchase_baseline_evaluation as evaluation;
