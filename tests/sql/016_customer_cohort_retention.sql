do $$
declare failures bigint;
begin
    select count(*) into failures
    from mart.customer_cohort_retention
    where activity_month < cohort_month
       or months_since_cohort < 0
       or cohort_customer_count <= 0
       or active_customer_count <= 0
       or retained_customer_count <= 0
       or retained_customer_count > cohort_customer_count
       or retained_customer_count > active_customer_count
       or retention_rate <= 0
       or retention_rate > 1;
    if failures <> 0 then
        raise exception 'cohort retention has % invalid metric rows', failures;
    end if;

    select count(*) into failures
    from mart.customer_cohort_retention
    where months_since_cohort = 0
      and (
          retained_customer_count <> cohort_customer_count
          or retention_rate <> 1
      );
    if failures <> 0 then
        raise exception 'cohort month retention is not 100%% for % rows', failures;
    end if;

    select count(*) into failures
    from (
        select source_file_id, cohort_month, activity_month
        from mart.customer_cohort_retention
        group by source_file_id, cohort_month, activity_month
        having count(*) <> 1
    ) as duplicate_grain;
    if failures <> 0 then
        raise exception 'cohort retention has % duplicate grain rows', failures;
    end if;

    with expected_customer_cohort as (
        select
            source_file_id,
            customer_id,
            date_trunc('month', min(event_at))::date as cohort_month
        from mart.customer_purchase_event
        where customer_id is not null
        group by source_file_id, customer_id
    ),
    expected_cohort_size as (
        select source_file_id, cohort_month, count(*) as cohort_customer_count
        from expected_customer_cohort
        group by source_file_id, cohort_month
    ),
    actual_cohort_size as (
        select source_file_id, cohort_month, max(cohort_customer_count) as cohort_customer_count
        from mart.customer_cohort_retention
        where months_since_cohort = 0
        group by source_file_id, cohort_month
    )
    select count(*) into failures
    from expected_cohort_size as expected
    full join actual_cohort_size as actual using (source_file_id, cohort_month)
    where expected.cohort_customer_count is distinct from actual.cohort_customer_count;
    if failures <> 0 then
        raise exception 'cohort sizes do not reconcile to customer purchase events for % cohorts', failures;
    end if;

    with expected_activity_population as (
        select
            source_file_id,
            date_trunc('month', event_at)::date as activity_month,
            count(distinct customer_id) as active_customer_count
        from mart.customer_purchase_event
        where customer_id is not null
        group by source_file_id, date_trunc('month', event_at)::date
    ),
    actual_activity_population as (
        select
            source_file_id,
            activity_month,
            min(active_customer_count) as active_customer_count_min,
            max(active_customer_count) as active_customer_count_max
        from mart.customer_cohort_retention
        group by source_file_id, activity_month
    )
    select count(*) into failures
    from expected_activity_population as expected
    full join actual_activity_population as actual using (source_file_id, activity_month)
    where expected.active_customer_count is distinct from actual.active_customer_count_min
       or actual.active_customer_count_min is distinct from actual.active_customer_count_max;
    if failures <> 0 then
        raise exception 'activity population does not reconcile for % source months', failures;
    end if;
end;
$$;
