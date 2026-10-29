-- Slice 9: one reproducible RFM snapshot per source snapshot and customer.

create or replace view mart.customer_rfm_snapshot as
with snapshot_as_of as (
    select source_file_id, max(event_at)::date + 1 as as_of_date
    from mart.customer_purchase_event
    group by source_file_id
)
select
    event.source_file_id,
    event.source_sha256,
    snapshot_as_of.as_of_date,
    event.customer_id,
    (snapshot_as_of.as_of_date - max(event.event_at)::date) as recency_days,
    count(*) as frequency,
    sum(event.gross_purchase_amount) as monetary_amount,
    max(event.event_at) as last_purchase_at
from mart.customer_purchase_event as event
join snapshot_as_of using (source_file_id)
where event.event_at < snapshot_as_of.as_of_date
group by event.source_file_id, event.source_sha256, snapshot_as_of.as_of_date, event.customer_id;
