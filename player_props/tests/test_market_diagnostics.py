from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = ROOT / "scripts" / "04_analysis"
if str(ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYSIS_DIR))

from diagnostics.buckets import add_buckets
from diagnostics.calibration import calibration_table
from diagnostics.loader import read_input, standardize_frame
from diagnostics.metrics import summarize
from diagnostics.recommendations import candidate_kill_table, generate_candidate_rules


class MarketDiagnosticsTests(unittest.TestCase):
    def test_receptions_baseline(self):
        raw = read_input(ROOT / "data" / "analysis" / "backtests" / "receptions_backtest_rows.csv")
        df = add_buckets(standardize_frame(raw).df)
        summary = summarize(df)
        self.assertEqual(summary["bets"], 608)
        self.assertEqual(summary["wins"], 278)
        self.assertEqual(summary["losses"], 330)
        self.assertEqual(summary["pushes"], 0)
        self.assertAlmostEqual(summary["profit_units"], -94.12)
        self.assertAlmostEqual(summary["roi"], -0.1548026315789474)

    def test_profit_uses_profit_1u_when_present(self):
        raw = pd.DataFrame(
            {
                "recommended_side": ["over"],
                "line": [1.5],
                "actual": [2],
                "bet_won": [True],
                "bet_pushed": [False],
                "bet_odds": [1.91],
                "profit_1u": [123.45],
            }
        )
        self.assertAlmostEqual(standardize_frame(raw).df["profit_units"].iloc[0], 123.45)

    def test_recommended_side_beats_fallback_alias(self):
        raw = pd.DataFrame(
            {
                "recommended_side": ["over"],
                "model_side": ["under"],
                "line": [2.5],
                "actual": [3],
                "bet_won": [True],
                "bet_pushed": [False],
                "profit_1u": [1.0],
            }
        )
        loaded = standardize_frame(raw)
        self.assertEqual(loaded.column_map["side"], "recommended_side")
        self.assertEqual(loaded.df["side"].iloc[0], "over")

    def test_recommended_prob_is_not_scaled(self):
        raw = pd.DataFrame(
            {
                "recommended_side": ["over"],
                "recommended_prob": [0.58],
                "line": [2.5],
                "actual": [3],
                "bet_won": [True],
                "bet_pushed": [False],
                "profit_1u": [0.8],
            }
        )
        self.assertAlmostEqual(standardize_frame(raw).df["predicted_probability"].iloc[0], 0.58)

    def test_probability_calibration_uses_bucket_win_rate(self):
        raw = pd.DataFrame(
            {
                "recommended_side": ["over", "over", "over", "over"],
                "recommended_prob": [0.48, 0.49, 0.61, 0.62],
                "line": [1.5, 1.5, 1.5, 1.5],
                "actual": [2, 1, 2, 2],
                "bet_won": [True, False, True, True],
                "bet_pushed": [False, False, False, False],
                "profit_1u": [0.8, -1.0, 0.8, 0.8],
            }
        )
        df = add_buckets(standardize_frame(raw).df)
        table = calibration_table(df, "predicted_probability", "probability_bucket", "recommended_probability", True, min_bets=1)
        rates = dict(zip(table["bucket"].astype(str), table["actual_win_rate"]))
        self.assertAlmostEqual(rates["45-50%"], 0.5)
        self.assertAlmostEqual(rates["60-62.5%"], 1.0)

    def test_recommended_ev_percent_retains_percentage_units(self):
        raw = pd.DataFrame(
            {
                "recommended_side": ["over"],
                "recommended_ev_percent": [5.5],
                "line": [2.5],
                "actual": [3],
                "bet_won": [True],
                "bet_pushed": [False],
                "profit_1u": [0.8],
            }
        )
        self.assertAlmostEqual(standardize_frame(raw).df["recommended_ev_percent_value"].iloc[0], 5.5)

    def test_pushes_are_graded_correctly(self):
        raw = pd.DataFrame(
            {
                "recommended_side": ["over", "under"],
                "line": [2.5, 3.5],
                "actual": [2.5, 2.0],
                "bet_won": [False, True],
                "bet_pushed": [True, False],
                "profit_1u": [0.0, 0.9],
            }
        )
        summary = summarize(standardize_frame(raw).df)
        self.assertEqual(summary["pushes"], 1)
        self.assertEqual(summary["wins"], 1)
        self.assertEqual(summary["losses"], 0)
        self.assertEqual(summary["bets"], 2)

    def test_missing_optional_dimensions_do_not_crash(self):
        raw = pd.DataFrame(
            {
                "recommended_side": ["over", "under"],
                "line": [1.5, 2.5],
                "actual": [2, 1],
                "bet_won": [True, True],
                "bet_pushed": [False, False],
                "profit_1u": [0.7, 0.8],
            }
        )
        self.assertEqual(summarize(add_buckets(standardize_frame(raw).df))["bets"], 2)

    def test_empty_or_ungradable_inputs_fail_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty.csv"
            empty.write_text("a,b\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no rows"):
                read_input(empty)
        with self.assertRaisesRegex(ValueError, "no bets could be graded"):
            standardize_frame(pd.DataFrame({"recommended_side": ["over"], "line": [1.5]}))

    def test_bucket_boundaries(self):
        raw = pd.DataFrame(
            {
                "recommended_side": ["over", "over", "under"],
                "line": [1.5, 2.5, 6.5],
                "projection_minus_line": [0.0, 0.5, -0.5],
                "edge_receptions": [0.49, 0.5, 1.0],
                "recommended_prob": [0.525, 0.55, 0.7],
                "recommended_ev_percent": [2.0, 5.0, 10.0],
                "actual": [2, 3, 6],
                "bet_won": [True, True, True],
                "bet_pushed": [False, False, False],
                "profit_1u": [0.8, 0.9, 0.7],
            }
        )
        df = add_buckets(standardize_frame(raw).df)
        self.assertEqual(list(df["verified_edge_bucket"].astype(str)), ["0-0.5", "0.5-1", "1-1.5"])
        self.assertEqual(list(df["ev_bucket"].astype(str)), ["2-5", "5-10", "10-15"])
        self.assertEqual(list(df["probability_bucket"].astype(str)), ["52.5-55%", "55-57.5%", "70%+"])

    def test_candidate_rules_do_not_mutate_dataframe(self):
        raw = pd.DataFrame(
            {
                "recommended_side": ["over"] * 35 + ["under"] * 35,
                "line": [1.5] * 70,
                "actual": [0] * 35 + [1] * 35,
                "bet_won": [False] * 35 + [True] * 35,
                "bet_pushed": [False] * 70,
                "profit_1u": [-1.0] * 35 + [0.8] * 35,
                "recommended_ev_percent": [3.0] * 70,
                "recommended_prob": [0.55] * 70,
                "projection_minus_line": [0.25] * 70,
                "edge_receptions": [0.25] * 70,
            }
        )
        df = add_buckets(standardize_frame(raw).df)
        before = df.copy(deep=True)
        rules = generate_candidate_rules(df, ["side", "line_bucket"], ["recommended_ev_percent_value"], 30, 40)
        candidate_kill_table(df, rules, 30)
        pd.testing.assert_frame_equal(df, before)


if __name__ == "__main__":
    unittest.main()
