-- Gate for migration 022.  It preserves raw lineage while preventing negative
-- non-C operational rows from entering sales or revenue measures.

do $$
declare
    failures bigint;
begin
    select count(*) into failures
    from stg.online_retail_transaction
    where transaction_class = 'SALE'
      and quantity < 0;
    if failures <> 0 then
        raise exception 'SALE contains % negative-quantity rows', failures;
    end if;

    select count(*) into failures
    from stg.online_retail_transaction
    where transaction_class = 'ADJUSTMENT'
      and (is_cancellation_invoice or quantity >= 0 or quantity is null);
    if failures <> 0 then
        raise exception 'ADJUSTMENT contains % rows outside the non-C negative-quantity contract', failures;
    end if;

    select count(*) into failures
    from stg.online_retail_transaction
    where transaction_class <> 'ADJUSTMENT'
      and invoice_no is not null
      and quantity is not null
      and invoice_at is not null
      and unit_price is not null
      and not is_cancellation_invoice
      and quantity < 0;
    if failures <> 0 then
        raise exception 'typed non-C negative-quantity rows missing from ADJUSTMENT: %', failures;
    end if;

    -- Observed baseline for the published UCI snapshot.  Any non-zero amount
    -- would make the gross/net revenue reclassification impact explicit.
    select count(*) into failures
    from (
        select
            count(*) as adjustment_row_count,
            sum(quantity) as adjustment_quantity,
            sum(quantity * unit_price) as adjustment_amount,
            count(*) filter (where unit_price <> 0) as nonzero_price_row_count
        from stg.online_retail_transaction
        where source_sha256 = 'bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980'
          and transaction_class = 'ADJUSTMENT'
    ) as actual
    where exists (
            select 1
            from stg.online_retail_transaction
            where source_sha256 = 'bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980'
        )
      and (actual.adjustment_row_count <> 3457
       or actual.adjustment_quantity <> -573085
       or actual.adjustment_amount <> 0
       or actual.nonzero_price_row_count <> 0);
    if failures <> 0 then
        raise exception 'snapshot adjustment baseline or zero-revenue impact changed';
    end if;

    select count(*) into failures
    from mart.revenue_daily
    where net_transaction_amount is distinct from gross_sales_amount + cancellation_signed_amount;
    if failures <> 0 then
        raise exception 'mart revenue has % rows with an inconsistent net transaction amount', failures;
    end if;
end;
$$;
