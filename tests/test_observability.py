"""Run-history and latency-summary contracts for the in-repo DAG runner."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from retailpulse.orchestration.dag import RunRecord, TaskResult
from retailpulse.orchestration.observability import (
    append_history,
    format_summary,
    load_history,
    run_history_entry,
    slowest_timings,
    summarize_history,
)


def task(name: str, elapsed: float, detail: dict | None = None) -> TaskResult:
    return TaskResult(
        name=name,
        status="succeeded",
        attempts=1,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:00+00:00",
        elapsed_seconds=elapsed,
        detail=detail or {},
    )


def record(run_id: str, tasks: list[TaskResult]) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:10+00:00",
        status="succeeded",
        tasks=tasks,
    )


class RunHistoryTests(unittest.TestCase):
    def test_history_entry_is_compact_and_identifies_slowest_items(self) -> None:
        run = record(
            "run-1",
            [
                task(
                    "ingest",
                    300.0,
                    {
                        "source_file_id": 1,
                        "materialized_view_timings": [
                            {"name": "dw.fct_sales_line", "elapsed_seconds": 120.0},
                            {"name": "dw.dim_date", "elapsed_seconds": 1.0},
                        ],
                    },
                ),
                task(
                    "sql_gates",
                    7.0,
                    {
                        "timings": [
                            {"name": "b_check.sql", "elapsed_seconds": 2.0},
                            {"name": "a_check.sql", "elapsed_seconds": 5.0},
                        ]
                    },
                ),
                task("train_model", 0.5),
            ],
        )

        entry = run_history_entry(run)

        self.assertEqual(entry["run_id"], "run-1")
        self.assertEqual(entry["elapsed_seconds"], 10.0)
        self.assertEqual(entry["source_file_id"], 1)
        self.assertEqual(
            [item["name"] for item in entry["slowest_tasks"]],
            ["ingest", "sql_gates", "train_model"],
        )
        self.assertEqual(
            [item["name"] for item in entry["slowest_sql_gates"]],
            ["a_check.sql", "b_check.sql"],
        )
        self.assertEqual(
            [item["name"] for item in entry["slowest_materialized_views"]],
            ["dw.fct_sales_line", "dw.dim_date"],
        )
        self.assertNotIn("detail", entry["tasks"][0])

    def test_history_appends_json_lines_and_loads_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            append_history(record("run-1", [task("a", 1.0)]), path)
            append_history(record("run-2", [task("a", 2.0)]), path)

            lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
            entries = load_history(path)

        self.assertEqual(len(lines), 2)
        self.assertEqual([entry["run_id"] for entry in entries], ["run-1", "run-2"])

    def test_malformed_history_line_is_rejected_with_its_number(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            path.write_text('{"run_id": "ok"}\nnot-json\n', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "line 2"):
                load_history(path)

    def test_summary_uses_latest_window_and_reports_medians(self) -> None:
        entries = [
            run_history_entry(record("run-1", [task("sql_gates", 10.0), task("ingest", 2.0)])),
            run_history_entry(record("run-2", [task("sql_gates", 20.0), task("ingest", 4.0)])),
        ]

        full = summarize_history(entries)
        latest = summarize_history(entries, last=1)

        self.assertEqual(full["run_count"], 2)
        self.assertEqual(full["latest_run_id"], "run-2")
        by_name = {item["name"]: item for item in full["tasks"]}
        self.assertEqual(by_name["sql_gates"]["median_seconds"], 15.0)
        self.assertEqual(by_name["sql_gates"]["latest_seconds"], 20.0)
        self.assertEqual(by_name["sql_gates"]["max_seconds"], 20.0)
        self.assertEqual(latest["run_count"], 1)
        self.assertEqual(latest["latest_elapsed_seconds"], 10.0)
        self.assertIn("Runs:", format_summary(full))

    def test_summary_rejects_empty_history(self) -> None:
        with self.assertRaisesRegex(ValueError, "empty run history"):
            summarize_history([])

    def test_slowest_timings_requires_a_positive_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 1"):
            slowest_timings([], limit=0)


if __name__ == "__main__":
    unittest.main()
