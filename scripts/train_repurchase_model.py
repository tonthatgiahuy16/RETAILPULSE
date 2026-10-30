"""Train a leakage-bounded Logistic Regression repurchase model and write JSON."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

from retailpulse.modeling.repurchase import (
    PREDICTION_DAYS,
    OBSERVATION_DAYS,
    RepurchaseExample,
    assert_published_holdout_matches,
    rolling_prediction_starts,
    split_temporally,
)
from retailpulse.pipeline_runner import connect_from_dsn


FEATURE_NAMES = ("observation_recency_days", "observation_frequency", "observation_monetary_amount")
LIFT_FRACTION = 0.20


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn-env", default="DATABASE_URL")
    parser.add_argument("--source-file-id", type=int)
    parser.add_argument("--output", type=Path, default=Path("data/processed/repurchase_model_evaluation.json"))
    return parser.parse_args()


def _source_bounds(connection: Any, source_file_id: int | None) -> tuple[int, Any, Any, Any]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select source_file_id, min(observation_start_date), min(prediction_start_date), min(prediction_end_date)
            from mart.customer_repurchase_label_dataset group by source_file_id order by source_file_id
            """
        )
        rows = cursor.fetchall()
    if source_file_id is not None:
        rows = [row for row in rows if int(row[0]) == source_file_id]
    if len(rows) != 1:
        raise ValueError("Specify one --source-file-id with a published repurchase label dataset")
    return int(rows[0][0]), rows[0][1], rows[0][2], rows[0][3]


def _examples(connection: Any, source_file_id: int, starts: tuple[Any, ...]) -> tuple[RepurchaseExample, ...]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            with anchors as (select unnest(%s::date[]) as prediction_start_date),
            observation as (
                select a.prediction_start_date, e.customer_id,
                       (a.prediction_start_date - max(e.event_at)::date)::integer as recency,
                       count(*)::integer as frequency,
                       sum(e.gross_purchase_amount)::double precision as monetary
                from anchors a join mart.customer_purchase_event e
                  on e.source_file_id = %s
                 and e.event_at >= a.prediction_start_date - interval '180 days'
                 and e.event_at < a.prediction_start_date
                group by a.prediction_start_date, e.customer_id
            )
            select o.customer_id, o.prediction_start_date, o.recency, o.frequency, o.monetary,
                   exists (
                     select 1 from mart.customer_purchase_event f
                     where f.source_file_id = %s and f.customer_id = o.customer_id
                       and f.event_at >= o.prediction_start_date
                       and f.event_at < o.prediction_start_date + interval '90 days'
                   )
            from observation o order by o.prediction_start_date, o.customer_id
            """,
            (list(starts), source_file_id, source_file_id),
        )
        rows = cursor.fetchall()
    return tuple(
        RepurchaseExample(str(customer), start, int(recency), int(frequency), float(monetary), bool(label))
        for customer, start, recency, frequency, monetary, label in rows
    )


def _published_holdout(connection: Any, source_file_id: int) -> list[tuple[str, int, int, float, bool]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select customer_id, observation_recency_days, observation_frequency,
                   observation_monetary_amount::double precision, repurchased_in_prediction_window
            from mart.customer_repurchase_label_dataset where source_file_id = %s order by customer_id
            """,
            (source_file_id,),
        )
        return [(str(c), int(r), int(f), float(m), bool(y)) for c, r, f, m, y in cursor.fetchall()]


