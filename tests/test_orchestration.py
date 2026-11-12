"""Tests for the in-repo DAG runner and pipeline composition."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from retailpulse.orchestration import PipelineConfig, build_dag, validate_config
from retailpulse.orchestration import tasks
from retailpulse.orchestration.dag import Dag, DagError, Task, TaskContext


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_TEMP_ROOT = PROJECT_ROOT / ".test-tmp"


def project_temp_directory() -> tempfile.TemporaryDirectory[str]:
    TEST_TEMP_ROOT.mkdir(exist_ok=True)
    return tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)


class DagRunnerTests(unittest.TestCase):
    def test_topological_order_places_dependencies_first(self) -> None:
        graph = Dag()
        graph.add(Task("c", lambda context: None, depends_on=("b",)))
        graph.add(Task("a", lambda context: None))
        graph.add(Task("b", lambda context: None, depends_on=("a",)))
        self.assertEqual(graph.order(), ("a", "b", "c"))

    def test_graph_rejects_unknown_dependency_and_cycle(self) -> None:
        unknown = Dag().add(Task("a", lambda context: None, depends_on=("missing",)))
        with self.assertRaisesRegex(DagError, "unknown task missing"):
            unknown.validate()

        cycle = Dag()
        cycle.add(Task("a", lambda context: None, depends_on=("b",)))
        cycle.add(Task("b", lambda context: None, depends_on=("a",)))
        with self.assertRaisesRegex(DagError, "dependency cycle"):
            cycle.validate()

    def test_retry_uses_exponential_backoff_and_records_attempts(self) -> None:
        attempts = {"count": 0}

        def flaky(context):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise RuntimeError("transient")
            return {"value": attempts["count"]}

        graph = Dag().add(Task("flaky", flaky))
        sleeps: list[float] = []
        record = graph.run(
            TaskContext(config=None, environ={}),
            default_max_attempts=3,
            backoff_seconds=1.5,
            sleep=sleeps.append,
        )
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(record.tasks[0].attempts, 3)
        self.assertEqual(sleeps, [1.5, 3.0])

    def test_failure_skips_downstream_but_keeps_independent_branch(self) -> None:
        calls: list[str] = []

        def boom(context):
            calls.append("boom")
            raise ValueError("broken")

        def note(name):
            def run(context):
                calls.append(name)
                return {"ok": True}

            return run

        graph = Dag()
        graph.add(Task("root", note("root")))
        graph.add(Task("bad", boom, depends_on=("root",)))
        graph.add(Task("child", note("child"), depends_on=("bad",)))
        graph.add(Task("side", note("side"), depends_on=("root",)))

        record = graph.run(TaskContext(config=None, environ={}))
        by_name = {task.name: task for task in record.tasks}
        self.assertEqual(record.status, "failed")
        self.assertEqual(by_name["bad"].status, "failed")
        self.assertEqual(by_name["child"].status, "skipped")
        self.assertTrue(by_name["child"].blocked)
        self.assertEqual(by_name["side"].status, "succeeded")
        self.assertNotIn("child", calls)

    def test_optional_skip_does_not_block_downstream(self) -> None:
        def skipped(context):
            return {"skipped": True, "reason": "disabled for test"}

        def downstream(context):
            return {"ok": True}

        graph = Dag()
        graph.add(Task("optional", skipped))
        graph.add(Task("next", downstream, depends_on=("optional",)))
        record = graph.run(TaskContext(config=None, environ={}))
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(record.tasks[0].status, "skipped")
        self.assertFalse(record.tasks[0].blocked)
        self.assertEqual(record.tasks[1].status, "succeeded")

    def test_run_record_collects_manual_actions(self) -> None:
        graph = Dag().add(
            Task("refresh", lambda context: {"manual_action": "refresh Desktop"})
        )
        record = graph.run(TaskContext(config=None, environ={}))
        payload = record.to_dict()
        json.dumps(payload)
        self.assertEqual(
            payload["manual_actions"],
            [{"task": "refresh", "action": "refresh Desktop"}],
        )

    def test_observer_reports_live_progress(self) -> None:
        events = []

        def observer(event, name, result):
            events.append((event, name, None if result is None else result.status))

        graph = Dag().add(Task("step", lambda context: {"ok": True}))
        graph.run(TaskContext(config=None, environ={}), observer=observer)
        self.assertEqual(
            events,
            [("start", "step", None), ("finish", "step", "succeeded")],
        )


class PipelineCompositionTests(unittest.TestCase):
    def config(self, **overrides) -> PipelineConfig:
        values = {
            "project_root": PROJECT_ROOT,
            "workbook": None,
            "source_uri": None,
            "source_retrieved_at": None,
        }
        values.update(overrides)
        return PipelineConfig(**values)

    def test_default_graph_has_expected_order_and_dependencies(self) -> None:
        graph = build_dag()
        self.assertEqual(
            graph.order(),
            (
                "validate_inputs",
                "migrate",
                "ingest",
                "sql_gates",
                "dbt_build",
                "train_model",
                "powerbi_refresh",
            ),
        )
        deps = {task.name: task.depends_on for task in graph.tasks}
        self.assertEqual(deps["sql_gates"], ("ingest",))
        self.assertEqual(deps["powerbi_refresh"], ("dbt_build", "train_model"))

    def test_validate_config_reports_all_input_errors(self) -> None:
        missing = PROJECT_ROOT / "data" / "raw" / "does-not-exist.xlsx"
        errors = validate_config(
            self.config(
                workbook=missing,
                source_uri=" ",
                source_retrieved_at=datetime(2026, 1, 1),
            ),
            {},
        )
        joined = "\n".join(errors)
        self.assertIn("non-blank --source-uri", joined)
        self.assertIn("must include a timezone", joined)
        self.assertIn("workbook not found", joined)
        self.assertIn("set DATABASE_URL", joined)

    def test_source_arguments_require_a_workbook(self) -> None:
        errors = validate_config(
            self.config(source_uri="https://example.test", source_retrieved_at=None),
            {"DATABASE_URL": "postgresql://example"},
        )
        self.assertEqual(
            errors, ["--source-uri and --source-retrieved-at require --workbook"]
        )

    def test_run_without_workbook_skips_optional_tasks_and_records_manual_refresh(self) -> None:
        graph = build_dag(
            {
                "validate_inputs": lambda context: {"ok": True},
                "migrate": lambda context: {"ok": True},
                "sql_gates": lambda context: {"ok": True},
            }
        )
        record = graph.run(
            TaskContext(
                config=self.config(),
                environ={"DATABASE_URL": "postgresql://example"},
            )
        )
        by_name = {task.name: task for task in record.tasks}
        self.assertEqual(record.status, "succeeded")
        for name in ("ingest", "dbt_build", "train_model"):
            with self.subTest(task=name):
                self.assertEqual(by_name[name].status, "skipped")
                self.assertFalse(by_name[name].blocked)
        self.assertEqual(len(record.manual_actions), 1)
        self.assertTrue(record.manual_actions[0]["action"].startswith("Open powerbi/"))

    def test_optional_tasks_skip_cleanly_with_default_handlers(self) -> None:
        config = self.config()
        context = TaskContext(
            config=config, environ={"DATABASE_URL": "postgresql://example"}
        )
        self.assertEqual(tasks.ingest(context), {"skipped": True, "reason": "no workbook supplied"})
        self.assertTrue(tasks.dbt_build(context).get("skipped"))
        self.assertTrue(tasks.train_model(context).get("skipped"))
        self.assertIn("manual_action", tasks.powerbi_refresh(context))

    def test_sql_gates_task_records_per_gate_timings(self) -> None:
        context = TaskContext(
            config=self.config(), environ={"DATABASE_URL": "postgresql://example"}
        )

        def fake_checks(connection, checks, *, timings=None):
            if timings is not None:
                timings.append({"name": "a_check.sql", "elapsed_seconds": 0.25})
            return ("a_check.sql",)

        with patch(
            "retailpulse.pipeline_runner.connect_from_dsn",
            return_value=MagicMock(),
        ), patch(
            "retailpulse.pipeline_runner.run_sql_checks",
            side_effect=fake_checks,
        ):
            detail = tasks.sql_gates(context)

        self.assertEqual(detail["count"], 1)
        self.assertEqual(
            detail["timings"], [{"name": "a_check.sql", "elapsed_seconds": 0.25}]
        )

    def test_powerbi_evidence_must_contain_required_fields(self) -> None:
        with project_temp_directory() as directory:
            evidence = Path(directory) / "refresh.json"
            evidence.write_text(json.dumps({"refreshed_at": "2026-11-10T10:00:00+07:00"}), encoding="utf-8")
            context = TaskContext(
                config=self.config(powerbi_evidence=evidence),
                environ={"DATABASE_URL": "postgresql://example"},
            )
            with self.assertRaisesRegex(ValueError, "refreshed_at and source_file_id"):
                tasks.powerbi_refresh(context)

    def test_powerbi_evidence_is_verified_without_claiming_a_refresh(self) -> None:
        with project_temp_directory() as directory:
            evidence = Path(directory) / "refresh.json"
            evidence.write_text(
                json.dumps({"refreshed_at": "2026-11-10T10:00:00+07:00", "source_file_id": 1}),
                encoding="utf-8",
            )
            context = TaskContext(
                config=self.config(powerbi_evidence=evidence),
                environ={"DATABASE_URL": "postgresql://example"},
            )
            detail = tasks.powerbi_refresh(context)
            self.assertEqual(detail["source_file_id"], 1)
            self.assertIn("does not refresh Power BI", detail["note"])

    def test_cli_dry_run_needs_no_database(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "run_dag", PROJECT_ROOT / "scripts" / "run_dag.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = module.main(["--dry-run"])
        self.assertEqual(exit_code, 0)
        self.assertIn("validate_inputs -> migrate", output.getvalue())


if __name__ == "__main__":
    unittest.main()
