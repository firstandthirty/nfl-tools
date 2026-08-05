from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "01_ingest"))

from projection_adapters.common import (
    PROJECT_ROOT,
    discover_snapshot_files,
    parse_snapshot_metadata,
)
from projection_adapters.pff import transform_pff_snapshot
from ingest_projection_snapshots import ingest_snapshot_file


class PFFProjectionAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_file = ROOT / "data" / "raw" / "projections" / "pff" / "2026" / "week_01" / "snapshots" / "08_04_26_1100_projections.csv"
        self.metadata = parse_snapshot_metadata(self.raw_file, source="pff", season=2026, week=1)

    def test_parse_current_snapshot_timestamp_in_america_new_york(self) -> None:
        self.assertEqual(self.metadata.captured_at_source, "filename")
        self.assertEqual(self.metadata.captured_at.strftime("%Y-%m-%d %H:%M:%S%z"), "2026-08-04 11:00:00-0400")

    def test_fall_back_to_filesystem_mtime_for_unparseable_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "unparseable.csv"
            path.write_text("a,b\n", encoding="utf-8")
            os.utime(path, (1_700_000_000, 1_700_000_000))
            metadata = parse_snapshot_metadata(path, source="pff", season=2026, week=1)
            self.assertEqual(metadata.captured_at_source, "filesystem_mtime")
            self.assertEqual(metadata.captured_at.year, 2023)

    def test_parse_source_season_and_week_from_directory_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            snapshots = root / "data" / "raw" / "projections" / "pff" / "2026" / "week_01" / "snapshots"
            snapshots.mkdir(parents=True, exist_ok=True)
            sample = snapshots / "snapshot.csv"
            sample.write_text("playerName,teamName,position,passYds\n", encoding="utf-8")
            discovered = discover_snapshot_files(root, source="pff", season=2026, week=1)
            self.assertEqual(discovered, [sample])

    def test_pff_market_mapping_is_correct(self) -> None:
        sample = pd.DataFrame(
            [{"playerName": "Test Player", "teamName": "DET", "position": "rb", "passYds": 0.0, "rushYds": 12.0, "recvYds": 18.0, "recvReceptions": 2.0}]
        )
        rows, _ = transform_pff_snapshot(sample, metadata=self.metadata, source="pff")
        markets = {row["market"] for row in rows}
        self.assertIn("player_rush_yds", markets)
        self.assertIn("player_reception_yds", markets)
        self.assertIn("player_receptions", markets)
        self.assertNotIn("player_pass_yds", markets)

    def test_running_back_sample_transforms_into_rushing_receiving_and_receptions(self) -> None:
        sample = pd.DataFrame(
            [{"playerName": "Jahmyr Gibbs", "teamName": "DET", "position": "rb", "passYds": 0.0, "rushYds": 79.7, "recvYds": 30.1, "recvReceptions": 4.2}]
        )
        rows, _ = transform_pff_snapshot(sample, metadata=self.metadata, source="pff")
        markets = {row["market"] for row in rows}
        self.assertEqual(markets, {"player_rush_yds", "player_reception_yds", "player_receptions"})

    def test_structural_passing_zero_for_running_back_is_not_emitted(self) -> None:
        sample = pd.DataFrame(
            [{"playerName": "Jahmyr Gibbs", "teamName": "DET", "position": "rb", "passYds": 0.0, "rushYds": 79.7, "recvYds": 30.1, "recvReceptions": 4.2}]
        )
        rows, _ = transform_pff_snapshot(sample, metadata=self.metadata, source="pff")
        self.assertFalse(any(row["market"] == "player_pass_yds" for row in rows))

    def test_nontraditional_nonzero_stat_is_retained(self) -> None:
        sample = pd.DataFrame(
            [{"playerName": "Tyreek Hill", "teamName": "MIA", "position": "wr", "passYds": 12.5, "rushYds": 0.0, "recvYds": 100.0, "recvReceptions": 6.0}]
        )
        rows, _ = transform_pff_snapshot(sample, metadata=self.metadata, source="pff")
        self.assertTrue(any(row["market"] == "player_pass_yds" and row["projection"] == 12.5 for row in rows))

    def test_canonical_key_uniqueness_is_enforced(self) -> None:
        sample = pd.DataFrame(
            [
                {"playerName": "Duplicate Player", "teamName": "DET", "position": "rb", "passYds": 0.0, "rushYds": 10.0, "recvYds": 0.0, "recvReceptions": 0.0},
                {"playerName": "Duplicate Player", "teamName": "DET", "position": "rb", "passYds": 0.0, "rushYds": 10.0, "recvYds": 0.0, "recvReceptions": 0.0},
            ]
        )
        with self.assertRaisesRegex(ValueError, "duplicate canonical"):
            transform_pff_snapshot(sample, metadata=self.metadata, source="pff")

    def test_reingesting_same_snapshot_does_not_duplicate_weekly_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_root = Path(tmp_dir)
            manifest_path = output_root / "manifest.csv"
            weekly_path = output_root / "projections_long.csv"
            result_1 = ingest_snapshot_file(self.raw_file, source="pff", season=2026, week=1, output_root=output_root, manifest_path=manifest_path, weekly_output_path=weekly_path)
            result_2 = ingest_snapshot_file(self.raw_file, source="pff", season=2026, week=1, output_root=output_root, manifest_path=manifest_path, weekly_output_path=weekly_path)
            self.assertEqual(result_1["rows_written"], result_2["rows_written"])
            self.assertTrue(weekly_path.exists())
            weekly_df = pd.read_csv(weekly_path)
            self.assertEqual(len(weekly_df), result_1["rows_written"])

    def test_raw_input_file_remains_unchanged(self) -> None:
        before = self.raw_file.read_bytes()
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_root = Path(tmp_dir)
            manifest_path = output_root / "manifest.csv"
            weekly_path = output_root / "projections_long.csv"
            ingest_snapshot_file(self.raw_file, source="pff", season=2026, week=1, output_root=output_root, manifest_path=manifest_path, weekly_output_path=weekly_path)
        self.assertEqual(self.raw_file.read_bytes(), before)

    def test_invalid_or_missing_required_pff_columns_fail_clearly(self) -> None:
        sample = pd.DataFrame([{"playerName": "Test", "teamName": "DET", "position": "rb"}])
        with self.assertRaisesRegex(ValueError, "Missing required PFF columns"):
            transform_pff_snapshot(sample, metadata=self.metadata, source="pff")

    def test_baseline_player_values_are_preserved_within_tolerance(self) -> None:
        rows, _ = transform_pff_snapshot(pd.read_csv(self.raw_file), metadata=self.metadata, source="pff")
        gibbs = [row for row in rows if row["player_normalized"] == "jahmyr gibbs"]
        rush = next(row for row in gibbs if row["market"] == "player_rush_yds")
        recv_yds = next(row for row in gibbs if row["market"] == "player_reception_yds")
        receptions = next(row for row in gibbs if row["market"] == "player_receptions")
        self.assertAlmostEqual(rush["projection"], 79.7416, places=4)
        self.assertAlmostEqual(recv_yds["projection"], 30.1683, places=4)
        self.assertAlmostEqual(receptions["projection"], 4.2142, places=4)


if __name__ == "__main__":
    unittest.main()
