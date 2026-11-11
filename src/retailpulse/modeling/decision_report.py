"""Pure ranking and distribution helpers for retention decision reports."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
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
