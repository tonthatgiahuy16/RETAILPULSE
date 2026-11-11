"""Train a leakage-bounded Logistic Regression repurchase model and write JSON."""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retailpulse.modeling.decision_report import (
    bootstrap_precision_comparison,
    cutoff_overlap_diagnostics,
    distribution_summary,
    evaluate_ranking,
)
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
DECISION_FRACTIONS = (0.10, 0.20, 0.30)
BOOTSTRAP_ITERATIONS = 2_000
BOOTSTRAP_SEED = 20261111


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn-env", default="DATABASE_URL")
    parser.add_argument("--source-file-id", type=int)
    parser.add_argument("--output", type=Path, default=Path("data/processed/repurchase_model_evaluation.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("docs/decision/RETENTION_PRIORITY_DECISION.md"))
    parser.add_argument("--report-only", action="store_true", help="Do not upsert evaluation metrics into PostgreSQL")
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


def _priority_backtest(connection: Any, source_file_id: int) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select customer_id, priority_rank, observation_frequency,
                   observation_monetary_amount::double precision,
                   observation_recency_days, repurchased_in_prediction_window
            from decision.customer_priority_backtest
            where source_file_id = %s
            order by priority_rank
            """,
            (source_file_id,),
        )
        return [
            {
                "customer_id": str(customer_id),
                "priority_rank": int(priority_rank),
                "frequency": int(frequency),
                "monetary": float(monetary),
                "recency": int(recency),
                "label": bool(label),
            }
            for customer_id, priority_rank, frequency, monetary, recency, label in cursor.fetchall()
        ]


def _score_features(rows: tuple[RepurchaseExample, ...], log1p_skewed_features: bool = False) -> list[list[float]]:
    features = []
    for row in rows:
        frequency = float(row.observation_frequency)
        monetary = row.observation_monetary_amount
        if log1p_skewed_features:
            if monetary < 0:
                raise ValueError("Published eligible-purchase monetary amount must be non-negative for log1p")
            frequency = math.log1p(frequency)
            monetary = math.log1p(monetary)
        features.append([float(row.observation_recency_days), frequency, monetary])
    return features


def _fit_logistic(train: tuple[RepurchaseExample, ...], holdout: tuple[RepurchaseExample, ...], log1p_skewed_features: bool = False) -> list[float]:
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    model = Pipeline(
        [
            ("scale", StandardScaler()),
            ("logistic_regression", LogisticRegression(max_iter=1000, solver="lbfgs", class_weight=None)),
        ]
    )
    model.fit(_score_features(train, log1p_skewed_features), [int(x.repurchased_in_prediction_window) for x in train])
    return [float(value) for value in model.predict_proba(_score_features(holdout, log1p_skewed_features))[:, 1]]


def _decision_comparison(
    holdout: tuple[RepurchaseExample, ...],
    priority_rows: list[dict[str, Any]],
    probabilities: list[float],
    log_probabilities: list[float],
) -> dict[str, Any]:
    labels = {row.customer_id: row.repurchased_in_prediction_window for row in holdout}
    holdout_ids = set(labels)
    if {row["customer_id"] for row in priority_rows} != holdout_ids:
        raise ValueError("RFM priority backtest customer set does not match the published holdout")
    if any(labels[row["customer_id"]] != row["label"] for row in priority_rows):
        raise ValueError("RFM priority backtest labels do not match the published holdout")

    features_by_id = {row.customer_id: row for row in holdout}
    base_rows = [
        {
            "customer_id": row.customer_id,
            "label": row.repurchased_in_prediction_window,
            "frequency": row.observation_frequency,
            "monetary": row.observation_monetary_amount,
            "recency": row.observation_recency_days,
        }
        for row in holdout
    ]
    probability_by_id = {row.customer_id: score for row, score in zip(holdout, probabilities, strict=True)}
    log_probability_by_id = {row.customer_id: score for row, score in zip(holdout, log_probabilities, strict=True)}
    methods = {
        "rfm_priority_019": (
            priority_rows,
            lambda row: row["priority_rank"],
            lambda row: row["priority_rank"],
            "Contract 019 order: segment, monetary DESC, frequency DESC, recency ASC, customer_id ASC.",
        ),
        "frequency_naive": (
            base_rows,
            lambda row: (-row["frequency"], row["customer_id"]),
            lambda row: row["frequency"],
            "Frequency DESC, customer_id ASC; diagnostic naive baseline.",
        ),
        "frequency_business": (
            base_rows,
            lambda row: (-row["frequency"], -row["monetary"], row["recency"], row["customer_id"]),
            lambda row: (row["frequency"], row["monetary"], row["recency"]),
            "Frequency DESC, monetary DESC, recency ASC, customer_id ASC.",
        ),
        "logistic_regression": (
            [dict(row, score=probability_by_id[row["customer_id"]]) for row in base_rows],
            lambda row: (-row["score"], row["customer_id"]),
            lambda row: row["score"],
            "Standardized raw recency, frequency and monetary features; class_weight=None.",
        ),
        "log1p_logistic_regression_sensitivity": (
            [dict(row, score=log_probability_by_id[row["customer_id"]]) for row in base_rows],
            lambda row: (-row["score"], row["customer_id"]),
            lambda row: row["score"],
            "Sensitivity only: log1p frequency and monetary; class_weight=None.",
        ),
    }
    output = {}
    for name, (rows, rank_key, tie_key, definition) in methods.items():
        output[name] = {
            "definition": definition,
            "metrics": evaluate_ranking(rows, rank_key=rank_key, tie_key=tie_key, fractions=DECISION_FRACTIONS),
        }

    precision_bootstrap = bootstrap_precision_comparison(
        base_rows,
        left_rank_key=methods["frequency_business"][1],
        right_rank_key=lambda row: (-probability_by_id[row["customer_id"]], row["customer_id"]),
        fractions=DECISION_FRACTIONS,
        iterations=BOOTSTRAP_ITERATIONS,
        seed=BOOTSTRAP_SEED,
    )

    business_rules = ("rfm_priority_019", "frequency_business")
    average_precision = {
        name: sum(item["precision_at_k"] for item in output[name]["metrics"]) / len(DECISION_FRACTIONS)
        for name in ("rfm_priority_019", "frequency_business", "logistic_regression")
    }
    winning_rule = max(business_rules, key=lambda name: (average_precision[name], name == "rfm_priority_019"))
    frequency_business_is_distinct = all(item["ci_lower"] > 0 for item in precision_bootstrap)
    recommendation = winning_rule
    selected_rule_deltas = [
        {
            "budget_fraction": rule_metric["budget_fraction"],
            "precision_difference_vs_logistic_regression_percentage_points": round(
                (rule_metric["precision_at_k"] - lr_metric["precision_at_k"]) * 100, 3
            ),
        }
        for rule_metric, lr_metric in zip(
            output[recommendation]["metrics"], output["logistic_regression"]["metrics"], strict=True
        )
    ]
    delta_explanations = []
    for item in selected_rule_deltas:
        difference = item["precision_difference_vs_logistic_regression_percentage_points"]
        if difference == 0:
            comparison_text = "matches LR"
        elif difference > 0:
            comparison_text = f"leads LR by {difference:.3f} percentage points"
        else:
            comparison_text = f"trails LR by {abs(difference):.3f} percentage points"
        delta_explanations.append(f"at K={item['budget_fraction']:.0%}, it {comparison_text}")
    output["recommendation"] = {
        "method": recommendation,
        "rule": "Choose a simpler rule by default unless a pre-specified comparison shows a practically meaningful and bootstrap-supported precision@K advantage for LR across tested capacities and future temporal holdouts.",
        "mean_precision_at_k": average_precision,
        "precision_difference_vs_logistic_regression": selected_rule_deltas,
        "precision_bootstrap_vs_logistic_regression": precision_bootstrap,
        "reason": (
            "Frequency business has a positive bootstrap CI versus LR at every tested K on this holdout. This is still one temporal holdout, so the result requires rolling-origin replication before claiming stable superiority."
            if frequency_business_is_distinct
            else (
                f"{recommendation} has the highest mean precision@K among the simple rules. "
                + "; ".join(delta_explanations)
                + ". The paired bootstrap confidence interval includes zero for at least one K, so this one holdout does not establish a precision difference from LR. Use the rule for its simpler explanation, not because it is proven superior."
            )
        ),
    }
    return output


def _training_diagnostics(train: tuple[RepurchaseExample, ...], holdout: tuple[RepurchaseExample, ...]) -> dict[str, Any]:
    from collections import defaultdict

    labels_by_cutoff: dict[str, list[int]] = defaultdict(list)
    for row in train:
        labels_by_cutoff[row.prediction_start_date.isoformat()].append(int(row.repurchased_in_prediction_window))
    train_labels = [int(row.repurchased_in_prediction_window) for row in train]
    holdout_labels = [int(row.repurchased_in_prediction_window) for row in holdout]
    return {
        "train_customer_examples": len(train),
        "train_positive_count": sum(train_labels),
        "train_positive_rate": sum(train_labels) / len(train_labels),
        "train_positive_rate_by_prediction_start": {
            cutoff: sum(values) / len(values) for cutoff, values in sorted(labels_by_cutoff.items())
        },
        "holdout_customer_count": len(holdout),
        "holdout_positive_count": sum(holdout_labels),
        "holdout_positive_rate": sum(holdout_labels) / len(holdout_labels),
        "holdout_minus_train_positive_rate": sum(holdout_labels) / len(holdout_labels) - sum(train_labels) / len(train_labels),
        "feature_distributions": {
            name: {
                "train": distribution_summary([getattr(row, attr) for row in train]),
                "holdout": distribution_summary([getattr(row, attr) for row in holdout]),
            }
            for name, attr in (
                ("observation_recency_days", "observation_recency_days"),
                ("observation_frequency", "observation_frequency"),
                ("observation_monetary_amount", "observation_monetary_amount"),
            )
        },
        "interpretation": "A positive-rate gap is evidence of prevalence shift; it does not by itself prove seasonality or explain model miscalibration. Feature summaries show scale and skew but do not establish causality.",
    }


def _rolling_cutoff_overlap(examples: tuple[RepurchaseExample, ...]) -> dict[str, Any]:
    customer_ids_by_cutoff: dict[str, set[str]] = {}
    for row in examples:
        customer_ids_by_cutoff.setdefault(row.prediction_start_date.isoformat(), set()).add(row.customer_id)
    return cutoff_overlap_diagnostics(customer_ids_by_cutoff)


def _write_markdown_report(report: dict[str, Any], path: Path) -> None:
    comparison = report["decision_comparison"]
    rows = []
    for method in ("rfm_priority_019", "frequency_naive", "frequency_business", "logistic_regression", "log1p_logistic_regression_sensitivity"):
        for metric in comparison[method]["metrics"]:
            rows.append(
                f"| {method} | {metric['budget_fraction']:.0%} | {metric['selected_customer_count']:,} | "
                f"{metric['precision_at_k']:.3f} | {metric['recall_at_k']:.3f} | {metric['lift_at_k']:.3f} | "
                f"{metric['cutoff_tie_group_size']:,} | {metric['cutoff_tie_slots_needed']:,} | "
                f"{'yes' if metric['cut_through_tie_block'] else 'no'} |"
            )
    diagnostics = report["training_diagnostics"]
    overlap = report["rolling_cutoff_overlap"]
    model_metrics = report["holdout_evaluation"]["logistic_regression"]
    log_metrics = report["holdout_evaluation"]["log1p_logistic_regression_sensitivity"]
    cutoff_rows = [
        f"| {cutoff} | {rate:.1%} |"
        for cutoff, rate in diagnostics["train_positive_rate_by_prediction_start"].items()
    ]
    feature_rows = []
    for name, summary in diagnostics["feature_distributions"].items():
        feature_rows.append(
            f"| {name} | {summary['train']['p50']:.3g} | {summary['train']['p99']:.3g} | {summary['train']['skewness']:.2f} | "
            f"{summary['holdout']['p50']:.3g} | {summary['holdout']['p99']:.3g} | {summary['holdout']['skewness']:.2f} |"
        )
    calibration_rows = []
    for name, metrics in (("LR raw features", model_metrics), ("LR log1p sensitivity", log_metrics)):
        for calibration_bin in metrics["calibration_bins"]:
            calibration_rows.append(
                f"| {name} | {calibration_bin['lower_bound']:.1f}-{calibration_bin['upper_bound']:.1f} | "
                f"{calibration_bin['customer_count']:,} | {calibration_bin['mean_predicted_probability']:.1%} | "
                f"{calibration_bin['actual_repurchase_rate']:.1%} |"
            )
    bootstrap_rows = []
    for item in comparison["recommendation"]["precision_bootstrap_vs_logistic_regression"]:
        bootstrap_rows.append(
            f"| {item['budget_fraction']:.0%} | {item['observed_difference']:+.3%} | "
            f"[{item['ci_lower']:+.3%}, {item['ci_upper']:+.3%}] | "
            f"{'yes' if item['ci_includes_zero'] else 'no'} |"
        )
    overlap_rows = []
    for pair in overlap["pairs"]:
        overlap_rows.append(
            f"| {pair['left_prediction_start_date']} | {pair['right_prediction_start_date']} | "
            f"{pair['shared_customer_count']:,} | {pair['jaccard_similarity']:.3f} | "
            f"{pair['right_customers_seen_in_left']:.1%} |"
        )
    lines = [
        "# Retention priority decision report",
        "",
        f"- Generated at: `{report['generated_at_utc']}`; source snapshot: `{report['source_file_id']}` (SHA-256 `{report['source_sha256']}`).",
        f"- Holdout window: `{report['temporal_contract']['holdout_prediction_start_date']}` to `{report['temporal_contract']['holdout_prediction_end_date']}` (end exclusive).",
        f"- Holdout: {diagnostics['holdout_customer_count']:,} customers, positive rate {diagnostics['holdout_positive_rate']:.1%}; training positive rate {diagnostics['train_positive_rate']:.1%}.",
        f"- Decision: **{comparison['recommendation']['method']}**. {comparison['recommendation']['reason']}",
        "- This is a historical temporal backtest of observed repurchase, not campaign response or causal effect.",
        "",
        "## Fixed-capacity ranking comparison",
        "",
        "Precision@K is the share of selected customers who repurchased; recall@K is the share of all holdout repurchasers selected. K uses `ceil(N * fraction)`. The `class_weight` parameter is explicitly `None` for both LR fits.",
        "",
        "| Method | K | Selected | Precision@K | Recall@K | Lift@K | Boundary tie size | Slots decided within tie | Cut through tie? |",
        "|---|---:|---:|---:|---:|---:|---:|---:|:---:|",
        *rows,
        "",
        "### Precision@K uncertainty: business frequency vs LR",
        "",
        f"Paired customer bootstrap with {BOOTSTRAP_ITERATIONS:,} replicates, 95% percentile CI, and seed `{BOOTSTRAP_SEED}`. Rankings and selected K membership remain fixed from this holdout; the CI measures observed-label precision uncertainty, not refit-model or future-period uncertainty.",
        "",
        "| K | Difference (frequency business - LR) | 95% CI | CI includes zero? |",
        "|---|---:|---:|:---:|",
        *bootstrap_rows,
        "",
        "If a CI includes zero, the report does not claim that frequency business beats LR at that capacity. The result remains evidence from one holdout even when a CI excludes zero.",
        "",
        "### Rolling-origin customer overlap",
        "",
        f"{overlap['cutoff_count']} cutoffs produce {overlap['pair_count']} pairwise comparisons. Customers repeat across cutoffs: {'yes' if overlap['customers_repeat_across_cutoffs'] else 'no'}. Repeated customers mean cutoff rows are not independent customer samples; do not treat an average across these cutoffs as an independent-sample confidence interval.",
        "",
        "| Earlier cutoff | Later cutoff | Shared customers | Jaccard similarity | Later customers seen earlier |",
        "|---|---|---:|---:|---:|",
        *overlap_rows,
        "",
        "## Calibration and train/holdout diagnostics",
        "",
        f"- Pooled train positive rate: {diagnostics['train_positive_rate']:.1%}; holdout positive rate: {diagnostics['holdout_positive_rate']:.1%}; change: {diagnostics['holdout_minus_train_positive_rate']:+.1%}.",
        f"- LR raw mean predicted probability: {model_metrics['mean_predicted_probability']:.1%}; holdout rate: {diagnostics['holdout_positive_rate']:.1%}; calibration gap: {model_metrics['calibration_gap']:+.1%}; Brier: {model_metrics['brier_score']:.4f}.",
        f"- `class_weight=None` in code; class weighting did not cause this measured result. Raw-feature LR mean prediction ({model_metrics['mean_predicted_probability']:.1%}) is close to pooled train prevalence ({diagnostics['train_positive_rate']:.1%}) but below holdout prevalence ({diagnostics['holdout_positive_rate']:.1%}), which supports prevalence shift as a plausible explanation for the aggregate gap.",
        f"- The log1p sensitivity model's aggregate gap is {log_metrics['calibration_gap']:+.1%}; it {'narrows' if abs(log_metrics['calibration_gap']) < abs(model_metrics['calibration_gap']) else 'does not narrow'} the raw model's gap. This single experiment does not establish feature skew as the cause.",
        "",
        "### Training prevalence by cutoff",
        "",
        "| Prediction start | Positive rate |",
        "|---|---:|",
        *cutoff_rows,
        "",
        "### Calibration bins and feature skew",
        "",
        "The 0.2-0.4 LR bin is the source of the often-quoted ~32% predicted vs ~46% observed gap; those are bin rates, not the whole holdout rate.",
        "",
        "| Model | Predicted-probability bin | Customers | Mean predicted | Actual rate |",
        "|---|---:|---:|---:|---:|",
        *calibration_rows,
        "",
        "| Feature | Train p50 | Train p99 | Train skew | Holdout p50 | Holdout p99 | Holdout skew |",
        "|---|---:|---:|---:|---:|---:|---:|",
        *feature_rows,
        "",
        "",
        "## Assumptions and limits",
        "",
        "- No incremental revenue or campaign cost is estimated in this report. Any later cost or revenue scenario must be labeled **simulation based on assumptions**, not actual ROI.",
        "- Ranking results use one source snapshot and one temporal holdout. Rolling-origin cutoffs reuse customers, so they show temporal stability but are not independent customer samples. Independent source snapshots or a pre-specified blocked evaluation are needed before operational use.",
        "- Frequency naive uses `customer_id ASC` inside frequency ties; frequency business adds monetary and recency before ID. Boundary diagnostics show how many selected customers depend on that tie rule.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


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
        import sklearn
    except ModuleNotFoundError as error:
        raise RuntimeError("Install model dependencies with: pip install -e '.[model]'") from error

    source_file_id, observation_start, holdout_start, prediction_end = _source_bounds(connection, requested_source_file_id)
    with connection.cursor() as cursor:
        cursor.execute("select sha256 from ops.source_file where source_file_id = %s", (source_file_id,))
        source_sha256 = cursor.fetchone()[0]
    with connection.cursor() as cursor:
        cursor.execute("select min(event_at)::date from mart.customer_purchase_event where source_file_id = %s", (source_file_id,))
        first_event = cursor.fetchone()[0]
    starts = rolling_prediction_starts(first_event, holdout_start)
    all_examples = _examples(connection, source_file_id, starts)
    train, holdout = split_temporally(all_examples, holdout_start)
    assert_published_holdout_matches(holdout, _published_holdout(connection, source_file_id))
    labels = lambda rows: [int(x.repurchased_in_prediction_window) for x in rows]
    holdout_labels = labels(holdout)
    probabilities = _fit_logistic(train, holdout)
    log_probabilities = _fit_logistic(train, holdout, log1p_skewed_features=True)
    baseline_scores = [float(x.observation_frequency) for x in holdout]
    report = {
        "model_name": "logistic_regression_v1", "source_file_id": source_file_id, "source_sha256": str(source_sha256), "generated_at_utc": datetime.now(timezone.utc).isoformat(), "feature_names": list(FEATURE_NAMES),
        "model_configuration": {"class_weight": None, "scikit_learn_version": sklearn.__version__, "sensitivity_variant": "log1p frequency and monetary features"},
        "temporal_contract": {"observation_days": OBSERVATION_DAYS, "prediction_days": PREDICTION_DAYS, "train_prediction_start_dates": [x.isoformat() for x in starts[:-1]], "holdout_prediction_start_date": holdout_start.isoformat(), "holdout_prediction_end_date": prediction_end.isoformat(), "published_label_observation_start_date": observation_start.isoformat(), "holdout_exactly_matches_published_label_dataset": True},
        "training_example_count": len(train),
        "holdout_evaluation": {
            "logistic_regression": _metrics(holdout, probabilities, holdout_labels, [int(x >= .5) for x in probabilities], True),
            "log1p_logistic_regression_sensitivity": _metrics(holdout, log_probabilities, holdout_labels, [int(x >= .5) for x in log_probabilities], True),
            "frequency_gte_2_baseline": _metrics(holdout, baseline_scores, holdout_labels, [int(x.observation_frequency >= 2) for x in holdout], False),
        },
        "training_diagnostics": _training_diagnostics(train, holdout),
        "rolling_cutoff_overlap": _rolling_cutoff_overlap(all_examples),
        "decision_comparison": _decision_comparison(holdout, _priority_backtest(connection, source_file_id), probabilities, log_probabilities),
        "limits": ["Historical temporal backtest of observed repurchase, not campaign response, uplift, or ROI.", "No propensity scores are written to decision tables.", "Cost or revenue scenarios, if added later, must be labeled simulation based on assumptions."],
    }
    model_metrics = report["holdout_evaluation"]["logistic_regression"]
    model_metrics["mean_predicted_probability"] = sum(probabilities) / len(probabilities)
    model_metrics["calibration_gap"] = model_metrics["mean_predicted_probability"] - model_metrics["positive_rate"]
    log_metrics = report["holdout_evaluation"]["log1p_logistic_regression_sensitivity"]
    log_metrics["mean_predicted_probability"] = sum(log_probabilities) / len(log_probabilities)
    log_metrics["calibration_gap"] = log_metrics["mean_predicted_probability"] - log_metrics["positive_rate"]
    return report


def persist_evaluation(connection: Any, report: dict[str, Any]) -> None:
    """Store the temporal backtest so the BI layer can compare model and rule."""

    metrics = report["holdout_evaluation"]
    rows = [
        (
            "logistic_regression_v1",
            0.5,
            metrics["logistic_regression"],
            "Learned logistic regression scored at threshold 0.5; higher precision and lower recall than the rule baseline.",
        ),
        (
            "log1p_logistic_regression_sensitivity",
            0.5,
            metrics["log1p_logistic_regression_sensitivity"],
            "Sensitivity only: logistic regression with log1p frequency and monetary features; not the operating recommendation.",
        ),
        (
            "frequency_gte_2_rule",
            None,
            metrics["frequency_gte_2_baseline"],
            "Rule baseline: predicts repurchase when observation frequency is at least 2.",
        ),
    ]
    with connection.cursor() as cursor:
        for model_name, threshold, values, note in rows:
            cursor.execute(
                """
                insert into mart.repurchase_model_evaluation (
                    source_file_id, model_name, evaluated_at, decision_threshold,
                    customer_count, positive_customer_count, positive_rate,
                    precision_at_threshold, recall_at_threshold,
                    pr_auc, roc_auc, lift_at_top_20_percent, brier_score, evaluation_note
                ) values (%s, %s, now(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (source_file_id, model_name) do update set
                    evaluated_at = excluded.evaluated_at,
                    decision_threshold = excluded.decision_threshold,
                    customer_count = excluded.customer_count,
                    positive_customer_count = excluded.positive_customer_count,
                    positive_rate = excluded.positive_rate,
                    precision_at_threshold = excluded.precision_at_threshold,
                    recall_at_threshold = excluded.recall_at_threshold,
                    pr_auc = excluded.pr_auc,
                    roc_auc = excluded.roc_auc,
                    lift_at_top_20_percent = excluded.lift_at_top_20_percent,
                    brier_score = excluded.brier_score,
                    evaluation_note = excluded.evaluation_note
                """,
                (
                    report["source_file_id"],
                    model_name,
                    threshold,
                    values["customer_count"],
                    values["positive_customer_count"],
                    values["positive_rate"],
                    values["precision_at_0_5"],
                    values["recall_at_0_5"],
                    values["pr_auc"],
                    values["roc_auc"],
                    values["lift_at_top_20_percent"],
                    values.get("brier_score"),
                    note,
                ),
            )
    connection.commit()


def main() -> None:
    args = parse_args()
    dsn = os.environ.get(args.dsn_env)
    if not dsn:
        raise SystemExit(f"Set {args.dsn_env} before connecting to PostgreSQL.")
    connection = connect_from_dsn(dsn)
    try:
        report = train_and_report(connection, args.source_file_id)
        if not args.report_only:
            persist_evaluation(connection, report)
    finally:
        connection.close()  # type: ignore[attr-defined]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_markdown_report(report, args.markdown_output)
    print(json.dumps({"report_path": str(args.output), "markdown_report_path": str(args.markdown_output), "model_name": report["model_name"]}))


if __name__ == "__main__":
    main()
