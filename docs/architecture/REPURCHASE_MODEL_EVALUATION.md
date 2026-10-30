# Repurchase model evaluation — Slice 15

`scripts/train_repurchase_model.py` trains a fixed Logistic Regression model
from published customer events. It does not write a score to PostgreSQL or
change `decision` relations.

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

## Metrics and limits

The report compares Logistic Regression with the existing
`observation_frequency >= 2` rule using PR-AUC, ROC-AUC, precision/recall at
0.5, and lift at the top 20% of ranked customers. The model also reports Brier
score and five calibration bins. Lift is the positive rate of the top 20%
divided by the overall positive rate; Customer ID deterministically breaks
equal-score ties.

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
