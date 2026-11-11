"""Pure ranking and distribution helpers for retention decision reports."""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Mapping, Sequence
from itertools import combinations
from typing import Any


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def distribution_summary(values: Sequence[float]) -> dict[str, float | int]:
    """Summarize feature scale, tail and moment skewness without extra deps."""

    if not values:
        raise ValueError("Cannot summarize an empty feature distribution")
    numbers = [float(value) for value in values]
    mean = sum(numbers) / len(numbers)
    variance = sum((value - mean) ** 2 for value in numbers) / len(numbers)
    standard_deviation = math.sqrt(variance)
    skewness = (
        sum((value - mean) ** 3 for value in numbers) / len(numbers) / standard_deviation**3
        if standard_deviation
        else 0.0
    )
    return {
        "count": len(numbers),
        "mean": mean,
        "stddev": standard_deviation,
        "min": min(numbers),
        "p50": _quantile(numbers, 0.50),
        "p90": _quantile(numbers, 0.90),
        "p95": _quantile(numbers, 0.95),
        "p99": _quantile(numbers, 0.99),
        "max": max(numbers),
        "skewness": skewness,
    }


def evaluate_ranking(
    rows: Sequence[Mapping[str, Any]],
    *,
    rank_key: Callable[[Mapping[str, Any]], Any],
    tie_key: Callable[[Mapping[str, Any]], Any],
    fractions: Sequence[float] = (0.10, 0.20, 0.30),
) -> list[dict[str, Any]]:
    """Calculate top-K metrics and expose whether K splits an equal-score block."""

    if not rows:
        raise ValueError("Cannot evaluate an empty ranking")
    customer_ids = [str(row["customer_id"]) for row in rows]
    if len(set(customer_ids)) != len(customer_ids):
        raise ValueError("Ranking rows must contain unique customer_id values")
    labels = [bool(row["label"]) for row in rows]
    positive_count = sum(labels)
    if positive_count == 0:
        raise ValueError("Ranking evaluation requires at least one positive label")
    ordered = sorted(rows, key=rank_key)
    output: list[dict[str, Any]] = []
    for fraction in fractions:
        if not 0 < fraction <= 1:
            raise ValueError("Budget fractions must be in (0, 1]")
        selected_count = max(1, math.ceil(len(ordered) * fraction))
        selected = ordered[:selected_count]
        cutoff_value = tie_key(ordered[selected_count - 1])
        boundary_start = next(index for index, row in enumerate(ordered) if tie_key(row) == cutoff_value)
        boundary_group_size = sum(tie_key(row) == cutoff_value for row in ordered)
        selected_from_boundary = sum(tie_key(row) == cutoff_value for row in selected)
        selected_positive_count = sum(bool(row["label"]) for row in selected)
        precision = selected_positive_count / selected_count
        output.append(
            {
                "budget_fraction": fraction,
                "selected_customer_count": selected_count,
                "positive_selected_count": selected_positive_count,
                "holdout_positive_count": positive_count,
                "precision_at_k": precision,
                "recall_at_k": selected_positive_count / positive_count,
                "holdout_positive_rate": positive_count / len(ordered),
                "lift_at_k": precision / (positive_count / len(ordered)),
                "cutoff_tie_value": list(cutoff_value) if isinstance(cutoff_value, tuple) else cutoff_value,
                "cutoff_tie_group_size": boundary_group_size,
                "cutoff_tie_slots_needed": selected_count - boundary_start,
                "selected_from_cutoff_tie": selected_from_boundary,
                "cut_through_tie_block": 0 < selected_from_boundary < boundary_group_size,
            }
        )
    return output


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        raise ValueError("Cannot calculate a percentile from empty values")
    return _quantile([float(value) for value in values], fraction)


def _selected_customer_ids(
    rows: Sequence[Mapping[str, Any]], rank_key: Callable[[Mapping[str, Any]], Any], fraction: float
) -> set[str]:
    if not 0 < fraction <= 1:
        raise ValueError("Budget fractions must be in (0, 1]")
    selected_count = max(1, math.ceil(len(rows) * fraction))
    return {str(row["customer_id"]) for row in sorted(rows, key=rank_key)[:selected_count]}


