"""Unit tests for persisting the repurchase backtest into the BI contract."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "train_repurchase_model", PROJECT_ROOT / "scripts" / "train_repurchase_model.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeCursor:
    def __init__(self, log: list[tuple[str, tuple]]) -> None:
        self._log = log

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def execute(self, sql: str, params: tuple) -> None:
        self._log.append((sql, params))


class FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []
        self.commits = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.executed)

    def commit(self) -> None:
        self.commits += 1


def report_fixture() -> dict:
    return {
        "source_file_id": 1,
        "model_name": "logistic_regression_v1",
        "holdout_evaluation": {
            "logistic_regression": {
                "customer_count": 2784,
                "positive_customer_count": 1722,
                "positive_rate": 0.6185,
                "precision_at_0_5": 0.8502,
                "recall_at_0_5": 0.4286,
                "pr_auc": 0.8162,
                "roc_auc": 0.7152,
                "lift_at_top_20_percent": 1.4629,
                "brier_score": 0.2286,
            },
            "log1p_logistic_regression_sensitivity": {
                "customer_count": 2784,
                "positive_customer_count": 1722,
                "positive_rate": 0.6185,
                "precision_at_0_5": 0.8116,
                "recall_at_0_5": 0.5180,
                "pr_auc": 0.8219,
                "roc_auc": 0.7245,
                "lift_at_top_20_percent": 1.4629,
                "brier_score": 0.2259,
            },
            "frequency_gte_2_baseline": {
                "customer_count": 2784,
                "positive_customer_count": 1722,
                "positive_rate": 0.6185,
                "precision_at_0_5": 0.7526,
                "recall_at_0_5": 0.6713,
                "pr_auc": 0.7789,
                "roc_auc": 0.7020,
                "lift_at_top_20_percent": 1.4513,
            },
        },
    }


class PersistEvaluationTests(unittest.TestCase):
    def test_all_evaluations_are_upserted_in_one_transaction(self) -> None:
        connection = FakeConnection()
        MODULE.persist_evaluation(connection, report_fixture())

        self.assertEqual(connection.commits, 1)
        self.assertEqual(len(connection.executed), 3)
        for sql, _ in connection.executed:
            self.assertIn("insert into mart.repurchase_model_evaluation", sql.lower())
            self.assertIn("on conflict (source_file_id, model_name) do update", sql)

        model_params = connection.executed[0][1]
        sensitivity_params = connection.executed[1][1]
        baseline_params = connection.executed[2][1]
        self.assertEqual(model_params[0], 1)
        self.assertEqual(model_params[1], "logistic_regression_v1")
        self.assertEqual(model_params[2], 0.5)
        self.assertEqual(sensitivity_params[1], "log1p_logistic_regression_sensitivity")
        self.assertEqual(sensitivity_params[2], 0.5)
        self.assertEqual(sensitivity_params[6], 0.8116)
        self.assertEqual(baseline_params[1], "frequency_gte_2_rule")
        self.assertIsNone(baseline_params[2])
        self.assertEqual(baseline_params[6], 0.7526)
        self.assertIsNone(baseline_params[-2])

    def test_note_keeps_the_backtest_interpretation(self) -> None:
        connection = FakeConnection()
        MODULE.persist_evaluation(connection, report_fixture())
        notes = [params[-1] for _, params in connection.executed]
        self.assertIn("threshold 0.5", notes[0])
        self.assertIn("Sensitivity only", notes[1])
        self.assertIn("frequency is at least 2", notes[2])


if __name__ == "__main__":
    unittest.main()
