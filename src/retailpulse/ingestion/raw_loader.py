"""Transactional PostgreSQL ingestion for immutable Online Retail II snapshots."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from openpyxl import load_workbook

from retailpulse.ingestion.source_snapshot import SourceSnapshot, describe_snapshot


EXPECTED_HEADERS = (
    "Invoice",
    "StockCode",
    "Description",
    "Quantity",
    "InvoiceDate",
    "Price",
    "Customer ID",
    "Country",
)
RAW_INSERT_BATCH_SIZE = 1_000


class DatabaseCursor(Protocol):
    def execute(self, query: str, parameters: tuple[Any, ...] | None = None) -> Any: ...

    def executemany(self, query: str, parameters: list[tuple[Any, ...]]) -> Any: ...

    def fetchone(self) -> tuple[Any, ...] | None: ...

    def close(self) -> None: ...


class DatabaseConnection(Protocol):
    def cursor(self) -> DatabaseCursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class WorkbookContractError(ValueError):
    """Raised when the source is not the workbook covered by this slice."""


class ReconciliationError(RuntimeError):
    """Raised when the database row count differs from the source count."""


@dataclass(frozen=True)
class IngestionResult:
    batch_id: UUID
    status: str
    source_file_id: int | None
    source_row_count: int
    committed_raw_row_count: int


@contextmanager
def _cursor(connection: DatabaseConnection) -> Iterator[DatabaseCursor]:
    cursor = connection.cursor()
    try:
        yield cursor
    finally:
        cursor.close()


def _normalise_raw_value(value: Any) -> str | None:
    """Represent a workbook cell without assigning it a business meaning."""

    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def validate_workbook_contract(workbook_path: Path) -> None:
    """Reject missing, empty, or header-incompatible workbooks before raw writes."""

    if not workbook_path.is_file():
        raise FileNotFoundError(f"Workbook does not exist or is not a file: {workbook_path}")

    workbook = load_workbook(workbook_path, read_only=True, data_only=False)
    try:
        if not workbook.worksheets:
            raise WorkbookContractError("Workbook has no worksheets")
        for sheet in workbook.worksheets:
            header = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), None)
            normalised_header = tuple(_normalise_raw_value(value) for value in header or ())
            if normalised_header != EXPECTED_HEADERS:
                raise WorkbookContractError(
                    f"Sheet {sheet.title!r} header does not match the Online Retail II contract: "
                    f"{normalised_header!r}"
                )
    finally:
        workbook.close()


def iter_workbook_raw_rows(workbook_path: Path) -> Iterator[tuple[str, int, tuple[str | None, ...]]]:
    """Yield every physical data row with its immutable sheet/row lineage."""

    workbook = load_workbook(workbook_path, read_only=True, data_only=False)
    try:
        for sheet in workbook.worksheets:
            for source_row_number, values in enumerate(
                sheet.iter_rows(min_row=2, values_only=True), start=2
            ):
                if len(values) != len(EXPECTED_HEADERS):
                    raise WorkbookContractError(
                        f"Sheet {sheet.title!r}, row {source_row_number} has {len(values)} columns; "
                        f"expected {len(EXPECTED_HEADERS)}"
                    )
                yield (
                    sheet.title,
                    source_row_number,
                    tuple(_normalise_raw_value(value) for value in values),
                )
    finally:
        workbook.close()


def _record_started_batch(connection: DatabaseConnection, batch_id: UUID) -> None:
    with _cursor(connection) as cursor:
        cursor.execute(
            """
            insert into ops.ingestion_batch (batch_id, status)
            values (%s, 'STARTED')
            """,
            (batch_id,),
        )
    connection.commit()


def _record_failed_batch(
    connection: DatabaseConnection, batch_id: UUID, error: Exception
) -> None:
    with _cursor(connection) as cursor:
        cursor.execute(
            """
            update ops.ingestion_batch
            set status = 'FAILED', failure_reason = %s
            where batch_id = %s
            """,
            (f"{type(error).__name__}: {error}", batch_id),
        )
    connection.commit()


def _advisory_lock(cursor: DatabaseCursor, sha256_hex: str) -> None:
    """Serialize attempts for one payload without blocking unrelated snapshots."""

    cursor.execute(
        "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (sha256_hex,),
    )


def _stream_raw_rows(
    cursor: DatabaseCursor,
    workbook_path: Path,
    *,
    source_file_id: int,
    batch_id: UUID,
) -> int:
    insert_sql = """
        insert into raw.online_retail_line (
            source_file_id, sheet_name, source_row_number, first_ingestion_batch_id,
            invoice_no_raw, stock_code_raw, description_raw, quantity_raw, invoice_date_raw,
            unit_price_raw, customer_id_raw, country_raw
        ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    pending_rows: list[tuple[Any, ...]] = []
    source_row_count = 0

    for sheet_name, source_row_number, values in iter_workbook_raw_rows(workbook_path):
        pending_rows.append((source_file_id, sheet_name, source_row_number, batch_id, *values))
        source_row_count += 1
        if len(pending_rows) == RAW_INSERT_BATCH_SIZE:
            cursor.executemany(insert_sql, pending_rows)
            pending_rows.clear()

    if pending_rows:
        cursor.executemany(insert_sql, pending_rows)

    return source_row_count


def ingest_workbook(
    workbook_path: Path,
    *,
    source_uri: str,
    source_retrieved_at: datetime,
    connection_factory: Callable[[], DatabaseConnection],
) -> IngestionResult:
    """Ingest one workbook under the Slice 1 transaction and retry contract.

    The STARTED/FAILED audit entries are deliberately committed separately. All
    source-manifest, raw-row, and SUCCEEDED changes belong to one transaction.
    """

    connection = connection_factory()
    batch_id = uuid4()
    _record_started_batch(connection, batch_id)

    try:
        if not source_uri.strip():
            raise ValueError("source_uri must not be blank")
        if source_retrieved_at.tzinfo is None:
            raise ValueError("source_retrieved_at must include a timezone")

        snapshot: SourceSnapshot = describe_snapshot(workbook_path, source_uri=source_uri)
        validate_workbook_contract(workbook_path)

        with _cursor(connection) as cursor:
            _advisory_lock(cursor, snapshot.sha256_hex)
            cursor.execute(
                """
                select source_file_id, expected_row_count
                from ops.source_file
                where sha256 = %s
                """,
                (snapshot.sha256_hex,),
            )
            existing = cursor.fetchone()

            if existing is not None:
                source_file_id, expected_row_count = int(existing[0]), int(existing[1])
                cursor.execute(
                    "select count(*) from raw.online_retail_line where source_file_id = %s",
                    (source_file_id,),
                )
                raw_row_count = int(cursor.fetchone()[0])
                if raw_row_count != expected_row_count:
                    raise ReconciliationError(
                        f"Existing source_file_id {source_file_id} records {expected_row_count} "
                        f"rows but raw contains {raw_row_count}"
                    )
                cursor.execute(
                    """
                    update ops.ingestion_batch
                    set source_file_id = %s,
                        status = 'SKIPPED_ALREADY_LOADED',
                        completed_at = now(),
                        committed_row_count = 0
                    where batch_id = %s
                    """,
                    (source_file_id, batch_id),
                )
                connection.commit()
                return IngestionResult(
                    batch_id=batch_id,
                    status="SKIPPED_ALREADY_LOADED",
                    source_file_id=source_file_id,
                    source_row_count=expected_row_count,
                    committed_raw_row_count=raw_row_count,
                )

            cursor.execute(
                """
                insert into ops.source_file (
                    sha256, source_uri, original_filename, byte_size,
                    source_retrieved_at, expected_row_count
                ) values (%s, %s, %s, %s, %s, %s)
                returning source_file_id
                """,
                (
                    snapshot.sha256_hex,
                    snapshot.source_uri,
                    snapshot.original_filename,
                    snapshot.byte_size,
                    source_retrieved_at.astimezone(UTC),
                    0,
                ),
            )
            source_file_id = int(cursor.fetchone()[0])
            source_row_count = _stream_raw_rows(
                cursor,
                workbook_path,
                source_file_id=source_file_id,
                batch_id=batch_id,
            )
            cursor.execute(
                "select count(*) from raw.online_retail_line where source_file_id = %s",
                (source_file_id,),
            )
            committed_raw_row_count = int(cursor.fetchone()[0])
            if committed_raw_row_count != source_row_count:
                raise ReconciliationError(
                    f"Source contains {source_row_count} rows but raw has {committed_raw_row_count}"
                )
            cursor.execute(
                """
                update ops.source_file
                set expected_row_count = %s
                where source_file_id = %s
                """,
                (source_row_count, source_file_id),
            )
            cursor.execute(
                """
                update ops.ingestion_batch
                set source_file_id = %s,
                    status = 'SUCCEEDED',
                    completed_at = now(),
                    committed_row_count = %s
                where batch_id = %s
                """,
                (source_file_id, committed_raw_row_count, batch_id),
            )
        connection.commit()
        return IngestionResult(
            batch_id=batch_id,
            status="SUCCEEDED",
            source_file_id=source_file_id,
            source_row_count=source_row_count,
            committed_raw_row_count=committed_raw_row_count,
        )
    except Exception as error:
        connection.rollback()
        _record_failed_batch(connection, batch_id, error)
        raise


def connect_psycopg(dsn: str) -> DatabaseConnection:
    """Create the production connection lazily so unit tests need no driver."""

    try:
        import psycopg
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "PostgreSQL support is not installed. Install the project dependencies first."
        ) from error
    return psycopg.connect(dsn)
