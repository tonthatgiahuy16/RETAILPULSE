-- Slice 7 performance support: avoid reopening the full staging view for the
-- small cancellation population during candidate resolution.

set local max_parallel_workers_per_gather = 0;

create materialized view int.cancellation_line as
select
    source_file_id,
    sheet_name as cancellation_sheet_name,
    source_row_number as cancellation_source_row_number,
    customer_id,
    stock_code,
    invoice_no as cancellation_invoice_no,
    invoice_at as cancellation_invoice_at,
    quantity as cancellation_quantity,
    unit_price as cancellation_unit_price
from stg.online_retail_transaction
where transaction_class = 'CANCELLATION';

create unique index ux_int_cancellation_line_lineage
    on int.cancellation_line (source_file_id, cancellation_sheet_name, cancellation_source_row_number);

create index ix_int_cancellation_line_candidate_lookup
    on int.cancellation_line (source_file_id, customer_id, stock_code, cancellation_quantity, cancellation_invoice_at);

create or replace view int.cancellation_sale_candidate as
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

create or replace view int.cancellation_match_resolution as
with candidate_counts as (
    select
        source_file_id,
        cancellation_sheet_name,
        cancellation_source_row_number,
        count(*) as candidate_count
    from int.cancellation_sale_candidate
    group by source_file_id, cancellation_sheet_name, cancellation_source_row_number
)
select
    cancellation.source_file_id,
    cancellation.cancellation_sheet_name,
    cancellation.cancellation_source_row_number,
    cancellation.customer_id,
    cancellation.stock_code,
    cancellation.cancellation_invoice_no,
    cancellation.cancellation_invoice_at,
    cancellation.cancellation_quantity,
    coalesce(candidate_counts.candidate_count, 0) as candidate_count,
    case
        when coalesce(candidate_counts.candidate_count, 0) = 1 then 'MATCHED_CANDIDATE'
        when coalesce(candidate_counts.candidate_count, 0) > 1 then 'AMBIGUOUS'
        else 'UNMATCHED'
    end as candidate_status,
    case
        when cancellation.customer_id is null then 'MISSING_CUSTOMER_ID'
        when cancellation.stock_code is null then 'MISSING_STOCK_CODE'
        when cancellation.cancellation_quantity is null or cancellation.cancellation_quantity >= 0 then 'INVALID_CANCELLATION_QUANTITY'
        when coalesce(candidate_counts.candidate_count, 0) = 0 then 'NO_ELIGIBLE_SALE_CANDIDATE'
        when candidate_counts.candidate_count = 1 then 'EXACTLY_ONE_HEURISTIC_CANDIDATE'
        else 'MULTIPLE_HEURISTIC_CANDIDATES'
    end as candidate_reason,
    'SAME_SNAPSHOT_CUSTOMER_STOCK_EXACT_QUANTITY_PRIOR_SALE'::text as heuristic_name
from int.cancellation_line as cancellation
left join candidate_counts
  using (source_file_id, cancellation_sheet_name, cancellation_source_row_number);
