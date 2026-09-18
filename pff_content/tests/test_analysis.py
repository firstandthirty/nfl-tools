from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pff_content.analysis import coverage, pass_blocking, qbs, receiving, rookies, stories, team_defense
from pff_content.analysis.qualifiers import QUALIFIERS, add_rank, safe_divide


class AnalysisTests(unittest.TestCase):
    def test_rank_directionality(self) -> None:
        df = pd.DataFrame({"metric": [10, 3, 7], "qualified": [True, True, True]})
        high = add_rank(df, "metric", "metric_rank", ascending=False, qualified_col="qualified")
        low = add_rank(df, "metric", "metric_rank", ascending=True, qualified_col="qualified")
        self.assertEqual(int(high.loc[0, "metric_rank"]), 1)
        self.assertEqual(int(low.loc[1, "metric_rank"]), 1)

    def test_safe_divide_zero_denominator(self) -> None:
        result = safe_divide(pd.Series([1]), pd.Series([0]))
        self.assertTrue(pd.isna(result.iloc[0]))

    def test_qb_twp_int_flags_and_qualifier(self) -> None:
        df = qbs.build(
            pd.DataFrame(
                [
                    {
                        "season": 2026,
                        "week": 1,
                        "player_name": "QB One",
                        "team": "A",
                        "opponent": "B",
                        "position": "QB",
                        "dropbacks": 21,
                        "attempts": 20,
                        "yards": 200,
                        "touchdowns": 1,
                        "interceptions": 0,
                        "turnover_worthy_plays": 2,
                        "big_time_throws": 1,
                        "avg_depth_of_target": 8,
                        "avg_time_to_throw": 2.5,
                        "def_gen_pressures": 7,
                        "sacks": 1,
                        "draft_season": 2026,
                        "rookie": True,
                    }
                ]
            )
        )
        self.assertTrue(bool(df.loc[0, "qualified_qb"]))
        self.assertTrue(bool(df.loc[0, "potential_turnover_fortune"]))
        self.assertEqual(df.loc[0, "pressure_rate_faced"], 7 / 21)

    def test_receiving_route_qualifier(self) -> None:
        df = receiving.build(pd.DataFrame([{"player_name": "WR", "team": "A", "opponent": "B", "targets": 5, "routes": QUALIFIERS["receiving_min_routes"], "receptions": 3, "yards": 30, "yprr": 2.0, "rookie": False}]))
        self.assertTrue(bool(df.loc[0, "qualified_routes"]))

    def test_ol_snap_qualification_excludes_non_ol(self) -> None:
        df = pass_blocking.build(
            pd.DataFrame(
                [
                    {"player_name": "LT", "team": "A", "opponent": "B", "position": "LT", "pass_block_snaps": 40, "pressures_allowed": 0, "sacks_allowed": 0, "pass_blocking_efficiency": 100, "rookie": False},
                    {"player_name": "TE", "team": "A", "opponent": "B", "position": "TE", "pass_block_snaps": 40, "pressures_allowed": 0, "sacks_allowed": 0, "pass_blocking_efficiency": 100, "rookie": False},
                    {"player_name": "RG", "team": "A", "opponent": "B", "position": "RG", "pass_block_snaps": 20, "pressures_allowed": 1, "sacks_allowed": 0, "pass_blocking_efficiency": 98, "rookie": False},
                ]
            )
        )
        self.assertTrue(bool(df[df["player_name"] == "LT"].iloc[0]["qualified_ol"]))
        self.assertFalse(bool(df[df["player_name"] == "TE"].iloc[0]["qualified_ol"]))
        self.assertFalse(bool(df[df["player_name"] == "RG"].iloc[0]["qualified_ol"]))

    def test_coverage_qualifier(self) -> None:
        df = coverage.build(pd.DataFrame([{"player_name": "CB", "team": "A", "opponent": "B", "coverage_snaps": 20, "targets": 4, "receptions": 1, "yards": 9, "forced_incompletes": 1, "passer_rating_when_targeted": 39.6, "rookie": False}]))
        self.assertTrue(bool(df.loc[0, "qualified_coverage"]))

    def test_rookie_definition_from_tables(self) -> None:
        rookie_table = rookies.build({"qbs": pd.DataFrame([{"player_name": "Rookie QB", "team": "A", "opponent": "B", "position": "QB", "rookie": True, "pressure_rate_faced": 0.4, "pressure_rate_faced_rank": 1, "dropbacks": 21}])})
        self.assertEqual(rookie_table.loc[0, "player"], "Rookie QB")

    def test_rookie_summary_handles_missing_nullable_ranks(self) -> None:
        rookie_table = rookies.build(
            {
                "qbs": pd.DataFrame(
                    [
                        {"player_name": "No Rank", "team": "A", "opponent": "B", "position": "QB", "rookie": True, "pressure_rate_faced": pd.NA, "pressure_rate_faced_rank": pd.NA, "dropbacks": 1}
                    ]
                )
            }
        )
        self.assertTrue(rookie_table.empty)

    def test_team_man_zone_aggregation(self) -> None:
        df = team_defense.build(
            pd.DataFrame(
                [
                    {"season": 2026, "week": 1, "team": "A", "opponent": "B", "man_snap_counts_coverage": 6, "zone_snap_counts_coverage": 4},
                    {"season": 2026, "week": 1, "team": "A", "opponent": "B", "man_snap_counts_coverage": 4, "zone_snap_counts_coverage": 6},
                ]
            )
        )
        self.assertEqual(df.loc[0, "total_scheme_coverage_assignments"], 20)
        self.assertEqual(df.loc[0, "man_coverage_assignment_share"], 0.5)
        self.assertEqual(df.loc[0, "zone_coverage_assignment_share"], 0.5)
        self.assertEqual(df.loc[0, "coverage_tendency_classification"], "VALID_PLAYER_ASSIGNMENT_RATE_ONLY")
        self.assertEqual(df.loc[0, "man_coverage_rate"], 0.5)
        self.assertEqual(df.loc[0, "zone_coverage_rate"], 0.5)

    def test_story_rule_triggering(self) -> None:
        qb_table = qbs.build(pd.DataFrame([{"player_name": "QB", "team": "A", "opponent": "B", "position": "QB", "dropbacks": 20, "attempts": 20, "yards": 1, "touchdowns": 0, "interceptions": 0, "turnover_worthy_plays": 2, "big_time_throws": 0, "avg_depth_of_target": 1, "avg_time_to_throw": 2, "def_gen_pressures": 10, "sacks": 0, "rookie": False}]))
        story_table = stories.build_stories({"qbs": qb_table}, pd.DataFrame(), pd.DataFrame(), top_n=10)
        self.assertIn("twp_without_int", set(story_table["rule_triggered"]))


if __name__ == "__main__":
    unittest.main()