def _metrics(examples: tuple[RepurchaseExample, ...], scores: list[float], labels: list[int], predictions: list[int], calibration: bool) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score, brier_score_loss, precision_score, recall_score, roc_auc_score

    if len(set(labels)) != 2:
        raise ValueError("Holdout must contain both classes for PR-AUC and ROC-AUC")
    top_count = max(1, math.ceil(len(labels) * LIFT_FRACTION))
    ranked = sorted(zip(scores, labels, examples, strict=True), key=lambda item: (-item[0], item[2].customer_id))
    positive_rate = sum(labels) / len(labels)
    result: dict[str, Any] = {
        "customer_count": len(labels), "positive_customer_count": sum(labels), "positive_rate": positive_rate,
        "pr_auc": average_precision_score(labels, scores), "roc_auc": roc_auc_score(labels, scores),
        "precision_at_0_5": precision_score(labels, predictions, zero_division=0),
        "recall_at_0_5": recall_score(labels, predictions, zero_division=0),
        "lift_at_top_20_percent": sum(item[1] for item in ranked[:top_count]) / top_count / positive_rate,
    }
    if calibration:
        result["brier_score"] = brier_score_loss(labels, scores)
        bins = []
        for index in range(5):
            low, high = index / 5, (index + 1) / 5
            members = [i for i, score in enumerate(scores) if low <= score < high or (index == 4 and score == high)]
            if members:
                bins.append({"lower_bound": low, "upper_bound": high, "customer_count": len(members), "mean_predicted_probability": sum(scores[i] for i in members) / len(members), "actual_repurchase_rate": sum(labels[i] for i in members) / len(members)})
        result["calibration_bins"] = bins
    return result


def train_and_report(connection: Any, requested_source_file_id: int | None) -> dict[str, Any]:
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
    except ModuleNotFoundError as error:
        raise RuntimeError("Install model dependencies with: pip install -e '.[model]'") from error

    source_file_id, observation_start, holdout_start, prediction_end = _source_bounds(connection, requested_source_file_id)
    with connection.cursor() as cursor:
        cursor.execute("select min(event_at)::date from mart.customer_purchase_event where source_file_id = %s", (source_file_id,))
        first_event = cursor.fetchone()[0]
    starts = rolling_prediction_starts(first_event, holdout_start)
    train, holdout = split_temporally(_examples(connection, source_file_id, starts), holdout_start)
    assert_published_holdout_matches(holdout, _published_holdout(connection, source_file_id))
    features = lambda rows: [[float(x.observation_recency_days), float(x.observation_frequency), x.observation_monetary_amount] for x in rows]
    labels = lambda rows: [int(x.repurchased_in_prediction_window) for x in rows]
    model = Pipeline([("scale", StandardScaler()), ("logistic_regression", LogisticRegression(max_iter=1000, solver="lbfgs"))])
    model.fit(features(train), labels(train))
    holdout_labels = labels(holdout)
    probabilities = [float(value) for value in model.predict_proba(features(holdout))[:, 1]]
    baseline_scores = [float(x.observation_frequency) for x in holdout]
    return {
        "model_name": "logistic_regression_v1", "source_file_id": source_file_id, "feature_names": list(FEATURE_NAMES),
        "temporal_contract": {"observation_days": OBSERVATION_DAYS, "prediction_days": PREDICTION_DAYS, "train_prediction_start_dates": [x.isoformat() for x in starts[:-1]], "holdout_prediction_start_date": holdout_start.isoformat(), "holdout_prediction_end_date": prediction_end.isoformat(), "published_label_observation_start_date": observation_start.isoformat(), "holdout_exactly_matches_published_label_dataset": True},
        "training_example_count": len(train),
        "holdout_evaluation": {
            "logistic_regression": _metrics(holdout, probabilities, holdout_labels, [int(x >= .5) for x in probabilities], True),
            "frequency_gte_2_baseline": _metrics(holdout, baseline_scores, holdout_labels, [int(x.observation_frequency >= 2) for x in holdout], False),
        },
        "limits": ["Historical temporal backtest, not campaign response, uplift, or ROI.", "No propensity scores are written to decision tables."],
    }


def main() -> None:
    args = parse_args()
    dsn = os.environ.get(args.dsn_env)
    if not dsn:
        raise SystemExit(f"Set {args.dsn_env} before connecting to PostgreSQL.")
    connection = connect_from_dsn(dsn)
    try:
        report = train_and_report(connection, args.source_file_id)
    finally:
        connection.close()  # type: ignore[attr-defined]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"report_path": str(args.output), "model_name": report["model_name"]}))


if __name__ == "__main__":
    main()
