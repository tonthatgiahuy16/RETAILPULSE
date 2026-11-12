# RetailPulse project charter

**Version:** 0.2
**Status:** Active — in progress
**Project type:** Solo data-engineering, analytics, and decision-support portfolio project

## Purpose

RetailPulse turns the UCI Online Retail II snapshot into reproducible retail
data contracts and decision-ready analytics. Its central question is:

> Given a limited retention budget, which customers should be prioritised for
> the next campaign, and what evidence supports that choice?

The project is not a claim about a real retailer's current customers or about
the causal effect of a campaign. It is a transparent demonstration of the
methods, assumptions, and limits required to answer that kind of question.

## Scope and non-goals

In scope:

- Reproducible batch ingestion, lineage, reconciliation, and data-quality
  gates for Online Retail II.
- PostgreSQL raw, staging, and analytical contracts; dbt adapter models and
  tests; documented SQL grain and business rules.
- Revenue, cancellation diagnostics, customer purchase events, RFM, cohort
  retention, and a temporally bounded repurchase-label baseline.
- A read-only analytics dashboard and portfolio documentation.
- Rule-based customer-priority contracts and a fixed-capacity temporal
  comparison of RFM, frequency rules, and Logistic Regression.

Out of scope:

- Realtime ingestion, cloud production deployment, marketing automation,
  payments, microservices, Kafka, Spark, and deep learning.
- Collecting additional personal data or claiming campaign uplift, ROI, or
  causal impact without experimental data.

Airflow is deferred until every underlying command and gate is independently
repeatable. A trained production prediction service is future work. The local
Power BI Project is present; a hosted Power BI Service artifact is not part of
this verified scope.

## Source and evidence boundaries

The source is UCI Online Retail II, licensed under CC BY 4.0. The original
workbook remains outside Git. The source and license contract is
[`docs/data/SOURCE_AND_LICENSE.md`](../data/SOURCE_AND_LICENSE.md).

The immutable source payload is identified by SHA-256. Raw lineage is one
physical source row at `(source_file_id, sheet_name, source_row_number)`;
`InvoiceNo` is never a raw row key. The raw retry and publication contract is
defined in [`docs/data/LINEAGE_AND_BATCHING.md`](../data/LINEAGE_AND_BATCHING.md).

Reported local evidence is scoped to the hash-recorded source snapshot and
the date stated in the linked technical documentation. Documentation or code
alone does not prove that a command, migration, test, or dashboard refresh has
run in another environment.

## Current implementation map

| Layer | Current contract | Status |
|---|---|---|
| Source and raw | Immutable source manifest, batch audit, PostgreSQL raw rows, same-hash retry protection | Implemented |
| Staging | Source-row typed transaction classification and explicit quarantine reasons | Implemented |
| Revenue | Snapshot-day event-date transaction amounts and missing-Customer-ID coverage | Implemented |
| Operations | Checksum migration ledger, runner, SQL gates, and integration CI configuration | Implemented |
| dbt | Adapter views and contract tests over PostgreSQL staging and mart relations | Implemented |
| Customer analytics | Candidate-only cancellation diagnostics, customer purchase events, RFM, repurchase label baseline, and cohort retention | Implemented |
| Dashboard and BI consumption | PostgreSQL `bi` semantic layer and local Power BI Project (PBIP) report | Semantic layer implemented; report manually opened and its three pages confirmed to show data in Power BI Desktop on 2026-11-07; Service publication, gateway, and scheduled refresh are not verified |
| Dimensional warehouse | Snapshot-scoped customer, product, and date dimensions plus a lineage-preserving sales-line fact | Local DAG run on 2026-11-10 refreshed warehouse materialized views and ran SQL gates against the existing source snapshot; this is not evidence of new-snapshot ingestion or an SLA |
| Decision and ML | Rule-based RFM priority contract, fixed-capacity comparison, and temporal Logistic Regression evaluation | [Local decision report](../decision/RETENTION_PRIORITY_DECISION.md) generated 2026-11-11 for source snapshot 1 (SHA-256 `bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980`); business frequency is the simpler candidate, but paired bootstrap CIs contain zero at all tested capacities and rolling cutoffs reuse customers; a separate CI job now verifies synthetic-fixture training, persistence, BI readback, and dashboard compilation, while propensity-score publication and production scoring remain planned |
| Orchestration | In-repo DAG runner with dependency order, retries, downstream skipping, JSON run records, and an optional failure webhook; Airflow DAG and backfill operations | Runner implemented and tested; Airflow planned |

