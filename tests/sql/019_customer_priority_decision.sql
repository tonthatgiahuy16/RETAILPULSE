do $$ declare failures bigint; begin
 select count(*) into failures from (
   select source_file_id, customer_id from decision.customer_priority_backtest group by 1, 2 having count(*) <> 1
 ) duplicate_decisions;
 if failures <> 0 then raise exception 'backtest has % duplicate customer decisions', failures; end if;
 select count(*) into failures from (
   select source_file_id, as_of_date, customer_id from decision.customer_priority_snapshot group by 1, 2, 3 having count(*) <> 1
 ) duplicate_snapshots;
 if failures <> 0 then raise exception 'snapshot has % duplicate customer decisions', failures; end if;
 select abs(
   (select count(*) from decision.customer_priority_backtest)
   - (select count(*) from mart.customer_repurchase_label_dataset)
 ) into failures;
 if failures <> 0 then raise exception 'backtest differs from label dataset by % rows', failures; end if;
 select abs(
   (select count(*) from decision.customer_priority_snapshot)
   - (select count(*) from mart.customer_rfm_snapshot)
 ) into failures;
 if failures <> 0 then raise exception 'priority snapshot differs from RFM by % rows', failures; end if;
 select count(*) into failures from decision.customer_priority_backtest
 where priority_segment not in ('CHAMPIONS','AT_RISK_HIGH_VALUE','POTENTIAL','LOST') or contact_capacity <> 500 or cost_per_contact_units <> 2 or budget_campaign_units <> 1000;
 if failures <> 0 then raise exception 'priority decision has % invalid rows', failures; end if;
 select count(*) into failures from decision.customer_priority_backtest where label_interpretation <> 'BACKTEST_OUTCOME_ONLY_NOT_CAUSAL_RESPONSE';
 if failures <> 0 then raise exception 'priority labels lack noncausal disclaimer'; end if;
 select count(*) into failures from decision.customer_priority_snapshot where decision_interpretation <> 'CURRENT_DESCRIPTIVE_SEGMENT_NOT_PREDICTIVE_SCORE';
 if failures <> 0 then raise exception 'priority snapshots lack descriptive disclaimer'; end if;
 select count(*) into failures from decision.customer_priority_backtest
 where is_within_illustrative_budget <> (priority_rank <= contact_capacity);
 if failures <> 0 then raise exception 'backtest capacity flag does not match rank'; end if;
 select count(*) into failures from decision.customer_priority_snapshot
 where is_within_illustrative_budget <> (priority_rank <= contact_capacity);
 if failures <> 0 then raise exception 'snapshot capacity flag does not match rank'; end if;
end $$;
