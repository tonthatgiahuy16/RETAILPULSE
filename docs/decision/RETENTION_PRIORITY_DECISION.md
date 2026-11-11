# Retention priority decision report

- Generated at: `2026-11-11T10:26:06.601769+00:00`; source snapshot: `1` (SHA-256 `bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980`).
- Holdout window: `2011-09-11` to `2011-12-10` (end exclusive).
- Holdout: 2,784 customers, positive rate 61.9%; training positive rate 46.9%.
- Decision: **frequency_business**. LR does not strictly lead both business rules at every tested K; frequency_business has the highest mean precision@K among the simple rules. at K=10%, it matches LR; at K=20%, it leads LR by 0.539 percentage points; at K=30%, it leads LR by 0.598 percentage points. The rule is easier to explain and the holdout provides no ranking gain that justifies LR's added model complexity.
- This is a historical temporal backtest of observed repurchase, not campaign response or causal effect.

## Fixed-capacity ranking comparison

Precision@K is the share of selected customers who repurchased; recall@K is the share of all holdout repurchasers selected. K uses `ceil(N * fraction)`. The `class_weight` parameter is explicitly `None` for both LR fits.

| Method | K | Selected | Precision@K | Recall@K | Lift@K | Boundary tie size | Slots decided within tie | Cut through tie? |
|---|---:|---:|---:|---:|---:|---:|---:|:---:|
| rfm_priority_019 | 10% | 279 | 0.950 | 0.154 | 1.536 | 1 | 1 | no |
| rfm_priority_019 | 20% | 557 | 0.865 | 0.280 | 1.399 | 1 | 1 | no |
| rfm_priority_019 | 30% | 836 | 0.835 | 0.405 | 1.350 | 1 | 1 | no |
| frequency_naive | 10% | 279 | 0.946 | 0.153 | 1.530 | 72 | 61 | yes |
| frequency_naive | 20% | 557 | 0.898 | 0.290 | 1.451 | 209 | 156 | yes |
| frequency_naive | 30% | 836 | 0.854 | 0.415 | 1.381 | 312 | 226 | yes |
| frequency_business | 10% | 279 | 0.950 | 0.154 | 1.536 | 1 | 1 | no |
| frequency_business | 20% | 557 | 0.910 | 0.294 | 1.472 | 1 | 1 | no |
| frequency_business | 30% | 836 | 0.861 | 0.418 | 1.392 | 1 | 1 | no |
| logistic_regression | 10% | 279 | 0.950 | 0.154 | 1.536 | 1 | 1 | no |
| logistic_regression | 20% | 557 | 0.905 | 0.293 | 1.463 | 1 | 1 | no |
| logistic_regression | 30% | 836 | 0.855 | 0.415 | 1.383 | 1 | 1 | no |
| log1p_logistic_regression_sensitivity | 10% | 279 | 0.946 | 0.153 | 1.530 | 1 | 1 | no |
| log1p_logistic_regression_sensitivity | 20% | 557 | 0.905 | 0.293 | 1.463 | 1 | 1 | no |
| log1p_logistic_regression_sensitivity | 30% | 836 | 0.862 | 0.419 | 1.394 | 1 | 1 | no |

## Calibration and train/holdout diagnostics

- Pooled train positive rate: 46.9%; holdout positive rate: 61.9%; change: +15.0%.
- LR raw mean predicted probability: 46.7%; holdout rate: 61.9%; calibration gap: -15.2%; Brier: 0.2286.
- `class_weight=None` in code; class weighting did not cause this measured result. Raw-feature LR mean prediction (46.7%) is close to pooled train prevalence (46.9%) but below holdout prevalence (61.9%), which supports prevalence shift as a plausible explanation for the aggregate gap.
- The log1p sensitivity model's aggregate gap is -15.4%; it does not narrow the raw model's gap. This single experiment does not establish feature skew as the cause.

### Training prevalence by cutoff

| Prediction start | Positive rate |
|---|---:|
| 2010-06-18 | 49.2% |
| 2010-09-16 | 61.3% |
| 2010-12-15 | 34.7% |
| 2011-03-15 | 43.2% |
| 2011-06-13 | 49.7% |

### Calibration bins and feature skew

The 0.2-0.4 LR bin is the source of the often-quoted ~32% predicted vs ~46% observed gap; those are bin rates, not the whole holdout rate.

| Model | Predicted-probability bin | Customers | Mean predicted | Actual rate |
|---|---:|---:|---:|---:|
| LR raw features | 0.2-0.4 | 1,368 | 31.8% | 46.0% |
| LR raw features | 0.4-0.6 | 829 | 48.7% | 68.2% |
| LR raw features | 0.6-0.8 | 341 | 68.8% | 85.9% |
| LR raw features | 0.8-1.0 | 246 | 91.6% | 95.5% |
| LR log1p sensitivity | 0.0-0.2 | 71 | 17.5% | 31.0% |
| LR log1p sensitivity | 0.2-0.4 | 1,228 | 28.7% | 45.8% |
| LR log1p sensitivity | 0.4-0.6 | 736 | 49.6% | 65.4% |
| LR log1p sensitivity | 0.6-0.8 | 503 | 69.0% | 84.1% |
| LR log1p sensitivity | 0.8-1.0 | 246 | 88.0% | 95.1% |

| Feature | Train p50 | Train p99 | Train skew | Holdout p50 | Holdout p99 | Holdout skew |
|---|---:|---:|---:|---:|---:|---:|
| observation_recency_days | 51 | 176 | 0.60 | 55 | 178 | 0.57 |
| observation_frequency | 2 | 19 | 9.68 | 2 | 18 | 8.50 |
| observation_monetary_amount | 541 | 1.35e+04 | 19.05 | 509 | 1.19e+04 | 15.11 |


## Assumptions and limits

- No incremental revenue or campaign cost is estimated in this report. Any later cost or revenue scenario must be labeled **simulation based on assumptions**, not actual ROI.
- Ranking results use one source snapshot and one temporal holdout. A repeated temporal holdout is needed before operational use.
- Frequency naive uses `customer_id ASC` inside frequency ties; frequency business adds monetary and recency before ID. Boundary diagnostics show how many selected customers depend on that tie rule.
