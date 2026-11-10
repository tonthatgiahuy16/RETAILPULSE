-- Slice 21: repair the cancellation candidate snapshot, expose the diagnostic
-- reason, and persist the repurchase model evaluation.
--
-- Migration 014 created int.cancellation_sale_candidate_snapshot from the view
-- int.cancellation_sale_candidate and then pointed that view at the snapshot.
-- The snapshot therefore selected from itself, so every refresh re-read its own
-- (initially empty) contents and no cancellation could ever find a candidate.
-- Rebuild the edge set from the two materialized inputs and keep the view name.

create materialized view int.cancellation_sale_candidate_snapshot_v2 as
select
    cancellation.source_file_id,
    cancellation.cancellation_sheet_name,
    cancellation.cancellation_source_row_number,
    sale.sale_sheet_name,
    sale.sale_source_row_number,
    cancellation.customer_id,
    cancellation.stock_code,
    cancellation.cancellation_invoice_no,
    cancellation.cancellation_invoice_at,
    cancellation.cancellation_quantity,
    cancellation.cancellation_unit_price,
    sale.sale_invoice_no,
    sale.sale_invoice_at,
    sale.sale_quantity,
    sale.sale_unit_price,
    'SAME_SNAPSHOT_CUSTOMER_STOCK_EXACT_QUANTITY_PRIOR_SALE'::text as heuristic_name
from int.cancellation_line as cancellation
join int.eligible_sale_line as sale
  on sale.source_file_id = cancellation.source_file_id
 and sale.customer_id = cancellation.customer_id
 and sale.stock_code = cancellation.stock_code
 and sale.sale_invoice_at <= cancellation.cancellation_invoice_at
 and sale.sale_quantity = abs(cancellation.cancellation_quantity);

create unique index ux_int_cancellation_sale_candidate_snapshot_v2_edge
    on int.cancellation_sale_candidate_snapshot_v2 (
        source_file_id,
        cancellation_sheet_name,
        cancellation_source_row_number,
        sale_sheet_name,
        sale_source_row_number
    );

create or replace view int.cancellation_sale_candidate as
select
    source_file_id,
    cancellation_sheet_name,
    cancellation_source_row_number,
    sale_sheet_name,
    sale_source_row_number,
    customer_id,
    stock_code,
    cancellation_invoice_no,
    cancellation_invoice_at,
    cancellation_quantity,
    cancellation_unit_price,
    sale_invoice_no,
    sale_invoice_at,
    sale_quantity,
    sale_unit_price,
    heuristic_name
from int.cancellation_sale_candidate_snapshot_v2;

drop materialized view int.cancellation_sale_candidate_snapshot;

alter materialized view int.cancellation_sale_candidate_snapshot_v2
    rename to cancellation_sale_candidate_snapshot;

alter index int.ux_int_cancellation_sale_candidate_snapshot_v2_edge
    rename to ux_int_cancellation_sale_candidate_snapshot_edge;

create or replace view bi.cancellation_diagnostic as
select
    resolution.source_file_id,
    resolution.candidate_status,
    count(*) as cancellation_row_count,
    'SAME_SNAPSHOT_CUSTOMER_STOCK_EXACT_QUANTITY_PRIOR_SALE'::text as heuristic_name,
    'DIAGNOSTIC_CANDIDATE_NOT_CONFIRMED_RETURN'::text as interpretation,
    resolution.candidate_reason
from int.cancellation_match_resolution as resolution
group by
    resolution.source_file_id,
    resolution.candidate_status,
    resolution.candidate_reason;

create table if not exists mart.repurchase_model_evaluation (
    source_file_id integer not null references ops.source_file (source_file_id),
    model_name text not null,
    evaluated_at timestamptz not null,
    decision_threshold numeric(6, 4),
    customer_count integer not null,
    positive_customer_count integer not null,
    positive_rate numeric(9, 6) not null,
    precision_at_threshold numeric(9, 6) not null,
    recall_at_threshold numeric(9, 6) not null,
    pr_auc numeric(9, 6) not null,
    roc_auc numeric(9, 6) not null,
    lift_at_top_20_percent numeric(12, 6) not null,
    brier_score numeric(9, 6),
    evaluation_note text not null,
    primary key (source_file_id, model_name)
);

create or replace view bi.repurchase_model_evaluation as
select
    evaluation.source_file_id,
    evaluation.model_name,
    evaluation.evaluated_at,
    evaluation.decision_threshold,
    evaluation.customer_count,
    evaluation.positive_customer_count,
    evaluation.positive_rate,
    evaluation.precision_at_threshold,
    evaluation.recall_at_threshold,
    evaluation.pr_auc,
    evaluation.roc_auc,
    evaluation.lift_at_top_20_percent,
    evaluation.brier_score,
    evaluation.evaluation_note,
    'HISTORICAL_TEMPORAL_BACKTEST_NOT_CAMPAIGN_RESPONSE'::text as interpretation
from mart.repurchase_model_evaluation as evaluation;
