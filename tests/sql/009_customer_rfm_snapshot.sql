do $$
declare failures bigint;
begin
    select count(*) into failures
    from mart.customer_rfm_snapshot
    where recency_days < 1
       or frequency <= 0
       or monetary_amount <= 0
       or last_purchase_at::date >= as_of_date;
    if failures <> 0 then raise exception 'RFM snapshot has % invalid rows', failures; end if;

    with expected as (
        select source_file_id, customer_id, count(*) as event_count, sum(gross_purchase_amount) as amount
        from int.customer_purchase_event_snapshot
        group by source_file_id, customer_id
    )
    select count(*) into failures
    from expected
    full join mart.customer_rfm_snapshot as actual using (source_file_id, customer_id)
    where expected.customer_id is null
       or actual.customer_id is null
       or expected.event_count is distinct from actual.frequency
       or expected.amount is distinct from actual.monetary_amount;
    if failures <> 0 then raise exception 'RFM does not reconcile to purchase events for % customers', failures; end if;
end;
$$;
