create or replace view ops.reconciliation_data_quality as
with raw_counts as (select source_file_id, count(*) raw_row_count from raw.online_retail_line group by 1),
staging_counts as (select source_file_id, count(*) staging_row_count, count(distinct (source_file_id, sheet_name, source_row_number)) distinct_lineage_count from stg.online_retail_transaction group by 1),
mart_counts as (select source_file_id, count(*) mart_day_count from mart.revenue_daily group by 1),
classes as (select source_file_id, count(*) filter (where transaction_class = 'SALE') sale_row_count, count(*) filter (where transaction_class = 'CANCELLATION') cancellation_row_count, count(*) filter (where transaction_class = 'QUARANTINE') quarantine_row_count from stg.online_retail_transaction group by 1)
select sf.source_file_id, sf.sha256, sf.expected_row_count, coalesce(r.raw_row_count, 0) raw_row_count,
       coalesce(s.staging_row_count, 0) staging_row_count, coalesce(s.distinct_lineage_count, 0) distinct_lineage_count,
       coalesce(m.mart_day_count, 0) mart_day_count, coalesce(c.sale_row_count, 0) sale_row_count,
       coalesce(c.cancellation_row_count, 0) cancellation_row_count, coalesce(c.quarantine_row_count, 0) quarantine_row_count
from ops.source_file sf left join raw_counts r using (source_file_id) left join staging_counts s using (source_file_id)
left join mart_counts m using (source_file_id) left join classes c using (source_file_id);
