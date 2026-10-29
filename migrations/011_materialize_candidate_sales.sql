-- Slice 7 performance support: one refreshable projection of the sale rows
-- eligible for candidate matching. The source-of-truth remains staging/raw.

-- stg.try_invoice_timestamp handles malformed source timestamps with an
-- exception block, which PostgreSQL cannot invoke in a parallel worker.
set local max_parallel_workers_per_gather = 0;

create materialized view int.eligible_sale_line as
select
    source_file_id,
    sheet_name as sale_sheet_name,
    source_row_number as sale_source_row_number,
    customer_id,
    stock_code,
    invoice_no as sale_invoice_no,
    invoice_at as sale_invoice_at,
    quantity as sale_quantity,
    unit_price as sale_unit_price
from stg.online_retail_transaction
where transaction_class = 'SALE'
  and customer_id is not null
  and stock_code is not null
  and quantity > 0
  and unit_price > 0;

create unique index ux_int_eligible_sale_line_lineage
    on int.eligible_sale_line (source_file_id, sale_sheet_name, sale_source_row_number);

create index ix_int_eligible_sale_line_candidate_lookup
    on int.eligible_sale_line (source_file_id, customer_id, stock_code, sale_quantity, sale_invoice_at);

create or replace view int.cancellation_sale_candidate as
with cancellations as (
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
    where transaction_class = 'CANCELLATION'
)
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
from cancellations as cancellation
join int.eligible_sale_line as sale
  on sale.source_file_id = cancellation.source_file_id
 and sale.customer_id = cancellation.customer_id
 and sale.stock_code = cancellation.stock_code
 and sale.sale_invoice_at <= cancellation.cancellation_invoice_at
 and sale.sale_quantity = abs(cancellation.cancellation_quantity);
