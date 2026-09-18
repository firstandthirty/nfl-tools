from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pff_content.week_status import (
    WeekCompleteness,
    assert_finalized_week,
    completeness_from_games_body,
    decide_cache_policy,
    read_week_status,
    write_week_status,
)


def games_body(flags: list[bool]) -> dict[str, list[dict[str, object]]]:
    games = []
    for index, has_stats in enumerate(flags, start=1):
        games.append(
            {
                "id": 1000 + index,
                "has_stats": has_stats,
                "home_team": {"abbreviation": f"H{index}"},
                "away_team": {"abbreviation": f"A{index}"},
            }
        )
    return {"games": games}


class WeekStatusTests(unittest.TestCase):
    def test_incomplete_week_detection_without_hard_coded_game_count(self) -> None:
        status = completeness_from_games_body(games_body([True, False, True]), season=2026, week=7)
        self.assertFalse(status.is_complete)
        self.assertEqual(status.total_games, 3)
        self.assertEqual(status.games_with_stats, 2)
        self.assertEqual(status.incomplete_game_ids, [1002])
        self.assertEqual(status.incomplete_matchups, ["H2 vs A2"])

    def test_complete_week_detection(self) -> None:
        status = completeness_from_games_body(games_body([True, True]), season=2026, week=20)
        self.assertTrue(status.is_complete)
        self.assertEqual(status.total_games, 2)
        self.assertEqual(status.games_without_stats, 0)

    def test_incomplete_cached_week_becoming_complete_refreshes_all(self) -> None:
        previous = completeness_from_games_body(games_body([True, False]), season=2026, week=1)
        current = completeness_from_games_body(games_body([True, True]), season=2026, week=1)
        decision = decide_cache_policy(
            refresh=False,
            all_cache_exists=True,
            saved_status=previous,
            cached_games_status=previous,
            current_games_status=current,
        )
        self.assertEqual(decision, "refresh_all_finalized")

    def test_finalized_cache_reuse(self) -> None:
        finalized = completeness_from_games_body(games_body([True, True, True]), season=2026, week=1)
        decision = decide_cache_policy(
            refresh=False,
            all_cache_exists=True,
            saved_status=finalized,
            cached_games_status=None,
        )
        self.assertEqual(decision, "reuse_finalized")

    def test_incomplete_analysis_rejected_by_default(self) -> None:
        status = completeness_from_games_body(games_body([True, False]), season=2026, week=1)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "week_status.json"
            write_week_status(status, path=path)
            original = __import__("pff_content.week_status", fromlist=["week_status_path"]).week_status_path
            import pff_content.week_status as week_status

            try:
                week_status.week_status_path = lambda season, week: path
                with self.assertRaisesRegex(RuntimeError, "incomplete"):
                    assert_finalized_week(2026, 1)
            finally:
                week_status.week_status_path = original

    def test_allow_incomplete_behavior(self) -> None:
        status = completeness_from_games_body(games_body([False]), season=2026, week=1)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "week_status.json"
            write_week_status(status, path=path)
            import pff_content.week_status as week_status

            original = week_status.week_status_path
            try:
                week_status.week_status_path = lambda season, week: path
                loaded = assert_finalized_week(2026, 1, allow_incomplete=True)
            finally:
                week_status.week_status_path = original
        self.assertFalse(loaded.is_complete)

    def test_status_metadata_does_not_leak_credentials(self) -> None:
        status = completeness_from_games_body(games_body([True]), season=2026, week=1)
        data = status.to_dict()
        text = json.dumps(data).lower()
        self.assertNotIn("authorization", text)
        self.assertNotIn("api_key", text)
        self.assertNotIn("token", text)

    def test_all_facets_policy_for_missing_cache(self) -> None:
        decision = decide_cache_policy(
            refresh=False,
            all_cache_exists=False,
            saved_status=None,
            cached_games_status=None,
        )
        self.assertEqual(decision, "fetch_all")


if __name__ == "__main__":
    unittest.main()
