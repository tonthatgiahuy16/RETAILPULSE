"""Create the small deterministic workbook used by data-backed CI gates."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests" / "fixtures" / "mini_retail.xlsx"
HEADERS = (
    "Invoice",
    "StockCode",
    "Description",
    "Quantity",
    "InvoiceDate",
    "Price",
    "Customer ID",
    "Country",
)


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    first = workbook.active
    first.title = "Year 2009-2010"
    second = workbook.create_sheet("Year 2010-2011")
    first.append(HEADERS)
    second.append(HEADERS)

    # The latest purchase is 2020-11-15. The derived 180-day observation
    # window starts 2020-02-20 and the 90-day prediction window starts
    # 2020-08-18, so repeated customers give both features and positive labels.
    start = datetime(2020, 1, 1, 10, 0)
    for index in range(160):
        event_at = start + timedelta(days=index * 2)
        customer_id = str(10000 + index % 12)
        invoice = str(50000 + index)
        row = (
            invoice,
            f"ITEM{index % 5}",
            "Mini fixture item",
            1 + index % 3,
            event_at,
            2.5 + (index % 4),
            customer_id,
            "United Kingdom",
        )
        (first if index % 2 == 0 else second).append(row)

    extras = [
        ("C60001", "ITEM1", "Cancellation", -2, datetime(2020, 11, 10), 4, "10001", "United Kingdom"),
        ("60002", "ITEM2", "Zero-price adjustment", -4, datetime(2020, 11, 11), 0, "10002", "United Kingdom"),
        ("60003", "ITEM3", "Priced adjustment", -1, datetime(2020, 11, 12), 7, "10003", "United Kingdom"),
        ("60004", "ITEM4", "Missing customer sale", 2, datetime(2020, 11, 13), 3, None, "United Kingdom"),
        ("60005", "ITEM0", "Late-window purchase", 1, datetime(2020, 11, 15), 5, "10000", "United Kingdom"),
    ]
    for index, row in enumerate(extras):
        (first if index % 2 == 0 else second).append(row)

    workbook.save(OUTPUT)
    workbook.close()
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
