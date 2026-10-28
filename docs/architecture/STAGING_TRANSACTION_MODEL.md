# Staging transaction model — Slice 2

## Consumer, input, output

| Item | Contract |
|---|---|
| Consumer | Later revenue, return-matching, product, and customer models; none is implemented in this slice. |
| Input/source of truth | `raw.online_retail_line`, an immutable physical source row, with its `ops.source_file` and `ops.ingestion_batch` lineage. |
| Output | `stg.online_retail_transaction`, a PostgreSQL view at exactly one row per published raw source row. |
| Publish boundary | A source file is visible only when its successful ingestion batch's committed count and the current raw count both equal `ops.source_file.expected_row_count`. |
| Deferred | Cancellation-to-sale matching, a definition of an accounting return, customer-level eligibility, revenue aggregation, and a dbt project. |

The view is defined in [`migrations/002_staging_transaction_classification.sql`](../../migrations/002_staging_transaction_classification.sql). It depends on `001_raw_lineage.sql` and has not been applied to PostgreSQL in this repository.

## Grain and lineage

The grain remains one physical workbook row. `(source_file_id, sheet_name, source_row_number)` remains the row identifier. The model retains the raw values alongside normalised and typed values, plus source SHA-256, retrieval time, ingestion batch, and ingestion time. It never deduplicates, overwrites, or matches raw rows.

`invoice_at` is a `timestamp without time zone`, because the UCI workbook has no timezone. This layer exposes no revenue metric, so it does not equate event-date revenue with accounting revenue.

## Classification

Classification is exhaustive and mutually exclusive for every published raw row:

| `transaction_class` | Rule |
|---|---|
| `QUARANTINE` | `Invoice`, `Quantity`, `InvoiceDate`, or `Price` is blank or cannot be parsed into the required staging type. `quarantine_reason` records every failing required field. |
| `CANCELLATION` | Required values parse successfully and normalised `Invoice` begins with `C`, case-insensitively. |
| `SALE` | Required values parse successfully and the invoice does not begin with `C`. |

The following are flags, not reclassification rules: missing `Description`, negative `Quantity`, and non-positive `Price`. The completed profile records these as conditions requiring later business decisions; this slice does not discard them or claim that a negative quantity is a cancellation.

Missing `Customer ID` is also a flag (`is_missing_customer_id`), not a quarantine condition. Such rows retain typed quantity, timestamp, and price for later revenue consumers, while a future customer-level model may explicitly exclude them.

`C` is a cancellation indicator only. `cancellation_match_status` is `NOT_EVALUATED` for every `C` invoice and this model performs no return matching; therefore it makes no claim that a cancellation is a matched return.

## Gate and verification

Run `001_raw_lineage.sql`, then `002_staging_transaction_classification.sql`, against an isolated PostgreSQL database containing an ingested snapshot. The gate in [`tests/sql/staging_transaction_classification.sql`](../../tests/sql/staging_transaction_classification.sql) must finish without error. It checks source-row coverage, allowed classes, quarantine reasons, and the no-auto-match rule.

This repository currently has no configured PostgreSQL credentials or executed migration evidence. The model and the SQL gate are present, but database integration and the actual source-row counts by class are **Unknown** until that command is run.
