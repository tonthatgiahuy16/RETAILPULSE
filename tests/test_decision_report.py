"""Decision-report ranking and diagnostic contracts."""

import unittest

from retailpulse.modeling.decision_report import (
    bootstrap_precision_comparison,
    cutoff_overlap_diagnostics,
    distribution_summary,
    evaluate_ranking,
)


class DecisionReportTests(unittest.TestCase):
    def test_top_k_metrics_and_frequency_tie_cut_are_explicit(self) -> None:
        rows = [
            {"customer_id": "a", "label": True, "frequency": 3},
            {"customer_id": "b", "label": False, "frequency": 2},
            {"customer_id": "c", "label": True, "frequency": 2},
            {"customer_id": "d", "label": False, "frequency": 2},
            {"customer_id": "e", "label": True, "frequency": 1},
        ]

        result = evaluate_ranking(
            rows,
            rank_key=lambda row: (-row["frequency"], row["customer_id"]),
            tie_key=lambda row: row["frequency"],
            fractions=(0.6,),
        )[0]

        self.assertEqual(result["selected_customer_count"], 3)
        self.assertEqual(result["positive_selected_count"], 2)
        self.assertAlmostEqual(result["precision_at_k"], 2 / 3)
        self.assertAlmostEqual(result["recall_at_k"], 2 / 3)
        self.assertTrue(result["cut_through_tie_block"])
        self.assertEqual(result["cutoff_tie_group_size"], 3)
        self.assertEqual(result["selected_from_cutoff_tie"], 2)
        self.assertEqual(result["cutoff_tie_slots_needed"], 2)

    def test_business_tie_key_can_remove_id_dependent_cut(self) -> None:
        rows = [
            {"customer_id": "a", "label": False, "frequency": 2, "monetary": 1, "recency": 20},
            {"customer_id": "b", "label": True, "frequency": 2, "monetary": 9, "recency": 10},
            {"customer_id": "c", "label": False, "frequency": 2, "monetary": 8, "recency": 15},
            {"customer_id": "d", "label": True, "frequency": 1, "monetary": 20, "recency": 1},
        ]

        result = evaluate_ranking(
            rows,
            rank_key=lambda row: (-row["frequency"], -row["monetary"], row["recency"], row["customer_id"]),
            tie_key=lambda row: (row["frequency"], row["monetary"], row["recency"]),
            fractions=(0.5,),
        )[0]

        self.assertFalse(result["cut_through_tie_block"])
        self.assertEqual(result["cutoff_tie_group_size"], 1)

    def test_distribution_summary_reports_right_skew(self) -> None:
        result = distribution_summary([1.0, 1.0, 1.0, 7.0])
        self.assertEqual(result["count"], 4)
        self.assertEqual(result["p50"], 1.0)
        self.assertGreater(result["skewness"], 0)

    def test_bootstrap_precision_difference_has_zero_width_for_identical_rankings(self) -> None:
        rows = [
            {"customer_id": "a", "label": True, "score": 4},
            {"customer_id": "b", "label": False, "score": 3},
            {"customer_id": "c", "label": True, "score": 2},
            {"customer_id": "d", "label": False, "score": 1},
        ]

        result = bootstrap_precision_comparison(
            rows,
            left_rank_key=lambda row: -row["score"],
            right_rank_key=lambda row: -row["score"],
            fractions=(0.5,),
            iterations=100,
            seed=17,
        )[0]

        self.assertEqual(result["observed_difference"], 0.0)
        self.assertEqual(result["ci_lower"], 0.0)
        self.assertEqual(result["ci_upper"], 0.0)
        self.assertTrue(result["ci_includes_zero"])

    def test_cutoff_overlap_exposes_reused_customers(self) -> None:
        result = cutoff_overlap_diagnostics(
            {
                "2020-01-01": {"a", "b", "c"},
                "2020-04-01": {"b", "c", "d"},
                "2020-07-01": {"e"},
            }
        )

        self.assertEqual(result["cutoff_count"], 3)
        self.assertEqual(result["pair_count"], 3)
        first_pair = result["pairs"][0]
        self.assertEqual(first_pair["shared_customer_count"], 2)
        self.assertAlmostEqual(first_pair["jaccard_similarity"], 0.5)
        self.assertTrue(result["customers_repeat_across_cutoffs"])


if __name__ == "__main__":
    unittest.main()
