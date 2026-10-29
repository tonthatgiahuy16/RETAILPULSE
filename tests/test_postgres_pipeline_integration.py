"""Opt-in PostgreSQL integration checks for migration operations.

These tests only run against a dedicated disposable database. They never run
from a developer shell unless both required environment variables are set.
"""

from __future__ import annotations

import os
from pathlib import Path
from queue import Queue
import tempfile
import threading
import unittest

from retailpulse.pipeline_runner import apply_migrations, connect_from_dsn, run_sql_checks


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_ENABLED = (
    os.environ.get("RETAILPULSE_INTEGRATION_TEST") == "1"
    and bool(os.environ.get("RETAILPULSE_INTEGRATION_DSN"))
)


@unittest.skipUnless(
    INTEGRATION_ENABLED,
    "set RETAILPULSE_INTEGRATION_TEST=1 and RETAILPULSE_INTEGRATION_DSN for PostgreSQL tests",
)
class PostgresPipelineIntegrationTests(unittest.TestCase):
    """Use an isolated CI database to exercise PostgreSQL transaction behavior."""

    dsn = os.environ.get("RETAILPULSE_INTEGRATION_DSN", "")

    def setUp(self) -> None:
        self._reset_database()

    def tearDown(self) -> None:
        self._reset_database()

    def _reset_database(self) -> None:
        connection = connect_from_dsn(self.dsn)
        try:
            with connection.cursor() as cursor:
                cursor.execute("drop schema if exists mart cascade")
                cursor.execute("drop schema if exists stg cascade")
                cursor.execute("drop schema if exists raw cascade")
                cursor.execute("drop schema if exists ops cascade")
            connection.commit()
        finally:
            connection.close()

    def test_full_runner_bootstraps_ledger_then_skips_and_runs_gates(self) -> None:
        connection = connect_from_dsn(self.dsn)
        try:
            first = apply_migrations(connection, PROJECT_ROOT / "migrations")
            second = apply_migrations(connection, PROJECT_ROOT / "migrations")
            checks = run_sql_checks(connection, (PROJECT_ROOT / "tests" / "sql").glob("*.sql"))

            with connection.cursor() as cursor:
                cursor.execute(
                    "select migration_id, filename from ops.schema_migration order by migration_id"
                )
                ledger = cursor.fetchall()
        finally:
            connection.close()

        self.assertEqual(first.applied[-1], "006_reconciliation_single_staging_scan.sql")
        self.assertEqual(second.applied, ())
        self.assertEqual(second.already_applied, first.applied)
        self.assertEqual(ledger, [(index, name) for index, name in enumerate(first.applied, start=1)])
        self.assertEqual(
            checks,
            (
                "mart_revenue_daily.sql",
                "reconciliation_data_quality.sql",
                "staging_transaction_classification.sql",
            ),
        )

    def test_two_runners_serialize_the_same_unapplied_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            migrations_dir = Path(directory_name)
            (migrations_dir / "001_hold.sql").write_text("select pg_sleep(0.25);", encoding="utf-8")
            start = threading.Barrier(2)
            outcomes: Queue[object] = Queue()

            def run_runner() -> None:
                connection = connect_from_dsn(self.dsn)
                try:
                    start.wait(timeout=5)
                    outcomes.put(apply_migrations(connection, migrations_dir))
                except Exception as error:  # pragma: no cover - asserted in caller
                    outcomes.put(error)
                finally:
                    connection.close()

            runners = [threading.Thread(target=run_runner) for _ in range(2)]
            for runner in runners:
                runner.start()
            for runner in runners:
                runner.join(timeout=10)

        self.assertFalse(any(runner.is_alive() for runner in runners))
        results = [outcomes.get_nowait() for _ in runners]
        self.assertFalse(any(isinstance(result, Exception) for result in results), results)
        applied = [result for result in results if result.applied]  # type: ignore[union-attr]
        skipped = [result for result in results if result.already_applied]  # type: ignore[union-attr]
        self.assertEqual(len(applied), 1)
        self.assertEqual(len(skipped), 1)

        connection = connect_from_dsn(self.dsn)
        try:
            with connection.cursor() as cursor:
                cursor.execute("select count(*) from ops.schema_migration")
                ledger_count = cursor.fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(ledger_count, 1)
