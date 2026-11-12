"""Validate that a trained repurchase evaluation is readable through ``bi``.

This is the CI gate for the model path: it proves that a synthetic source can
produce a leak-safe label dataset, train and persist evaluation metrics, and
expose the same rows through the read-only BI view. It intentionally does not
claim that synthetic metrics describe the published Online Retail II snapshot.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any

from retailpulse.pipeline_runner import connect_from_dsn


EXPECTED_MODELS = {
    "logistic_regression_v1",
    "log1p_logistic_regression_sensitivity",
    "frequency_gte_2_rule",
}
INTERPRETATION = "HISTORICAL_TEMPORAL_BACKTEST_NOT_CAMPAIGN_RESPONSE"
METRIC_FIELDS = (
    "customer_count",
    "positive_customer_count",
    "positive_rate",
    "precision_at_threshold",
    "recall_at_threshold",
    "pr_auc",
    "roc_auc",
    "lift_at_top_20_percent",
    "brier_score",
)
REPORT_METRIC_FIELDS = {
    "customer_count": "customer_count",
    "positive_customer_count": "positive_customer_count",
    "positive_rate": "positive_rate",
    "precision_at_threshold": "precision_at_0_5",
    "recall_at_threshold": "recall_at_0_5",
    "pr_auc": "pr_auc",
    "roc_auc": "roc_auc",
    "lift_at_top_20_percent": "lift_at_top_20_percent",
    "brier_score": "brier_score",
}
REPORT_MODELS = {
    "logistic_regression_v1": "logistic_regression",
    "log1p_logistic_regression_sensitivity": "log1p_logistic_regression_sensitivity",
    "frequency_gte_2_rule": "frequency_gte_2_baseline",
}


def _number(value: Any) -> float | None:
    return None if value is None else float(value)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_rows(
    mart_rows: list[dict[str, Any]],
    bi_rows: list[dict[str, Any]],
    source_file_id: int | None = None,
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate persisted evaluation rows and optional JSON report agreement."""

    _require(bool(mart_rows), "mart.repurchase_model_evaluation has no rows")
    _require(bool(bi_rows), "bi.repurchase_model_evaluation has no rows")

    source_ids = {int(row["source_file_id"]) for row in mart_rows}
    _require(len(source_ids) == 1, "evaluation rows must belong to exactly one source file")
    actual_source_id = next(iter(source_ids))
    if source_file_id is not None:
        _require(
            actual_source_id == source_file_id,
            f"evaluation source_file_id {actual_source_id} does not match requested {source_file_id}",
        )

    by_model = {str(row["model_name"]): row for row in mart_rows}
    _require(
        set(by_model) == EXPECTED_MODELS,
        f"unexpected evaluation models: {sorted(set(by_model) ^ EXPECTED_MODELS)}",
    )
    bi_by_model = {str(row["model_name"]): row for row in bi_rows}
    _require(
        set(bi_by_model) == EXPECTED_MODELS,
        f"BI view is missing evaluation models: {sorted(set(bi_by_model) ^ EXPECTED_MODELS)}",
    )

    for model_name in sorted(EXPECTED_MODELS):
        row = by_model[model_name]
        bi_row = bi_by_model[model_name]
        _require(
            int(row["source_file_id"]) == int(bi_row["source_file_id"]),
            f"{model_name}: BI source_file_id differs from mart",
        )
        _require(
            bi_row.get("interpretation") == INTERPRETATION,
            f"{model_name}: BI interpretation must be {INTERPRETATION}",
        )
        for field in ("evaluated_at", "decision_threshold", *METRIC_FIELDS, "evaluation_note"):
            _require(
                row[field] == bi_row[field],
                f"{model_name}: BI field {field} differs from mart",
            )

        customer_count = int(row["customer_count"])
        positive_count = int(row["positive_customer_count"])
        _require(customer_count > 0, f"{model_name}: customer_count must be positive")
        _require(
            0 <= positive_count <= customer_count,
            f"{model_name}: positive_customer_count is out of range",
        )
        positive_rate = _number(row["positive_rate"])
        _require(positive_rate is not None, f"{model_name}: positive_rate is required")
        _require(
            abs(positive_rate - positive_count / customer_count) <= 1e-6,
            f"{model_name}: positive_rate disagrees with counts",
        )
        for field in (
            "precision_at_threshold",
            "recall_at_threshold",
            "pr_auc",
            "roc_auc",
        ):
            value = _number(row[field])
            _require(
                value is not None and 0 <= value <= 1,
                f"{model_name}: {field} must be between 0 and 1",
            )
        lift = _number(row["lift_at_top_20_percent"])
        _require(lift is not None and lift >= 0, f"{model_name}: lift must be non-negative")
        threshold = _number(row["decision_threshold"])
        if model_name == "frequency_gte_2_rule":
            _require(threshold is None, "frequency_gte_2_rule must not have a threshold")
            _require(row["brier_score"] is None, "frequency_gte_2_rule must not have a Brier score")
        else:
            _require(
                threshold is not None and 0 <= threshold <= 1,
                f"{model_name}: decision_threshold must be between 0 and 1",
            )
            _require(
                _number(row["brier_score"]) is not None,
                f"{model_name}: Brier score is required for a probabilistic model",
            )
        _require(
            isinstance(row["evaluation_note"], str) and bool(row["evaluation_note"].strip()),
            f"{model_name}: evaluation_note must not be blank",
        )

    if report is not None:
        _require(
            int(report["source_file_id"]) == actual_source_id,
            "report source_file_id differs from persisted rows",
        )
        holdout = report["holdout_evaluation"]
        for persisted_name, report_name in REPORT_MODELS.items():
            report_metrics = holdout[report_name]
            row = by_model[persisted_name]
            for persisted_field, report_field in REPORT_METRIC_FIELDS.items():
                expected = report_metrics.get(report_field)
                actual = row[persisted_field]
                if expected is None or actual is None:
                    _require(
                        expected is None and actual is None,
                        f"{persisted_name}: {persisted_field} presence differs from report",
                    )
                    continue
                _require(
                    abs(float(actual) - float(expected)) <= 1e-6,
                    f"{persisted_name}: {persisted_field} differs from report",
                )

    return {
        "status": "ok",
        "source_file_id": actual_source_id,
        "models": sorted(EXPECTED_MODELS),
        "row_count": len(mart_rows),
        "bi_row_count": len(bi_rows),
    }