The detailed and authoritative implementation contracts live in
[`docs/architecture/`](../architecture/). This Charter deliberately does not
duplicate their SQL definitions.

## Business rules and interpretation guardrails

- A `C` invoice is a cancellation indicator. Candidate matching is diagnostic
  evidence only; it does not establish an accounting return.
- Revenue marts report event-date transaction amounts. They are not accounting
  revenue and do not net heuristic cancellation candidates.
- Missing Customer ID remains in revenue reporting, but is excluded from
  customer-level purchase, RFM, cohort, and label consumers by their own
  eligibility contracts.
- A customer purchase event is an independent eligible invoice event, not a
  line-item count.
- Repurchase labels use source-derived temporal windows. Features cannot use
  information from the prediction window.
- Any campaign-size, response-rate, cost, or incremental-revenue scenario is
  an assumption-based simulation unless supplied with experimental evidence.

These guardrails override any simplified wording in dashboards, analysis, or
portfolio material. See the relevant staging, revenue, cancellation, and
customer architecture notes for exact grains and tests.

## KPI policy

Every published KPI must state its business definition, SQL definition,
grain, source contract, refresh/snapshot date, missing-data treatment, and
known limitations. No dashboard should display a metric before those terms
are defined.

Priority KPI families are:

- Revenue: gross sales, signed cancellation amount, net transaction amount,
  and the share without Customer ID.
- Customer lifecycle: eligible customer purchase events, RFM components,
  repeat-purchase behaviour, and cohort retention.
- Decision evaluation: temporal baselines, precision@K, recall@K, lift@K,
  threshold metrics, and calibration; fixed-capacity results must use one
  holdout cohort and disclose tie-breaking.

`net_transaction_amount` must not be relabelled as accounting net revenue.

## Delivery principles

- Work in small slices with a declared input, output, grain, acceptance gate,
  and evidence.
- Keep migrations immutable after application; protect source snapshots and
  preserve lineage.
- Use pull requests, narrow branches, self-review, targeted tests, and
  documentation updates. Never commit raw source files, credentials, or
  generated local secrets.
- Treat raw as the durable source of truth. Dashboard, analytics, and future
  models must consume published derived contracts, never the workbook or raw
  tables directly.
- Prefer a verified smaller scope to an unverified broader stack.

## Definition of done

The portfolio is complete only when the following are evidenced for the
declared release scope:

- Source attribution/license, immutable lineage, safe retry, and migration
  history are verified.
- Published data contracts have explicit grain, business rules, and passing
  quality/reconciliation gates.
- Analytics and dashboard metrics trace to documented contracts and disclose
  limitations.
- Any predictive model uses temporal validation, leakage checks, an explicit
  baseline, and a reproducible evaluation report.
- Any prioritisation table separates observed facts from business assumptions.
- The README distinguishes implemented work, reported runtime evidence, and
  planned work; repository history contains no credentials or raw source
  snapshot.

## Roadmap

1. Repeat the fixed-capacity comparison across additional temporal holdouts or
   an independently verified source snapshot; check decision stability and
   calibration before considering score publication.
2. Add product/country marts only when a defined consumer needs contracts
   beyond the existing `bi.sales_line` relation.
3. Keep Airflow deferred until the manual pipeline and its validation commands
   are independently repeatable; production scoring remains a separate scope.

## Related documents

- [Source and license](../data/SOURCE_AND_LICENSE.md)
- [Lineage and batching](../data/LINEAGE_AND_BATCHING.md)
- [Pipeline operations](../architecture/PIPELINE_OPERATIONS.md)
- [Customer purchase events](../architecture/CUSTOMER_PURCHASE_EVENT.md)
- [Repurchase label dataset](../architecture/REPURCHASE_LABEL_DATASET.md)
- [Customer cohort retention](../architecture/CUSTOMER_COHORT_RETENTION.md)
- [Retention-priority decision report](../decision/RETENTION_PRIORITY_DECISION.md)
