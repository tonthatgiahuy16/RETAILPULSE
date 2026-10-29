# Customer purchase event — Slice 8

`mart.customer_purchase_event` has grain `(source_file_id, customer_id, invoice_no)`. `InvoiceNo` is used only as an event grouping attribute; raw lineage remains `(source_file_id, sheet_name, source_row_number)`.

Eligible event rows are `SALE` rows with non-null Customer ID, positive quantity, and positive unit price. `int.customer_analytics_row_eligibility` keeps one row for every staging row and records why every excluded row, including missing Customer ID, is excluded. Revenue continues to retain missing Customer ID rows; this mart does not.

`mart.customer_purchase_event_cancellation_diagnostic` exposes candidate counts at the same event grain. It never reduces `gross_purchase_amount` and never converts a candidate into an accounting return.

The published mart remains a view, backed by `int.customer_purchase_event_snapshot`, a refreshable materialized aggregate. The runner refreshes it after both candidate support projections, so RFM and label models consume a coherent immutable snapshot.

For source snapshot 1 on 2026-10-29, the mart contains 36,969 eligible customer purchase events across 5,878 customers. These counts exclude missing Customer ID and nonpositive sale rows by the stated eligibility contract.
