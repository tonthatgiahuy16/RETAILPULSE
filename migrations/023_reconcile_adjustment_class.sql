-- Slice 23: include the post-022 ADJUSTMENT class in staging reconciliation.
-- Migrations 001 through 022 remain immutable ledger history.

create or replace view ops.reconciliation_data_quality as
with raw_counts as (
    select source_file_id, count(*) as raw_row_count
    from raw.online_retail_line
    group by source_file_id
),
staging_counts as (
    select
        source_file_id,
        count(*) as staging_row_count,
        count(distinct (source_file_id, sheet_name, source_row_number)) as distinct_lineage_count,
        count(*) filter (where transaction_class = 'SALE') as sale_row_count,
        count(*) filter (where transaction_class = 'CANCELLATION') as cancellation_row_count,
        count(*) filter (where transaction_class = 'QUARANTINE') as quarantine_row_count,
        count(*) filter (where transaction_class = 'ADJUSTMENT') as adjustment_row_count,
        count(distinct invoice_at::date) filter (
            where transaction_class in ('SALE', 'CANCELLATION')
        ) as mart_day_count
    from stg.online_retail_transaction
    group by source_file_id
)
select
    source_file.source_file_id,
    source_file.sha256,
    source_file.expected_row_count,
    coalesce(raw_counts.raw_row_count, 0) as raw_row_count,
    coalesce(staging_counts.staging_row_count, 0) as staging_row_count,
    coalesce(staging_counts.distinct_lineage_count, 0) as distinct_lineage_count,
    coalesce(staging_counts.mart_day_count, 0) as mart_day_count,
    coalesce(staging_counts.sale_row_count, 0) as sale_row_count,
    coalesce(staging_counts.cancellation_row_count, 0) as cancellation_row_count,
    coalesce(staging_counts.quarantine_row_count, 0) as quarantine_row_count,
    coalesce(staging_counts.adjustment_row_count, 0) as adjustment_row_count
from ops.source_file as source_file
left join raw_counts using (source_file_id)
left join staging_counts using (source_file_id);
