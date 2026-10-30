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
