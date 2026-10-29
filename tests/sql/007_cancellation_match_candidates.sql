do $$
declare failures bigint;
begin
    select count(*) into failures
    from (
        select source_file_id, sheet_name, source_row_number
        from stg.online_retail_transaction
        where transaction_class = 'CANCELLATION'
        except
        select source_file_id, cancellation_sheet_name, cancellation_source_row_number
        from int.cancellation_match_resolution
    ) as missing_resolution;
    if failures <> 0 then raise exception 'cancellation resolution is missing % staging rows', failures; end if;

    select count(*) into failures
    from int.cancellation_match_resolution
    where candidate_status not in ('MATCHED_CANDIDATE', 'AMBIGUOUS', 'UNMATCHED')
       or (candidate_status = 'MATCHED_CANDIDATE' and candidate_count <> 1)
       or (candidate_status = 'AMBIGUOUS' and candidate_count <= 1)
       or (candidate_status = 'UNMATCHED' and candidate_count <> 0);
    if failures <> 0 then raise exception 'cancellation candidate status is inconsistent for % rows', failures; end if;

    select count(*) into failures
    from int.cancellation_sale_candidate as candidate
    join int.cancellation_match_resolution as resolution
      on resolution.source_file_id = candidate.source_file_id
     and resolution.cancellation_sheet_name = candidate.cancellation_sheet_name
     and resolution.cancellation_source_row_number = candidate.cancellation_source_row_number
    where resolution.candidate_status = 'UNMATCHED';
    if failures <> 0 then raise exception 'unmatched cancellations expose % candidate edges', failures; end if;
end;
$$;
