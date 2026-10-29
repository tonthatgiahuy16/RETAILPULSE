-- Integration gate for migrations/001 through 003. Successful execution emits
-- no output and raises no exception. It compares every mart row to staging.

do $$
declare
    mismatch_count bigint;
begin
    with expected as (
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
        group by source_file_id, source_sha256, invoice_at::date
    )
    select count(*) into mismatch_count
    from expected
    full join mart.revenue_daily as actual
        using (source_file_id, source_sha256, event_date)
    where expected.source_file_id is null
       or actual.source_file_id is null
       or expected.gross_sales_amount is distinct from actual.gross_sales_amount
       or expected.cancellation_signed_amount is distinct from actual.cancellation_signed_amount
       or expected.net_transaction_amount is distinct from actual.net_transaction_amount
       or expected.transaction_row_count is distinct from actual.transaction_row_count
       or expected.missing_customer_id_row_count is distinct from actual.missing_customer_id_row_count;

    if mismatch_count <> 0 then
        raise exception 'mart revenue reconciliation failed for % snapshot-day rows', mismatch_count;
    end if;

    select count(*) into mismatch_count
    from mart.revenue_daily
    where net_transaction_amount is distinct from gross_sales_amount + cancellation_signed_amount;

    if mismatch_count <> 0 then
        raise exception 'mart has % rows with an inconsistent net transaction amount', mismatch_count;
    end if;
end;
$$;
