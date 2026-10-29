-- Slice 3: event-date transaction revenue by immutable source snapshot.
-- This is not accounting revenue and does not match cancellations to sales.

create schema if not exists mart;

create or replace view mart.revenue_daily as
select
    source_file_id,
    source_sha256,
    invoice_at::date as event_date,
    sum(case when transaction_class = 'SALE' then quantity * unit_price else 0 end) as gross_sales_amount,
    sum(case when transaction_class = 'CANCELLATION' then quantity * unit_price else 0 end) as cancellation_signed_amount,
    sum(quantity * unit_price) as net_transaction_amount,
    count(*) as transaction_row_count,
    count(*) filter (where is_missing_customer_id) as missing_customer_id_row_count
from stg.online_retail_transaction
where transaction_class in ('SALE', 'CANCELLATION')
group by source_file_id, source_sha256, invoice_at::date;
