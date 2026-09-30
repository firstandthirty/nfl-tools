from __future__ import annotations

import csv
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from injury_tracker.scripts.schedule_context import (  # noqa: E402
    load_schedule_context,
    normalize_team,
    schedule_for_team,
)


class ScheduleContextTests(unittest.TestCase):
    def test_loads_week_team_home_away_context_from_saved_inventory_shape(self) -> None:
        scratch = ROOT / "data" / "processed" / "_test_schedule_context"
        path = scratch / "2026" / "future_games_inventory.csv"
        try:
            if scratch.exists():
                for child in scratch.iterdir():
                    child.unlink()
                scratch.rmdir()
            path.parent.mkdir(parents=True)
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["event_id", "week", "commence_time", "away_team", "home_team"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "event_id": "abc",
                        "week": "3",
                        "commence_time": "2026-09-29T00:15:00Z",
                        "away_team": "Philadelphia Eagles",
                        "home_team": "Chicago Bears",
                    }
                )

            contexts = load_schedule_context(paths=[path])
            chi = schedule_for_team(2026, 3, "CHI", contexts=contexts)
            phi = schedule_for_team(2026, 3, "PHI", contexts=contexts)
        finally:
            if path.exists():
                path.unlink()
            if path.parent.exists():
                path.parent.rmdir()
            if scratch.exists():
                scratch.rmdir()

        self.assertIsNotNone(chi)
        self.assertEqual(chi.opponent, "PHI")
        self.assertEqual(chi.home_away, "HOME")
        self.assertEqual(chi.game_date, "2026-09-29")
        self.assertIsNotNone(phi)
        self.assertEqual(phi.opponent, "CHI")
        self.assertEqual(phi.home_away, "AWAY")

    def test_normalizes_common_team_aliases(self) -> None:
        self.assertEqual(normalize_team("WSH"), "WAS")
        self.assertEqual(normalize_team("Los Angeles Rams"), "LAR")
        self.assertEqual(normalize_team("Arizona Cardinals"), "ARI")


if __name__ == "__main__":
    unittest.main()
