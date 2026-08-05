from __future__ import annotations

from pathlib import Path
import sys
import unittest

import math
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = ROOT / "scripts" / "04_analysis"
if str(ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYSIS_DIR))

from diagnostics.buckets import add_buckets
from diagnostics.holdout import (
    add_probability_audit_fields,
    choose_chronological_split,
    implied_probability_from_american,
    no_vig_side_probability,
    probability_audit,
    threshold_stability,
)
from diagnostics.loader import read_input, standardize_frame
from diagnostics.metrics import summarize


def sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "market_key": ["player_receptions"] * 8,
            "season": [2023, 2023, 2023, 2023, 2024, 2024, 2024, 2024],
            "week": [1, 2, 3, 4, 1, 2, 3, 4],
            "recommended_side": ["over", "under"] * 4,
            "line": [1.5, 2.5, 1.5, 2.5, 1.5, 2.5, 1.5, 2.5],
            "over_price": [1.9, 2.1, 1.8, 2.2, 1.9, 2.1, 1.8, 2.2],
            "under_price": [1.9, 1.8, 2.0, 1.7, 1.9, 1.8, 2.0, 1.7],
            "bet_odds": [1.9, 1.8, 1.8, 1.7, 1.9, 1.8, 1.8, 1.7],
            "projection": [2.0, 2.0, 1.9, 2.0, 2.0, 2.0, 1.9, 2.0],
            "projection_minus_line": [0.5, -0.5, 0.4, -0.5, 0.5, -0.5, 0.4, -0.5],
            "edge": [0.5, -0.5, 0.4, -0.5, 0.5, -0.5, 0.4, -0.5],
            "edge_receptions": [0.5, 0.5, 0.4, 0.5, 0.5, 0.5, 0.4, 0.5],
            "recommended_prob": [0.6, 0.58, 0.55, 0.57, 0.6, 0.58, 0.55, 0.57],
            "recommended_ev_percent": [5, 4, 3, 2, 5, 4, 3, 2],
            "actual": [2, 2, 1, 2, 2, 3, 1, 2],
            "bet_won": [True, True, False, True, True, False, False, True],
            "bet_pushed": [False] * 8,
            "profit_1u": [0.9, 0.8, -1, 0.7, 0.9, -1, -1, 0.7],
        }
    )


class ReceptionsHoldoutAutopsyTests(unittest.TestCase):
    def prepared(self, raw: pd.DataFrame | None = None) -> pd.DataFrame:
        return add_probability_audit_fields(add_buckets(standardize_frame(raw if raw is not None else sample_frame()).df))

    def test_chronological_split_selection(self):
        df = self.prepared()
        split = choose_chronological_split(df, min_validation_bets=2)
        self.assertEqual(split.method, "season_holdout")
        self.assertTrue(df.loc[split.discovery, "season"].lt(2024).all())
        self.assertTrue(df.loc[split.validation, "season"].eq(2024).all())

    def test_no_leakage_between_discovery_and_validation(self):
        df = self.prepared()
        split = choose_chronological_split(df, min_validation_bets=2)
        self.assertEqual(int((split.discovery & split.validation).sum()), 0)
        self.assertEqual(int((split.discovery | split.validation).sum()), len(df))

    def test_threshold_evaluation_uses_samples_independently(self):
        df = self.prepared()
        split = choose_chronological_split(df, min_validation_bets=2)
        table = threshold_stability(df[split.discovery], df[split.validation])
        row = table[table["rule"].eq("absolute_projection_edge >= 0.5")].iloc[0]
        self.assertEqual(row["discovery_bets"], 3)
        self.assertEqual(row["validation_bets"], 3)

    def test_implied_probability_from_american_odds(self):
        self.assertAlmostEqual(implied_probability_from_american(-150), 0.6)
        self.assertAlmostEqual(implied_probability_from_american(200), 1 / 3)

    def test_no_vig_probability_calculation(self):
        df = pd.DataFrame({"over_price": [1.9], "under_price": [1.9], "side": ["over"]})
        self.assertAlmostEqual(no_vig_side_probability(df).iloc[0], 0.5)

    def test_probability_metrics(self):
        df = self.prepared()
        split = choose_chronological_split(df, min_validation_bets=2)
        audit = probability_audit(df[split.discovery], df[split.validation])
        self.assertIn("brier_score", audit.columns)
        self.assertTrue(audit["brier_score"].notna().all())

    def test_one_outcome_class_auc_is_nan(self):
        raw = sample_frame()
        raw["bet_won"] = True
        df = self.prepared(raw)
        audit = probability_audit(df.iloc[:4], df.iloc[4:])
        self.assertTrue(math.isnan(audit.loc[audit["sample"].eq("discovery"), "auc_probability"].iloc[0]))

    def test_input_dataframe_remains_unchanged(self):
        raw = sample_frame()
        before = raw.copy(deep=True)
        df = self.prepared(raw)
        split = choose_chronological_split(df, min_validation_bets=2)
        threshold_stability(df[split.discovery], df[split.validation])
        pd.testing.assert_frame_equal(raw, before)

    def test_current_baseline_remains_unchanged(self):
        raw = read_input(ROOT / "data" / "analysis" / "backtests" / "receptions_backtest_rows.csv")
        df = self.prepared(raw)
        summary = summarize(df)
        self.assertEqual(summary["bets"], 608)
        self.assertEqual(summary["wins"], 278)
        self.assertEqual(summary["losses"], 330)
        self.assertEqual(summary["pushes"], 0)
        self.assertAlmostEqual(summary["profit_units"], -94.12)
        self.assertAlmostEqual(summary["roi"], -0.1548026315789474)


if __name__ == "__main__":
    unittest.main()
