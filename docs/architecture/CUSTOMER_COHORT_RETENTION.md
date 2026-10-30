# Customer cohort retention — Slice 12

`mart.customer_cohort_retention` is a cohort-retention view built only from
`mart.customer_purchase_event`. Its grain is
`(source_file_id, cohort_month, activity_month)`, with `source_sha256` carried
as immutable snapshot lineage.

Each non-null customer has exactly one `cohort_month` per source snapshot: the
calendar month of that customer's first eligible purchase event. Every cohort
has one output row for every calendar `activity_month` from its cohort month
through that source snapshot's final event month. The model produces no
activity before the cohort month and preserves months with no retained
customers as explicit zeroes.

## Metrics

- `cohort_customer_count`: customers whose first eligible event is in the
  cohort month; this is the retention denominator.
- `active_customer_count`: all eligible customers active in the activity month
  for the source snapshot. It is contextual and repeats for every cohort row
  in that source/activity month; do not sum it across cohorts.
- `retained_customer_count`: customers from the row's cohort who are active in
  the row's activity month; it is zero when no cohort customer is active.
- `retention_rate`: `retained_customer_count / cohort_customer_count`.
- `months_since_cohort`: non-negative calendar-month distance between cohort
  and activity months.

Consequently the month-zero row for every cohort has 100% retention, while a
later month with no retained customer has a retention rate of 0%. The mart
uses the Slice 8 customer-event eligibility contract, so rows with missing
Customer ID are absent from cohort analytics but remain in revenue reporting.

Cancellation-match candidates remain diagnostic evidence only. This mart does
not convert candidates into accounting returns or subtract them from customer
purchase amounts.

`tests/sql/016_customer_cohort_retention.sql` verifies the baseline cohort
contract. `tests/sql/017_dense_customer_cohort_retention.sql` verifies the
dense cohort calendar, including explicit zero-retention rows through snapshot
end, against a recomputation from customer purchase events.
