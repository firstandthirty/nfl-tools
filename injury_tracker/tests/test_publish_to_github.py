from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from injury_tracker.scripts.publish_to_github import (  # noqa: E402
    classify_divergence,
    commit_message,
    remote_matches_expected,
    unexpected_staged_paths,
    weekly_publish_allowlist,
)


class PublishToGithubTests(unittest.TestCase):
    def test_weekly_allowlist_is_narrow_public_manual_and_config_state(self) -> None:
        paths = weekly_publish_allowlist(2026, 4)

        self.assertIn("injuries/index.html", paths)
        self.assertIn("injuries/2026/week_04/index.html", paths)
        self.assertIn("injury_tracker/config/current_week.json", paths)
        self.assertIn("injury_tracker/data/manual/review_decisions.csv", paths)
        self.assertIn("injury_tracker/data/manual/review_status.csv", paths)
        self.assertNotIn("index.html", paths)
        self.assertNotIn("injury_tracker/scripts/publish_to_github.py", paths)

    def test_unexpected_paths_reject_generated_raw_processed_and_source_files(self) -> None:
        staged = [
            "injuries/index.html",
            "injuries/2026/week_04/index.html",
            "injury_tracker/data/manual/review_decisions.csv",
            "injury_tracker/data/raw/official_team/2026/week_04/run/NE.html",
            "injury_tracker/data/processed/2026/week_04/run/reviewed_players.json",
            "injury_tracker/scripts/review_app.py",
        ]

        self.assertEqual(
            unexpected_staged_paths(staged, season=2026, week=4),
            [
                "injury_tracker/data/raw/official_team/2026/week_04/run/NE.html",
                "injury_tracker/data/processed/2026/week_04/run/reviewed_players.json",
                "injury_tracker/scripts/review_app.py",
            ],
        )

    def test_unexpected_paths_reject_wrong_week_archive(self) -> None:
        staged = [
            "injuries/index.html",
            "injuries/2026/week_03/index.html",
            "injuries/2026/week_04/index.html",
        ]

        self.assertEqual(unexpected_staged_paths(staged, season=2026, week=4), ["injuries/2026/week_03/index.html"])

    def test_commit_message_uses_current_week(self) -> None:
        self.assertEqual(commit_message(2026, 4), "Update Week 4 injury tracker")

    def test_divergence_classification(self) -> None:
        self.assertEqual(classify_divergence("a", "a", "a"), "synced")
        self.assertEqual(classify_divergence("a", "b", "a"), "remote_ahead")
        self.assertEqual(classify_divergence("b", "a", "a"), "local_ahead")
        self.assertEqual(classify_divergence("b", "c", "a"), "diverged")

    def test_remote_slug_accepts_https_and_ssh_origin(self) -> None:
        self.assertTrue(remote_matches_expected("https://github.com/firstandthirty/nfl-tools.git"))
        self.assertTrue(remote_matches_expected("git@github.com:firstandthirty/nfl-tools.git"))
        self.assertFalse(remote_matches_expected("https://github.com/someone/else.git"))


if __name__ == "__main__":
    unittest.main()
