create schema if not exists decision;
create or replace view decision.illustrative_campaign_scenario as
select 'illustrative_fixed_cap_v1'::text as scenario_id, 1000::numeric as budget_campaign_units,
       2::numeric as cost_per_contact_units, 500::integer as contact_capacity;

create or replace view decision.customer_priority_backtest as
with thresholds as (
 select source_file_id,
        percentile_cont(.25) within group (order by observation_recency_days) as recency_p25,
        percentile_cont(.75) within group (order by observation_recency_days) as recency_p75,
        percentile_cont(.75) within group (order by observation_frequency) as frequency_p75,
        percentile_cont(.75) within group (order by observation_monetary_amount) as monetary_p75
 from mart.customer_repurchase_label_dataset group by source_file_id
), scored as (
 select
   l.*,
   d.primary_country,
   t.recency_p25,
   t.recency_p75,
   t.frequency_p75,
   t.monetary_p75,
   case
   when l.observation_recency_days <= t.recency_p25 and l.observation_frequency >= t.frequency_p75 and l.observation_monetary_amount >= t.monetary_p75 then 'CHAMPIONS'
   when l.observation_recency_days >= t.recency_p75 and l.observation_monetary_amount >= t.monetary_p75 then 'AT_RISK_HIGH_VALUE'
   when l.observation_recency_days >= t.recency_p75 then 'LOST'
   else 'POTENTIAL' end as priority_segment
 from mart.customer_repurchase_label_dataset l join thresholds t using (source_file_id)
 left join dw.dim_customer d on d.source_file_id=l.source_file_id and d.customer_id=l.customer_id
), ranked as (
 select *, row_number() over (partition by source_file_id order by case priority_segment when 'CHAMPIONS' then 1 when 'AT_RISK_HIGH_VALUE' then 2 when 'POTENTIAL' then 3 else 4 end, observation_monetary_amount desc, observation_frequency desc, observation_recency_days, customer_id) as priority_rank
 from scored
)
select r.*, s.scenario_id, s.budget_campaign_units, s.cost_per_contact_units, s.contact_capacity,
       r.priority_rank <= s.contact_capacity as is_within_illustrative_budget,
       'BACKTEST_OUTCOME_ONLY_NOT_CAUSAL_RESPONSE'::text as label_interpretation
from ranked r cross join decision.illustrative_campaign_scenario s;

create or replace view decision.customer_priority_snapshot as
with thresholds as (
    select
        source_file_id,
        as_of_date,
        percentile_cont(.25) within group (order by recency_days) as recency_p25,
        percentile_cont(.75) within group (order by recency_days) as recency_p75,
        percentile_cont(.75) within group (order by frequency) as frequency_p75,
        percentile_cont(.75) within group (order by monetary_amount) as monetary_p75
    from mart.customer_rfm_snapshot
    group by source_file_id, as_of_date
), scored as (
    select
        r.*,
        d.primary_country,
        t.recency_p25,
        t.recency_p75,
        t.frequency_p75,
        t.monetary_p75,
        case
            when r.recency_days <= t.recency_p25
             and r.frequency >= t.frequency_p75
             and r.monetary_amount >= t.monetary_p75 then 'CHAMPIONS'
            when r.recency_days >= t.recency_p75
             and r.monetary_amount >= t.monetary_p75 then 'AT_RISK_HIGH_VALUE'
            when r.recency_days >= t.recency_p75 then 'LOST'
            else 'POTENTIAL'
        end as priority_segment
    from mart.customer_rfm_snapshot r
    join thresholds t using (source_file_id, as_of_date)
    left join dw.dim_customer d
      on d.source_file_id = r.source_file_id
     and d.customer_id = r.customer_id
), ranked as (
    select
        *,
        row_number() over (
            partition by source_file_id, as_of_date
            order by
                case priority_segment
                    when 'CHAMPIONS' then 1
                    when 'AT_RISK_HIGH_VALUE' then 2
                    when 'POTENTIAL' then 3
                    else 4
                end,
                monetary_amount desc,
                frequency desc,
                recency_days,
                customer_id
        ) as priority_rank
    from scored
)
select
    r.*,
    s.scenario_id,
    s.budget_campaign_units,
    s.cost_per_contact_units,
    s.contact_capacity,
    r.priority_rank <= s.contact_capacity as is_within_illustrative_budget,
    'CURRENT_DESCRIPTIVE_SEGMENT_NOT_PREDICTIVE_SCORE'::text as decision_interpretation
from ranked r
cross join decision.illustrative_campaign_scenario s;
