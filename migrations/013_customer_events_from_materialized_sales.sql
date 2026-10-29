-- Slice 8 performance support: aggregate customer events from the refreshed
-- eligible-sale projection rather than reopening staging for each consumer.

create or replace view mart.customer_purchase_event as
with eligible_rows as (
    select
        sale.source_file_id,
        source_file.sha256 as source_sha256,
        sale.customer_id,
        sale.sale_invoice_no as invoice_no,
        sale.sale_invoice_at as invoice_at,
        sale.sale_quantity as quantity,
        sale.sale_unit_price as unit_price,
        sale.sale_sheet_name as sheet_name,
        sale.sale_source_row_number as source_row_number
    from int.eligible_sale_line as sale
    join ops.source_file as source_file using (source_file_id)
),
candidate_diagnostics as (
    select
        candidate.source_file_id,
        candidate.sale_sheet_name,
        candidate.sale_source_row_number,
        count(*) filter (where resolution.candidate_status = 'MATCHED_CANDIDATE')
            as matched_candidate_cancellation_row_count,
        count(*) filter (where resolution.candidate_status = 'AMBIGUOUS')
            as ambiguous_candidate_cancellation_row_count
    from int.cancellation_sale_candidate as candidate
    join int.cancellation_match_resolution as resolution
      on resolution.source_file_id = candidate.source_file_id
     and resolution.cancellation_sheet_name = candidate.cancellation_sheet_name
     and resolution.cancellation_source_row_number = candidate.cancellation_source_row_number
    group by candidate.source_file_id, candidate.sale_sheet_name, candidate.sale_source_row_number
)
select
    eligible.source_file_id,
    eligible.source_sha256,
    eligible.customer_id,
    eligible.invoice_no,
    min(eligible.invoice_at) as event_at,
    count(*) as eligible_sale_row_count,
    sum(eligible.quantity * eligible.unit_price) as gross_purchase_amount,
    coalesce(sum(diagnostics.matched_candidate_cancellation_row_count), 0)
        as matched_candidate_cancellation_row_count,
    coalesce(sum(diagnostics.ambiguous_candidate_cancellation_row_count), 0)
        as ambiguous_candidate_cancellation_row_count
from eligible_rows as eligible
left join candidate_diagnostics as diagnostics
  on diagnostics.source_file_id = eligible.source_file_id
 and diagnostics.sale_sheet_name = eligible.sheet_name
 and diagnostics.sale_source_row_number = eligible.source_row_number
group by eligible.source_file_id, eligible.source_sha256, eligible.customer_id, eligible.invoice_no;
