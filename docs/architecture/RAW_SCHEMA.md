# Raw schema — Slice 1

`ops.source_file` is the immutable manifest for a file payload. `ops.ingestion_batch` records an attempt. `raw.online_retail_line` stores source values as text plus lineage columns so parsing and business interpretation happen only in staging.

The source workbook's actual sheets and column headers remain unknown until profiling. The migration therefore documents the eight UCI fields provisionally; it must be checked against the downloaded workbook before execution.
