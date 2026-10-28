-- Slice 2: one typed, source-row-grain staging view for transaction classification.
--
-- Apply after 001_raw_lineage.sql. This migration deliberately creates a view:
-- raw remains the immutable, lossless source of truth and this layer is rebuilt
-- from it. No cancellation-to-sale return matching happens in this slice.

create schema if not exists stg;

create or replace function stg.normalise_text(value text)
returns text
language sql
immutable
parallel safe
as $$
    select nullif(btrim(value), '');
$$;

create or replace function stg.try_numeric(value text)
returns numeric
language sql
immutable
parallel safe
as $$
    select case
        when stg.normalise_text(value) ~
            '^[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?$'
            then stg.normalise_text(value)::numeric
    end;
$$;

create or replace function stg.try_invoice_timestamp(value text)
returns timestamp without time zone
language plpgsql
immutable
parallel safe
as $$
declare
    normalised_value text := stg.normalise_text(value);
begin
    if normalised_value is null then
        return null;
    end if;

    return normalised_value::timestamp without time zone;
exception
    when invalid_datetime_format or datetime_field_overflow then
        return null;
end;
$$;

create or replace view stg.online_retail_transaction as
with published_source_files as (
    -- Do not expose a snapshot whose raw-row reconciliation is incomplete.
    select
        source_file.source_file_id,
        source_file.sha256 as source_sha256,
        source_file.source_retrieved_at,
        batch.batch_id as successful_ingestion_batch_id
    from ops.source_file as source_file
    join ops.ingestion_batch as batch
        on batch.source_file_id = source_file.source_file_id
    join (
        select source_file_id, count(*) as raw_row_count
        from raw.online_retail_line
        group by source_file_id
    ) as raw_row_count
        on raw_row_count.source_file_id = source_file.source_file_id
    where batch.status = 'SUCCEEDED'
      and batch.committed_row_count = source_file.expected_row_count
      and raw_row_count.raw_row_count = source_file.expected_row_count
),
normalised as (
    select
        raw_line.source_file_id,
        published_source_files.source_sha256,
        published_source_files.source_retrieved_at,
        raw_line.sheet_name,
        raw_line.source_row_number,
        raw_line.first_ingestion_batch_id,
        raw_line.ingested_at,
        raw_line.invoice_no_raw,
        stg.normalise_text(raw_line.invoice_no_raw) as invoice_no,
        raw_line.stock_code_raw,
        stg.normalise_text(raw_line.stock_code_raw) as stock_code,
        raw_line.description_raw,
        stg.normalise_text(raw_line.description_raw) as description,
        raw_line.quantity_raw,
        stg.try_numeric(raw_line.quantity_raw) as quantity,
        raw_line.invoice_date_raw,
        stg.try_invoice_timestamp(raw_line.invoice_date_raw) as invoice_at,
        raw_line.unit_price_raw,
        stg.try_numeric(raw_line.unit_price_raw) as unit_price,
        raw_line.customer_id_raw,
        stg.normalise_text(raw_line.customer_id_raw) as customer_id,
        raw_line.country_raw,
        stg.normalise_text(raw_line.country_raw) as country
    from raw.online_retail_line as raw_line
    join published_source_files
        on published_source_files.source_file_id = raw_line.source_file_id
       and published_source_files.successful_ingestion_batch_id
           = raw_line.first_ingestion_batch_id
),
classified as (
    select
        normalised.*,
        (customer_id is null) as is_missing_customer_id,
        (description is null) as is_missing_description,
        (quantity < 0) as is_negative_quantity,
        (unit_price <= 0) as is_nonpositive_unit_price,
        (upper(invoice_no) like 'C%') as is_cancellation_invoice,
        case
            when invoice_no is null
              or quantity is null
              or invoice_at is null
              or unit_price is null
                then 'QUARANTINE'
            when upper(invoice_no) like 'C%'
                then 'CANCELLATION'
            else 'SALE'
        end as transaction_class
    from normalised
)
select
    source_file_id,
    source_sha256,
    source_retrieved_at,
    sheet_name,
    source_row_number,
    first_ingestion_batch_id,
    ingested_at,
    invoice_no_raw,
    invoice_no,
    stock_code_raw,
    stock_code,
    description_raw,
    description,
    quantity_raw,
    quantity,
    invoice_date_raw,
    invoice_at,
    unit_price_raw,
    unit_price,
    customer_id_raw,
    customer_id,
    country_raw,
    country,
    is_missing_customer_id,
    is_missing_description,
    is_negative_quantity,
    is_nonpositive_unit_price,
    is_cancellation_invoice,
    transaction_class,
    case
        when transaction_class = 'QUARANTINE' then concat_ws(
            '; ',
            case when invoice_no is null then 'MISSING_OR_INVALID_INVOICE' end,
            case when quantity is null then 'MISSING_OR_INVALID_QUANTITY' end,
            case when invoice_at is null then 'MISSING_OR_INVALID_INVOICE_DATE' end,
            case when unit_price is null then 'MISSING_OR_INVALID_UNIT_PRICE' end
        )
    end as quarantine_reason,
    case
        when is_cancellation_invoice then 'NOT_EVALUATED'
        else 'NOT_APPLICABLE'
    end as cancellation_match_status
from classified;
