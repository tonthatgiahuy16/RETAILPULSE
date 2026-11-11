"""Regression and contract tests for the dashboard brief generator (scripts/build_dashboard.py)."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from scripts.build_dashboard import (
    DEFAULT_EVAL_PATH,
    DEFAULT_RUN_PATH,
    DEFAULT_TEMPLATE_PATH,
    build_dashboard,
    format_timezone_offset,
    parse_artifact_datetime,
    validate_and_extract_budget_data,
)


class BuildDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.temp_path = Path(self.temp_dir.name)

    def test_default_build_succeeds_from_repo_artifacts(self) -> None:
        output_file = self.temp_path / "index.html"
        summary = build_dashboard(output_path=output_file)
        self.assertEqual(summary["status"], "success")
        self.assertEqual(summary["run_id"], "8c0fc3c3e9ca")
        self.assertEqual(summary["snapshot_id"], 1)
        self.assertTrue(output_file.exists())
        content = output_file.read_text(encoding="utf-8")
        self.assertIn("0.7152", content)
        self.assertIn("8c0fc3c3e9ca", content)
        self.assertNotIn("{{", content)

    def test_timezone_offset_formatting_handles_various_offsets(self) -> None:
        dt_utc = datetime.fromisoformat("2026-11-11T16:04:25+00:00")
        self.assertEqual(format_timezone_offset(dt_utc), "UTC+00:00")

        dt_vn = datetime.fromisoformat("2026-11-11T23:04:25+07:00")
        self.assertEqual(format_timezone_offset(dt_vn), "UTC+07:00")

        dt_ny = datetime.fromisoformat("2026-11-11T11:04:25-05:00")
        self.assertEqual(format_timezone_offset(dt_ny), "UTC-05:00")

        _, date_str, formatted = parse_artifact_datetime("2026-11-11T23:04:25+07:00")
        self.assertEqual(date_str, "2026-11-11")
        self.assertEqual(formatted, "2026-11-11 23:04:25 (UTC+07:00)")

    def test_rejects_missing_budget_fractions(self) -> None:
        eval_payload = json.loads(DEFAULT_EVAL_PATH.read_text(encoding="utf-8"))
        # Remove K=0.30
        eval_payload["decision_comparison"]["frequency_business"]["metrics"] = [
            m for m in eval_payload["decision_comparison"]["frequency_business"]["metrics"]
            if round(m["budget_fraction"], 2) != 0.30
        ]
        bad_eval_file = self.temp_path / "bad_eval.json"
        bad_eval_file.write_text(json.dumps(eval_payload), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "Missing budget fraction K=0.3"):
            build_dashboard(eval_path=bad_eval_file, output_path=self.temp_path / "out.html")

    def test_rejects_snapshot_mismatch_between_run_and_model(self) -> None:
        eval_payload = json.loads(DEFAULT_EVAL_PATH.read_text(encoding="utf-8"))
        eval_payload["source_file_id"] = 999
        bad_eval_file = self.temp_path / "mismatch_eval.json"
        bad_eval_file.write_text(json.dumps(eval_payload), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "Snapshot ID mismatch"):
            build_dashboard(eval_path=bad_eval_file, output_path=self.temp_path / "out.html")


if __name__ == "__main__":
    unittest.main()
