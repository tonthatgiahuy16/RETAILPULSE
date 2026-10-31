"""Temporal dataset helpers for the repurchase propensity baseline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable


OBSERVATION_DAYS = 180
PREDICTION_DAYS = 90


@dataclass(frozen=True)
class RepurchaseExample:
    """One customer observed at one prediction cutoff."""

    customer_id: str
    prediction_start_date: date
    observation_recency_days: int
    observation_frequency: int
    observation_monetary_amount: float
    repurchased_in_prediction_window: bool


def rolling_prediction_starts(first_event_date: date, holdout_prediction_start: date) -> tuple[date, ...]:
    """Return non-overlapping prediction starts ending at the published holdout."""

    earliest_start = first_event_date + timedelta(days=OBSERVATION_DAYS)
    starts: list[date] = []
    current = holdout_prediction_start
    while current >= earliest_start:
        starts.append(current)
        current -= timedelta(days=PREDICTION_DAYS)
    starts.reverse()
    if len(starts) < 2:
        raise ValueError(
            "Need at least one earlier 180-day observation/90-day prediction window before holdout"
        )
    return tuple(starts)


def split_temporally(
    examples: Iterable[RepurchaseExample], holdout_prediction_start: date
) -> tuple[tuple[RepurchaseExample, ...], tuple[RepurchaseExample, ...]]:
    """Keep every earlier cutoff in train and only the latest cutoff in holdout."""

    train: list[RepurchaseExample] = []
    holdout: list[RepurchaseExample] = []
    for example in examples:
        if example.prediction_start_date < holdout_prediction_start:
            train.append(example)
        elif example.prediction_start_date == holdout_prediction_start:
            holdout.append(example)
        else:
            raise ValueError("Example occurs after the declared temporal holdout")
    if not train or not holdout:
        raise ValueError("Temporal split requires non-empty train and holdout examples")
    return tuple(train), tuple(holdout)


def assert_published_holdout_matches(
    holdout: Iterable[RepurchaseExample],
    published_rows: Iterable[tuple[str, int, int, float, bool]],
) -> None:
    """Prove that the final rolling cutoff is the existing leakage-safe label mart."""

    expected = {
        customer_id: (recency, frequency, monetary, label)
        for customer_id, recency, frequency, monetary, label in published_rows
    }
    actual = {
        example.customer_id: (
            example.observation_recency_days,
            example.observation_frequency,
            example.observation_monetary_amount,
            example.repurchased_in_prediction_window,
        )
        for example in holdout
    }
    if actual != expected:
        raise ValueError("Final rolling holdout does not exactly match mart.customer_repurchase_label_dataset")
