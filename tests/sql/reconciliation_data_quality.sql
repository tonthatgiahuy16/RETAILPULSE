do $$
declare failures bigint;
begin
 select count(*) into failures from ops.reconciliation_data_quality
 where raw_row_count <> expected_row_count or staging_row_count <> raw_row_count
    or distinct_lineage_count <> staging_row_count
    or sale_row_count + cancellation_row_count + quarantine_row_count <> staging_row_count
    or mart_day_count = 0;
 if failures <> 0 then raise exception 'reconciliation/data-quality failed for % source snapshots', failures; end if;
end;
$$;
