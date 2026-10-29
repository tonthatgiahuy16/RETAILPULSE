"""Contract tests for the Slice 1 raw-ingestion transaction flow."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from openpyxl import Workbook

from retailpulse.ingestion.raw_loader import (
    EXPECTED_HEADERS,
    ReconciliationError,
    WorkbookContractError,
    ingest_workbook,
)
from retailpulse.ingestion.source_snapshot import compute_sha256


TEST_TEMP_ROOT = Path(__file__).resolve().parents[1] / ".test-tmp"


class FakeConnection:
    """Small transactional fake that exposes the ingestion boundary's effects."""

    def __init__(self, *, fail_raw_insert: bool = False) -> None:
        self.batches: dict[Any, dict[str, Any]] = {}
        self.sources: dict[str, dict[str, Any]] = {}
        self.raw_rows: list[tuple[Any, ...]] = []
        self._pending_batches: dict[Any, dict[str, Any]] = {}
        self._pending_sources: dict[str, dict[str, Any]] = {}
        self._pending_raw_rows: list[tuple[Any, ...]] = []
        self._next_source_file_id = 1
        self.fail_raw_insert = fail_raw_insert
        self.commit_count = 0
        self.rollback_count = 0

    def cursor(self) -> "FakeCursor":
        return FakeCursor(self)

    def commit(self) -> None:
        self.batches.update(self._pending_batches)
        self.sources.update(self._pending_sources)
        self.raw_rows.extend(self._pending_raw_rows)
        self._clear_pending()
        self.commit_count += 1

    def rollback(self) -> None:
        self._clear_pending()
        self.rollback_count += 1

    def _clear_pending(self) -> None:
        self._pending_batches = {}
        self._pending_sources = {}
        self._pending_raw_rows = []

    def mutable_batch(self, batch_id: Any) -> dict[str, Any]:
        if batch_id not in self._pending_batches:
            self._pending_batches[batch_id] = deepcopy(self.batches[batch_id])
        return self._pending_batches[batch_id]

    def source_by_id(self, source_file_id: int) -> dict[str, Any]:
        for source in [*self.sources.values(), *self._pending_sources.values()]:
            if source["source_file_id"] == source_file_id:
                return source
        raise AssertionError(f"Unknown source_file_id {source_file_id}")

    def raw_count(self, source_file_id: int) -> int:
        rows = [*self.raw_rows, *self._pending_raw_rows]
        return sum(row[0] == source_file_id for row in rows)


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self._fetchone: tuple[Any, ...] | None = None

    def execute(self, query: str, parameters: tuple[Any, ...] | None = None) -> None:
        normalised = " ".join(query.lower().split())
        parameters = parameters or ()

        if normalised.startswith("insert into ops.ingestion_batch"):
            batch_id = parameters[0]
            self.connection._pending_batches[batch_id] = {
                "batch_id": batch_id,
                "status": "STARTED",
                "source_file_id": None,
                "failure_reason": None,
                "committed_row_count": None,
            }
        elif normalised.startswith("select pg_advisory_xact_lock"):
            pass
        elif normalised.startswith("select source_file.source_file_id, source_file.expected_row_count"):
            source = self.connection.sources.get(parameters[0])
            has_successful_batch = source is not None and any(
                batch["source_file_id"] == source["source_file_id"]
                and batch["status"] == "SUCCEEDED"
                and batch["committed_row_count"] == source["expected_row_count"]
                for batch in self.connection.batches.values()
            )
            self._fetchone = (
                (source["source_file_id"], source["expected_row_count"], has_successful_batch)
                if source is not None
                else None
            )
        elif normalised.startswith("insert into ops.source_file"):
            source_file_id = self.connection._next_source_file_id
            self.connection._next_source_file_id += 1
            source = {
                "source_file_id": source_file_id,
                "sha256": parameters[0],
                "expected_row_count": int(parameters[5]),
            }
            self.connection._pending_sources[parameters[0]] = source
            self._fetchone = (source_file_id,)
        elif normalised.startswith("select count(*) from raw.online_retail_line"):
            self._fetchone = (self.connection.raw_count(int(parameters[0])),)
        elif normalised.startswith("update ops.source_file"):
            source = self.connection.source_by_id(int(parameters[1]))
            source["expected_row_count"] = int(parameters[0])
        elif normalised.startswith("update ops.ingestion_batch"):
            batch_id = parameters[-1]
            batch = self.connection.mutable_batch(batch_id)
            if "'failed'" in normalised:
                batch.update(status="FAILED", failure_reason=parameters[0])
            elif "'skipped_already_loaded'" in normalised:
                batch.update(
                    status="SKIPPED_ALREADY_LOADED",
                    source_file_id=int(parameters[0]),
                    committed_row_count=0,
                )
            elif "'succeeded'" in normalised:
                batch.update(
                    status="SUCCEEDED",
                    source_file_id=int(parameters[0]),
                    committed_row_count=int(parameters[1]),
                )
            else:
                raise AssertionError(f"Unhandled batch update: {query}")
        else:
            raise AssertionError(f"Unhandled SQL: {query}")

    def executemany(self, query: str, parameters: list[tuple[Any, ...]]) -> None:
        if self.connection.fail_raw_insert:
            raise RuntimeError("simulated raw insert failure")
        if "insert into raw.online_retail_line" not in " ".join(query.lower().split()):
            raise AssertionError(f"Unhandled SQL: {query}")
        self.connection._pending_raw_rows.extend(parameters)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._fetchone

    def close(self) -> None:
        pass


