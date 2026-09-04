from __future__ import annotations

import math
import sys
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "03_modeling"))

from prop_probability import (
    empirical_probabilities,
    expected_value_1u,
    forecast_residual,
    model_probabilities,
    normal_probabilities,
    select_chronological_split,
    american_to_decimal,
    break_even_probability,
)
from evaluate_prop_probabilities import build_projection_versions, direction, evaluate_rows, source_agreement


class PropProbabilityLayerTests(unittest.TestCase):
    def test_residual_sign_convention(self) -> None:
        self.assertEqual(forecast_residual(80, 72.5), 7.5)

    def test_normal_probability_calculation(self) -> None:
        probs = normal_probabilities(projection=100, line=100, mu=0, sigma=10)
        self.assertAlmostEqual(probs["p_over"], 0.5)
        self.assertAlmostEqual(probs["p_under"], 0.5)

    def test_empirical_probability_calculation(self) -> None:
        probs = empirical_probabilities(projection=100, line=105, residuals=[-10, 0, 5, 10])
        self.assertAlmostEqual(probs["p_over"], 0.25)
        self.assertAlmostEqual(probs["p_under"], 0.50)
        self.assertAlmostEqual(probs["p_push"], 0.25)

    def test_push_handling_integer_line(self) -> None:
        probs = empirical_probabilities(projection=10, line=12, residuals=[-1, 0, 2, 4])
        self.assertAlmostEqual(probs["p_push"], 0.25)

    def test_half_point_line_push_probability_is_zero(self) -> None:
        probs = empirical_probabilities(projection=10, line=12.5, residuals=[-1, 0, 2, 4])
        self.assertEqual(probs["p_push"], 0.0)

    def test_over_under_probabilities_are_consistent(self) -> None:
        probs = empirical_probabilities(projection=10, line=12, residuals=[-1, 0, 2, 4])
        self.assertAlmostEqual(probs["p_over"] + probs["p_under"] + probs["p_push"], 1.0)

    def test_american_odds_conversion(self) -> None:
        self.assertAlmostEqual(american_to_decimal(150), 2.5)
        self.assertAlmostEqual(american_to_decimal(-110), 1.9090909)
        self.assertAlmostEqual(break_even_probability(150), 0.4)

    def test_ev_math_positive_price(self) -> None:
        self.assertAlmostEqual(expected_value_1u(0.45, 0.0, 150), 0.125)

    def test_ev_math_negative_price(self) -> None:
        self.assertAlmostEqual(expected_value_1u(0.55, 0.0, -110), 0.05, places=2)

    def test_ev_with_push_probability(self) -> None:
        self.assertAlmostEqual(expected_value_1u(0.45, 0.10, 100), 0.0)

    def test_market_specific_calibration_loading(self) -> None:
        artifact = {"markets": {"player_rush_yds": {"selected_method": "empirical", "empirical_residuals": [0]}}}
        self.assertEqual(artifact["markets"]["player_rush_yds"]["selected_method"], "empirical")

    def _fixture_inputs(self):
        source = pd.DataFrame([
            {"season": 2026, "week": 1, "source": "pff", "player": "A", "player_normalized": "a", "team": "AAA", "position": "RB", "market": "player_rush_yds", "projection": 12.0, "captured_at": "2026-09-01T12:00:00-04:00", "snapshot_age_hours": 49.0, "raw_file": "pff.csv"},
            {"season": 2026, "week": 1, "source": "fantasypros", "player": "A", "player_normalized": "a", "team": "AAA", "position": "RB", "market": "player_rush_yds", "projection": 14.0, "captured_at": "2026-09-03T12:00:00-04:00", "snapshot_age_hours": 1.0, "raw_file": "fp.json"},
            {"season": 2026, "week": 1, "source": "pff", "player": "A", "player_normalized": "a", "team": "AAA", "position": "RB", "market": "player_receptions", "projection": 3.0, "captured_at": "2026-09-01T12:00:00-04:00", "snapshot_age_hours": 49.0, "raw_file": "pff.csv"},
        ])
        consensus = pd.DataFrame([
            {"season": 2026, "week": 1, "player": "A", "player_normalized": "a", "team": "AAA", "position": "RB", "market": "player_rush_yds", "projection_count": 2, "projection_mean": 13.0, "projection_std": 1.414, "projection_min": 12.0, "projection_max": 14.0, "sources": "fantasypros|pff", "latest_selected_snapshot": "2026-09-03T12:00:00-04:00"},
            {"season": 2026, "week": 1, "player": "A", "player_normalized": "a", "team": "AAA", "position": "RB", "market": "player_receptions", "projection_count": 2, "projection_mean": 3.0, "projection_std": 0.1, "projection_min": 2.9, "projection_max": 3.1, "sources": "fantasypros|pff", "latest_selected_snapshot": "2026-09-03T12:00:00-04:00"},
        ])
        odds = pd.DataFrame([
            {"season": 2026, "week": 1, "event_id": "e1", "commence_time": "2026-09-10T00:20:00Z", "sportsbook": "draftkings", "player": "A", "player_normalized": "a", "market": "player_rush_yds", "line": 13.0, "side": "over", "price": -110, "is_alternate": False, "raw_file": "odds.json", "captured_at": "2026-09-03T13:00:00-04:00"},
            {"season": 2026, "week": 1, "event_id": "e1", "commence_time": "2026-09-10T00:20:00Z", "sportsbook": "fanduel", "player": "A", "player_normalized": "a", "market": "player_rush_yds", "line": 15.5, "side": "under", "price": 104, "is_alternate": True, "raw_file": "odds.json", "captured_at": "2026-09-03T13:00:00-04:00"},
        ])
        artifact = {"markets": {"player_rush_yds": {"selected_method": "empirical", "empirical_residuals": [-5, 0, 5], "sample_size": 3, "empirical_quantiles": {"0.05": -5, "0.95": 5}}}}
        return source, consensus, odds, artifact

    def test_no_receptions_evaluation_and_source_rows_remain_distinct(self) -> None:
        source, consensus, odds, artifact = self._fixture_inputs()
        versions = build_projection_versions(source, consensus, datetime.fromisoformat("2026-09-03T13:00:00-04:00"))
        self.assertNotIn("player_receptions", set(versions["market"]))
        self.assertEqual(set(versions["projection_type"]), {"source", "aggregate"})
        self.assertEqual(len(versions[versions["projection_type"].eq("source")]), 2)

    def test_two_source_aggregate_row_and_production_false(self) -> None:
        source, consensus, _, _ = self._fixture_inputs()
        versions = build_projection_versions(source, consensus, datetime.fromisoformat("2026-09-03T13:00:00-04:00"))
        agg = versions[versions["projection_type"].eq("aggregate")].iloc[0]
        self.assertEqual(agg["projection_source_count"], 2)
        self.assertFalse(bool(agg["production_consensus_eligible"]))

    def test_alt_lines_and_sportsbooks_remain_distinct_in_evaluation(self) -> None:
        source, consensus, odds, artifact = self._fixture_inputs()
        versions = build_projection_versions(source, consensus, datetime.fromisoformat("2026-09-03T13:00:00-04:00"))
        rows = evaluate_rows(versions, odds, artifact, Path("artifact.json"), "2026-09-03T13:00:00-04:00")
        self.assertEqual(set(rows["sportsbook"]), {"draftkings", "fanduel"})
        self.assertEqual(set(rows["line"]), {13.0, 15.5})
        self.assertEqual(set(rows["side"]), {"over", "under"})

    def test_source_agreement_diagnostic(self) -> None:
        source, _, odds, _ = self._fixture_inputs()
        agreement = source_agreement(source, odds)
        self.assertEqual(direction(12, 10.5), "over")
        self.assertIn(False, set(agreement["sources_agree_direction"]))

    def test_projection_age_calculation(self) -> None:
        source, consensus, _, _ = self._fixture_inputs()
        versions = build_projection_versions(source, consensus, datetime.fromisoformat("2026-09-03T13:00:00-04:00"))
        agg = versions[versions["projection_type"].eq("aggregate")].iloc[0]
        self.assertAlmostEqual(float(agg["snapshot_age_hours"]), 1.0)

    def test_historical_calibration_split_is_leakage_safe(self) -> None:
        df = pd.DataFrame({"week": [1, 2, 3, 14, 15, 16], "x": range(6)})
        split = select_chronological_split(df, min_validation_rows=2)
        self.assertTrue(max(split.train_weeks) < min(split.validation_weeks))

    def test_candidate_method_comparison_is_out_of_sample_shape(self) -> None:
        df = pd.DataFrame({"week": list(range(1, 18)), "x": range(17)})
        split = select_chronological_split(df, min_validation_rows=4)
        self.assertEqual(split.validation_weeks, [14, 15, 16, 17])


if __name__ == "__main__":
    unittest.main()
