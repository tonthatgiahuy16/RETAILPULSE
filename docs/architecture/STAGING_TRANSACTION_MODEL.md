# Staging transaction model — Slice 2

## Consumer, input, output

| Item | Contract |
|---|---|
| Consumer | Later revenue, return-matching, product, and customer models; none is implemented in this slice. |
| Input/source of truth | `raw.online_retail_line`, an immutable physical source row, with its `ops.source_file` and `ops.ingestion_batch` lineage. |
| Output | `stg.online_retail_transaction`, a PostgreSQL view at exactly one row per published raw source row. |
| Publish boundary | A source file is visible only when its successful ingestion batch's committed count and the current raw count both equal `ops.source_file.expected_row_count`. |
| Deferred | A confirmed cancellation-to-sale return match, a definition of accounting revenue/returns, and any customer-level model beyond the published eligibility contract. Event-date revenue, dbt contract adapters, and candidate-only cancellation evidence are implemented separately. |

The view is defined in [`migrations/002_staging_transaction_classification.sql`](../../migrations/002_staging_transaction_classification.sql). It depends on `001_raw_lineage.sql`. Migrations `001` and `002` have runtime evidence on the local development database.

## Grain and lineage

The grain remains one physical workbook row. `(source_file_id, sheet_name, source_row_number)` remains the row identifier. The model retains the raw values alongside normalised and typed values, plus source SHA-256, retrieval time, ingestion batch, and ingestion time. It never deduplicates, overwrites, or matches raw rows.

`invoice_at` is a `timestamp without time zone`, because the UCI workbook has no timezone. This layer exposes no revenue metric, so it does not equate event-date revenue with accounting revenue.

## Classification

Classification is exhaustive and mutually exclusive for every published raw row:

| `transaction_class` | Rule |
|---|---|
| `QUARANTINE` | `Invoice`, `Quantity`, `InvoiceDate`, or `Price` is blank or cannot be parsed into the required staging type. `quarantine_reason` records every failing required field. |
| `CANCELLATION` | Required values parse successfully and normalised `Invoice` begins with `C`, case-insensitively. |
| `ADJUSTMENT` | Required values parse successfully, the invoice does not begin with `C`, and `Quantity < 0`. This is an operational adjustment, not a confirmed return. |
| `SALE` | Required values parse successfully, the invoice does not begin with `C`, and `Quantity >= 0`. |

Missing `Description` and non-positive `Price` remain flags, not reclassification rules. The non-`C` negative-quantity decision and snapshot-scoped evidence are recorded in [Revenue adjustment contract](../data/REVENUE_ADJUSTMENT_CONTRACT.md). No row is discarded and this classification does not claim a return match.

Missing `Customer ID` is also a flag (`is_missing_customer_id`), not a quarantine condition. Such rows retain typed quantity, timestamp, and price for later revenue consumers, while a future customer-level model may explicitly exclude them.

`C` is a cancellation indicator only. `cancellation_match_status` is `NOT_EVALUATED` for every `C` invoice and this model performs no return matching; therefore it makes no claim that a cancellation is a matched return.

## Gate and verification

Apply `002_staging_transaction_classification.sql` to the local development database containing the already-ingested snapshot. The gate in [`tests/sql/staging_transaction_classification.sql`](../../tests/sql/staging_transaction_classification.sql) must finish without error. It checks source-row coverage, allowed classes, quarantine reasons, and the no-auto-match rule.

No PostgreSQL credential is committed to this repository. On 2026-10-29, `002` was applied locally and the SQL gate completed without error: 1,067,371 source-row-grain staging rows with 1,047,877 `SALE`, 19,494 `CANCELLATION`, and no `QUARANTINE`. All 19,494 cancellation rows had `cancellation_match_status = NOT_EVALUATED`; no return matching was performed.
