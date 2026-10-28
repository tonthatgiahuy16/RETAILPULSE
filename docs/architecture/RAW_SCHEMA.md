# Raw schema — Slice 1

`ops.source_file` is the immutable manifest for a file payload. `ops.ingestion_batch` records an attempt. `raw.online_retail_line` stores source values as text plus lineage columns so parsing and business interpretation happen only in staging.

The profile documents two source sheets and the eight exact UCI headers. The loader validates those headers before any raw writes, while retaining all data cells as text and preserving `(source_file_id, sheet_name, source_row_number)` lineage. On 2026-10-29, the migration was applied to the local development database; a full source load reconciled 1,067,371 source rows to 1,067,371 raw rows. A same-hash rerun was skipped without new rows, and a forced PostgreSQL insert failure rolled back its source/raw writes while retaining a `FAILED` audit batch.
