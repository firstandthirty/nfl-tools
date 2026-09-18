from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pff_content.metric_registry import AggregationClass, METRIC_REGISTRY
from pff_content.paths import period_output_dir
from pff_content.periods import Period
from pff_content.season_aggregation import aggregate_period, nfl_passer_rating


class PeriodAndAggregationTests(unittest.TestCase):
    def test_period_labels_and_paths(self) -> None:
        week = Period.week(2026, 8)
        season = Period.season_to_date(2026, 8)
        self.assertEqual(week.display_label, "2026 Week 8")
        self.assertEqual(season.display_label, "2026 Season Through Week 8")
        self.assertTrue(str(period_output_dir(week)).endswith(r"outputs\2026\week_08"))
        self.assertTrue(str(period_output_dir(season)).endswith(r"outputs\2026\season_through_week_08"))

    def test_registry_classifies_supported_and_unsupported_metrics(self) -> None:
        by_metric = {(spec.dataset, spec.metric): spec for spec in METRIC_REGISTRY}
        self.assertEqual(by_metric[("receiving", "targets_per_route_run")].aggregation_class, AggregationClass.RATIO_RECOMPUTABLE)
        self.assertTrue(by_metric[("coverage", "passer_rating_when_targeted")].supported_season_to_date)
        self.assertFalse(by_metric[("pass_blocking", "pass_blocking_efficiency")].supported_season_to_date)

    def test_receiving_uses_cumulative_targets_over_routes(self) -> None:
        period = Period.season_to_date(2026, 2)
        week1 = pd.DataFrame([{"season": 2026, "week": 1, "player_id": 1, "player_name": "A", "team": "AAA", "position": "WR", "routes": 20, "targets": 10, "receptions": 5, "yards": 100}])
        week2 = pd.DataFrame([{"season": 2026, "week": 2, "player_id": 1, "player_name": "A", "team": "AAA", "position": "WR", "routes": 5, "targets": 1, "receptions": 1, "yards": 20}])
        out = aggregate_period("receiving", [week1, week2], period)
        self.assertAlmostEqual(out.loc[0, "targets_per_route_run"], 11 / 25)
        self.assertNotAlmostEqual(out.loc[0, "targets_per_route_run"], ((10 / 20) + (1 / 5)) / 2)
        self.assertAlmostEqual(out.loc[0, "yprr"], 120 / 25)

    def test_rushing_pressure_twp_and_forced_incompletion_rates_are_recomputed(self) -> None:
        period = Period.season_to_date(2026, 2)
        rush = aggregate_period(
            "rushing",
            [
                pd.DataFrame([{"season": 2026, "week": 1, "player_id": 1, "player_name": "A", "team": "A", "position": "HB", "attempts": 10, "yards": 40, "yards_after_contact": 30}]),
                pd.DataFrame([{"season": 2026, "week": 2, "player_id": 1, "player_name": "A", "team": "A", "position": "HB", "attempts": 2, "yards": 4, "yards_after_contact": 0}]),
            ],
            period,
        )
        self.assertAlmostEqual(rush.loc[0, "yards_after_contact_per_attempt"], 30 / 12)
        qb = aggregate_period(
            "passing",
            [
                pd.DataFrame([{"season": 2026, "week": 1, "player_id": 2, "player_name": "QB", "team": "A", "position": "QB", "dropbacks": 50, "def_gen_pressures": 10, "turnover_worthy_plays": 5, "big_time_throws": 1, "avg_time_to_throw": 3.0, "attempts": 40, "avg_depth_of_target": 10}]),
                pd.DataFrame([{"season": 2026, "week": 2, "player_id": 2, "player_name": "QB", "team": "A", "position": "QB", "dropbacks": 10, "def_gen_pressures": 5, "turnover_worthy_plays": 0, "big_time_throws": 1, "avg_time_to_throw": 2.0, "attempts": 10, "avg_depth_of_target": 4}]),
            ],
            period,
        )
        self.assertAlmostEqual(qb.loc[0, "pressure_rate_faced"], 15 / 60)
        self.assertAlmostEqual(qb.loc[0, "twp_per_dropback"], 5 / 60)
        self.assertAlmostEqual(qb.loc[0, "avg_time_to_throw"], ((3.0 * 50) + (2.0 * 10)) / 60)
        cov = aggregate_period(
            "coverage",
            [
                pd.DataFrame([{"season": 2026, "week": 1, "player_id": 3, "player_name": "CB", "team": "A", "position": "CB", "coverage_snaps": 30, "targets": 10, "receptions": 5, "yards": 50, "touchdowns_allowed": 1, "interceptions": 0, "forced_incompletes": 1}]),
                pd.DataFrame([{"season": 2026, "week": 2, "player_id": 3, "player_name": "CB", "team": "B", "position": "CB", "coverage_snaps": 20, "targets": 2, "receptions": 1, "yards": 5, "touchdowns_allowed": 0, "interceptions": 1, "forced_incompletes": 2}]),
            ],
            period,
        )
        self.assertAlmostEqual(cov.loc[0, "forced_incompletion_rate"], 3 / 12)
        self.assertEqual(cov.loc[0, "team"], "B")
        self.assertEqual(cov.loc[0, "team_list"], "A,B")

    def test_missing_week_only_week_and_zero_denominator(self) -> None:
        period = Period.season_to_date(2026, 2)
        out = aggregate_period(
            "receiving",
            [
                pd.DataFrame([{"season": 2026, "week": 1, "player_id": 1, "player_name": "A", "team": "AAA", "position": "WR", "routes": 0, "targets": 0, "receptions": 0, "yards": 0}]),
                pd.DataFrame([{"season": 2026, "week": 2, "player_id": 2, "player_name": "B", "team": "BBB", "position": "TE", "routes": 10, "targets": 5, "receptions": 3, "yards": 40}]),
            ],
            period,
        ).sort_values("player_id").reset_index(drop=True)
        self.assertTrue(pd.isna(out.loc[0, "targets_per_route_run"]))
        self.assertEqual(out.loc[0, "games_represented"], 1)
        self.assertAlmostEqual(out.loc[1, "targets_per_route_run"], 0.5)

    def test_nfl_passer_rating_caps_and_cumulative_components(self) -> None:
        perfect = nfl_passer_rating(pd.Series([10]), pd.Series([10]), pd.Series([200]), pd.Series([3]), pd.Series([0]))
        self.assertAlmostEqual(float(perfect.iloc[0]), 158.33333333333331)
        cumulative = nfl_passer_rating(pd.Series([6]), pd.Series([12]), pd.Series([55]), pd.Series([1]), pd.Series([1]))
        self.assertAlmostEqual(float(cumulative.iloc[0]), 55.90277777777778)


if __name__ == "__main__":
    unittest.main()
