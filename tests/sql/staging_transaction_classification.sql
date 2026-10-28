-- Integration gate for migrations/001_raw_lineage.sql and
-- migrations/002_staging_transaction_classification.sql.
--
-- Run against an isolated PostgreSQL database after loading a snapshot. A
-- successful run has no output and no exception. This file makes no writes.

do $$
declare
    expected_source_row_count bigint;
    model_row_count bigint;
    invalid_class_count bigint;
    invalid_quarantine_count bigint;
    invalid_match_status_count bigint;
begin
    select count(*) into expected_source_row_count
    from raw.online_retail_line as raw_line
    join ops.ingestion_batch as batch
        on batch.batch_id = raw_line.first_ingestion_batch_id
       and batch.source_file_id = raw_line.source_file_id
    join ops.source_file as source_file
        on source_file.source_file_id = raw_line.source_file_id
    join (
        select source_file_id, count(*) as raw_row_count
        from raw.online_retail_line
        group by source_file_id
    ) as raw_row_count
        on raw_row_count.source_file_id = raw_line.source_file_id
    where batch.status = 'SUCCEEDED'
      and batch.committed_row_count = source_file.expected_row_count
      and raw_row_count.raw_row_count = source_file.expected_row_count;

    select count(*) into model_row_count
    from stg.online_retail_transaction;

    if expected_source_row_count <> model_row_count then
        raise exception
            'staging source-row coverage failed: expected %, got %',
            expected_source_row_count,
            model_row_count;
    end if;

    select count(*) into invalid_class_count
    from stg.online_retail_transaction
    where transaction_class not in ('SALE', 'CANCELLATION', 'QUARANTINE');

    if invalid_class_count <> 0 then
        raise exception 'staging contains % rows outside the three transaction classes', invalid_class_count;
    end if;

    select count(*) into invalid_quarantine_count
    from stg.online_retail_transaction
    where (transaction_class = 'QUARANTINE' and quarantine_reason is null)
       or (transaction_class <> 'QUARANTINE' and quarantine_reason is not null);

    if invalid_quarantine_count <> 0 then
        raise exception 'staging has % rows with an inconsistent quarantine reason', invalid_quarantine_count;
    end if;

    select count(*) into invalid_match_status_count
    from stg.online_retail_transaction
    where (is_cancellation_invoice and cancellation_match_status <> 'NOT_EVALUATED')
       or (not is_cancellation_invoice and cancellation_match_status <> 'NOT_APPLICABLE');

    if invalid_match_status_count <> 0 then
        raise exception
            'staging has % rows that treat cancellation matching inconsistently',
            invalid_match_status_count;
    end if;
end;
$$;
