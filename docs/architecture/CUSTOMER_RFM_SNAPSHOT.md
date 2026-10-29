# Customer RFM snapshot — Slice 9

`mart.customer_rfm_snapshot` has one row per `(source_file_id, as_of_date, customer_id)`. `as_of_date` is `max(event_at)::date + 1` within the immutable source snapshot, never the machine's current date.

Recency is days from the last eligible purchase event to `as_of_date`; frequency is count of customer purchase events; monetary is their gross purchase amount. The model excludes no additional events beyond Slice 8 eligibility and contains no cancellation net-off.
