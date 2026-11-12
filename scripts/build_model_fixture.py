"""Create the deterministic workbook used by the model-evaluation CI job.

The workbook is synthetic and deliberately separate from ``mini_retail.xlsx``.
It provides enough customers and history for two non-overlapping temporal
cutoffs, plus customers whose behaviour changes before the holdout so the
training and holdout label sets contain both classes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests" / "fixtures" / "model_evaluation_retail.xlsx"
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


def _event_dates(start: date, step_days: int, count: int) -> list[date]:
    return [start + timedelta(days=index * step_days) for index in range(count)]


def build_rows() -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    sequence = 0

    def add_events(customer_id: str, dates: list[date], customer_index: int) -> None:
        nonlocal sequence
        for event_index, event_date in enumerate(dates):
            sequence += 1
            quantity = 1 + (sequence + customer_index) % 3
            price = 5 + ((sequence + customer_index + event_index) % 9) * 1.5
            rows.append(
                (
                    str(700000 + sequence),
                    f"ITEM{(sequence + customer_index) % 7}",
                    "Synthetic model fixture item",
                    quantity,
                    datetime.combine(event_date, datetime.min.time()).replace(hour=10, minute=sequence % 60),
                    price,
                    customer_id,
                    "United Kingdom",
                )
            )

    # Observed throughout both the training and holdout prediction windows.
    for index in range(20):
        start = date(2019, 12, 1) + timedelta(days=index % 5)
        add_events(str(30000 + index), _event_dates(start, 28, 14), index)

    # Present in both observation windows but silent in both prediction windows.
    for index in range(10):
        start = date(2019, 12, 5) + timedelta(days=index % 4)
        add_events(str(30100 + index), _event_dates(start, 22, 7), index)

    # Only in the training observation window; silent before the holdout starts.
    for index in range(10):
        start = date(2019, 12, 10) + timedelta(days=index % 3)
        add_events(str(30200 + index), _event_dates(start, 30, 3), index)

    # Present in the holdout observation window but silent in its prediction window.
    for index in range(10):
        start = date(2020, 6, 1) + timedelta(days=index % 5)
        add_events(str(30300 + index), _event_dates(start, 22, 4), index)

    # First purchase after the training cutoff; positive in the holdout window.
    for index in range(10):
        start = date(2020, 8, 5) + timedelta(days=index % 4)
        add_events(str(30400 + index), _event_dates(start, 30, 5), index)

    # Establish the latest source date used by the leakage-safe holdout contract.
    add_events("30000", [date(2020, 12, 20)], 0)
    return rows


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    first = workbook.active
    first.title = "Year 2009-2010"
    second = workbook.create_sheet("Year 2010-2011")
    first.append(HEADERS)
    second.append(HEADERS)

    for index, row in enumerate(build_rows()):
        (first if index % 2 == 0 else second).append(row)

    workbook.save(OUTPUT)
    workbook.close()
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
