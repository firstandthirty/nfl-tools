from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pff_content.normalize import normalize_rows, safe_divide, snake_case
from pff_content.schemas import validation_report


class NormalizeTests(unittest.TestCase):
    def test_snake_case_normalization(self) -> None:
        self.assertEqual(snake_case("avgTimeToThrow"), "avg_time_to_throw")
        self.assertEqual(snake_case("Player ID"), "player_id")

    def test_numeric_rookie_and_receiving_derived_fields(self) -> None:
        body = {"receiving_summary": [{"player": "A", "player_id": "1", "team": "ATL", "targets": "3", "routes": "12", "draft_season": "2026"}]}
        df, _ = normalize_rows("receiving", body, table="receiving_summary", season=2026, week=1)
        self.assertTrue(pd.api.types.is_numeric_dtype(df["targets"]))
        self.assertTrue(bool(df.loc[0, "rookie"]))
        self.assertEqual(df.loc[0, "targets_per_route_run"], 0.25)

    def test_division_by_zero_stays_missing(self) -> None:
        result = safe_divide(pd.Series([4]), pd.Series([0]))
        self.assertTrue(pd.isna(result.iloc[0]))

    def test_rushing_yards_after_contact_per_attempt(self) -> None:
        body = {"rushing_summary": [{"player": "B", "attempts": 8, "yards_after_contact": 24, "draft_season": 2025}]}
        df, _ = normalize_rows("rushing", body, table="rushing_summary", season=2026, week=1)
        self.assertEqual(df.loc[0, "yards_after_contact_per_attempt"], 3)
        self.assertFalse(bool(df.loc[0, "rookie"]))

    def test_pressure_rates(self) -> None:
        pb, _ = normalize_rows("pass_blocking", {"pass_blocking": [{"player": "C", "pressures_allowed": 2, "snap_counts_pass_block": 20}]}, table="pass_blocking")
        pr, _ = normalize_rows("pass_rush", {"pass_rush_summary": [{"player": "D", "total_pressures": 3, "snap_counts_pass_rush": 30}]}, table="pass_rush_summary")
        self.assertEqual(pb.loc[0, "pressure_rate_allowed"], 0.1)
        self.assertEqual(pr.loc[0, "pressure_rate"], 0.1)

    def test_validation_flags_bad_receiving_counts(self) -> None:
        report = validation_report({"receiving": pd.DataFrame([{"player_id": 1, "team": "ATL", "receptions": 2, "targets": 1}])})
        self.assertIn("ERROR: receptions exceed targets", report.loc[0, "notes"])

    def test_validation_does_not_treat_efficiency_snap_columns_as_counts(self) -> None:
        report = validation_report(
            {
                "coverage": pd.DataFrame(
                    [{"season": 2026, "week": 1, "player_id": 1, "team": "ATL", "coverage_snaps": 12, "yards_per_coverage_snap": -0.1}]
                )
            }
        )
        self.assertNotIn("negative snap count", report.loc[0, "notes"])
