"""Temporal split contracts for the repurchase model script."""

from datetime import date
import unittest

from retailpulse.modeling.repurchase import (
    RepurchaseExample,
    assert_published_holdout_matches,
    rolling_prediction_starts,
    split_temporally,
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
