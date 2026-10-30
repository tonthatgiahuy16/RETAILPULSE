# Customer cohort retention — Slice 12

`mart.customer_cohort_retention` is a cohort-retention view built only from
`mart.customer_purchase_event`. Its grain is
`(source_file_id, cohort_month, activity_month)`, with `source_sha256` carried
as immutable snapshot lineage.

Each non-null customer has exactly one `cohort_month` per source snapshot: the
calendar month of that customer's first eligible purchase event. An
`activity_month` is a calendar month in which the customer has an eligible
purchase event. The model produces no activity before the cohort month.

## Metrics

- `cohort_customer_count`: customers whose first eligible event is in the
  cohort month; this is the retention denominator.
- `active_customer_count`: all eligible customers active in the activity month
  for the source snapshot. It is contextual and repeats for every cohort row
  in that source/activity month; do not sum it across cohorts.
- `retained_customer_count`: customers from the row's cohort who are active in
  the row's activity month.
- `retention_rate`: `retained_customer_count / cohort_customer_count`.
- `months_since_cohort`: non-negative calendar-month distance between cohort
  and activity months.

Consequently the month-zero row for every cohort has 100% retention. The mart
uses the Slice 8 customer-event eligibility contract, so rows with missing
Customer ID are absent from cohort analytics but remain in revenue reporting.

Cancellation-match candidates remain diagnostic evidence only. This mart does
not convert candidates into accounting returns or subtract them from customer
purchase amounts.

`tests/sql/016_customer_cohort_retention.sql` is the publish gate. It verifies
the output grain, non-negative timing, month-zero 100% retention, cohort-size
reconciliation to customer purchase events, and activity-population
reconciliation.
