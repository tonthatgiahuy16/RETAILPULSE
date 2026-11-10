"""Generate the RetailPulse PBIR dashboard from the checked-in semantic model."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "powerbi" / "RetailPulse.Report" / "definition"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.14.0/schema.json"


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def field(table: str, column: str, *, aggregate: int | None = None) -> dict:
    expression: dict = {
        "Column": {
            "Expression": {"SourceRef": {"Entity": table}},
            "Property": column,
        }
    }
    if aggregate is not None:
        expression = {"Aggregation": {"Function": aggregate, "Expression": expression}}
    return expression


def measure(table: str, name: str) -> dict:
    return {
        "Measure": {
            "Expression": {"SourceRef": {"Entity": table}},
            "Property": name,
        }
    }


def visual(
    name: str,
    visual_type: str,
    position: tuple[int, int, int, int],
    title: str,
    roles: dict[str, list[tuple[str, dict]]],
    *,
    subtitle: str | None = None,
    show_data_labels: bool = False,
    card_color: str | None = None,
    sort_by: dict | None = None,
) -> dict:
    query_state = {
        role: {
            "projections": [
                {
                    "field": expression,
                    "queryRef": query_ref,
                    "displayName": query_ref,
                    "active": True,
                }
                for query_ref, expression in projections
            ]
        }
        for role, projections in roles.items()
    }
    x, y, width, height = position
    container_objects: dict = {
        "title": [
            {
                "properties": {
                    "show": {"expr": {"Literal": {"Value": "true"}}},
                    "text": {"expr": {"Literal": {"Value": f"'{title}'"}}},
                }
            }
        ]
    }
    if subtitle:
        container_objects["subTitle"] = [
            {
                "properties": {
                    "show": {"expr": {"Literal": {"Value": "true"}}},
                    "text": {"expr": {"Literal": {"Value": f"'{subtitle}'"}}},
                }
            }
        ]

    visual_objects: dict = {}
    if show_data_labels:
        visual_objects["labels"] = [
            {
                "properties": {
                    "show": {"expr": {"Literal": {"Value": "true"}}}
                }
            }
        ]
    if card_color and visual_type == "card":
        visual_objects["labels"] = [
            {
                "properties": {
                    "color": {
                        "solid": {
                            "color": {
                                "expr": {
                                    "Literal": {
                                        "Value": f"'{card_color}'"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        ]

    query_payload: dict = {"queryState": query_state}
    if sort_by is not None:
        query_payload["sortDefinition"] = {
            "sort": [{"field": sort_by, "direction": "Ascending"}]
        }

    visual_payload: dict = {
        "visualType": visual_type,
        "drillFilterOtherVisuals": True,
        "query": query_payload,
        "visualContainerObjects": container_objects,
    }
    if visual_objects:
        visual_payload["objects"] = visual_objects

    return {
        "$schema": SCHEMA,
        "name": name,
        "howCreated": "Default",
        "position": {"x": x, "y": y, "z": 0, "height": height, "width": width},
        "visual": visual_payload,
    }


def snapshot_slicer(name: str) -> dict:
    return visual(
        name,
        "slicer",
        (1528, 36, 352, 134),
        "Source snapshot",
        {"Values": [("Snapshot ID", field("bi source_snapshot", "source_file_id"))]},
        subtitle="Select audited data batch",
    )


def page(name: str, display_name: str) -> None:
    write(
        ROOT / "pages" / name / "page.json",
        {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json",
            "name": name,
            "displayName": display_name,
            "displayOption": "FitToPage",
            "height": 1080,
            "width": 1920,
        },
    )


def add(page_name: str, payload: dict) -> None:
    write(ROOT / "pages" / page_name / "visuals" / payload["name"] / "visual.json", payload)


def build() -> None:
    overview = "retailpulse_overview"
    customer = "retailpulse_customer"
    quality = "retailpulse_quality"
    page(overview, "01 Overview")
    page(customer, "02 Customer lifecycle")
    page(quality, "03 Data quality & diagnostics")

    add(overview, snapshot_slicer("source_snapshot_slicer"))
    add(customer, snapshot_slicer("source_snapshot_slicer"))
    add(quality, snapshot_slicer("source_snapshot_slicer"))

    # -------------------------------------------------------------------------
    # Page 1: Overview
    # -------------------------------------------------------------------------
    sales = "bi sales_daily"
    add(
        overview,
        visual(
            "gross_sales",
            "card",
            (40, 36, 352, 134),
            "Gross sales (£)",
            {"Values": [("Gross sales (£)", measure(sales, "Gross sales amount"))]},
            subtitle="Positive sale lines before cancellations",
            card_color="#4F46E5",
        ),
    )
    add(
        overview,
        visual(
            "net_transaction",
            "card",
            (412, 36, 352, 134),
            "Net transaction amount (£)",
            {"Values": [("Net transaction (£)", measure(sales, "Net transaction amount"))]},
            subtitle="Gross sales minus signed cancellations",
            card_color="#0D9488",
        ),
    )
    add(
        overview,
        visual(
            "transaction_rows",
            "card",
            (784, 36, 352, 134),
            "Transaction rows",
            {"Values": [("Transaction rows", measure(sales, "Transaction rows (exact)"))]},
            subtitle="Total audited staging line items (exact count)",
            card_color="#0F172A",
        ),
    )
    add(
        overview,
        visual(
            "missing_share",
            "card",
            (1156, 36, 352, 134),
            "Missing Customer ID share",
            {"Values": [("Missing ID share", measure(sales, "Missing customer ID share"))]},
            subtitle="Share of guest rows without customer key",
            card_color="#D97706",
        ),
    )

    # Row 2: Expanded Trend Chart (w=1360) & Compact Fitted Table (w=460)
    add(
        overview,
        visual(
            "net_trend",
            "lineChart",
            (40, 190, 1360, 450),
            "Net transaction trend (£)",
            {
                "Category": [("Event date", field(sales, "event_date"))],
                "Y": [("Net transaction (£)", measure(sales, "Net transaction amount"))],
            },
            subtitle="Daily event-date transaction trajectory (not accounting revenue)",
        ),
    )
    add(
        overview,
        visual(
            "daily_revenue_table",
            "tableEx",
            (1420, 190, 460, 450),
            "Daily revenue reconciliation",
            {
                "Values": [
                    ("Date", field(sales, "event_date")),
                    ("Gross (£)", measure(sales, "Gross sales amount")),
                    ("Cancelled (£)", measure(sales, "Cancellations (signed)")),
                    ("Net (£)", measure(sales, "Net transaction amount")),
                ]
            },
            subtitle="Reconciled staging to mart totals by event date; the Total row spans the whole snapshot",
        ),
    )
    add(
        overview,
        visual(
            "revenue_components",
            "lineChart",
            (40, 660, 1840, 380),
            "Gross sales vs signed cancellations (£)",
            {
                "Category": [("Event date", field(sales, "event_date"))],
                "Y": [
                    ("Gross sales (£)", measure(sales, "Gross sales amount")),
                    ("Cancellations (£)", measure(sales, "Cancellations (signed)")),
                ],
            },
            subtitle="Indigo: positive sale volume | Rose: negative signed cancellation volume",
        ),
    )

    # -------------------------------------------------------------------------
    # Page 2: Customer lifecycle
    # -------------------------------------------------------------------------
    life = "bi customer_lifecycle_snapshot"
    cohort = "bi customer_cohort_retention"
    add(
        customer,
        visual(
            "customers",
            "card",
            (40, 36, 352, 134),
            "Eligible customers",
            {"Values": [("Eligible customers", measure(life, "Customers"))]},
            subtitle="Distinct identified customer accounts",
            card_color="#0F172A",
        ),
    )
    add(
        customer,
        visual(
            "capacity",
            "card",
            (412, 36, 352, 134),
            "Campaign budget capacity",
            {"Values": [("Within capacity", measure(life, "Illustrative capacity customers"))]},
            subtitle="Top 500 ranked under illustrative budget",
            card_color="#4F46E5",
        ),
    )
    add(
        customer,
        visual(
            "champions",
            "card",
            (784, 36, 352, 134),
            "Champions segment",
            {"Values": [("Champions", measure(life, "Champions count"))]},
            subtitle="High recency, frequency & monetary tier",
            card_color="#059669",
        ),
    )
    add(
        customer,
        visual(
            "at_risk",
            "card",
            (1156, 36, 352, 134),
            "At-risk high-value",
            {"Values": [("At-risk high-value", measure(life, "At-risk high-value count"))]},
            subtitle="High monetary spend but lapsing recency",
            card_color="#E11D48",
        ),
    )

    add(
        customer,
        visual(
            "segments",
            "clusteredBarChart",
            (40, 190, 724, 450),
            "Customers by RFM segment",
            {
                "Category": [("Segment", field(life, "priority_segment"))],
                "Y": [("Customers", measure(life, "Customers"))],
            },
            subtitle="Rule-based percentile segmentation across snapshot",
            show_data_labels=True,
        ),
    )
    add(
        customer,
        visual(
            "retention",
            "lineChart",
            (784, 190, 1096, 450),
            "Cohort retention trajectory",
            {
                "Category": [("Months since first purchase", field(cohort, "months_since_cohort"))],
                "Y": [("Retention rate", measure(cohort, "Weighted retention rate"))],
            },
            subtitle="Weighted repeat-purchase retention across dense monthly cohorts; month 0 is 100% by definition",
            show_data_labels=True,
        ),
    )

    # Row 3: Fitted Priority Table on the left (w=724) + 2 Value Breakdown Charts on the right (w=538 each)
    add(
        customer,
        visual(
            "priority_table",
            "tableEx",
            (40, 660, 724, 380),
            "Customer priority decision ranking",
            {
                "Values": [
                    ("Customer ID", field(life, "customer_id")),
                    ("Country", field(life, "primary_country")),
                    ("RFM Segment", field(life, "priority_segment")),
                    ("Orders", field(life, "frequency", aggregate=0)),
                    ("Total Spend (£)", field(life, "monetary_amount", aggregate=0)),
                    ("Priority Rank", field(life, "priority_rank")),
                    ("In Budget (Top 500)", field(life, "is_within_illustrative_budget")),
                ]
            },
            subtitle="Descriptive RFM prioritisation table sorted by priority rank (not learned propensity scoring)",
            sort_by=field(life, "priority_rank"),
        ),
    )
    add(
        customer,
        visual(
            "segment_spend",
            "clusteredBarChart",
            (784, 660, 538, 380),
            "Monetary spend (£) by RFM segment",
            {
                "Category": [("Segment", field(life, "priority_segment"))],
                "Y": [("Monetary spend (£)", measure(life, "Monetary spend (£)"))],
            },
            subtitle="Total historical customer spend (£) contributed by each segment",
            show_data_labels=True,
        ),
    )
    add(
        customer,
        visual(
            "country_spend",
            "clusteredBarChart",
            (1342, 660, 538, 380),
            "Customer spend (£) by primary country",
            {
                "Category": [("Country", field(life, "primary_country"))],
                "Y": [("Monetary spend (£)", measure(life, "Monetary spend (£)"))],
            },
            subtitle="Geographic distribution of eligible customer monetary value",
            show_data_labels=True,
        ),
    )

    # -------------------------------------------------------------------------
    # Page 3: Data quality & diagnostics
    # -------------------------------------------------------------------------
    diag = "bi cancellation_diagnostic"
    baseline = "bi repurchase_baseline_evaluation"
    add(
        quality,
        visual(
            "baseline_precision",
            "card",
            (40, 36, 280, 134),
            "Baseline precision",
            {"Values": [("Precision", measure(baseline, "Baseline precision"))]},
            subtitle="True positives / predicted repurchasers",
            card_color="#4F46E5",
        ),
    )
    add(
        quality,
        visual(
            "baseline_recall",
            "card",
            (342, 36, 280, 134),
            "Baseline recall",
            {"Values": [("Recall", measure(baseline, "Baseline recall"))]},
            subtitle="True positives / actual repurchasers",
            card_color="#0D9488",
        ),
    )
    add(
        quality,
        visual(
            "baseline_accuracy",
            "card",
            (644, 36, 280, 134),
            "Baseline accuracy",
            {"Values": [("Accuracy", measure(baseline, "Baseline accuracy"))]},
            subtitle="Overall accuracy; compare with the base rate",
            card_color="#0284C7",
        ),
    )
    add(
        quality,
        visual(
            "base_rate",
            "card",
            (946, 36, 280, 134),
            "Repurchase base rate",
            {"Values": [("Base rate", measure(baseline, "Repurchase base rate"))]},
            subtitle="Always-predict-repurchase accuracy floor",
            card_color="#B45309",
        ),
    )
    add(
        quality,
        visual(
            "labeled_customers",
            "card",
            (1248, 36, 280, 134),
            "Holdout cohort size",
            {"Values": [("Labeled customers", measure(baseline, "Labeled customers"))]},
            subtitle="Customers in 180d observation / 90d prediction window",
            card_color="#0F172A",
        ),
    )

    # Row 2: Taller diagnostic charts (h=420) so the compact tables fit below
    add(
        quality,
        visual(
            "missing_customer_trend",
            "lineChart",
            (40, 190, 904, 420),
            "Missing Customer ID volume",
            {
                "Category": [("Event date", field(sales, "event_date"))],
                "Y": [("Missing ID rows", measure(sales, "Missing customer ID rows"))],
            },
            subtitle="Daily count of unattributed guest transactions excluded from customer marts",
        ),
    )
    add(
        quality,
        visual(
            "cancellation_status",
            "clusteredBarChart",
            (964, 190, 916, 420),
            "Cancellation candidate matching",
            {
                "Category": [("Match reason", field(diag, "candidate_reason"))],
                "Y": [("Cancellation rows", measure(diag, "Cancellation diagnostic rows"))],
            },
            subtitle="Why each cancellation row did or did not find a prior sale; diagnostic only, not verified returns",
            show_data_labels=True,
        ),
    )
    add(
        quality,
        visual(
            "baseline_table",
            "tableEx",
            (40, 630, 904, 200),
            "Temporal holdout baseline evaluation",
            {
                "Values": [
                    ("Snapshot", field(baseline, "source_file_id")),
                    ("Obs. Start", field(baseline, "observation_start_date")),
                    ("Pred. Start", field(baseline, "prediction_start_date")),
                    ("Pred. End (excl.)", field(baseline, "prediction_end_date")),
                    ("Cohort", field(baseline, "labeled_customer_count", aggregate=0)),
                    ("Actual Pos.", field(baseline, "actual_repurchase_customer_count", aggregate=0)),
                    ("Pred. Pos.", field(baseline, "predicted_repurchase_customer_count", aggregate=0)),
                    ("True Pos.", field(baseline, "true_positive_count", aggregate=0)),
                    ("Precision", measure(baseline, "Baseline precision")),
                    ("Recall", measure(baseline, "Baseline recall")),
                ]
            },
            subtitle="Frequency >= 2 baseline evaluated on leakage-free temporal split",
        ),
    )
    add(
        quality,
        visual(
            "snapshot_table",
            "tableEx",
            (964, 630, 916, 200),
            "Source snapshot lineage & audit",
            {
                "Values": [
                    ("ID", field("bi source_snapshot", "source_file_id")),
                    ("Retrieved At", field("bi source_snapshot", "source_retrieved_at")),
                    ("Workbook", field("bi source_snapshot", "original_filename")),
                    ("Source Rows", field("bi source_snapshot", "expected_row_count", aggregate=0)),
                    ("SHA-256 Digest", field("bi source_snapshot", "source_sha256")),
                ]
            },
            subtitle="Immutable source manifest verified before analytical publication",
        ),
    )
    model_eval = "bi repurchase_model_evaluation"
    add(
        quality,
        visual(
            "model_comparison",
            "tableEx",
            (40, 850, 1840, 180),
            "Model vs rule baseline (holdout)",
            {
                "Values": [
                    ("Evaluation", field(model_eval, "model_name")),
                    ("Threshold", field(model_eval, "decision_threshold", aggregate=0)),
                    ("Cohort", field(model_eval, "customer_count", aggregate=0)),
                    ("Precision", field(model_eval, "precision_at_threshold", aggregate=0)),
                    ("Recall", field(model_eval, "recall_at_threshold", aggregate=0)),
                    ("PR-AUC", field(model_eval, "pr_auc", aggregate=0)),
                    ("ROC-AUC", field(model_eval, "roc_auc", aggregate=0)),
                    ("Lift @ top 20%", field(model_eval, "lift_at_top_20_percent", aggregate=0)),
                    ("Brier", field(model_eval, "brier_score", aggregate=0)),
                ]
            },
            subtitle="Historical temporal backtest; not campaign response, uplift, or ROI",
        ),
    )

    write(
        ROOT / "pages" / "pages.json",
        {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json",
            "pageOrder": [overview, customer, quality],
            "activePageName": overview,
        },
    )


if __name__ == "__main__":
    build()
