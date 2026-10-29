do $$
declare failures bigint;
begin
    select count(*) into failures
    from (
        select source_file_id, sheet_name, source_row_number
        from stg.online_retail_transaction
        except
        select source_file_id, sheet_name, source_row_number
        from int.customer_analytics_row_eligibility
    ) as missing_eligibility;
    if failures <> 0 then raise exception 'customer eligibility is missing % staging rows', failures; end if;

    with expected as (
        select
            sale.source_file_id,
            source_file.sha256 as source_sha256,
            sale.customer_id,
            sale.sale_invoice_no as invoice_no,
            min(sale.sale_invoice_at) as event_at,
            count(*) as eligible_sale_row_count,
            sum(sale.sale_quantity * sale.sale_unit_price) as gross_purchase_amount
        from int.eligible_sale_line as sale
        join ops.source_file as source_file using (source_file_id)
        group by sale.source_file_id, source_file.sha256, sale.customer_id, sale.sale_invoice_no
    )
    select count(*) into failures
    from expected
    full join mart.customer_purchase_event as actual
      using (source_file_id, source_sha256, customer_id, invoice_no)
    where expected.customer_id is null
       or actual.customer_id is null
       or expected.event_at is distinct from actual.event_at
       or expected.eligible_sale_row_count is distinct from actual.eligible_sale_row_count
       or expected.gross_purchase_amount is distinct from actual.gross_purchase_amount;
    if failures <> 0 then raise exception 'customer purchase event reconciliation failed for % invoice events', failures; end if;

    select count(*) into failures
    from mart.customer_purchase_event
    where customer_id is null or gross_purchase_amount <= 0 or eligible_sale_row_count <= 0;
    if failures <> 0 then raise exception 'customer purchase events contain % ineligible rows', failures; end if;
end;
$$;
