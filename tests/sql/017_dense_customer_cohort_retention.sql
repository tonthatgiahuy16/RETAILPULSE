do $$
declare failures bigint;
begin
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
            source_file_id,
            customer_id,
            date_trunc('month', min(event_at))::date as cohort_month
        from mart.customer_purchase_event
        where customer_id is not null
        group by source_file_id, customer_id
    ),
    cohort_size as (
        select source_file_id, cohort_month, count(*) as cohort_customer_count
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
    expected_grid as (
        select
            cohort.source_file_id,
            cohort.cohort_month,
            months.activity_month::date as activity_month,
            cohort.cohort_customer_count,
            coalesce(population.active_customer_count, 0) as active_customer_count,
            coalesce(activity.retained_customer_count, 0) as retained_customer_count
        from cohort_size as cohort
        join source_bounds using (source_file_id)
        cross join lateral generate_series(
            cohort.cohort_month,
            source_bounds.snapshot_end_month,
            interval '1 month'
        ) as months(activity_month)
        left join activity_population as population
          on population.source_file_id = cohort.source_file_id
         and population.activity_month = months.activity_month::date
        left join cohort_activity as activity
          on activity.source_file_id = cohort.source_file_id
         and activity.cohort_month = cohort.cohort_month
         and activity.activity_month = months.activity_month::date
    )
    select count(*) into failures
    from expected_grid as expected
    full join mart.customer_cohort_retention as actual
      on actual.source_file_id = expected.source_file_id
     and actual.cohort_month = expected.cohort_month
     and actual.activity_month = expected.activity_month
    where expected.source_file_id is null
       or actual.source_file_id is null
       or expected.cohort_customer_count is distinct from actual.cohort_customer_count
       or expected.active_customer_count is distinct from actual.active_customer_count
       or expected.retained_customer_count is distinct from actual.retained_customer_count
       or (expected.retained_customer_count::numeric / expected.cohort_customer_count)
          is distinct from actual.retention_rate;
    if failures <> 0 then
        raise exception 'dense cohort calendar disagrees with events for % rows', failures;
    end if;

    select count(*) into failures
    from mart.customer_cohort_retention
    where retained_customer_count = 0
      and retention_rate <> 0;
    if failures <> 0 then
        raise exception 'zero-retention cohort rows have % nonzero rates', failures;
    end if;
end;
$$;
