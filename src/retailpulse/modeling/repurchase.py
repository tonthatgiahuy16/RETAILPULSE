"""Temporal dataset helpers for the repurchase propensity baseline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable

from retailpulse.modeling.decision_report import percentile


OBSERVATION_DAYS = 180
PREDICTION_DAYS = 90
PRIORITY_SEGMENT_ORDER = {
    "CHAMPIONS": 1,
    "AT_RISK_HIGH_VALUE": 2,
    "POTENTIAL": 3,
    "LOST": 4,
}


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


def training_cutoffs_for_block(
    all_cutoffs: Iterable[date],
    holdout_start: date,
    max_training_cutoffs: int = 3,
) -> tuple[date, ...]:
    """Return the previous cutoffs used to train one temporal holdout block."""

    if max_training_cutoffs < 1:
        raise ValueError("A block needs at least one training cutoff")
    ordered = tuple(sorted(set(all_cutoffs)))
    if holdout_start not in ordered:
        raise ValueError("Holdout cutoff is not in the rolling cutoff set")
    earlier = tuple(cutoff for cutoff in ordered if cutoff < holdout_start)
    if not earlier:
        raise ValueError("A block needs at least one earlier training cutoff")
    return earlier[-max_training_cutoffs:]


def split_for_training_cutoffs(
    examples: Iterable[RepurchaseExample],
    holdout_start: date,
    training_cutoffs: Iterable[date],
) -> tuple[tuple[RepurchaseExample, ...], tuple[RepurchaseExample, ...]]:
    """Select one block's training cutoffs and its holdout, discarding other cutoffs."""

    train_starts = set(training_cutoffs)
    train: list[RepurchaseExample] = []
    holdout: list[RepurchaseExample] = []
    for example in examples:
        if example.prediction_start_date in train_starts:
            train.append(example)
        elif example.prediction_start_date == holdout_start:
            holdout.append(example)
        elif example.prediction_start_date > holdout_start:
            raise ValueError("Example occurs after the declared temporal holdout")
    if not train or not holdout:
        raise ValueError("Temporal block requires non-empty train and holdout examples")
    assert_training_labels_precede_holdout(train, holdout_start)
    return tuple(train), tuple(holdout)


def assert_training_labels_precede_holdout(
    train: Iterable[RepurchaseExample], holdout_start: date
) -> None:
    """Reject any training example whose 90-day label window reaches the holdout."""

    for example in train:
        label_end = example.prediction_start_date + timedelta(days=PREDICTION_DAYS)
        if label_end > holdout_start:
            raise ValueError(
                "Training example label window overlaps the temporal holdout"
            )


def priority_backtest_rows(
    examples: Iterable[RepurchaseExample],
) -> list[dict[str, Any]]:
    """Reproduce contract 019's descriptive RFM priority order for one cohort.

    Thresholds are recomputed inside the cohort so an earlier holdout block
    cannot borrow percentile cutoffs fitted on a later snapshot.
    """

    rows = list(examples)
    if not rows:
        raise ValueError("RFM priority backtest requires at least one customer")
    recency_p25 = percentile([row.observation_recency_days for row in rows], 0.25)
    recency_p75 = percentile([row.observation_recency_days for row in rows], 0.75)
    frequency_p75 = percentile([row.observation_frequency for row in rows], 0.75)
    monetary_p75 = percentile(
        [row.observation_monetary_amount for row in rows], 0.75
    )
    scored = []
    for row in rows:
        if (
            row.observation_recency_days <= recency_p25
            and row.observation_frequency >= frequency_p75
            and row.observation_monetary_amount >= monetary_p75
        ):
            segment = "CHAMPIONS"
        elif (
            row.observation_recency_days >= recency_p75
            and row.observation_monetary_amount >= monetary_p75
        ):
            segment = "AT_RISK_HIGH_VALUE"
        elif row.observation_recency_days >= recency_p75:
            segment = "LOST"
        else:
            segment = "POTENTIAL"
        scored.append(
            {
                "customer_id": row.customer_id,
                "label": row.repurchased_in_prediction_window,
                "frequency": row.observation_frequency,
                "monetary": row.observation_monetary_amount,
                "recency": row.observation_recency_days,
                "priority_segment": segment,
            }
        )
    scored.sort(
        key=lambda row: (
            PRIORITY_SEGMENT_ORDER[row["priority_segment"]],
            -row["monetary"],
            -row["frequency"],
            row["recency"],
            row["customer_id"],
        )
    )
    return [
        dict(row, priority_rank=index)
        for index, row in enumerate(scored, start=1)
    ]
