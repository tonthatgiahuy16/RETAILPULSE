# RetailPulse data model

This is the current PostgreSQL contract model. `raw` is the durable immutable
source of truth. `stg`, `int`, `mart`, `dw`, and `decision` are derived views
or refreshable materialized projections; none replace raw lineage.

## ERD

```mermaid
erDiagram
    OPS_SOURCE_FILE ||--o{ OPS_INGESTION_BATCH : "source_file_id physical FK"
    OPS_SOURCE_FILE ||--o{ RAW_ONLINE_RETAIL_LINE : "source_file_id physical FK"
    OPS_INGESTION_BATCH ||--o{ RAW_ONLINE_RETAIL_LINE : "first_ingestion_batch_id physical FK"

    RAW_ONLINE_RETAIL_LINE ||--|| STG_ONLINE_RETAIL_TRANSACTION : "published typed source-row view"
    STG_ONLINE_RETAIL_TRANSACTION ||--o| INT_ELIGIBLE_SALE_LINE : "eligible SALE projection"
    STG_ONLINE_RETAIL_TRANSACTION ||--o| INT_CANCELLATION_LINE : "cancellation projection"
    STG_ONLINE_RETAIL_TRANSACTION }o--|| MART_REVENUE_DAILY : "aggregates by snapshot and day"
    STG_ONLINE_RETAIL_TRANSACTION ||--|| INT_CUSTOMER_ANALYTICS_ROW_ELIGIBILITY : "one status per source row"

    INT_ELIGIBLE_SALE_LINE ||--o{ INT_CANCELLATION_SALE_CANDIDATE_SNAPSHOT : "candidate sale edge"
    INT_CANCELLATION_LINE ||--o{ INT_CANCELLATION_SALE_CANDIDATE_SNAPSHOT : "candidate cancellation edge"
    INT_CANCELLATION_SALE_CANDIDATE_SNAPSHOT ||--|| INT_CANCELLATION_MATCH_RESOLUTION : "candidate counts"

    INT_ELIGIBLE_SALE_LINE }o--|| INT_CUSTOMER_PURCHASE_EVENT_SNAPSHOT : "aggregates customer invoice"
    INT_CUSTOMER_PURCHASE_EVENT_SNAPSHOT ||--|| MART_CUSTOMER_PURCHASE_EVENT : "published event view"
    INT_CANCELLATION_MATCH_RESOLUTION }o--o{ MART_CUSTOMER_PURCHASE_EVENT_CANCELLATION_DIAGNOSTIC : "diagnostic only"
    MART_CUSTOMER_PURCHASE_EVENT ||--|| MART_CUSTOMER_RFM_SNAPSHOT : "customer aggregate"
    MART_CUSTOMER_PURCHASE_EVENT ||--|| MART_CUSTOMER_COHORT_RETENTION : "dense cohort calendar"
    INT_CUSTOMER_PURCHASE_EVENT_SNAPSHOT ||--|| MART_CUSTOMER_REPURCHASE_LABEL_DATASET : "temporal label"
    MART_CUSTOMER_REPURCHASE_LABEL_DATASET ||--|| MART_CUSTOMER_REPURCHASE_BASELINE_EVALUATION : "baseline aggregate"
    STG_ONLINE_RETAIL_TRANSACTION ||--o{ DW_FCT_SALES_LINE : "published SALE source row"
    DW_DIM_DATE ||--o{ DW_FCT_SALES_LINE : "date_key logical join"
    DW_DIM_CUSTOMER ||--o{ DW_FCT_SALES_LINE : "nullable customer_key logical join"
    DW_DIM_PRODUCT ||--o{ DW_FCT_SALES_LINE : "nullable product_key logical join"
    MART_CUSTOMER_RFM_SNAPSHOT ||--|| DECISION_CUSTOMER_PRIORITY_SNAPSHOT : "descriptive current segment"
    MART_CUSTOMER_REPURCHASE_LABEL_DATASET ||--|| DECISION_CUSTOMER_PRIORITY_BACKTEST : "temporal outcome only"
    DW_DIM_CUSTOMER ||--o{ DECISION_CUSTOMER_PRIORITY_SNAPSHOT : "primary country logical join"
    DW_DIM_CUSTOMER ||--o{ DECISION_CUSTOMER_PRIORITY_BACKTEST : "primary country logical join"

    OPS_SOURCE_FILE {
        bigint source_file_id PK
        char_64 sha256 UK
        text source_uri
        timestamptz source_retrieved_at
        bigint expected_row_count
    }
    OPS_INGESTION_BATCH {
        uuid batch_id PK
        bigint source_file_id FK
        text status
        bigint committed_row_count
    }
    RAW_ONLINE_RETAIL_LINE {
        bigint source_file_id PK_FK
        text sheet_name PK
        bigint source_row_number PK
        uuid first_ingestion_batch_id FK
        text invoice_no_raw
        text customer_id_raw
    }
    STG_ONLINE_RETAIL_TRANSACTION {
        bigint source_file_id
        text sheet_name
        bigint source_row_number
        text transaction_class
        timestamp invoice_at
        numeric quantity
        numeric unit_price
        text customer_id
    }
    MART_REVENUE_DAILY {
        bigint source_file_id
        date event_date
        numeric gross_sales_amount
        numeric cancellation_signed_amount
        numeric net_transaction_amount
    }
    INT_ELIGIBLE_SALE_LINE {
        bigint source_file_id
        text customer_id
        text sale_invoice_no
        timestamp sale_invoice_at
    }
    INT_CANCELLATION_LINE {
        bigint source_file_id
        text customer_id
        text cancellation_invoice_no
    }
    INT_CANCELLATION_SALE_CANDIDATE_SNAPSHOT {
        bigint source_file_id
        bigint cancellation_source_row_number
        bigint sale_source_row_number
        text heuristic_name
    }
    INT_CANCELLATION_MATCH_RESOLUTION {
        bigint source_file_id
        bigint cancellation_source_row_number
        text candidate_status
        bigint candidate_count
    }
    INT_CUSTOMER_ANALYTICS_ROW_ELIGIBILITY {
        bigint source_file_id
        bigint source_row_number
        text customer_eligibility_status
    }
    INT_CUSTOMER_PURCHASE_EVENT_SNAPSHOT {
        bigint source_file_id
        text customer_id
        text invoice_no
        timestamp event_at
        numeric gross_purchase_amount
    }
    MART_CUSTOMER_PURCHASE_EVENT {
        bigint source_file_id
        text customer_id
        text invoice_no
        timestamp event_at
        numeric gross_purchase_amount
    }
    MART_CUSTOMER_PURCHASE_EVENT_CANCELLATION_DIAGNOSTIC {
        bigint source_file_id
        text customer_id
        text invoice_no
        numeric matched_candidate_cancellation_row_count
    }
    MART_CUSTOMER_RFM_SNAPSHOT {
        bigint source_file_id
        date as_of_date
        text customer_id
        integer recency_days
        bigint frequency
        numeric monetary_amount
    }
    MART_CUSTOMER_COHORT_RETENTION {
        bigint source_file_id
        date cohort_month
        date activity_month
        bigint cohort_customer_count
        bigint retained_customer_count
        numeric retention_rate
    }
    MART_CUSTOMER_REPURCHASE_LABEL_DATASET {
        bigint source_file_id
        text customer_id
        date observation_start_date
        date prediction_start_date
        boolean repurchased_in_prediction_window
    }
    MART_CUSTOMER_REPURCHASE_BASELINE_EVALUATION {
        bigint source_file_id
        date observation_start_date
        date prediction_start_date
        numeric accuracy
        numeric precision
        numeric recall
    }
```

