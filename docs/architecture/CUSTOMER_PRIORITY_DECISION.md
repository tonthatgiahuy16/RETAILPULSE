# Customer priority decision contract — Slice 14

The `decision` schema is a transparent prioritisation aid, not a deployed
model or a marketing automation system. It separates a current descriptive
RFM ranking from a historical label backtest so the future prediction window
cannot leak into the features used for retrospective evaluation.

## Inputs, outputs, and grain

| Relation | Grain | Inputs | Purpose |
|---|---|---|---|
| `decision.customer_priority_snapshot` | `(source_file_id, as_of_date, customer_id)` | `mart.customer_rfm_snapshot`, `dw.dim_customer` | Current descriptive segment and capacity rank. It has no outcome label. |
| `decision.customer_priority_backtest` | `(source_file_id, customer_id)` | `mart.customer_repurchase_label_dataset`, `dw.dim_customer` | Historical decision rows with the repurchase label. Its RFM-like features are observation-window-only. |
| `decision.illustrative_campaign_scenario` | One scenario | Versioned constants in migration | Explicit campaign-capacity assumption. |

Both decision outputs carry `primary_country` when a country is available from
the customer dimension. A missing country remains null; it does not remove a
customer from the decision relation.

## Segments and ranking

Thresholds are calculated independently per source snapshot (and per
`as_of_date` for the current snapshot): recency 25th/75th percentiles and
frequency/monetary 75th percentiles. The deterministic rules are:

| Segment | Rule |
|---|---|
| `CHAMPIONS` | Recency <= p25, frequency >= p75, and monetary >= p75. |
| `AT_RISK_HIGH_VALUE` | Recency >= p75 and monetary >= p75. |
| `LOST` | Recency >= p75, excluding the higher-value at-risk rule. |
| `POTENTIAL` | All remaining customers. |

Within a snapshot, rank is segment order above, then monetary descending,
frequency descending, recency ascending, and Customer ID ascending. This is a
rule-based prioritisation, not a learned propensity score.

## Budget assumption and limits

`illustrative_fixed_cap_v1` fixes a campaign budget of **1,000 campaign
units**, a contact cost of **2 campaign units**, and capacity of **500
customers**. It deliberately has no currency: the constants demonstrate a
capacity constraint and are not sourced business costs. `is_within_illustrative_budget`
means only `priority_rank <= 500`; it does not predict response, revenue,
profit, uplift, or ROI.

## Fixed-capacity historical comparison

The [retention-priority decision report](../decision/RETENTION_PRIORITY_DECISION.md)
compares contract-019 RFM priority, two frequency rankings, and Logistic
Regression on the same 2,784-customer temporal holdout for source snapshot 1
(SHA-256 `bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980`).
The holdout window is `[2011-09-11, 2011-12-10)`; a positive means an eligible
purchase during that historical 90-day period.

K is `ceil(holdout_customer_count * fraction)`. Results from the 2026-11-11
local run are:

| Ranking | Precision@10% / Recall@10% | Precision@20% / Recall@20% | Precision@30% / Recall@30% |
|---|---:|---:|---:|
| RFM priority, contract 019 | 95.0% / 15.4% | 86.5% / 28.0% | 83.5% / 40.5% |
| Frequency naive (`frequency DESC, customer_id ASC`) | 94.6% / 15.3% | 89.8% / 29.0% | 85.4% / 41.5% |
| Frequency business (`frequency DESC, monetary DESC, recency ASC, customer_id ASC`) | 95.0% / 15.4% | 91.0% / 29.4% | 86.1% / 41.8% |
| Logistic Regression | 95.0% / 15.4% | 90.5% / 29.3% | 85.5% / 41.5% |

For this holdout, the recommendation is the business frequency rule. It ties LR
at 10% and has higher precision by 0.539 percentage points at 20% and 0.598
points at 30%, with a simpler ranking rule. Frequency naive relies on ID to
select 61 of 72, 156 of 209, and 226 of 312 customers in the boundary-frequency
groups at the three capacities; the business tie-breakers avoid cutting through
a tied group at these cutoffs. These results are historical ranking evidence
from one source snapshot, not evidence of a campaign effect or stable
performance across periods.

The model used `class_weight=None`. Pooled training-example positive rate was
46.9%, versus 61.9% on holdout; LR mean predicted probability was 46.7%.
The log1p frequency/monetary sensitivity did not reduce the calibration gap.
This supports prevalence shift as a plausible explanation, but does not prove
seasonality. The bin with predictions from 0.2 to 0.4 had 31.8% mean predicted
probability and 46.0% observed repurchase; those figures apply to that bin,
not the whole holdout.

The comparison estimates no campaign costs or incremental revenue. Any future
cost or revenue scenario must be labeled **simulation based on assumptions**;
it must not be presented as actual ROI, uplift, or causal impact.

The backtest label is explicitly marked
`BACKTEST_OUTCOME_ONLY_NOT_CAUSAL_RESPONSE`. It is whether a customer made an
eligible purchase in the source-derived future 90-day prediction window, not
whether a campaign caused a purchase. Its recency, frequency, and monetary
inputs use only the preceding 180-day observation window. Do not use the full
`mart.customer_rfm_snapshot` as a backtest feature because it includes the
end-of-snapshot period.

SQL gate `019` validates decision grains, equality of backtest and label row
counts, allowed segments, scenario constants, capacity-flag logic, and the
two interpretation disclosures. No revenue or cancellation candidate is
changed by these relations.