def _load_rows(connection: Any, relation: str, with_interpretation: bool) -> list[dict[str, Any]]:
    columns = (
        "source_file_id, model_name, evaluated_at, decision_threshold, "
        "customer_count, positive_customer_count, positive_rate, "
        "precision_at_threshold, recall_at_threshold, pr_auc, roc_auc, "
        "lift_at_top_20_percent, brier_score, evaluation_note"
    )
    if with_interpretation:
        columns += ", interpretation"
    with connection.cursor() as cursor:
        cursor.execute(f"select {columns} from {relation} order by model_name")
        names = [description.name for description in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn-env", default="DATABASE_URL")
    parser.add_argument("--source-file-id", type=int)
    parser.add_argument("--report-json", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dsn = os.environ.get(args.dsn_env)
    if not dsn:
        raise SystemExit(f"Set {args.dsn_env} before connecting to PostgreSQL.")
    report = None
    if args.report_json is not None:
        report = json.loads(args.report_json.read_text(encoding="utf-8"))
    connection = connect_from_dsn(dsn)
    try:
        mart_rows = _load_rows(connection, "mart.repurchase_model_evaluation", False)
        bi_rows = _load_rows(connection, "bi.repurchase_model_evaluation", True)
    finally:
        connection.close()  # type: ignore[attr-defined]
    if args.source_file_id is not None:
        mart_rows = [row for row in mart_rows if int(row["source_file_id"]) == args.source_file_id]
        bi_rows = [row for row in bi_rows if int(row["source_file_id"]) == args.source_file_id]
    summary = validate_rows(mart_rows, bi_rows, args.source_file_id, report)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
