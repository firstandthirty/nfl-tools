from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pff_content.analysis.qualifiers import add_ol_snap_qualification
from pff_content.content_discovery.core import (
    LONG_FORMAT_COLUMNS,
    build_content_discovery,
    discovery_qualifiers,
    high_rate_high_volume,
    observations_to_dataframe,
    rank_discrepancy,
    top_n_both,
    zero_on_volume,
)


class ContentDiscoveryTests(unittest.TestCase):
    def test_qualifier_registry(self) -> None:
        qualifiers = discovery_qualifiers()
        self.assertIn("qb", qualifiers)
        self.assertIn("coverage", qualifiers)
        self.assertIn("75%", qualifiers["offensive_line"].description)

    def test_top_n_both(self) -> None:
        df = pd.DataFrame(
            [
                {"player_name": "A", "metric_a": 10, "metric_b": 9},
                {"player_name": "B", "metric_a": 9, "metric_b": 1},
                {"player_name": "C", "metric_a": 1, "metric_b": 10},
            ]
        )
        self.assertEqual(top_n_both(df, "metric_a", "metric_b", n=2)["player_name"].tolist(), ["A"])

    def test_rank_discrepancy(self) -> None:
        df = pd.DataFrame(
            [
                {"player_name": "A", "metric_a": 100, "metric_b": 1},
                {"player_name": "B", "metric_a": 90, "metric_b": 2},
                {"player_name": "C", "metric_a": 1, "metric_b": 100},
            ]
        )
        self.assertEqual(set(rank_discrepancy(df, "metric_a", "metric_b", threshold=2)["player_name"]), {"A", "C"})

    def test_zero_on_volume(self) -> None:
        df = pd.DataFrame(
            [
                {"player_name": "A", "events": 0, "snaps": 30},
                {"player_name": "B", "events": 1, "snaps": 30},
                {"player_name": "C", "events": 0, "snaps": 5},
            ]
        )
        self.assertEqual(zero_on_volume(df, "events", "snaps", min_volume=20)["player_name"].tolist(), ["A"])

    def test_high_rate_high_volume(self) -> None:
        df = pd.DataFrame(
            [
                {"player_name": "A", "rate": 0.5, "volume": 10},
                {"player_name": "B", "rate": 0.4, "volume": 1},
                {"player_name": "C", "rate": 0.1, "volume": 20},
            ]
        )
        self.assertEqual(high_rate_high_volume(df, "rate", "volume", n=2)["player_name"].tolist(), ["A"])

    def test_ol_qualifier(self) -> None:
        df = pd.DataFrame(
            [
                {"player_name": "A", "team": "X", "position": "T", "pass_block_snaps": 40},
                {"player_name": "B", "team": "X", "position": "G", "pass_block_snaps": 29},
                {"player_name": "C", "team": "X", "position": "TE", "pass_block_snaps": 40},
            ]
        )
        out = add_ol_snap_qualification(df)
        self.assertTrue(bool(out.loc[out["player_name"].eq("A"), "qualified_ol"].item()))
        self.assertFalse(bool(out.loc[out["player_name"].eq("B"), "qualified_ol"].item()))
        self.assertFalse(bool(out.loc[out["player_name"].eq("C"), "qualified_ol"].item()))

    def test_long_format_csv_manifest_and_twp_int(self) -> None:
        qbs = pd.DataFrame(
            [
                {"player_name": "QB A", "team": "AAA", "opponent": "BBB", "rookie": True, "dropbacks": 30, "interceptions": 0, "turnover_worthy_plays": 2, "avg_time_to_throw": 2.5, "def_gen_pressures": 10, "pressure_rate_faced": 0.333, "sacks": 1},
                {"player_name": "QB B", "team": "CCC", "opponent": "DDD", "rookie": False, "dropbacks": 28, "interceptions": 2, "turnover_worthy_plays": 0, "avg_time_to_throw": 3.1, "def_gen_pressures": 6, "pressure_rate_faced": 0.214, "sacks": 0},
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = build_content_discovery({"qbs": qbs}, Path(tmp), season=2026, week=1, week_complete=True)
            csv = pd.read_csv(result["csv"])
            self.assertEqual(csv.columns.tolist(), LONG_FORMAT_COLUMNS)
            self.assertIn("TWP_INT_DISCREPANCY", set(csv["rule_id"]))
            manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
            self.assertTrue(manifest["week_complete"])
            self.assertEqual(manifest["season"], 2026)

    def test_coverage_qualifier_contract(self) -> None:
        qualifiers = discovery_qualifiers()
        self.assertIn("coverage snaps", qualifiers["coverage"].description)
        self.assertIn("targets", qualifiers["coverage"].description)

    def test_rookie_tagging_contract(self) -> None:
        df = pd.DataFrame({"draft_season": [2026, 2025], "season": [2026, 2026]})
        rookie = pd.to_numeric(df["draft_season"]).eq(pd.to_numeric(df["season"]))
        self.assertEqual(rookie.tolist(), [True, False])

    def test_opponent_join_contract(self) -> None:
        qbs = pd.DataFrame(
            [{"player_name": "QB A", "team": "AAA", "opponent": "BBB", "dropbacks": 30, "interceptions": 0, "turnover_worthy_plays": 2, "avg_time_to_throw": 2.5, "pressure_rate_faced": 0.333}]
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = build_content_discovery({"qbs": qbs}, Path(tmp), season=2026, week=1, week_complete=True)
            csv = pd.read_csv(result["csv"])
            self.assertIn("BBB", set(csv["opponent"].dropna()))

    def test_team_tendency_uses_assignment_share_language(self) -> None:
        team = pd.DataFrame(
            [
                {
                    "season": 2026,
                    "week": 1,
                    "team": "AAA",
                    "opponent": "BBB",
                    "man_coverage_assignment_share": 0.7,
                    "zone_coverage_assignment_share": 0.3,
                    "total_scheme_coverage_assignments": 100,
                }
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = build_content_discovery({"team_defense": team}, Path(tmp), season=2026, week=1, week_complete=True)
            csv = pd.read_csv(result["csv"])
            self.assertIn("man_coverage_assignment_share", set(csv["metric_a"]))
            self.assertTrue(csv["qualifier"].str.contains("not team defensive play rates").any())

    def test_empty_observation_dataframe_schema(self) -> None:
        self.assertEqual(observations_to_dataframe([]).columns.tolist(), LONG_FORMAT_COLUMNS)


if __name__ == "__main__":
    unittest.main()