def project_temp_directory() -> tempfile.TemporaryDirectory[str]:
    TEST_TEMP_ROOT.mkdir(exist_ok=True)
    return tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)


def write_workbook(path: Path, *, header: tuple[str, ...] = EXPECTED_HEADERS) -> None:
    workbook = Workbook()
    first_sheet = workbook.active
    first_sheet.title = "Year 2009-2010"
    first_sheet.append(header)
    first_sheet.append(("10001", "A", "Thing", 2, datetime(2009, 12, 1, 7, 45), 1.5, 12345, "UK"))
    first_sheet.append(("C10002", "B", None, -1, datetime(2009, 12, 1, 8, 0), 2, None, "UK"))
    second_sheet = workbook.create_sheet("Year 2010-2011")
    second_sheet.append(header)
    second_sheet.append(("20001", "C", "Other", 1, datetime(2010, 12, 1, 8, 0), 3, 23456, "France"))
    workbook.save(path)
    workbook.close()


class RawLoaderTests(unittest.TestCase):
    def test_load_then_repeat_same_content_skips_without_new_raw_rows(self) -> None:
        with project_temp_directory() as directory:
            workbook = Path(directory) / "source.xlsx"
            write_workbook(workbook)
            connection = FakeConnection()
            arguments = {
                "source_uri": "https://example.test/online_retail_ii.xlsx",
                "source_retrieved_at": datetime(2026, 10, 29, tzinfo=UTC),
                "connection_factory": lambda: connection,
            }

            first = ingest_workbook(workbook, **arguments)
            second = ingest_workbook(workbook, **arguments)

        self.assertEqual(first.status, "SUCCEEDED")
        self.assertEqual(first.source_row_count, 3)
        self.assertEqual(first.committed_raw_row_count, 3)
        self.assertEqual(second.status, "SKIPPED_ALREADY_LOADED")
        self.assertEqual(second.source_row_count, 3)
        self.assertEqual(second.committed_raw_row_count, 3)
        self.assertEqual(len(connection.sources), 1)
        self.assertEqual(len(connection.raw_rows), 3)
        self.assertEqual(connection.batches[second.batch_id]["committed_row_count"], 0)

    def test_insert_failure_rolls_back_raw_state_and_records_failed_batch(self) -> None:
        with project_temp_directory() as directory:
            workbook = Path(directory) / "source.xlsx"
            write_workbook(workbook)
            connection = FakeConnection(fail_raw_insert=True)

            with self.assertRaisesRegex(RuntimeError, "simulated raw insert failure"):
                ingest_workbook(
                    workbook,
                    source_uri="https://example.test/online_retail_ii.xlsx",
                    source_retrieved_at=datetime(2026, 10, 29, tzinfo=UTC),
                    connection_factory=lambda: connection,
                )

        self.assertEqual(connection.sources, {})
        self.assertEqual(connection.raw_rows, [])
        self.assertEqual(len(connection.batches), 1)
        failed_batch = next(iter(connection.batches.values()))
        self.assertEqual(failed_batch["status"], "FAILED")
        self.assertIn("simulated raw insert failure", failed_batch["failure_reason"])
        self.assertEqual(connection.rollback_count, 1)

    def test_bad_header_records_a_failed_batch_without_raw_writes(self) -> None:
        with project_temp_directory() as directory:
            workbook = Path(directory) / "source.xlsx"
            write_workbook(workbook, header=("wrong", *EXPECTED_HEADERS[1:]))
            connection = FakeConnection()

            with self.assertRaises(WorkbookContractError):
                ingest_workbook(
                    workbook,
                    source_uri="https://example.test/online_retail_ii.xlsx",
                    source_retrieved_at=datetime(2026, 10, 29, tzinfo=UTC),
                    connection_factory=lambda: connection,
                )

        self.assertEqual(connection.sources, {})
        self.assertEqual(connection.raw_rows, [])
        failed_batch = next(iter(connection.batches.values()))
        self.assertEqual(failed_batch["status"], "FAILED")

    def test_load_uses_the_materialized_bytes_if_input_changes_after_validation(self) -> None:
        with project_temp_directory() as directory:
            workbook = Path(directory) / "source.xlsx"
            write_workbook(workbook)
            expected_hash = compute_sha256(workbook)
            connection = FakeConnection()

            from retailpulse.ingestion.raw_loader import validate_workbook_contract as real_validate

            def validate_then_replace(materialized_path: Path) -> None:
                real_validate(materialized_path)
                write_workbook(workbook, header=("changed", *EXPECTED_HEADERS[1:]))

            with patch(
                "retailpulse.ingestion.raw_loader.validate_workbook_contract",
                side_effect=validate_then_replace,
            ):
                result = ingest_workbook(
                    workbook,
                    source_uri="https://example.test/online_retail_ii.xlsx",
                    source_retrieved_at=datetime(2026, 10, 29, tzinfo=UTC),
                    connection_factory=lambda: connection,
                )

        self.assertEqual(result.status, "SUCCEEDED")
        self.assertEqual(connection.sources[expected_hash]["expected_row_count"], 3)
        self.assertEqual(len(connection.raw_rows), 3)

    def test_same_hash_with_raw_rows_but_no_successful_batch_is_not_skipped(self) -> None:
        with project_temp_directory() as directory:
            workbook = Path(directory) / "source.xlsx"
            write_workbook(workbook)
            source_hash = compute_sha256(workbook)
            connection = FakeConnection()
            connection.sources[source_hash] = {
                "source_file_id": 1,
                "sha256": source_hash,
                "expected_row_count": 3,
            }
            connection.raw_rows = [(1,), (1,), (1,)]

            with self.assertRaisesRegex(ReconciliationError, "no reconciled SUCCEEDED batch"):
                ingest_workbook(
                    workbook,
                    source_uri="https://example.test/online_retail_ii.xlsx",
                    source_retrieved_at=datetime(2026, 10, 29, tzinfo=UTC),
                    connection_factory=lambda: connection,
                )

        failed_batch = next(iter(connection.batches.values()))
        self.assertEqual(failed_batch["status"], "FAILED")
