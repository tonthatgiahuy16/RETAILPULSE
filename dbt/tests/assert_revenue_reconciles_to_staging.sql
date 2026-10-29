with expected as (
    select
        source_file_id,
        invoice_at::date as event_date,
        sum(case when transaction_class = 'SALE' then quantity * unit_price else 0 end) as gross_sales_amount,
        sum(case when transaction_class = 'CANCELLATION' then quantity * unit_price else 0 end) as cancellation_signed_amount,
        sum(quantity * unit_price) as net_transaction_amount,
        count(*) as transaction_row_count,
        count(*) filter (where is_missing_customer_id) as missing_customer_id_row_count
    from {{ ref('stg_online_retail_transaction') }}
    where transaction_class in ('SALE', 'CANCELLATION')
    group by 1, 2
)
select *
from expected
full outer join {{ ref('mart_revenue_daily') }} as actual using (source_file_id, event_date)
where expected.gross_sales_amount is distinct from actual.gross_sales_amount
   or expected.cancellation_signed_amount is distinct from actual.cancellation_signed_amount
   or expected.net_transaction_amount is distinct from actual.net_transaction_amount
   or expected.transaction_row_count is distinct from actual.transaction_row_count
   or expected.missing_customer_id_row_count is distinct from actual.missing_customer_id_row_count
