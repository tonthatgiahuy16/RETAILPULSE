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

    select abs(
        (select count(*) from bi.source_snapshot)
        - (select count(*) from ops.source_file as source
           where exists (
               select 1
               from ops.ingestion_batch as batch
               where batch.source_file_id = source.source_file_id
                 and batch.status = 'SUCCEEDED'
           ))
    ) into failures;
    if failures <> 0 then
        raise exception 'bi.source_snapshot row count differs from successful source files by % rows', failures;
    end if;

    select count(*) into failures
    from (
        select source_file_id, source_sha256
        from bi.source_snapshot
        except
        select source_file_id, sha256 as source_sha256
        from ops.source_file as source
        where exists (
            select 1
            from ops.ingestion_batch as batch
            where batch.source_file_id = source.source_file_id
              and batch.status = 'SUCCEEDED'
        )
    ) as mismatched_snapshot;
    if failures <> 0 then
        raise exception 'bi.source_snapshot differs from successful source files by % rows', failures;
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
