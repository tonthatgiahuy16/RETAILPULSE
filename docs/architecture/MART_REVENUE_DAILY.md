# Revenue daily mart - Slice 3

## Contract

`mart.revenue_daily` is a PostgreSQL view at grain `(source_file_id, event_date)`. It reads only `stg.online_retail_transaction`, so each output row belongs to one immutable source snapshot and one event date.

| Field | Definition |
|---|---|
| `gross_sales_amount` | Sum of `quantity * unit_price` for `SALE` rows. |
| `cancellation_signed_amount` | Signed sum of `quantity * unit_price` for `CANCELLATION` rows. |
| `net_transaction_amount` | `gross_sales_amount + cancellation_signed_amount`. |
| `transaction_row_count` | Count of included `SALE` and `CANCELLATION` source rows. |
| `missing_customer_id_row_count` | Count of included rows whose Customer ID is missing. |

`QUARANTINE` rows are excluded because the staging contract has no valid event date or amount for them. This is event-date transaction revenue, not accounting revenue: cancellations are not matched to original sales and no return-accounting claim is made.

## Gate

Apply [`003_mart_revenue_daily.sql`](../../migrations/003_mart_revenue_daily.sql) after `002`. The SQL gate in [`tests/sql/mart_revenue_daily.sql`](../../tests/sql/mart_revenue_daily.sql) recalculates every snapshot-day directly from staging and fails on a mismatch or an inconsistent net amount.
