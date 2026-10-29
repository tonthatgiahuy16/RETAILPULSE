-- Slice 10: fixed, data-derived windows for a leakage-safe repurchase label.
-- Observation is 180 days and prediction is the final 90 days of each source.

create or replace view mart.customer_repurchase_label_dataset as
with source_bounds as (
    select
        source_file_id,
        max(event_at)::date + 1 as prediction_end_date,
        max(event_at)::date + 1 - 90 as prediction_start_date,
        max(event_at)::date + 1 - 90 - 180 as observation_start_date
    from mart.customer_purchase_event
    group by source_file_id
),
observation_events as (
    select event.*, bounds.observation_start_date, bounds.prediction_start_date, bounds.prediction_end_date
    from mart.customer_purchase_event as event
    join source_bounds as bounds using (source_file_id)
    where event.event_at >= bounds.observation_start_date
      and event.event_at < bounds.prediction_start_date
),
prediction_customers as (
    select distinct
        event.source_file_id,
        event.customer_id
    from mart.customer_purchase_event as event
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
left join prediction_customers as prediction
  using (source_file_id, customer_id)
group by
    observation.source_file_id,
    observation.observation_start_date,
    observation.prediction_start_date,
    observation.prediction_end_date,
    observation.customer_id,
    prediction.customer_id;

create or replace view mart.customer_repurchase_baseline_evaluation as
with predictions as (
    select
        source_file_id,
        observation_start_date,
        prediction_start_date,
        prediction_end_date,
        repurchased_in_prediction_window,
        (observation_frequency >= 2) as baseline_predicts_repurchase
    from mart.customer_repurchase_label_dataset
)
select
    source_file_id,
    observation_start_date,
    prediction_start_date,
    prediction_end_date,
    count(*) as labeled_customer_count,
    count(*) filter (where repurchased_in_prediction_window) as actual_repurchase_customer_count,
    count(*) filter (where baseline_predicts_repurchase) as predicted_repurchase_customer_count,
    count(*) filter (where baseline_predicts_repurchase and repurchased_in_prediction_window)
        as true_positive_count,
    count(*) filter (where baseline_predicts_repurchase = repurchased_in_prediction_window)
        as correct_prediction_count,
    case when count(*) = 0 then null
         else count(*) filter (where baseline_predicts_repurchase = repurchased_in_prediction_window)::numeric / count(*) end
        as accuracy,
    case when count(*) filter (where baseline_predicts_repurchase) = 0 then null
         else count(*) filter (where baseline_predicts_repurchase and repurchased_in_prediction_window)::numeric
              / count(*) filter (where baseline_predicts_repurchase) end as precision,
    case when count(*) filter (where repurchased_in_prediction_window) = 0 then null
         else count(*) filter (where baseline_predicts_repurchase and repurchased_in_prediction_window)::numeric
              / count(*) filter (where repurchased_in_prediction_window) end as recall
from predictions
group by source_file_id, observation_start_date, prediction_start_date, prediction_end_date;