def bootstrap_precision_comparison(
    rows: Sequence[Mapping[str, Any]],
    *,
    left_rank_key: Callable[[Mapping[str, Any]], Any],
    right_rank_key: Callable[[Mapping[str, Any]], Any],
    fractions: Sequence[float] = (0.10, 0.20, 0.30),
    iterations: int = 2_000,
    seed: int = 20261111,
    confidence_level: float = 0.95,
) -> list[dict[str, Any]]:
    """Paired customer bootstrap CI for fixed-ranking precision@K differences.

    Rankings and K membership remain fixed from the original holdout. Each
    replicate samples customers with replacement, preserving whether each
    customer belongs to either selected list and its observed label.
    """

    if len(rows) < 2:
        raise ValueError("Bootstrap comparison requires at least two holdout customers")
    if iterations < 100:
        raise ValueError("Bootstrap comparison requires at least 100 iterations")
    if not 0 < confidence_level < 1:
        raise ValueError("Confidence level must be in (0, 1)")
    customer_ids = [str(row["customer_id"]) for row in rows]
    if len(set(customer_ids)) != len(customer_ids):
        raise ValueError("Bootstrap comparison requires unique customer_id values")
    rng = random.Random(seed)
    alpha = (1 - confidence_level) / 2
    output = []
    for fraction in fractions:
        left_selected = _selected_customer_ids(rows, left_rank_key, fraction)
        right_selected = _selected_customer_ids(rows, right_rank_key, fraction)
        left_precision = sum(bool(row["label"]) for row in rows if str(row["customer_id"]) in left_selected) / len(left_selected)
        right_precision = sum(bool(row["label"]) for row in rows if str(row["customer_id"]) in right_selected) / len(right_selected)
        replicates = []
        for _ in range(iterations):
            sampled = [rows[rng.randrange(len(rows))] for _ in range(len(rows))]
            left_members = [row for row in sampled if str(row["customer_id"]) in left_selected]
            right_members = [row for row in sampled if str(row["customer_id"]) in right_selected]
            if not left_members or not right_members:
                continue
            left_bootstrap = sum(bool(row["label"]) for row in left_members) / len(left_members)
            right_bootstrap = sum(bool(row["label"]) for row in right_members) / len(right_members)
            replicates.append(left_bootstrap - right_bootstrap)
        if len(replicates) < iterations * 0.90:
            raise ValueError("Too many bootstrap replicates had an empty selected group")
        ci_lower = _percentile(replicates, alpha)
        ci_upper = _percentile(replicates, 1 - alpha)
        output.append(
            {
                "budget_fraction": fraction,
                "method": "paired_customer_bootstrap_fixed_ranking",
                "iterations": iterations,
                "seed": seed,
                "confidence_level": confidence_level,
                "left_precision_at_k": left_precision,
                "right_precision_at_k": right_precision,
                "observed_difference": left_precision - right_precision,
                "ci_lower": ci_lower,
                "ci_upper": ci_upper,
                "ci_includes_zero": ci_lower <= 0 <= ci_upper,
                "interpretation": "CI conditions on the rankings fitted to this holdout; it measures uncertainty in observed-label precision, not refit-model or future-period uncertainty.",
            }
        )
    return output


def cutoff_overlap_diagnostics(customer_ids_by_cutoff: Mapping[str, set[str]]) -> dict[str, Any]:
    """Report customer reuse among rolling temporal cutoffs."""

    ordered = sorted((str(cutoff), set(customer_ids)) for cutoff, customer_ids in customer_ids_by_cutoff.items())
    pairs = []
    for (left_cutoff, left_ids), (right_cutoff, right_ids) in combinations(ordered, 2):
        shared = left_ids & right_ids
        union = left_ids | right_ids
        pairs.append(
            {
                "left_prediction_start_date": left_cutoff,
                "right_prediction_start_date": right_cutoff,
                "left_customer_count": len(left_ids),
                "right_customer_count": len(right_ids),
                "shared_customer_count": len(shared),
                "jaccard_similarity": len(shared) / len(union) if union else 0.0,
                "left_customers_seen_in_right": len(shared) / len(left_ids) if left_ids else 0.0,
                "right_customers_seen_in_left": len(shared) / len(right_ids) if right_ids else 0.0,
            }
        )
    return {
        "cutoff_count": len(ordered),
        "pair_count": len(pairs),
        "customers_repeat_across_cutoffs": any(pair["shared_customer_count"] > 0 for pair in pairs),
        "pairs": pairs,
        "interpretation": "Rows from different rolling cutoffs are not independent customer samples when customers recur; aggregate summaries across cutoffs must disclose this dependency.",
    }
