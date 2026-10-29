-- Slice 8: customer purchase events. Cancellations are diagnostic evidence,
-- never an automatic reduction of customer purchase amounts.

create or replace view int.customer_analytics_row_eligibility as
select
    source_file_id,
    sheet_name,
    source_row_number,
    transaction_class,
    customer_id,
    invoice_no,
    invoice_at,
    quantity,
    unit_price,
    case
        when transaction_class <> 'SALE' then 'EXCLUDED_NOT_SALE'
        when customer_id is null then 'EXCLUDED_MISSING_CUSTOMER_ID'
        when quantity is null or quantity <= 0 then 'EXCLUDED_NONPOSITIVE_QUANTITY'
        when unit_price is null or unit_price <= 0 then 'EXCLUDED_NONPOSITIVE_UNIT_PRICE'
        else 'ELIGIBLE'
    end as customer_eligibility_status
from stg.online_retail_transaction;

create or replace view mart.customer_purchase_event as
with eligible_rows as (
    select
        transaction.source_file_id,
        transaction.source_sha256,
        transaction.customer_id,
        transaction.invoice_no,
        transaction.invoice_at,
        transaction.quantity,
        transaction.unit_price,
        transaction.sheet_name,
        transaction.source_row_number
    from stg.online_retail_transaction as transaction
    join int.customer_analytics_row_eligibility as eligibility
      using (source_file_id, sheet_name, source_row_number)
    where eligibility.customer_eligibility_status = 'ELIGIBLE'
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
