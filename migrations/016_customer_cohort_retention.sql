-- Slice 12: customer cohort retention from the published purchase-event contract.
-- Cancellation diagnostics remain informational and do not change this mart.

create or replace view mart.customer_cohort_retention as
with customer_cohort as (
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
        max(cohort.source_sha256) as source_sha256,
        cohort.cohort_month,
        date_trunc('month', event.event_at)::date as activity_month,
        count(distinct cohort.customer_id) as retained_customer_count
    from customer_cohort as cohort
    join mart.customer_purchase_event as event
      on event.source_file_id = cohort.source_file_id
     and event.customer_id = cohort.customer_id
    group by cohort.source_file_id, cohort.cohort_month, date_trunc('month', event.event_at)::date
)
select
    activity.source_file_id,
    activity.source_sha256,
    activity.cohort_month,
    activity.activity_month,
    (
        (extract(year from activity.activity_month)::integer - extract(year from activity.cohort_month)::integer) * 12
        + extract(month from activity.activity_month)::integer - extract(month from activity.cohort_month)::integer
    ) as months_since_cohort,
    cohort_size.cohort_customer_count,
    population.active_customer_count,
    activity.retained_customer_count,
    activity.retained_customer_count::numeric / cohort_size.cohort_customer_count as retention_rate
from cohort_activity as activity
join cohort_size
  on cohort_size.source_file_id = activity.source_file_id
 and cohort_size.cohort_month = activity.cohort_month
join activity_population as population
  on population.source_file_id = activity.source_file_id
 and population.activity_month = activity.activity_month;
