do $$
declare failures bigint;
begin
    select count(*) into failures
    from mart.customer_repurchase_label_dataset
    where observation_start_date >= prediction_start_date
       or prediction_start_date >= prediction_end_date
       or prediction_start_date - observation_start_date <> 180
       or prediction_end_date - prediction_start_date <> 90
       or last_observation_purchase_at::date >= prediction_start_date
       or observation_frequency <= 0
       or observation_monetary_amount <= 0;
    if failures <> 0 then raise exception 'repurchase labels have % invalid windows or observation features', failures; end if;

    with recomputed_label as (
        select
            label.source_file_id,
            label.customer_id,
            exists (
                select 1
                from int.customer_purchase_event_snapshot as future_event
                where future_event.source_file_id = label.source_file_id
                  and future_event.customer_id = label.customer_id
                  and future_event.event_at >= label.prediction_start_date
                  and future_event.event_at < label.prediction_end_date
            ) as expected_label
        from mart.customer_repurchase_label_dataset as label
    )
    select count(*) into failures
    from recomputed_label
    join mart.customer_repurchase_label_dataset as actual using (source_file_id, customer_id)
    where recomputed_label.expected_label is distinct from actual.repurchased_in_prediction_window;
    if failures <> 0 then raise exception 'repurchase labels leak or disagree for % customers', failures; end if;

    select count(*) into failures
    from mart.customer_repurchase_baseline_evaluation as baseline
    where labeled_customer_count <= 0
       or correct_prediction_count > labeled_customer_count
       or true_positive_count > actual_repurchase_customer_count
       or true_positive_count > predicted_repurchase_customer_count;
    if failures <> 0 then raise exception 'repurchase baseline metrics are invalid for % snapshots', failures; end if;
end;
$$;
