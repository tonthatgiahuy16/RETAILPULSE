"""Temporal split contracts for the repurchase model script."""

from datetime import date
import unittest

from retailpulse.modeling.repurchase import (
    RepurchaseExample,
    assert_published_holdout_matches,
    assert_training_labels_precede_holdout,
    priority_backtest_rows,
    rolling_prediction_starts,
    split_for_training_cutoffs,
    split_temporally,
    training_cutoffs_for_block,
)


class RepurchaseModelContractTests(unittest.TestCase):
    def test_rolling_cutoffs_are_non_overlapping_and_end_at_holdout(self) -> None:
        starts = rolling_prediction_starts(date(2020, 1, 1), date(2020, 11, 1))
        self.assertEqual(starts, (date(2020, 8, 3), date(2020, 11, 1)))

    def test_split_keeps_only_earlier_labels_in_training(self) -> None:
        early = RepurchaseExample("customer-a", date(2020, 8, 3), 1, 2, 10.0, True)
        holdout = RepurchaseExample("customer-a", date(2020, 11, 1), 3, 1, 5.0, False)
        train, evaluation = split_temporally((early, holdout), date(2020, 11, 1))
        self.assertEqual(train, (early,))
        self.assertEqual(evaluation, (holdout,))

    def test_published_holdout_mismatch_is_rejected(self) -> None:
        holdout = RepurchaseExample("customer-a", date(2020, 11, 1), 3, 1, 5.0, False)
        with self.assertRaisesRegex(ValueError, "does not exactly match"):
            assert_published_holdout_matches((holdout,), [("customer-a", 3, 1, 5.0, True)])


class MultiHoldoutBlockTests(unittest.TestCase):
    STARTS = (
        date(2020, 2, 1),
        date(2020, 5, 1),
        date(2020, 8, 1),
        date(2020, 11, 1),
    )

    def test_training_cutoffs_use_only_the_previous_blocks(self) -> None:
        selected = training_cutoffs_for_block(self.STARTS, date(2020, 11, 1), 2)
        self.assertEqual(selected, (date(2020, 5, 1), date(2020, 8, 1)))

    def test_training_cutoffs_reject_an_unknown_or_earliest_holdout(self) -> None:
        with self.assertRaisesRegex(ValueError, "not in the rolling cutoff set"):
            training_cutoffs_for_block(self.STARTS, date(2020, 12, 1))
        with self.assertRaisesRegex(ValueError, "at least one earlier training cutoff"):
            training_cutoffs_for_block(self.STARTS, date(2020, 2, 1))

    def test_block_split_discards_cutoffs_outside_train_and_holdout(self) -> None:
        ignored = RepurchaseExample("customer-a", date(2020, 5, 1), 1, 1, 10.0, False)
        train = RepurchaseExample("customer-b", date(2020, 8, 1), 2, 2, 20.0, True)
        holdout = RepurchaseExample("customer-c", date(2020, 11, 1), 3, 1, 30.0, False)

        split_train, split_holdout = split_for_training_cutoffs(
            (ignored, train, holdout), date(2020, 11, 1), (date(2020, 8, 1),)
        )

        self.assertEqual(split_train, (train,))
        self.assertEqual(split_holdout, (holdout,))

    def test_example_after_the_declared_holdout_is_rejected(self) -> None:
        future = RepurchaseExample("customer-a", date(2021, 2, 1), 1, 1, 10.0, False)
        train = RepurchaseExample("customer-b", date(2020, 8, 1), 2, 2, 20.0, True)
        holdout = RepurchaseExample("customer-c", date(2020, 11, 1), 3, 1, 30.0, False)

        with self.assertRaisesRegex(ValueError, "after the declared temporal holdout"):
            split_for_training_cutoffs(
                (train, holdout, future), date(2020, 11, 1), (date(2020, 8, 1),)
            )

    def test_training_label_window_that_reaches_the_holdout_is_rejected(self) -> None:
        train = RepurchaseExample("customer-a", date(2020, 9, 1), 1, 1, 10.0, False)
        holdout = RepurchaseExample("customer-b", date(2020, 11, 1), 3, 1, 30.0, False)

        with self.assertRaisesRegex(ValueError, "overlaps the temporal holdout"):
            split_for_training_cutoffs(
                (train, holdout), date(2020, 11, 1), (date(2020, 9, 1),)
            )

    def test_label_window_ending_exactly_at_the_holdout_is_accepted(self) -> None:
        train = RepurchaseExample("customer-a", date(2020, 8, 3), 1, 1, 10.0, False)
        holdout = RepurchaseExample("customer-b", date(2020, 11, 1), 3, 1, 30.0, False)

        split_train, split_holdout = split_for_training_cutoffs(
            (train, holdout), date(2020, 11, 1), (date(2020, 8, 3),)
        )

        self.assertEqual(split_train, (train,))
        self.assertEqual(split_holdout, (holdout,))
        assert_training_labels_precede_holdout(split_train, date(2020, 11, 1))

    def test_priority_backtest_recomputes_rfm_order_inside_the_cohort(self) -> None:
        examples = (
            RepurchaseExample("a", date(2020, 11, 1), 1, 10, 100.0, True),
            RepurchaseExample("b", date(2020, 11, 1), 10, 1, 100.0, False),
            RepurchaseExample("c", date(2020, 11, 1), 10, 1, 1.0, False),
            RepurchaseExample("d", date(2020, 11, 1), 2, 1, 1.0, True),
        )

        rows = priority_backtest_rows(examples)

        self.assertEqual(
            [(row["customer_id"], row["priority_segment"], row["priority_rank"]) for row in rows],
            [
                ("a", "CHAMPIONS", 1),
                ("b", "AT_RISK_HIGH_VALUE", 2),
                ("d", "POTENTIAL", 3),
                ("c", "LOST", 4),
            ],
        )
        self.assertEqual([row["label"] for row in rows], [True, False, True, False])

    def test_priority_thresholds_change_with_the_cohort(self) -> None:
        target = RepurchaseExample("a", date(2020, 11, 1), 1, 10, 100.0, True)
        small_cohort = (
            target,
            RepurchaseExample("b", date(2020, 11, 1), 10, 1, 1.0, False),
            RepurchaseExample("c", date(2020, 11, 1), 10, 1, 1.0, False),
            RepurchaseExample("d", date(2020, 11, 1), 2, 1, 1.0, False),
        )
        rich_cohort = (
            target,
            RepurchaseExample("b", date(2020, 11, 1), 10, 1, 1_000.0, False),
            RepurchaseExample("c", date(2020, 11, 1), 10, 1, 1_000.0, False),
            RepurchaseExample("d", date(2020, 11, 1), 10, 1, 1_000.0, False),
        )

        small_segment = next(
            row["priority_segment"] for row in priority_backtest_rows(small_cohort) if row["customer_id"] == "a"
        )
        rich_segment = next(
            row["priority_segment"] for row in priority_backtest_rows(rich_cohort) if row["customer_id"] == "a"
        )

        self.assertEqual(small_segment, "CHAMPIONS")
        self.assertNotEqual(rich_segment, "CHAMPIONS")

    def test_priority_backtest_rejects_an_empty_cohort(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one customer"):
            priority_backtest_rows(())
