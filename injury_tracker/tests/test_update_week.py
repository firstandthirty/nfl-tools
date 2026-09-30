from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from injury_tracker.scripts.schedule_context import ScheduleGameContext  # noqa: E402
from injury_tracker.scripts.update_week import update_week  # noqa: E402


class UpdateWeekTests(unittest.TestCase):
    def setUp(self) -> None:
        root = ROOT / ".tmp_tests" / f"update_{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.manual_file = root / "review_decisions.csv"
        self.manual_file.write_text("season,week,team,player_name,decision,ft_note\n2026,4,CLE,Fixture,INCLUDE,Keep me\n", encoding="utf-8")

    def test_skip_live_fetch_orders_schedule_pff_review_and_preserves_manual_files(self) -> None:
        calls: list[str] = []
        output_dir = self.root / "reviewed"
        output_dir.mkdir()

        def schedule():
            calls.append("schedule")
            return [
                ScheduleGameContext(
                    season=2026,
                    week=4,
                    team="CLE",
                    opponent="PIT",
                    home_away="HOME",
                    game_date="2026-10-02",
                    kickoff="2026-10-02T00:15:00Z",
                    schedule_source="fixture",
                    home_team="CLE",
                    away_team="PIT",
                ),
                ScheduleGameContext(
                    season=2026,
                    week=4,
                    team="PIT",
                    opponent="CLE",
                    home_away="AWAY",
                    game_date="2026-10-02",
                    kickoff="2026-10-02T00:15:00Z",
                    schedule_source="fixture",
                    home_team="CLE",
                    away_team="PIT",
                ),
            ]

        def pff(season: int, week: int):
            calls.append("pff")
            return {"through_week": week - 1, "weeks": []}

        def review(season: int, week: int):
            calls.append("review")
            return {"summary": {"automated_candidates": 1}, "paths": SimpleNamespace(output_dir=output_dir)}

        before = self.manual_file.read_text(encoding="utf-8")
        with patch("injury_tracker.scripts.update_week.load_schedule_context", schedule), patch(
            "injury_tracker.scripts.update_week.ensure_current_season_pff", pff
        ), patch("injury_tracker.scripts.update_week.load_review_bundle", review):
            summary = update_week(season=2026, week=4, skip_live_fetch=True)

        self.assertEqual(calls, ["schedule", "pff", "review"])
        self.assertEqual(self.manual_file.read_text(encoding="utf-8"), before)
        self.assertEqual([stage["stage"] for stage in summary["stages"]], ["schedule_context", "pff_participation", "review_population"])


if __name__ == "__main__":
    unittest.main()
