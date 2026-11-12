"""Contract tests for the model-evaluation persistence gate."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import unittest

from scripts.validate_model_evaluation import (
    EXPECTED_MODELS,
    INTERPRETATION,
    validate_rows,
)


def row(
    model_name: str,
    *,
    threshold: Decimal | None,
    brier: Decimal | None,
    precision: Decimal,
    note: str,
) -> dict:
    return {
        "source_file_id": 7,
        "model_name": model_name,
        "evaluated_at": datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc),
        "decision_threshold": threshold,
        "customer_count": 40,
        "positive_customer_count": 20,
        "positive_rate": Decimal("0.500000"),
        "precision_at_threshold": precision,
        "recall_at_threshold": Decimal("0.500000"),
        "pr_auc": Decimal("0.700000"),
        "roc_auc": Decimal("0.650000"),
        "lift_at_top_20_percent": Decimal("1.200000"),
        "brier_score": brier,
        "evaluation_note": note,
    }


def valid_rows() -> tuple[list[dict], list[dict]]:
    mart = [
        row(
            "logistic_regression_v1",
            threshold=Decimal("0.5000"),
            brier=Decimal("0.220000"),
            precision=Decimal("0.600000"),
            note="threshold 0.5",
        ),
        row(
            "log1p_logistic_regression_sensitivity",
            threshold=Decimal("0.5000"),
            brier=Decimal("0.210000"),
            precision=Decimal("0.580000"),
            note="Sensitivity only",
        ),
        row(
            "frequency_gte_2_rule",
            threshold=None,
            brier=None,
            precision=Decimal("0.550000"),
            note="frequency is at least 2",
        ),
    ]
    bi = [dict(item, interpretation=INTERPRETATION) for item in mart]
    return mart, bi


def valid_report() -> dict:
    return {
        "source_file_id": 7,
        "holdout_evaluation": {
            "logistic_regression": {
                "customer_count": 40,
                "positive_customer_count": 20,
                "positive_rate": 0.5,
                "precision_at_0_5": 0.6,
                "recall_at_0_5": 0.5,
                "pr_auc": 0.7,
                "roc_auc": 0.65,
                "lift_at_top_20_percent": 1.2,
                "brier_score": 0.22,
            },
            "log1p_logistic_regression_sensitivity": {
                "customer_count": 40,
                "positive_customer_count": 20,
                "positive_rate": 0.5,
                "precision_at_0_5": 0.58,
                "recall_at_0_5": 0.5,
                "pr_auc": 0.7,
                "roc_auc": 0.65,
                "lift_at_top_20_percent": 1.2,
                "brier_score": 0.21,
            },
            "frequency_gte_2_baseline": {
                "customer_count": 40,
                "positive_customer_count": 20,
                "positive_rate": 0.5,
                "precision_at_0_5": 0.55,
                "recall_at_0_5": 0.5,
                "pr_auc": 0.7,
                "roc_auc": 0.65,
                "lift_at_top_20_percent": 1.2,
            },
        },
    }


class ValidateModelEvaluationTests(unittest.TestCase):
    def test_valid_rows_and_report_pass(self) -> None:
        mart, bi = valid_rows()
        summary = validate_rows(mart, bi, 7, valid_report())
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["source_file_id"], 7)
        self.assertEqual(summary["models"], sorted(EXPECTED_MODELS))

    def test_missing_model_is_rejected(self) -> None:
        mart, bi = valid_rows()
        mart = [item for item in mart if item["model_name"] != "frequency_gte_2_rule"]
        bi = [item for item in bi if item["model_name"] != "frequency_gte_2_rule"]
        with self.assertRaisesRegex(ValueError, "unexpected evaluation models"):
            validate_rows(mart, bi, 7)

    def test_bi_interpretation_is_rejected(self) -> None:
        mart, bi = valid_rows()
        bi[0]["interpretation"] = "CAMPAIGN_RESPONSE"
        with self.assertRaisesRegex(ValueError, "interpretation must be"):
            validate_rows(mart, bi, 7)

    def test_invalid_positive_rate_is_rejected(self) -> None:
        mart, bi = valid_rows()
        mart[0]["positive_rate"] = Decimal("0.900000")
        bi[0]["positive_rate"] = Decimal("0.900000")
        with self.assertRaisesRegex(ValueError, "positive_rate disagrees with counts"):
            validate_rows(mart, bi, 7)

    def test_report_mismatch_is_rejected(self) -> None:
        mart, bi = valid_rows()
        report = deepcopy(valid_report())
        report["holdout_evaluation"]["logistic_regression"]["roc_auc"] = 0.9
        with self.assertRaisesRegex(ValueError, "roc_auc differs from report"):
            validate_rows(mart, bi, 7, report)

    def test_rule_must_not_have_threshold_or_brier(self) -> None:
        mart, bi = valid_rows()
        mart[2]["decision_threshold"] = Decimal("0.5000")
        bi[2]["decision_threshold"] = Decimal("0.5000")
        with self.assertRaisesRegex(ValueError, "must not have a threshold"):
            validate_rows(mart, bi, 7)


if __name__ == "__main__":
    unittest.main()
