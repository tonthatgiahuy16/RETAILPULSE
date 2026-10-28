"""Profile an Online Retail II workbook without changing it.

Usage:
    python scripts/profile_source.py data/raw/online_retail_ii/online_retail_II.xlsx
    python scripts/profile_source.py data/raw/online_retail_ii/online_retail_II.xlsx "Year 2009-2010"
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def serialise(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def profile_workbook(source: Path, *, sheet_name: str | None = None) -> dict[str, Any]:
    if not source.is_file():
        raise FileNotFoundError(f"Workbook not found: {source}")

    workbook = load_workbook(source, read_only=True, data_only=True)
    profiles: list[dict[str, Any]] = []

    sheets = [workbook[sheet_name]] if sheet_name is not None else workbook.worksheets
    for sheet in sheets:
        rows = sheet.iter_rows(values_only=True)
        header = next(rows, None)
        profile: dict[str, Any] = {
            "sheet_name": sheet.title,
            "header": [serialise(value) for value in header] if header else [],
        }

        if header is None:
            profiles.append(profile)
            continue

        data_row_count = 0
        missing_customer_id_count = 0
        missing_description_count = 0
        cancellation_invoice_count = 0
        negative_quantity_count = 0
        nonpositive_unit_price_count = 0
        invalid_or_missing_invoice_date_count = 0
        min_invoice_timestamp: datetime | None = None
        max_invoice_timestamp: datetime | None = None

        for row in rows:
            data_row_count += 1
            invoice_no, _, description, quantity, invoice_date, unit_price, customer_id, _ = row

            if customer_id is None or str(customer_id).strip() == "":
                missing_customer_id_count += 1
            if description is None or str(description).strip() == "":
                missing_description_count += 1
            if isinstance(invoice_no, str) and invoice_no.strip().upper().startswith("C"):
                cancellation_invoice_count += 1
            if is_number(quantity) and quantity < 0:
                negative_quantity_count += 1
            if is_number(unit_price) and unit_price <= 0:
                nonpositive_unit_price_count += 1
            if not isinstance(invoice_date, datetime):
                invalid_or_missing_invoice_date_count += 1
            else:
                if min_invoice_timestamp is None or invoice_date < min_invoice_timestamp:
                    min_invoice_timestamp = invoice_date
                if max_invoice_timestamp is None or invoice_date > max_invoice_timestamp:
                    max_invoice_timestamp = invoice_date

        profile.update(
            data_row_count=data_row_count,
            missing_customer_id_count=missing_customer_id_count,
            missing_description_count=missing_description_count,
            cancellation_invoice_count=cancellation_invoice_count,
            negative_quantity_count=negative_quantity_count,
            nonpositive_unit_price_count=nonpositive_unit_price_count,
            invalid_or_missing_invoice_date_count=invalid_or_missing_invoice_date_count,
            min_invoice_timestamp=serialise(min_invoice_timestamp),
            max_invoice_timestamp=serialise(max_invoice_timestamp),
        )
        profiles.append(profile)

    return {
        "source_path": str(source.resolve()),
        "workbook_size_bytes": source.stat().st_size,
        "sheets": profiles,
    }


def main() -> None:
    if len(sys.argv) not in (2, 3):
        raise SystemExit("Usage: python scripts/profile_source.py PATH_TO_WORKBOOK [SHEET_NAME]")
    selected_sheet = sys.argv[2] if len(sys.argv) == 3 else None
    print(
        json.dumps(
            profile_workbook(Path(sys.argv[1]), sheet_name=selected_sheet),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
