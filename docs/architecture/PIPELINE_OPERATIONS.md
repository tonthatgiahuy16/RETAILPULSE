# Pipeline operations — Slice 5

## One runner and an immutable migration ledger

[`scripts/run_pipeline.py`](../../scripts/run_pipeline.py) is the operational entry point. It connects through the environment variable `DATABASE_URL`, applies every contiguous file in `migrations/`, optionally ingests one workbook, then runs every SQL gate in `tests/sql/` in lexical order.

`ops.schema_migration` records the numeric migration id, exact filename, SHA-256 checksum, and application time. A file that has already been recorded is not re-executed. A changed filename/checksum, a removed applied migration, a malformed filename, or an id gap stops the run before later migrations are applied. Each new migration and its ledger insert commit together; a failed migration is rolled back and has no ledger record. The runner does not fabricate a historical application time: when introduced to an older database with no ledger, it executes and records the repository's idempotent migrations from the start.

Only one runner may inspect or update the ledger at a time: it holds a database-wide PostgreSQL advisory lock from ledger bootstrap through the final migration. A second runner waits, then rereads the committed ledger and skips each recorded migration. This serializes the check-and-apply sequence instead of exposing a unique-key race.

Migration files are immutable once released. The `not yet executed` wording at the top of `001_raw_lineage.sql` is historical authoring text, not a current runtime claim; it is retained byte-for-byte so the ledger can detect drift. Runtime state is determined only by `ops.schema_migration`, never by migration-file comments.

Migration 006 replaces the reconciliation view without changing its columns or gate contract. It aggregates staging counts, transaction classes, and expected mart-day coverage in one reference to `stg.online_retail_transaction`; the separate mart SQL gate still reconciles the actual mart view. This avoids every direct or indirect additional staging expansion from migration 004. Measure `EXPLAIN (ANALYZE, BUFFERS)` on the target PostgreSQL database before and after applying it; row counts alone do not establish an improvement.

SQL gates run only after migrations and optional ingestion. They execute inside a transaction that is rolled back after success, so checks do not leave durable state. A failed gate also rolls back its check transaction and exits non-zero; it does not claim the snapshot published.

## File identity during ingestion

Before the workbook is parsed, the loader copies it once to a private temporary file while calculating SHA-256. It validates and streams only that copy, and stores that copy's filename metadata, byte size, and hash in `ops.source_file`. Therefore the hash identifies the exact bytes that supplied `raw.online_retail_line`, even if the original path is replaced after copying. A malformed or partial temporary copy fails validation before raw writes, leaving the existing `FAILED` batch audit behavior intact.

## Recovery guard for same-hash retries

Same-hash retry is permitted only when its `ops.source_file` has both the expected raw-row count and an associated `SUCCEEDED` batch whose committed count matches that expectation. A manually created manifest/raw pair without this audit proof fails and records the new attempt as `FAILED`; it is not silently treated as published.
