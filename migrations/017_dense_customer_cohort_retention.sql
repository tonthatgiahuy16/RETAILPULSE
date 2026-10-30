-- Slice 12 follow-up: preserve zero-retention months for cohort heatmaps.
-- Migration 016 remains immutable; this replaces only its published view.

create or replace view mart.customer_cohort_retention as
with source_bounds as (
    select
        source_file_id,
        date_trunc('month', max(event_at))::date as snapshot_end_month
    from mart.customer_purchase_event
    where customer_id is not null
    group by source_file_id
),
customer_cohort as (
    select
        event.source_file_id,
        max(event.source_sha256) as source_sha256,
        event.customer_id,
        date_trunc('month', min(event.event_at))::date as cohort_month
    from mart.customer_purchase_event as event
    where event.customer_id is not null
    group by event.source_file_id, event.customer_id
),
cohort_size as (
    select
        source_file_id,
        cohort_month,
        max(source_sha256) as source_sha256,
        count(*) as cohort_customer_count
    from customer_cohort
    group by source_file_id, cohort_month
),
activity_population as (
    select
        source_file_id,
        date_trunc('month', event_at)::date as activity_month,
        count(distinct customer_id) as active_customer_count
    from mart.customer_purchase_event
    where customer_id is not null
    group by source_file_id, date_trunc('month', event_at)::date
),
cohort_activity as (
    select
        cohort.source_file_id,
        cohort.cohort_month,
        date_trunc('month', event.event_at)::date as activity_month,
        count(distinct cohort.customer_id) as retained_customer_count
    from customer_cohort as cohort
    join mart.customer_purchase_event as event
      on event.source_file_id = cohort.source_file_id
     and event.customer_id = cohort.customer_id
    group by cohort.source_file_id, cohort.cohort_month, date_trunc('month', event.event_at)::date
),
cohort_calendar as (
    select
        cohort.source_file_id,
        cohort.source_sha256,
        cohort.cohort_month,
        cohort.cohort_customer_count,
        months.activity_month::date as activity_month
    from cohort_size as cohort
    join source_bounds using (source_file_id)
    cross join lateral generate_series(
        cohort.cohort_month,
        source_bounds.snapshot_end_month,
        interval '1 month'
    ) as months(activity_month)
)
select
    calendar.source_file_id,
    calendar.source_sha256,
    calendar.cohort_month,
    calendar.activity_month,
    (
        (extract(year from calendar.activity_month)::integer - extract(year from calendar.cohort_month)::integer) * 12
        + extract(month from calendar.activity_month)::integer - extract(month from calendar.cohort_month)::integer
    ) as months_since_cohort,
    calendar.cohort_customer_count,
    coalesce(population.active_customer_count, 0) as active_customer_count,
    coalesce(activity.retained_customer_count, 0) as retained_customer_count,
    coalesce(activity.retained_customer_count, 0)::numeric / calendar.cohort_customer_count as retention_rate
from cohort_calendar as calendar
left join activity_population as population
  on population.source_file_id = calendar.source_file_id
 and population.activity_month = calendar.activity_month
left join cohort_activity as activity
  on activity.source_file_id = calendar.source_file_id
 and activity.cohort_month = calendar.cohort_month
 and activity.activity_month = calendar.activity_month;
