-- Slice 8 performance support: preserve the mart view contract while caching
-- its immutable-snapshot event aggregate for RFM and labeling consumers.

create materialized view int.cancellation_sale_candidate_snapshot as
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
from int.cancellation_sale_candidate;

create unique index ux_int_cancellation_sale_candidate_snapshot_edge
    on int.cancellation_sale_candidate_snapshot (
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
from int.cancellation_sale_candidate_snapshot;

create materialized view int.customer_purchase_event_snapshot as
select
    sale.source_file_id,
    source_file.sha256 as source_sha256,
    sale.customer_id,
    sale.sale_invoice_no as invoice_no,
    min(sale.sale_invoice_at) as event_at,
    count(*) as eligible_sale_row_count,
    sum(sale.sale_quantity * sale.sale_unit_price) as gross_purchase_amount
from int.eligible_sale_line as sale
join ops.source_file as source_file using (source_file_id)
group by sale.source_file_id, source_file.sha256, sale.customer_id, sale.sale_invoice_no;

create unique index ux_int_customer_purchase_event_snapshot_grain
    on int.customer_purchase_event_snapshot (source_file_id, customer_id, invoice_no);

create or replace view mart.customer_purchase_event_cancellation_diagnostic as
select
    event_snapshot.source_file_id,
    event_snapshot.customer_id,
    event_snapshot.invoice_no,
    count(*) filter (where resolution.candidate_status = 'MATCHED_CANDIDATE')
        as matched_candidate_cancellation_row_count,
    count(*) filter (where resolution.candidate_status = 'AMBIGUOUS')
        as ambiguous_candidate_cancellation_row_count
from int.customer_purchase_event_snapshot as event_snapshot
join int.cancellation_sale_candidate as candidate
  on candidate.source_file_id = event_snapshot.source_file_id
 and candidate.customer_id = event_snapshot.customer_id
 and candidate.sale_invoice_no = event_snapshot.invoice_no
join int.cancellation_match_resolution as resolution
  on resolution.source_file_id = candidate.source_file_id
 and resolution.cancellation_sheet_name = candidate.cancellation_sheet_name
 and resolution.cancellation_source_row_number = candidate.cancellation_source_row_number
group by event_snapshot.source_file_id, event_snapshot.customer_id, event_snapshot.invoice_no;

create or replace view mart.customer_purchase_event as
select
    event_snapshot.source_file_id,
    event_snapshot.source_sha256,
    event_snapshot.customer_id,
    event_snapshot.invoice_no,
    event_snapshot.event_at,
    event_snapshot.eligible_sale_row_count,
    event_snapshot.gross_purchase_amount,
    coalesce(diagnostic.matched_candidate_cancellation_row_count, 0)::numeric
        as matched_candidate_cancellation_row_count,
    coalesce(diagnostic.ambiguous_candidate_cancellation_row_count, 0)::numeric
        as ambiguous_candidate_cancellation_row_count
from int.customer_purchase_event_snapshot as event_snapshot
left join mart.customer_purchase_event_cancellation_diagnostic as diagnostic
  using (source_file_id, customer_id, invoice_no);