## Relation inventory

| Relation | Type | Grain | Contract |
|---|---|---|---|
| `ops.source_file` | Physical table | Immutable source payload | `source_file_id`; SHA-256 is unique. |
| `ops.ingestion_batch` | Physical table | One ingestion attempt | `batch_id`; records audit status and committed count. |
| `raw.online_retail_line` | Physical table | One physical workbook row | `(source_file_id, sheet_name, source_row_number)`. |
| `stg.online_retail_transaction` | View | One published source row | Typed/classified raw derivative with lineage. |
| `int.eligible_sale_line`, `int.cancellation_line` | Materialized views | One qualifying staging row | Performance projections only. |
| `int.cancellation_sale_candidate_snapshot` | Materialized view | Cancellation row × sale row heuristic edge | Candidate evidence, not a return fact. |
| `int.cancellation_match_resolution` | View | One cancellation source row | Candidate status and reason. |
| `int.customer_purchase_event_snapshot` | Materialized view | Customer × invoice × source snapshot | Eligible-sale aggregate. |
| `mart.revenue_daily` | View | Source snapshot × event date | Event-date transaction amounts. |
| `mart.customer_purchase_event` | View | Customer × invoice × source snapshot | Published customer event. |
| `mart.customer_rfm_snapshot` | View | Customer × source snapshot × as-of date | RFM features. |
| `mart.customer_cohort_retention` | View | Source snapshot × cohort month × activity month | Dense calendar with zero retention rows. |
| `mart.customer_repurchase_label_dataset` | View | Customer × source snapshot × temporal window | Leakage-bounded features and label. |
| `mart.customer_repurchase_baseline_evaluation` | View | Source snapshot × temporal window | Frequency ≥ 2 baseline evaluation. |
| `dw.dim_date` | Materialized view | Calendar date | Conformed date dimension from staging timestamps. |
| `dw.dim_customer` | Materialized view | Source snapshot × customer | First seen timestamp and deterministic primary country. |
| `dw.dim_product` | Materialized view | Source snapshot × StockCode | Latest normalized description and heuristic special-item class. |
| `dw.fct_sales_line` | Materialized view | One `SALE` staging source row | Lineage-preserving sales fact; nullable customer/product keys are retained. |
| `decision.customer_priority_snapshot` | View | Source snapshot × RFM as-of date × customer | Descriptive RFM segment and capacity rank; no outcome label. |
| `decision.customer_priority_backtest` | View | Source snapshot × observed customer | Observation-only features, segment/rank, country, and historical repurchase label. |

## Boundaries

1. Only arrows labelled **physical FK** are database-enforced foreign keys.
   All other arrows are SQL dependencies, lineage joins, or aggregations.
2. Staging publishes a source snapshot only when the successful batch count,
   raw count, and `expected_row_count` agree.
3. Missing Customer ID stays in revenue but is excluded from customer events,
   RFM, cohorts, labels, and baseline metrics.
4. Cancellation candidates and diagnostics never change staging cancellation
   status, revenue, or customer purchase amount.
5. The runner refreshes eligible-sale, cancellation, candidate,
   customer-event, and dimensional materialized snapshots after successful
   ingestion and before SQL gates. Their dependent views reflect that snapshot
   state.

See [Dimensional warehouse](DIMENSIONAL_WAREHOUSE.md) and [Customer priority
decision](CUSTOMER_PRIORITY_DECISION.md) for keys, business rules, and limits.

See [KPI Dictionary](KPI_DICTIONARY.md) for metric semantics and
[Pipeline Operations](PIPELINE_OPERATIONS.md) for ledger, refresh, retry, and
gate behavior.
