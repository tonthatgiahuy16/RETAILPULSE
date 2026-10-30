create schema if not exists dw;

create materialized view dw.dim_date as
select distinct
    to_char(invoice_at::date, 'YYYYMMDD')::integer as date_key,
    invoice_at::date as calendar_date,
    extract(year from invoice_at)::integer as calendar_year,
    extract(quarter from invoice_at)::integer as calendar_quarter,
    extract(month from invoice_at)::integer as calendar_month,
    extract(isodow from invoice_at)::integer as iso_day_of_week
from stg.online_retail_transaction
where invoice_at is not null;
create unique index ux_dw_dim_date on dw.dim_date (date_key);

create materialized view dw.dim_customer as
with customer_rows as materialized (
    select source_file_id, customer_id, country, invoice_at
    from stg.online_retail_transaction
    where customer_id is not null and invoice_at is not null
), customer_activity as (
    select source_file_id, customer_id, min(invoice_at) as first_seen_at
    from customer_rows
    group by source_file_id, customer_id
), country_rank as (
    select source_file_id, customer_id, country,
           row_number() over (partition by source_file_id, customer_id order by count(*) desc, max(invoice_at) desc, country) as rank
    from customer_rows
    where country is not null
    group by source_file_id, customer_id, country
)
select
    c.source_file_id,
    c.source_file_id::text || ':' || c.customer_id as customer_key,
    c.customer_id,
    c.first_seen_at,
    r.country as primary_country
from customer_activity c
left join country_rank r
  on r.source_file_id = c.source_file_id
 and r.customer_id = c.customer_id
 and r.rank = 1;
create unique index ux_dw_dim_customer on dw.dim_customer (customer_key);

create materialized view dw.dim_product as
with product_rows as (
    select
        source_file_id,
        stock_code,
        nullif(regexp_replace(upper(trim(description)), E'\\s+', ' ', 'g'), '')
            as normalized_description,
        invoice_at,
        source_row_number
    from stg.online_retail_transaction where stock_code is not null
), latest_description as (
    select *, row_number() over (partition by source_file_id, stock_code order by invoice_at desc nulls last, source_row_number desc) as rank
    from product_rows
)
select source_file_id, source_file_id::text || ':' || stock_code as product_key, stock_code,
       max(normalized_description) filter (where rank = 1) as latest_normalized_description,
       case when coalesce(upper(stock_code),'') in ('POST','PADS','M','DOT') or coalesce(max(normalized_description) filter (where rank = 1), '') ~ '(POSTAGE|CARRIAGE|BANK CHARGES|MANUAL|ADJUSTMENT)' then 'SERVICE_OR_FEE'
            when coalesce(upper(stock_code),'') ~ '^TEST' or coalesce(max(normalized_description) filter (where rank = 1), '') ~ E'\\m(SAMPLE|TEST)\\M' then 'SAMPLE_OR_TEST'
            when max(normalized_description) filter (where rank = 1) is null then 'MISSING_DESCRIPTION'
            else 'MERCHANDISE_OR_UNCLASSIFIED' end as special_item_class
from latest_description group by source_file_id, stock_code;
create unique index ux_dw_dim_product on dw.dim_product (product_key);

create materialized view dw.fct_sales_line as
select t.source_file_id, t.sheet_name, t.source_row_number, t.invoice_no,
       t.source_file_id::text || ':' || t.customer_id as customer_key,
       t.source_file_id::text || ':' || t.stock_code as product_key,
       to_char(t.invoice_at::date, 'YYYYMMDD')::integer as date_key,
       t.customer_id is not null as has_customer_key, t.stock_code is not null as has_product_key,
       t.quantity, t.unit_price, t.quantity * t.unit_price as sales_amount
from stg.online_retail_transaction t
where t.transaction_class = 'SALE';
create unique index ux_dw_fct_sales_line on dw.fct_sales_line (source_file_id, sheet_name, source_row_number);
