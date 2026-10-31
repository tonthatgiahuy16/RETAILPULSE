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
        (1750, 40, 130, 970),
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
    add(overview, visual("gross_sales", "card", (40, 40, 400, 180), "Gross sales", {"Values": [("Gross sales", measure(sales, "Gross sales amount"))]}))
    add(overview, visual("net_transaction", "card", (470, 40, 400, 180), "Net transaction amount", {"Values": [("Net transaction", measure(sales, "Net transaction amount"))]}))
    add(overview, visual("transaction_rows", "card", (900, 40, 400, 180), "Transaction rows", {"Values": [("Transaction rows", measure(sales, "Transaction rows"))]}))
    add(overview, visual("missing_share", "card", (1330, 40, 400, 180), "Missing Customer ID share", {"Values": [("Missing Customer ID share", measure(sales, "Missing customer ID share"))]}))
    add(overview, visual("net_trend", "lineChart", (40, 270, 1080, 420), "Event-date net transaction amount (not accounting revenue)", {"Category": [("event_date", field(sales, "event_date"))], "Y": [("Net transaction", measure(sales, "Net transaction amount"))]}))
    add(overview, visual("daily_revenue_table", "table", (1150, 270, 580, 420), "Daily revenue reconciliation", {"Values": [("event_date", field(sales, "event_date")), ("gross_sales_amount", measure(sales, "Gross sales amount")), ("cancellation_signed_amount", field(sales, "cancellation_signed_amount", aggregate=0)), ("net_transaction_amount", measure(sales, "Net transaction amount"))]}))
    add(overview, visual("revenue_components", "clusteredColumnChart", (40, 730, 1690, 280), "Gross sales and signed cancellations by event date", {"Category": [("event_date", field(sales, "event_date"))], "Y": [("Gross sales", measure(sales, "Gross sales amount")), ("Cancellation signed", field(sales, "cancellation_signed_amount", aggregate=0))]}))

    life = "bi customer_lifecycle_snapshot"
    cohort = "bi customer_cohort_retention"
    add(customer, visual("customers", "card", (40, 40, 400, 180), "Eligible customers", {"Values": [("Customers", measure(life, "Customers"))]}))
    add(customer, visual("capacity", "card", (470, 40, 400, 180), "Within illustrative capacity", {"Values": [("Capacity customers", measure(life, "Illustrative capacity customers"))]}))
    add(customer, visual("segments", "clusteredBarChart", (40, 270, 700, 400), "Customers by descriptive RFM segment", {"Category": [("priority_segment", field(life, "priority_segment"))], "Y": [("Customers", measure(life, "Customers"))]}))
    add(customer, visual("retention", "lineChart", (780, 270, 950, 400), "Weighted cohort retention by months since cohort", {"Category": [("months_since_cohort", field(cohort, "months_since_cohort"))], "Y": [("Weighted retention", measure(cohort, "Weighted retention rate"))]}))
    add(customer, visual("priority_table", "table", (40, 720, 1690, 290), "Customer-priority detail — descriptive, not propensity scoring", {"Values": [("customer_id", field(life, "customer_id")), ("primary_country", field(life, "primary_country")), ("priority_segment", field(life, "priority_segment")), ("frequency", field(life, "frequency", aggregate=0)), ("monetary_amount", field(life, "monetary_amount", aggregate=0)), ("priority_rank", field(life, "priority_rank", aggregate=0)), ("is_within_illustrative_budget", field(life, "is_within_illustrative_budget"))]}))

    diag = "bi cancellation_diagnostic"
    baseline = "bi repurchase_baseline_evaluation"
    add(quality, visual("missing_customer_trend", "lineChart", (40, 40, 830, 380), "Missing Customer ID rows by event date", {"Category": [("event_date", field(sales, "event_date"))], "Y": [("Missing Customer ID rows", measure(sales, "Missing customer ID rows"))]}))
    add(quality, visual("cancellation_status", "clusteredBarChart", (900, 40, 830, 380), "Cancellation candidate status — diagnostic only", {"Category": [("candidate_status", field(diag, "candidate_status"))], "Y": [("Cancellation diagnostic rows", measure(diag, "Cancellation diagnostic rows"))]}))
    add(quality, visual("baseline_table", "table", (40, 480, 820, 320), "Repurchase baseline evaluation — historical label, not causal uplift", {"Values": [("source_file_id", field(baseline, "source_file_id")), ("labeled_customer_count", field(baseline, "labeled_customer_count", aggregate=0)), ("actual_repurchase_customer_count", field(baseline, "actual_repurchase_customer_count", aggregate=0)), ("precision", field(baseline, "precision", aggregate=1)), ("recall", field(baseline, "recall", aggregate=1)), ("accuracy", field(baseline, "accuracy", aggregate=1))]}))
    add(quality, visual("snapshot_table", "table", (900, 480, 830, 320), "Source snapshot metadata", {"Values": [("source_file_id", field("bi source_snapshot", "source_file_id")), ("source_retrieved_at", field("bi source_snapshot", "source_retrieved_at")), ("original_filename", field("bi source_snapshot", "original_filename")), ("expected_row_count", field("bi source_snapshot", "expected_row_count", aggregate=0)), ("source_sha256", field("bi source_snapshot", "source_sha256"))]}))

    write(ROOT / "pages" / "pages.json", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json", "pageOrder": [overview, customer, quality], "activePageName": overview})


if __name__ == "__main__":
    build()
