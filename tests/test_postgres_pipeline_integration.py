"""Opt-in PostgreSQL integration checks for migration operations.

These tests only run against a dedicated disposable database. They never run
from a developer shell unless both required environment variables are set.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import os
from pathlib import Path
from queue import Queue
import tempfile
import threading
import unittest
from uuid import uuid4

from retailpulse.pipeline_runner import (
    apply_migrations,
    connect_from_dsn,
    discover_migrations,
    refresh_ingestion_materializations,
    run_sql_checks,
)


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
                cursor.execute("drop schema if exists int cascade")
                cursor.execute("drop schema if exists stg cascade")
                cursor.execute("drop schema if exists decision cascade")
                cursor.execute("drop schema if exists dw cascade")
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

        expected_migrations = tuple(
            migration.path.name for migration in discover_migrations(PROJECT_ROOT / "migrations")
        )
        self.assertEqual(first.applied, expected_migrations)
        self.assertEqual(second.applied, ())
        self.assertEqual(second.already_applied, first.applied)
        self.assertEqual(ledger, [(index, name) for index, name in enumerate(first.applied, start=1)])
        expected_checks = tuple(
            path.name for path in sorted((PROJECT_ROOT / "tests" / "sql").glob("*.sql"))
        )
        self.assertEqual(checks, expected_checks)

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

    def test_dense_cohort_retention_materializes_zero_retention_months(self) -> None:
        """A cohort with no later event must still emit an explicit zero row."""

        connection = connect_from_dsn(self.dsn)
        try:
            apply_migrations(connection, PROJECT_ROOT / "migrations")
            with connection.cursor() as cursor:
                cursor.execute("drop view mart.customer_cohort_retention")
                cursor.execute("drop view mart.customer_purchase_event cascade")
                cursor.execute(
                    """
                    create view mart.customer_purchase_event as
                    select *
                    from (
                        values
                            (1::bigint, 'synthetic'::text, 'customer-a'::text,
                             'invoice-a'::text, timestamp '2020-01-15 10:00:00',
                             1::bigint, 10::numeric, 0::numeric, 0::numeric),
                            (1::bigint, 'synthetic'::text, 'customer-b'::text,
                             'invoice-b'::text, timestamp '2020-02-15 10:00:00',
                             1::bigint, 10::numeric, 0::numeric, 0::numeric)
                    ) as event(
                        source_file_id,
                        source_sha256,
                        customer_id,
                        invoice_no,
                        event_at,
                        eligible_sale_row_count,
                        gross_purchase_amount,
                        matched_candidate_cancellation_row_count,
                        ambiguous_candidate_cancellation_row_count
                    )
                    """
                )
                cursor.execute(
                    (PROJECT_ROOT / "migrations" / "017_dense_customer_cohort_retention.sql").read_text(
                        encoding="utf-8"
                    )
                )
                cursor.execute(
                    """
                    select
                        cohort_month,
                        activity_month,
                        months_since_cohort,
                        active_customer_count,
                        retained_customer_count,
                        retention_rate
                    from mart.customer_cohort_retention
                    order by cohort_month, activity_month
                    """
                )
                rows = cursor.fetchall()
        finally:
            connection.close()

        self.assertEqual(
            rows,
            [
                (date(2020, 1, 1), date(2020, 1, 1), 0, 1, 1, Decimal("1")),
                (date(2020, 1, 1), date(2020, 2, 1), 1, 1, 0, Decimal("0")),
                (date(2020, 2, 1), date(2020, 2, 1), 0, 1, 1, Decimal("1")),
            ],
        )

    def test_warehouse_and_decision_contracts_preserve_lineage_and_temporal_boundaries(self) -> None:
        """Exercise the new dimensions/fact and decision views on published rows."""

        connection = connect_from_dsn(self.dsn)
        batch_id = uuid4()
        try:
            apply_migrations(connection, PROJECT_ROOT / "migrations")
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into ops.source_file (
                        sha256, source_uri, original_filename, byte_size,
                        source_retrieved_at, expected_row_count
                    ) values (%s, %s, %s, %s, %s, %s)
                    returning source_file_id
                    """,
                    (
                        "a" * 64,
                        "https://example.test/synthetic.xlsx",
                        "synthetic.xlsx",
                        1,
                        "2020-11-02T00:00:00+00:00",
                        4,
                    ),
                )
                source_file_id = cursor.fetchone()[0]
                cursor.execute(
                    "insert into ops.ingestion_batch (batch_id, source_file_id, status) values (%s, %s, 'STARTED')",
                    (batch_id, source_file_id),
                )
                cursor.executemany(
                    """
                    insert into raw.online_retail_line (
                        source_file_id, sheet_name, source_row_number, first_ingestion_batch_id,
                        invoice_no_raw, stock_code_raw, description_raw, quantity_raw,
                        invoice_date_raw, unit_price_raw, customer_id_raw, country_raw
                    ) values (%s, 'synthetic', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (source_file_id, 2, batch_id, "10001", "ITEM1", "first widget", "1", "2020-07-01 10:00:00", "10", "customer-a", "United Kingdom"),
                        (source_file_id, 3, batch_id, "10002", "ITEM1", " latest   widget ", "1", "2020-11-01 10:00:00", "12", "customer-a", "United Kingdom"),
                        (source_file_id, 4, batch_id, "10003", "POST", "Postage", "1", "2020-11-01 11:00:00", "2", None, "United Kingdom"),
                        (source_file_id, 5, batch_id, "10004", "ITEM2", "Another item", "1", "2020-11-01 12:00:00", "3", None, "United Kingdom"),
                    ],
                )
                cursor.execute(
                    """
                    update ops.ingestion_batch
                    set status = 'SUCCEEDED', completed_at = now(), committed_row_count = 4
                    where batch_id = %s
                    """,
                    (batch_id,),
                )
            connection.commit()
            refresh_ingestion_materializations(connection)
            checks = run_sql_checks(
                connection,
                [
                    PROJECT_ROOT / "tests" / "sql" / "018_dimensional_warehouse.sql",
                    PROJECT_ROOT / "tests" / "sql" / "019_customer_priority_decision.sql",
                ],
            )

            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select customer_id, first_seen_at::date, primary_country
                    from dw.dim_customer
                    order by customer_id
                    """
                )
                customer_rows = cursor.fetchall()
                cursor.execute(
                    """
                    select count(*), count(*) filter (where customer_key is null)
                    from dw.fct_sales_line
                    """
                )
                fact_counts = cursor.fetchone()
                cursor.execute(
                    """
                    select latest_normalized_description, special_item_class
                    from dw.dim_product
                    where stock_code = 'ITEM1'
                    """
                )
                item1 = cursor.fetchone()
                cursor.execute(
                    """
                    select special_item_class
                    from dw.dim_product
                    where stock_code = 'POST'
                    """
                )
                post_class = cursor.fetchone()[0]
                cursor.execute(
                    """
                    select customer_id, frequency, monetary_amount, priority_segment
                    from decision.customer_priority_snapshot
                    """
                )
                snapshot_rows = cursor.fetchall()
                cursor.execute(
                    """
                    select customer_id, observation_frequency, repurchased_in_prediction_window,
                           label_interpretation
                    from decision.customer_priority_backtest
                    """
                )
                backtest_rows = cursor.fetchall()
        finally:
            connection.close()

        self.assertEqual(customer_rows, [("customer-a", date(2020, 7, 1), "United Kingdom")])
        self.assertEqual(fact_counts, (4, 2))
        self.assertEqual(item1, ("LATEST WIDGET", "MERCHANDISE_OR_UNCLASSIFIED"))
        self.assertEqual(post_class, "SERVICE_OR_FEE")
        self.assertEqual(snapshot_rows, [("customer-a", 2, Decimal("22"), "CHAMPIONS")])
        self.assertEqual(
            backtest_rows,
            [("customer-a", 1, True, "BACKTEST_OUTCOME_ONLY_NOT_CAUSAL_RESPONSE")],
        )
        self.assertIn("018_dimensional_warehouse.sql", checks)
        self.assertIn("019_customer_priority_decision.sql", checks)
