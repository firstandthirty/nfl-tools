from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pff_content.leaderboards.core import (
    LeaderboardColumn,
    LeaderboardDefinition,
    build_leaderboard,
    format_decimal,
    format_integer,
    format_percentage,
    leaderboard_definitions,
    manifest_entry,
    select_top_n,
    write_manifest,
)


def fixture_definition() -> LeaderboardDefinition:
    return LeaderboardDefinition(
        id="test",
        title="Test",
        subtitle="Testing",
        dataset="test",
        qualifier="sample qualifier",
        ranking_metric="metric",
        sort_direction="descending",
        volume_tiebreaker="volume",
        n=3,
        primary_metric=LeaderboardColumn("metric", "Metric", lambda value: format_decimal(value, 1)),
        context_columns=(LeaderboardColumn("volume", "volume", format_integer),),
        output_filename="test",
        data_builder=lambda data: data["test"],
    )


class LeaderboardTests(unittest.TestCase):
    def test_top_n_descending_and_volume_tiebreaker(self) -> None:
        df = pd.DataFrame(
            [
                {"player_name": "Beta", "team": "B", "metric": 0.5, "volume": 10},
                {"player_name": "Alpha", "team": "A", "metric": 0.7, "volume": 5},
                {"player_name": "Gamma", "team": "G", "metric": 0.5, "volume": 12},
                {"player_name": "Delta", "team": "D", "metric": 0.2, "volume": 99},
            ]
        )
        out = select_top_n(fixture_definition(), df)
        self.assertEqual(out["player_name"].tolist(), ["Alpha", "Gamma", "Beta"])
        self.assertEqual(out["rank"].tolist(), [1, 2, 3])

    def test_deterministic_ties_fall_back_to_player_name(self) -> None:
        df = pd.DataFrame(
            [
                {"player_name": "Charlie", "team": "C", "metric": 1.0, "volume": 10},
                {"player_name": "Alpha", "team": "A", "metric": 1.0, "volume": 10},
                {"player_name": "Bravo", "team": "B", "metric": 1.0, "volume": 10},
            ]
        )
        first = select_top_n(fixture_definition(), df)
        second = select_top_n(fixture_definition(), df.sample(frac=1, random_state=4))
        self.assertEqual(first["player_name"].tolist(), ["Alpha", "Bravo", "Charlie"])
        self.assertEqual(first["player_name"].tolist(), second["player_name"].tolist())

    def test_formatters(self) -> None:
        self.assertEqual(format_percentage(0.45, 1), "45.0%")
        self.assertEqual(format_decimal(5.912, 2), "5.91")
        self.assertEqual(format_integer(9.0), "9")

    def test_leaderboard_definitions(self) -> None:
        definitions = leaderboard_definitions()
        self.assertEqual(len(definitions), 5)
        self.assertEqual({definition.id for definition in definitions}, {"target_earners", "yprr_leaders", "yac_per_attempt_leaders", "pressure_leaders", "pass_rush_win_rate_leaders"})

    def test_long_player_name_is_preserved_in_csv(self) -> None:
        df = pd.DataFrame(
            [
                {"player_name": "Marquez Valdes-Scantling", "team": "AAA", "metric": 2.0, "volume": 10},
                {"player_name": "Jaxon Smith-Njigba", "team": "BBB", "metric": 1.0, "volume": 9},
            ]
        )
        out = select_top_n(fixture_definition(), df)
        self.assertEqual(out.loc[0, "player_name"], "Marquez Valdes-Scantling")

    def test_manifest_generation(self) -> None:
        df = pd.DataFrame([{"player_name": "Alpha", "team": "A", "metric": 1.5, "volume": 10}])
        with tempfile.TemporaryDirectory() as tmp:
            result = build_leaderboard(fixture_definition(), {"test": df}, Path(tmp), season=2026, week=1, use_bars=False)
            entry = manifest_entry(result)
            self.assertEqual(entry["id"], "test")
            self.assertEqual(entry["leader"], "Alpha")
            self.assertEqual(entry["leader_value"], "1.5")
            manifest = write_manifest([result], Path(tmp) / "manifest.json")
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))[0]["id"], "test")

    def test_csv_output_matches_displayed_ranking(self) -> None:
        df = pd.DataFrame(
            [
                {"player_name": "B", "team": "B", "metric": 1.0, "volume": 5},
                {"player_name": "A", "team": "A", "metric": 2.0, "volume": 4},
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = build_leaderboard(fixture_definition(), {"test": df}, Path(tmp), season=2026, week=1, use_bars=False)
            csv = pd.read_csv(result.csv_path)
            self.assertEqual(csv["player_name"].tolist(), result.rows["player_name"].tolist())

    def test_real_definitions_reuse_qualified_populations(self) -> None:
        definitions = {definition.id: definition for definition in leaderboard_definitions()}
        receiving = pd.DataFrame(
            [
                {"player_name": "WR", "team": "A", "position": "WR", "routes": 15, "targets": 5, "receptions": 3, "yards": 45, "yprr": 3.0},
                {"player_name": "HB", "team": "B", "position": "HB", "routes": 30, "targets": 20, "receptions": 10, "yards": 100, "yprr": 3.3333333333333335},
            ]
        )
        pop = definitions["target_earners"].data_builder({"receiving": receiving})
        self.assertEqual(pop["player_name"].tolist(), ["WR"])


if __name__ == "__main__":
    unittest.main()
