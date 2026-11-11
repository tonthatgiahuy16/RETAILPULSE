-- Integration gate for migration 020. BI views must remain thin, snapshot-aware
-- projections of their published contracts rather than competing calculations.
-- Every comparison below is symmetric (both EXCEPT directions) so a dropped,
-- duplicated, or altered value fails the gate in either relation.

do $$
declare failures bigint;
begin
    select count(*) into failures
    from (
        (select source_file_id, source_sha256, event_date, gross_sales_amount,
                cancellation_signed_amount, net_transaction_amount,
                transaction_row_count, missing_customer_id_row_count
         from bi.sales_daily
         except
         select source_file_id, source_sha256, event_date, gross_sales_amount,
                cancellation_signed_amount, net_transaction_amount,
                transaction_row_count, missing_customer_id_row_count
         from mart.revenue_daily)
        union all
        (select source_file_id, source_sha256, event_date, gross_sales_amount,
                cancellation_signed_amount, net_transaction_amount,
                transaction_row_count, missing_customer_id_row_count
         from mart.revenue_daily
         except
         select source_file_id, source_sha256, event_date, gross_sales_amount,
                cancellation_signed_amount, net_transaction_amount,
                transaction_row_count, missing_customer_id_row_count
         from bi.sales_daily)
    ) as mismatched_revenue;
    if failures <> 0 then
        raise exception 'bi.sales_daily differs from mart.revenue_daily in % column-comparison rows', failures;
    end if;

    select count(*) into failures
    from bi.sales_daily
    where missing_customer_id_share is distinct from
              missing_customer_id_row_count::numeric / nullif(transaction_row_count, 0)
       or revenue_interpretation <> 'EVENT_DATE_TRANSACTION_AMOUNT_NOT_ACCOUNTING_REVENUE'
       or cancellation_interpretation <> 'CANCELLATION_CANDIDATES_ARE_NOT_CONFIRMED_RETURNS';
    if failures <> 0 then
        raise exception 'bi.sales_daily has % rows with an inconsistent derived column or interpretation label', failures;
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

    select count(*) into failures
    from (
        (select source_file_id, sheet_name,
                count(*) as line_count,
                sum(quantity) as quantity_sum,
                sum(sales_amount) as sales_amount_sum,
                count(*) filter (where not has_customer_key) as missing_customer_rows
         from bi.sales_line
         group by source_file_id, sheet_name
         except
         select source_file_id, sheet_name,
                count(*) as line_count,
                sum(quantity) as quantity_sum,
                sum(sales_amount) as sales_amount_sum,
                count(*) filter (where not has_customer_key) as missing_customer_rows
         from dw.fct_sales_line
         group by source_file_id, sheet_name)
        union all
        (select source_file_id, sheet_name,
                count(*) as line_count,
                sum(quantity) as quantity_sum,
                sum(sales_amount) as sales_amount_sum,
                count(*) filter (where not has_customer_key) as missing_customer_rows
         from dw.fct_sales_line
         group by source_file_id, sheet_name
         except
         select source_file_id, sheet_name,
                count(*) as line_count,
                sum(quantity) as quantity_sum,
                sum(sales_amount) as sales_amount_sum,
                count(*) filter (where not has_customer_key) as missing_customer_rows
         from bi.sales_line
         group by source_file_id, sheet_name)
    ) as mismatched_sales_line;
    if failures <> 0 then
        raise exception 'bi.sales_line differs from dw.fct_sales_line in % per-snapshot aggregate rows', failures;
    end if;

    select count(*) into failures
    from (
        (select source_file_id, source_sha256, as_of_date, customer_id,
                primary_country, recency_days, frequency, monetary_amount,
                last_purchase_at, priority_segment, priority_rank,
                is_within_illustrative_budget, scenario_id,
                budget_campaign_units, cost_per_contact_units,
                contact_capacity, decision_interpretation
         from bi.customer_lifecycle_snapshot
         except
         select source_file_id, source_sha256, as_of_date, customer_id,
                primary_country, recency_days, frequency, monetary_amount,
                last_purchase_at, priority_segment, priority_rank,
                is_within_illustrative_budget, scenario_id,
                budget_campaign_units, cost_per_contact_units,
                contact_capacity, decision_interpretation
         from decision.customer_priority_snapshot)
        union all
        (select source_file_id, source_sha256, as_of_date, customer_id,
                primary_country, recency_days, frequency, monetary_amount,
                last_purchase_at, priority_segment, priority_rank,
                is_within_illustrative_budget, scenario_id,
                budget_campaign_units, cost_per_contact_units,
                contact_capacity, decision_interpretation
         from decision.customer_priority_snapshot
         except
         select source_file_id, source_sha256, as_of_date, customer_id,
                primary_country, recency_days, frequency, monetary_amount,
                last_purchase_at, priority_segment, priority_rank,
                is_within_illustrative_budget, scenario_id,
                budget_campaign_units, cost_per_contact_units,
                contact_capacity, decision_interpretation
         from bi.customer_lifecycle_snapshot)
    ) as mismatched_lifecycle;
    if failures <> 0 then
        raise exception 'bi.customer_lifecycle_snapshot differs from priority snapshot in % column-comparison rows', failures;
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

    select count(*) into failures
    from bi.customer_lifecycle_snapshot
    where model_interpretation <> 'DESCRIPTIVE_RFM_SEGMENT_NOT_A_PROPENSITY_SCORE';
    if failures <> 0 then
        raise exception 'bi.customer_lifecycle_snapshot has % invalid model interpretation rows', failures;
    end if;

    select count(*) into failures
    from (
        (select source_file_id, source_sha256, cohort_month, activity_month,
                months_since_cohort, cohort_customer_count,
                active_customer_count, retained_customer_count, retention_rate
         from bi.customer_cohort_retention
         except
         select source_file_id, source_sha256, cohort_month, activity_month,
                months_since_cohort, cohort_customer_count,
                active_customer_count, retained_customer_count, retention_rate
         from mart.customer_cohort_retention)
        union all
        (select source_file_id, source_sha256, cohort_month, activity_month,
                months_since_cohort, cohort_customer_count,
                active_customer_count, retained_customer_count, retention_rate
         from mart.customer_cohort_retention
         except
         select source_file_id, source_sha256, cohort_month, activity_month,
                months_since_cohort, cohort_customer_count,
                active_customer_count, retained_customer_count, retention_rate
         from bi.customer_cohort_retention)
    ) as mismatched_cohort;
    if failures <> 0 then
        raise exception 'bi.customer_cohort_retention differs from cohort mart in % column-comparison rows', failures;
    end if;

    select count(*) into failures
    from bi.customer_cohort_retention
    where months_since_cohort = 0
      and retention_rate <> 1;
    if failures <> 0 then
        raise exception 'bi.customer_cohort_retention has % non-100%% cohort-month rows', failures;
    end if;

    select count(*) into failures
    from bi.customer_cohort_retention
    where customer_eligibility_interpretation <> 'ELIGIBLE_CUSTOMER_PURCHASE_EVENTS_ONLY';
    if failures <> 0 then
        raise exception 'bi.customer_cohort_retention has % invalid eligibility interpretation rows', failures;
    end if;

    select count(*) into failures
    from (
        (select source_file_id, candidate_status, candidate_reason,
                cancellation_row_count
         from bi.cancellation_diagnostic
         except
         select source_file_id, candidate_status, candidate_reason,
                count(*) as cancellation_row_count
         from int.cancellation_match_resolution
         group by source_file_id, candidate_status, candidate_reason)
        union all
        (select source_file_id, candidate_status, candidate_reason,
                count(*) as cancellation_row_count
         from int.cancellation_match_resolution
         group by source_file_id, candidate_status, candidate_reason
         except
         select source_file_id, candidate_status, candidate_reason,
                cancellation_row_count
         from bi.cancellation_diagnostic)
    ) as mismatched_cancellation;
    if failures <> 0 then
        raise exception 'bi.cancellation_diagnostic differs from candidate resolution in % status/reason-count rows', failures;
    end if;

    select count(*) into failures
    from bi.cancellation_diagnostic
    where candidate_status not in ('MATCHED_CANDIDATE', 'AMBIGUOUS', 'UNMATCHED')
       or heuristic_name <> 'SAME_SNAPSHOT_CUSTOMER_STOCK_EXACT_QUANTITY_PRIOR_SALE'
       or interpretation <> 'DIAGNOSTIC_CANDIDATE_NOT_CONFIRMED_RETURN';
    if failures <> 0 then
        raise exception 'bi.cancellation_diagnostic has % invalid diagnostic rows', failures;
    end if;

    select count(*) into failures
    from (
        (select source_file_id, source_sha256, source_retrieved_at, source_uri,
                original_filename, byte_size, expected_row_count
         from bi.source_snapshot
         except
         select source.source_file_id, source.sha256 as source_sha256,
                source.source_retrieved_at, source.source_uri,
                source.original_filename, source.byte_size,
                source.expected_row_count
         from ops.source_file as source
         where exists (
             select 1
             from ops.ingestion_batch as batch
             where batch.source_file_id = source.source_file_id
               and batch.status = 'SUCCEEDED'
         ))
        union all
        (select source.source_file_id, source.sha256 as source_sha256,
                source.source_retrieved_at, source.source_uri,
                source.original_filename, source.byte_size,
                source.expected_row_count
         from ops.source_file as source
         where exists (
             select 1
             from ops.ingestion_batch as batch
             where batch.source_file_id = source.source_file_id
               and batch.status = 'SUCCEEDED'
         )
         except
         select source_file_id, source_sha256, source_retrieved_at, source_uri,
                original_filename, byte_size, expected_row_count
         from bi.source_snapshot)
    ) as mismatched_snapshot;
    if failures <> 0 then
        raise exception 'bi.source_snapshot differs from successful source files in % column-comparison rows', failures;
    end if;

    select count(*) into failures
    from (
        (select source_file_id, observation_start_date, prediction_start_date,
                prediction_end_date, labeled_customer_count,
                actual_repurchase_customer_count, predicted_repurchase_customer_count,
                true_positive_count, correct_prediction_count, accuracy, precision, recall
         from bi.repurchase_baseline_evaluation
         except
         select source_file_id, observation_start_date, prediction_start_date,
                prediction_end_date, labeled_customer_count,
                actual_repurchase_customer_count, predicted_repurchase_customer_count,
                true_positive_count, correct_prediction_count, accuracy, precision, recall
         from mart.customer_repurchase_baseline_evaluation)
        union all
        (select source_file_id, observation_start_date, prediction_start_date,
                prediction_end_date, labeled_customer_count,
                actual_repurchase_customer_count, predicted_repurchase_customer_count,
                true_positive_count, correct_prediction_count, accuracy, precision, recall
         from mart.customer_repurchase_baseline_evaluation
         except
         select source_file_id, observation_start_date, prediction_start_date,
                prediction_end_date, labeled_customer_count,
                actual_repurchase_customer_count, predicted_repurchase_customer_count,
                true_positive_count, correct_prediction_count, accuracy, precision, recall
         from bi.repurchase_baseline_evaluation)
    ) as mismatched_baseline;
    if failures <> 0 then
        raise exception 'bi.repurchase_baseline_evaluation differs from baseline mart in % column-comparison rows', failures;
    end if;

    select count(*) into failures
    from bi.repurchase_baseline_evaluation
    where label_interpretation <> 'HISTORICAL_LABEL_NOT_CAMPAIGN_RESPONSE_OR_CAUSAL_UPLIFT';
    if failures <> 0 then
        raise exception 'bi.repurchase_baseline_evaluation has % invalid label interpretation rows', failures;
    end if;

    select count(*) into failures
    from (
        (select source_file_id, model_name, evaluated_at, decision_threshold,
                customer_count, positive_customer_count, positive_rate,
                precision_at_threshold, recall_at_threshold, pr_auc, roc_auc,
                lift_at_top_20_percent, brier_score, evaluation_note
         from bi.repurchase_model_evaluation
         except
         select source_file_id, model_name, evaluated_at, decision_threshold,
                customer_count, positive_customer_count, positive_rate,
                precision_at_threshold, recall_at_threshold, pr_auc, roc_auc,
                lift_at_top_20_percent, brier_score, evaluation_note
         from mart.repurchase_model_evaluation)
        union all
        (select source_file_id, model_name, evaluated_at, decision_threshold,
                customer_count, positive_customer_count, positive_rate,
                precision_at_threshold, recall_at_threshold, pr_auc, roc_auc,
                lift_at_top_20_percent, brier_score, evaluation_note
         from mart.repurchase_model_evaluation
         except
         select source_file_id, model_name, evaluated_at, decision_threshold,
                customer_count, positive_customer_count, positive_rate,
                precision_at_threshold, recall_at_threshold, pr_auc, roc_auc,
                lift_at_top_20_percent, brier_score, evaluation_note
         from bi.repurchase_model_evaluation)
    ) as mismatched_model_evaluation;
    if failures <> 0 then
        raise exception 'bi.repurchase_model_evaluation differs from model evaluation mart in % column-comparison rows', failures;
    end if;

    select count(*) into failures
    from bi.repurchase_model_evaluation
    where interpretation <> 'HISTORICAL_TEMPORAL_BACKTEST_NOT_CAMPAIGN_RESPONSE'
       or (decision_threshold is not null and (decision_threshold < 0 or decision_threshold > 1));
    if failures <> 0 then
        raise exception 'bi.repurchase_model_evaluation has % invalid evaluation rows', failures;
    end if;
end $$;
