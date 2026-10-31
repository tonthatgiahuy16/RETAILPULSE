-- Integration gate for migration 020. BI views must remain thin, snapshot-aware
-- projections of their published contracts rather than competing calculations.

do $$
declare failures bigint;
begin
    select count(*) into failures
    from (
        select source_file_id, event_date, gross_sales_amount,
               cancellation_signed_amount, net_transaction_amount,
               transaction_row_count, missing_customer_id_row_count
        from bi.sales_daily
        except
        select source_file_id, event_date, gross_sales_amount,
               cancellation_signed_amount, net_transaction_amount,
               transaction_row_count, missing_customer_id_row_count
        from mart.revenue_daily
    ) as mismatched_revenue;
    if failures <> 0 then
        raise exception 'bi.sales_daily differs from mart.revenue_daily by % rows', failures;
    end if;

    select count(*) into failures
    from (
        select source_file_id, sheet_name, source_row_number
        from bi.sales_line
        group by source_file_id, sheet_name, source_row_number
        having count(*) <> 1
    ) as duplicate_sales_line;
    if failures <> 0 then
        raise exception 'bi.sales_line has % duplicate source rows', failures;
    end if;

    select abs(
        (select count(*) from bi.sales_line)
        - (select count(*) from dw.fct_sales_line)
    ) into failures;
    if failures <> 0 then
        raise exception 'bi.sales_line differs from sales fact by % rows', failures;
    end if;

    select abs(
        (select count(*) from bi.customer_lifecycle_snapshot)
        - (select count(*) from decision.customer_priority_snapshot)
    ) into failures;
    if failures <> 0 then
        raise exception 'bi.customer_lifecycle_snapshot differs from priority snapshot by % rows', failures;
    end if;

    select count(*) into failures
    from (
        select source_file_id, as_of_date, customer_id
        from bi.customer_lifecycle_snapshot
        group by source_file_id, as_of_date, customer_id
        having count(*) <> 1
    ) as duplicate_customer;
    if failures <> 0 then
        raise exception 'bi.customer_lifecycle_snapshot has % duplicate customer rows', failures;
    end if;

    select abs(
        (select count(*) from bi.customer_cohort_retention)
        - (select count(*) from mart.customer_cohort_retention)
    ) into failures;
    if failures <> 0 then
        raise exception 'bi.customer_cohort_retention differs from cohort mart by % rows', failures;
    end if;

    select count(*) into failures
    from bi.customer_cohort_retention
    where months_since_cohort = 0
      and retention_rate <> 1;
    if failures <> 0 then
        raise exception 'bi.customer_cohort_retention has % non-100%% cohort-month rows', failures;
    end if;

    select count(*) into failures
    from bi.cancellation_diagnostic
    where candidate_status not in ('MATCHED_CANDIDATE', 'AMBIGUOUS', 'UNMATCHED')
       or interpretation <> 'DIAGNOSTIC_CANDIDATE_NOT_CONFIRMED_RETURN';
    if failures <> 0 then
        raise exception 'bi.cancellation_diagnostic has % invalid diagnostic rows', failures;
    end if;
end $$;
