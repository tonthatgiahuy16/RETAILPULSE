# Repurchase-label dataset — Slice 10

`mart.customer_repurchase_label_dataset` has one row per source snapshot and customer active in its 180-day observation window. The final 90 days of available events are the prediction window; both window boundaries are derived from the source snapshot's maximum event date.

Observation features only use events before `prediction_start_date`. The boolean label says whether the customer has at least one eligible purchase event inside `[prediction_start_date, prediction_end_date)`. This is a descriptive temporal label, not a campaign effect, uplift, or ROI estimate.

`mart.customer_repurchase_baseline_evaluation` evaluates the simple baseline `observation_frequency >= 2` with accuracy, precision, and recall. It is a baseline for later modelling, not a production prediction service.

For source snapshot 1 on 2026-10-29, the data-derived windows are 2011-03-15 through 2011-09-10 for observation and 2011-09-11 through 2011-12-09 for prediction. The dataset has 2,784 labeled customers and 1,722 positives. The baseline has accuracy 0.6602, precision 0.7526, and recall 0.6713; these are descriptive backtest results only.
