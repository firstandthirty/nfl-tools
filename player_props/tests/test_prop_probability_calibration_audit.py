from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = PROJECT_ROOT / "scripts" / "04_analysis" / "audit_prop_probability_calibration.py"
spec = importlib.util.spec_from_file_location("audit_prop_probability_calibration", AUDIT_PATH)
audit = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(audit)


class PropProbabilityCalibrationAuditTests(unittest.TestCase):
    def test_50_percent_brier_baseline(self) -> None:
        df = pd.DataFrame({"won": [True, False], "is_push": [False, False], "p": [0.5, 0.5]})
        self.assertAlmostEqual(audit.binary_metrics(df, "p")["brier_score"], 0.25)

    def test_50_percent_log_loss_baseline(self) -> None:
        df = pd.DataFrame({"won": [True, False], "is_push": [False, False], "p": [0.5, 0.5]})
        self.assertAlmostEqual(audit.binary_metrics(df, "p")["log_loss"], 0.6931471805599453)

    def test_pushes_are_excluded_from_binary_scoring(self) -> None:
        df = pd.DataFrame({"won": [True, False, False], "is_push": [False, False, True], "p": [0.8, 0.2, 0.99]})
        metrics = audit.binary_metrics(df, "p")
        self.assertEqual(metrics["n"], 2)
        self.assertEqual(metrics["pushes"], 1)
        self.assertAlmostEqual(metrics["actual_win_rate"], 0.5)

    def test_training_base_rate_uses_training_rows_only(self) -> None:
        train = pd.DataFrame({
            "market": ["player_pass_yds"] * 3,
            "season": [2024] * 3,
            "week": [1, 1, 1],
            "player": ["A", "B", "C"],
            "player_norm": ["a", "b", "c"],
            "projection": [12.0, 8.0, 8.0],
            "line": [10.0, 10.0, 10.0],
            "actual": [11.0, 12.0, 9.0],
            "is_push": [False, False, False],
        })
        rates = audit.training_base_rates(train)
        self.assertAlmostEqual(rates["over"], 2 / 3)
        self.assertAlmostEqual(rates["under"], 1 / 3)

    def test_shrinkage_formula(self) -> None:
        self.assertAlmostEqual(audit.shrink_probability(0.70, 0.25), 0.55)

    def test_alpha_zero_produces_50_percent(self) -> None:
        self.assertAlmostEqual(audit.shrink_probability(0.83, 0.0), 0.5)

    def test_alpha_one_reproduces_original_probability(self) -> None:
        self.assertAlmostEqual(audit.shrink_probability(0.83, 1.0), 0.83)

    def test_bootstrap_is_deterministic_with_fixed_seed(self) -> None:
        df = pd.DataFrame({
            "market": ["player_pass_yds"] * 8,
            "won": [True, False, True, False, True, False, True, False],
            "is_push": [False] * 8,
            "model_probability": [0.6, 0.4, 0.55, 0.45, 0.7, 0.3, 0.52, 0.48],
            "constant_50_probability": [0.5] * 8,
            "season": [2024] * 8,
            "week": [17] * 8,
            "player_norm": [f"p{i}" for i in range(8)],
            "line": [10.5] * 8,
            "projection_indicated_won": [True, False, True, False, True, False, True, False],
        })
        first = audit.bootstrap_metrics(df, iterations=25, seed=7)
        second = audit.bootstrap_metrics(df, iterations=25, seed=7)
        pd.testing.assert_frame_equal(first, second)

    def test_probability_bucket_assignment(self) -> None:
        buckets = audit.make_probability_buckets(pd.Series([0.49, 0.51, 0.56, 0.61, 0.70])).astype(str).tolist()
        self.assertEqual(buckets, ["<50%", "50-52.5%", "55-57.5%", "60-65%", "65%+"])

    def test_projection_edge_direction(self) -> None:
        self.assertEqual(audit.projection_direction(1.0), "over")
        self.assertEqual(audit.projection_direction(-1.0), "under")
        self.assertEqual(audit.projection_direction(0.0), "equal")

    def test_over_under_side_separation(self) -> None:
        df = pd.DataFrame({
            "market": ["player_pass_yds", "player_pass_yds"],
            "side": ["over", "under"],
            "won": [True, False],
            "is_push": [False, False],
            "model_probability": [0.6, 0.4],
            "projection_indicated_side": ["over", "over"],
        })
        result = audit.side_diagnostics(df)
        self.assertEqual(set(result["side"]), {"over", "under"})

    def test_no_receptions_in_week1_diagnostics(self) -> None:
        rows = pd.DataFrame({
            "market": ["player_pass_yds", "player_receptions"],
            "expected_value_pct": [6.0, 100.0],
            "expected_value_1u": [0.06, 1.0],
            "suspicious_flags": ["", ""],
            "projection_source": ["pff", "pff"],
            "model_win_probability": [0.56, 0.99],
            "projection": [250.0, 5.0],
            "line": [240.5, 4.5],
            "american_price": [-110, -110],
            "projection_type": ["source", "source"],
            "is_alternate": [False, False],
            "sportsbook": ["book", "book"],
            "side": ["over", "over"],
            "break_even_probability": [0.5238, 0.5238],
            "probability_edge": [0.0362, 0.4662],
        })
        filtered, _ = audit.week1_ev_diagnostics(rows)
        self.assertEqual(filtered["market"].tolist(), ["player_pass_yds"])

    def test_no_future_validation_data_used_for_fitting(self) -> None:
        df = pd.DataFrame({"week": [1, 2, 3, 4], "x": [1, 1, 1, 1]})
        split = audit.select_chronological_split(df, min_validation_rows=1)
        self.assertLess(max(split.train_weeks), min(split.validation_weeks))

    def test_week1_diagnostics_do_not_alter_evaluation_rows(self) -> None:
        rows = pd.DataFrame({
            "market": ["player_pass_yds"],
            "expected_value_pct": [6.0],
            "expected_value_1u": [0.06],
            "suspicious_flags": [""],
            "projection_source": ["pff"],
            "model_win_probability": [0.56],
            "projection": [250.0],
            "line": [240.5],
            "american_price": [-110],
            "projection_type": ["source"],
            "is_alternate": [False],
            "sportsbook": ["book"],
            "side": ["over"],
            "break_even_probability": [0.5238],
            "probability_edge": [0.0362],
        })
        original = rows.copy(deep=True)
        audit.week1_ev_diagnostics(rows)
        pd.testing.assert_frame_equal(rows, original)

    def test_unique_opportunity_grouping_counts(self) -> None:
        rows = pd.DataFrame({
            "projection_type": ["source", "source", "aggregate"],
            "projection_source": ["pff", "fantasypros", "pff|fantasypros"],
            "sportsbook": ["book", "book", "book"],
            "player_normalized": ["player", "player", "player"],
            "market": ["player_pass_yds"] * 3,
            "line": [250.5, 250.5, 250.5],
            "side": ["over", "over", "over"],
            "expected_value_pct": [6.0, 4.0, 7.0],
        })
        counts = audit.week1_unique_counts(rows)
        sportsbook = counts[counts["grain"].eq("unique_sportsbook_wagers")].iloc[0]
        self.assertEqual(int(sportsbook["total"]), 1)
        self.assertEqual(int(sportsbook["ev_gt_5pct"]), 1)


if __name__ == "__main__":
    unittest.main()
