# Repurchase model evaluation — Slice 15

`scripts/train_repurchase_model.py` trains a fixed Logistic Regression model
from published customer events. It does not write propensity scores or change
`decision` relations. A normal run persists aggregate evaluation metrics;
`--report-only` omits that database write.

## Temporal contract

Each example has grain `(source_file_id, prediction_start_date, customer_id)`.
Features use the 180 days before `prediction_start_date`; the label is an
eligible purchase in the following 90 days. Cutoffs are 90 days apart, so an
earlier training label ends no later than the next cutoff. All earlier cutoffs
train the model and the latest cutoff is the holdout.

The final holdout must exactly equal
`mart.customer_repurchase_label_dataset`. This proves that evaluation uses the
existing leakage-checked label contract. A random customer split is not used
as temporal model evidence.

## Run

```powershell
python -m pip install -e '.[model]'
$env:PYTHONPATH = 'src'
$env:DATABASE_URL = 'postgresql://...'
python scripts/train_repurchase_model.py
```

The default report is `data/processed/repurchase_model_evaluation.json`, an
ignored local file. Use `--source-file-id` when multiple snapshots exist.

## Metrics, fixed-capacity ranking and limits

The report retains Logistic Regression versus the binary
`observation_frequency >= 2` metrics using PR-AUC, ROC-AUC, precision/recall at
0.5, and lift at the top 20%. It also compares fixed-capacity precision@K,
recall@K and lift@K at 10%, 20% and 30% for:

- contract-019 RFM priority, ranked by its published `priority_rank`;
- naive frequency, ordered `frequency DESC, customer_id ASC`;
- business frequency, ordered `frequency DESC, monetary DESC, recency ASC,
  customer_id ASC`;
- Logistic Regression probabilities.

All methods use the same source snapshot and holdout customer set. K is
`ceil(holdout_count * fraction)`. The report shows the tie block at each cutoff
and how many positions K needs from it. A frequency cut can therefore show
when customer ID decides membership. The model reports Brier score and five
calibration bins. A log1p transform of frequency and monetary is run as a
feature-skew sensitivity check; it is not selected automatically.

For business-frequency versus Logistic Regression, the report also emits a
paired customer bootstrap 95% percentile confidence interval for the
Precision@K difference at every tested capacity. It resamples holdout customers
with rankings and original K membership fixed, using a recorded seed and 2,000
replicates. This interval measures observed-label precision uncertainty for
the declared holdout; it does not measure refit-model uncertainty or predict a
future time period. If an interval includes zero, the report must not claim
that the rule beats the model at that capacity.

The report also records pairwise customer overlap across all rolling prediction
cutoffs. Repeated customers make cutoff rows dependent, so a mean across
cutoffs is not an independent-sample confidence interval. Use these cutoffs to
inspect temporal stability; use an independent source snapshot or a
pre-specified blocked evaluation before making an operational claim.

The written decision report is `docs/decision/RETENTION_PRIORITY_DECISION.md`.
Run with `--report-only` to generate the JSON and Markdown report from PostgreSQL
without upserting evaluation metrics. Model configuration records
`class_weight=None` explicitly.

Cost or incremental-revenue scenarios are outside the measured backtest. If
added later, each must be labeled **simulation based on assumptions**, not
actual ROI.

This is a historical backtest, not campaign response, causal uplift, revenue,
profit, or ROI. Model scoring/publishing is intentionally a later slice.

## Local runtime evidence

On 2026-10-30, source snapshot `1` produced 14,939 earlier-cutoff training
examples and a final holdout of 2,784 customers. The holdout exactly matched
the published label dataset. Logistic Regression scored PR-AUC `0.8162`,
ROC-AUC `0.7152`, lift@20% `1.4629`, and Brier score `0.2286`; the frequency
baseline scored PR-AUC `0.7789`, ROC-AUC `0.7020`, and lift@20% `1.4513`.

At threshold 0.5, the model's precision was `85.0%` and recall `42.9%`, while
the frequency baseline was `75.3%` precision and `67.1%` recall. This is a
threshold trade-off, not proof that one campaign policy is economically better.
