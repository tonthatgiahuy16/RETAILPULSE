-- Slice 9/10 performance support: temporal models consume the materialized
-- customer-event aggregate, not optional cancellation diagnostics.

create or replace view mart.customer_rfm_snapshot as
with snapshot_as_of as (
    select source_file_id, max(event_at)::date + 1 as as_of_date
    from int.customer_purchase_event_snapshot
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
from int.customer_purchase_event_snapshot as event
join snapshot_as_of using (source_file_id)
where event.event_at < snapshot_as_of.as_of_date
group by event.source_file_id, event.source_sha256, snapshot_as_of.as_of_date, event.customer_id;

create or replace view mart.customer_repurchase_label_dataset as
with source_bounds as (
    select
        source_file_id,
        max(event_at)::date + 1 as prediction_end_date,
        max(event_at)::date + 1 - 90 as prediction_start_date,
        max(event_at)::date + 1 - 90 - 180 as observation_start_date
    from int.customer_purchase_event_snapshot
    group by source_file_id
),
observation_events as (
    select event.*, bounds.observation_start_date, bounds.prediction_start_date, bounds.prediction_end_date
    from int.customer_purchase_event_snapshot as event
    join source_bounds as bounds using (source_file_id)
    where event.event_at >= bounds.observation_start_date
      and event.event_at < bounds.prediction_start_date
),
prediction_customers as (
    select distinct event.source_file_id, event.customer_id
    from int.customer_purchase_event_snapshot as event
    join source_bounds as bounds using (source_file_id)
    where event.event_at >= bounds.prediction_start_date
      and event.event_at < bounds.prediction_end_date
)
select
    observation.source_file_id,
    max(observation.source_sha256) as source_sha256,
    observation.observation_start_date,
    observation.prediction_start_date,
    observation.prediction_end_date,
    observation.customer_id,
    (observation.prediction_start_date - max(observation.event_at)::date) as observation_recency_days,
    count(*) as observation_frequency,
    sum(observation.gross_purchase_amount) as observation_monetary_amount,
    max(observation.event_at) as last_observation_purchase_at,
    (prediction.customer_id is not null) as repurchased_in_prediction_window
from observation_events as observation
left join prediction_customers as prediction using (source_file_id, customer_id)
group by observation.source_file_id, observation.observation_start_date, observation.prediction_start_date,
         observation.prediction_end_date, observation.customer_id, prediction.customer_id;
