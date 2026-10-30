# Dimensional warehouse — Slice 13

This is a small star-schema serving layer. It does not replace immutable
`raw`, typed staging, or existing marts; it supplies conformed dimensions and
a line-grain fact for downstream analysis. All keys and measures remain scoped
to `source_file_id`, so consumers must not silently add different source
snapshots together.

## Relations and grain

| Relation | Type | Grain | Source and rule |
|---|---|---|---|
| `dw.dim_date` | Materialized view | One calendar date | All non-null `invoice_at` dates in published staging. `date_key` is `YYYYMMDD`. |
| `dw.dim_customer` | Materialized view | Source snapshot × customer | All non-null staging Customer IDs. `first_seen_at` is the earliest staging timestamp; `primary_country` is the most frequent non-null country, with latest timestamp then alphabetic country as deterministic ties. |
| `dw.dim_product` | Materialized view | Source snapshot × StockCode | All non-null staging StockCodes. The latest non-null description is uppercased, trimmed, and whitespace-normalized. |
| `dw.fct_sales_line` | Materialized view | One `SALE` staging source row | Preserves `(source_file_id, sheet_name, source_row_number)` and raw sales amount `quantity * unit_price`. |

`customer_key` and `product_key` are snapshot-scoped text keys formed from
`source_file_id` and the natural identifier. They are `NULL` on the fact when
the corresponding identifier is missing. The fact preserves those sale rows;
it does not discard revenue because Customer ID is absent.

## Product classification

`special_item_class` is a deterministic convenience classification, not a
curated product taxonomy:

- `SERVICE_OR_FEE`: known service codes or latest descriptions indicating
  postage, carriage, bank charges, manual handling, or adjustment.
- `SAMPLE_OR_TEST`: test codes or descriptions containing `sample`/`test` as
  whole words.
- `MISSING_DESCRIPTION`: no normalized description is available.
- `MERCHANDISE_OR_UNCLASSIFIED`: every other StockCode.

It must not be interpreted as a financial-accounting category. Refreshing the
dimension after a newer source snapshot can change which description is
"latest" only within that snapshot.

## Refresh and checks

The normal runner refreshes the four `dw` materialized views after ingestion
and after the existing staging/intermediate refreshes. SQL gate `018` proves
that fact row count equals published staging `SALE` row count, lineage is
unique, dates resolve, and non-null dimension keys resolve. It intentionally
does not impose a Customer ID requirement on the sales fact.

Cancellation rows are excluded from `dw.fct_sales_line`; they remain available
through staging and the candidate-only cancellation diagnostics. Therefore
this fact is not accounting revenue and must not be used to imply a confirmed
return match.

## Evidence boundary

The PostgreSQL integration suite publishes a small synthetic snapshot, refreshes
these relations, and runs gates `018` and `019`. It is not evidence of a
completed full-workbook refresh or of a runtime SLA. Before applying these
migrations to a shared database, run the normal pipeline against the intended
snapshot and record refresh duration, row reconciliation, and gate output.
