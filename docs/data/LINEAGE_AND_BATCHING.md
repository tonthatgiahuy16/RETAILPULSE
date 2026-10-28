# Lineage and batching contract — Slice 1

## Purpose

Make it possible to trace every raw row to one immutable source-file snapshot and rerun ingestion safely.

## Grain and identifiers

| Object | Grain | Identifier |
|---|---|---|
| `ops.source_file` | One distinct source-file payload | `source_file_id`; `sha256` is unique |
| `ops.ingestion_batch` | One ingestion attempt | application-generated `batch_id` (UUID) |
| `raw.online_retail_line` | One physical data row from a source worksheet | `(source_file_id, sheet_name, source_row_number)` |

`InvoiceNo` is a business attribute, not a raw-row key. Raw ingestion never removes rows merely because business fields look duplicated.

## Snapshot policy

Online Retail II is handled as a snapshot. A content-identical file is skipped. A different hash is a new source snapshot and needs an explicit new batch; it never overwrites old raw rows.

## Retry and failure contract

1. Create an `ingestion_batch` in `STARTED` state.
2. Calculate hash and validate the workbook before writing raw data.
3. If a successful `source_file` already has the hash, mark this attempt `SKIPPED_ALREADY_LOADED` and insert no raw rows.
4. Otherwise, insert the source manifest, all raw rows, and the `SUCCEEDED` batch state in one database transaction.
5. On an error, roll back that transaction and mark the attempt `FAILED` in a separate audit update. A retry creates a new `batch_id`.

This thin first slice deliberately uses one transaction rather than checkpoints. Chunking/resume is a later optimization only if profiling proves it necessary.

## Publish gate

Raw loading is successful only when the source row count recorded during workbook reading equals the committed raw row count for the source snapshot. No staging or mart may consume an incomplete snapshot.
