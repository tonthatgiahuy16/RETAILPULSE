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
) -> dict:
    query_state = {
        role: {
            "projections": [
                {"field": expression, "queryRef": query_ref} for query_ref, expression in projections
            ]
        }
        for role, projections in roles.items()
    }
    x, y, width, height = position
    return {
        "$schema": SCHEMA,
        "name": name,
        "howCreated": "Default",
        "position": {"x": x, "y": y, "z": 0, "height": height, "width": width},
        "visual": {
            "visualType": visual_type,
            "drillFilterOtherVisuals": True,
            "query": {"queryState": query_state},
            "visualContainerObjects": {
                "title": [
                    {
                        "properties": {
                            "show": {"expr": {"Literal": {"Value": "true"}}},
                            "text": {"expr": {"Literal": {"Value": f"'{title}'"}}},
                        }
                    }
                ]
            },
        },
    }


def snapshot_slicer(name: str) -> dict:
    return visual(
        name,
        "slicer",
        (1528, 40, 352, 150),
        "Source snapshot",
        {"Values": [("source_file_id", field("bi source_snapshot", "source_file_id"))]},
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

    sales = "bi sales_daily"
    add(overview, visual("gross_sales", "card", (40, 40, 352, 150), "Gross sales", {"Values": [("Gross sales", measure(sales, "Gross sales amount"))]}))
    add(overview, visual("net_transaction", "card", (412, 40, 352, 150), "Net transaction amount", {"Values": [("Net transaction", measure(sales, "Net transaction amount"))]}))
    add(overview, visual("transaction_rows", "card", (784, 40, 352, 150), "Transaction rows", {"Values": [("Transaction rows", measure(sales, "Transaction rows"))]}))
    add(overview, visual("missing_share", "card", (1156, 40, 352, 150), "Missing Customer ID share", {"Values": [("Missing Customer ID share", measure(sales, "Missing customer ID share"))]}))
    add(overview, visual("net_trend", "lineChart", (40, 210, 1160, 450), "Event-date net transaction amount (not accounting revenue)", {"Category": [("event_date", field(sales, "event_date"))], "Y": [("Net transaction", measure(sales, "Net transaction amount"))]}))
    add(overview, visual("daily_revenue_table", "tableEx", (1220, 210, 660, 450), "Daily revenue reconciliation", {"Values": [("Date", field(sales, "event_date")), ("Gross sales", measure(sales, "Gross sales amount")), ("Cancellations (signed)", field(sales, "cancellation_signed_amount", aggregate=0)), ("Net transaction", measure(sales, "Net transaction amount"))]}))
    add(overview, visual("revenue_components", "clusteredColumnChart", (40, 680, 1840, 360), "Gross sales and signed cancellations by event date", {"Category": [("event_date", field(sales, "event_date"))], "Y": [("Gross sales", measure(sales, "Gross sales amount")), ("Cancellation signed", field(sales, "cancellation_signed_amount", aggregate=0))]}))

    life = "bi customer_lifecycle_snapshot"
    cohort = "bi customer_cohort_retention"
    add(customer, visual("customers", "card", (40, 40, 724, 150), "Eligible customers", {"Values": [("Customers", measure(life, "Customers"))]}))
    add(customer, visual("capacity", "card", (784, 40, 724, 150), "Within illustrative capacity", {"Values": [("Capacity customers", measure(life, "Illustrative capacity customers"))]}))
    add(customer, visual("segments", "clusteredBarChart", (40, 210, 724, 450), "Customers by descriptive RFM segment", {"Category": [("priority_segment", field(life, "priority_segment"))], "Y": [("Customers", measure(life, "Customers"))]}))
    add(customer, visual("retention", "lineChart", (784, 210, 1096, 450), "Weighted cohort retention by months since cohort", {"Category": [("months_since_cohort", field(cohort, "months_since_cohort"))], "Y": [("Weighted retention", measure(cohort, "Weighted retention rate"))]}))
    add(customer, visual("priority_table", "tableEx", (40, 680, 1840, 360), "Customer-priority detail — descriptive, not propensity scoring", {"Values": [("Customer ID", field(life, "customer_id")), ("Country", field(life, "primary_country")), ("Segment", field(life, "priority_segment")), ("Frequency", field(life, "frequency", aggregate=0)), ("Monetary amount", field(life, "monetary_amount", aggregate=0)), ("Priority rank", field(life, "priority_rank", aggregate=0)), ("Within illustrative budget", field(life, "is_within_illustrative_budget"))]}))

    diag = "bi cancellation_diagnostic"
    baseline = "bi repurchase_baseline_evaluation"
    add(quality, visual("baseline_precision", "card", (40, 40, 476, 150), "Baseline precision", {"Values": [("Baseline precision", measure(baseline, "Baseline precision"))]}))
    add(quality, visual("baseline_recall", "card", (536, 40, 476, 150), "Baseline recall", {"Values": [("Baseline recall", measure(baseline, "Baseline recall"))]}))
    add(quality, visual("baseline_accuracy", "card", (1032, 40, 476, 150), "Baseline accuracy", {"Values": [("Baseline accuracy", measure(baseline, "Baseline accuracy"))]}))
    add(quality, visual("missing_customer_trend", "lineChart", (40, 210, 904, 450), "Missing Customer ID rows by event date", {"Category": [("event_date", field(sales, "event_date"))], "Y": [("Missing Customer ID rows", measure(sales, "Missing customer ID rows"))]}))
    add(quality, visual("cancellation_status", "clusteredBarChart", (964, 210, 916, 450), "Cancellation candidate status — diagnostic only", {"Category": [("candidate_status", field(diag, "candidate_status"))], "Y": [("Cancellation diagnostic rows", measure(diag, "Cancellation diagnostic rows"))]}))
    add(quality, visual("baseline_table", "tableEx", (40, 680, 904, 360), "Repurchase baseline evaluation — historical label, not causal uplift", {"Values": [("Snapshot ID", field(baseline, "source_file_id")), ("Labeled customers", field(baseline, "labeled_customer_count", aggregate=0)), ("Actual repurchasers", field(baseline, "actual_repurchase_customer_count", aggregate=0)), ("Predicted repurchasers", field(baseline, "predicted_repurchase_customer_count", aggregate=0)), ("True positives", field(baseline, "true_positive_count", aggregate=0))]}))
    add(quality, visual("snapshot_table", "tableEx", (964, 680, 916, 360), "Source snapshot metadata", {"Values": [("Snapshot ID", field("bi source_snapshot", "source_file_id")), ("Retrieved at", field("bi source_snapshot", "source_retrieved_at")), ("Original file", field("bi source_snapshot", "original_filename")), ("Expected rows", field("bi source_snapshot", "expected_row_count", aggregate=0)), ("SHA-256", field("bi source_snapshot", "source_sha256"))]}))

    write(ROOT / "pages" / "pages.json", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json", "pageOrder": [overview, customer, quality], "activePageName": overview})


if __name__ == "__main__":
    build()
