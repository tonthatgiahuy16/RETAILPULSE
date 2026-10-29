"""Unit tests for the migration-ledger and SQL-gate boundary."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from typing import Any

from retailpulse.pipeline_runner import MigrationDriftError, apply_migrations, run_sql_checks


class FakeConnection:
    def __init__(self) -> None:
        self.ledger: dict[int, tuple[str, str]] = {}
        self.pending_ledger: dict[int, tuple[str, str]] = {}
        self.executed_sql: list[str] = []
        self.commit_count = 0
        self.rollback_count = 0

    def cursor(self) -> "FakeCursor":
        return FakeCursor(self)

    def commit(self) -> None:
        self.ledger.update(self.pending_ledger)
        self.pending_ledger = {}
        self.commit_count += 1

    def rollback(self) -> None:
        self.pending_ledger = {}
        self.rollback_count += 1


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.rows: list[tuple[Any, ...]] = []

    def execute(self, query: str, parameters: tuple[Any, ...] | None = None) -> None:
        normalised = " ".join(query.lower().split())
        parameters = parameters or ()
        if normalised.startswith("select migration_id, filename, checksum"):
            self.rows = [
                (migration_id, filename, checksum)
                for migration_id, (filename, checksum) in self.connection.ledger.items()
            ]
        elif normalised.startswith("insert into ops.schema_migration"):
            self.connection.pending_ledger[int(parameters[0])] = (
                str(parameters[1]),
                str(parameters[2]),
            )
        elif normalised.startswith("create schema") or normalised.startswith("create table"):
            pass
        else:
            self.connection.executed_sql.append(query)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return deepcopy(self.rows)

    def close(self) -> None:
        pass


class PipelineRunnerTests(unittest.TestCase):
    def make_sql_files(self, directory: Path) -> None:
        (directory / "001_first.sql").write_text("select 1;", encoding="utf-8")
        (directory / "002_second.sql").write_text("select 2;", encoding="utf-8")

    def test_migrations_are_recorded_once_then_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            self.make_sql_files(directory)
            connection = FakeConnection()

            first = apply_migrations(connection, directory)
            second = apply_migrations(connection, directory)

        self.assertEqual(first.applied, ("001_first.sql", "002_second.sql"))
        self.assertEqual(second.applied, ())
        self.assertEqual(second.already_applied, ("001_first.sql", "002_second.sql"))
        self.assertEqual(len(connection.ledger), 2)
        self.assertEqual(connection.executed_sql, ["select 1;", "select 2;"])

    def test_changed_applied_migration_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            self.make_sql_files(directory)
            connection = FakeConnection()
            apply_migrations(connection, directory)
            (directory / "001_first.sql").write_text("select changed;", encoding="utf-8")

            with self.assertRaisesRegex(MigrationDriftError, "differs"):
                apply_migrations(connection, directory)

    def test_sql_checks_are_sorted_and_leave_no_persistent_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            second = directory / "b_check.sql"
            first = directory / "a_check.sql"
            first.write_text("select 'first';", encoding="utf-8")
            second.write_text("select 'second';", encoding="utf-8")
            connection = FakeConnection()

            executed = run_sql_checks(connection, [second, first])

        self.assertEqual(executed, ("a_check.sql", "b_check.sql"))
        self.assertEqual(connection.executed_sql, ["select 'first';", "select 'second';"])
        self.assertEqual(connection.rollback_count, 1)
