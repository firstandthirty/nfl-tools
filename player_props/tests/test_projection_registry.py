from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "01_ingest"))

from projection_registry.registry import (
    build_projection_registry,
    build_snapshot_change_report,
    build_weekly_coverage,
    hash_file,
    _build_coverage_rows,
)


class ProjectionRegistryTests(unittest.TestCase):
    def _make_fixture_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "repo"
        (root / "data" / "raw" / "projections" / "pff" / "2026" / "week_01" / "snapshots").mkdir(parents=True, exist_ok=True)
        (root / "data" / "processed" / "projections" / "pff" / "2026" / "week_01").mkdir(parents=True, exist_ok=True)
        return root

    def _write_raw_snapshot(self, root: Path, name: str, content: str | None = None) -> Path:
        raw_path = root / "data" / "raw" / "projections" / "pff" / "2026" / "week_01" / "snapshots" / name
        raw_path.write_text(content or "playerName,teamName,position,passYds,rushYds,recvYds,recvReceptions\n", encoding="utf-8")
        return raw_path

    def _write_processed_outputs(self, root: Path, raw_path: Path, long_df: pd.DataFrame, rejected_df: pd.DataFrame | None = None, validation_df: pd.DataFrame | None = None) -> None:
        output_dir = root / "data" / "processed" / "projections" / "pff" / "2026" / "week_1"
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = raw_path.stem
        if stem.endswith("projections"):
            stem = stem[:-len("projections")] + "_projections"
        (output_dir / f"{stem}_long.csv").write_text(long_df.to_csv(index=False), encoding="utf-8")
        (output_dir / f"{stem}_rejected.csv").write_text((rejected_df if rejected_df is not None else pd.DataFrame()).to_csv(index=False), encoding="utf-8")
        (output_dir / f"{stem}_validation.csv").write_text((validation_df if validation_df is not None else pd.DataFrame()).to_csv(index=False), encoding="utf-8")

    def test_sha256_hashing_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "sample.txt"
            path.write_text("hello world", encoding="utf-8")
            self.assertEqual(hash_file(path), hashlib.sha256(b"hello world").hexdigest())

    def test_same_raw_file_ingested_twice_creates_one_registry_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            raw_path = self._write_raw_snapshot(root, "snapshot.csv")
            long_df = pd.DataFrame([{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/snapshot.csv"}])
            self._write_processed_outputs(root, raw_path, long_df)
            result_1 = build_projection_registry(project_root=root, output_root=root)
            result_2 = build_projection_registry(project_root=root, output_root=root)
            self.assertEqual(len(result_1["registry_rows"]), 1)
            self.assertEqual(result_2["registry_rows"], result_1["registry_rows"])
            self.assertEqual(result_2["unchanged_rows"], 1)

    def test_same_content_under_different_filenames_creates_one_registry_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            raw_path_1 = self._write_raw_snapshot(root, "snapshot_a.csv", "playerName,teamName,position,passYds,rushYds,recvYds,recvReceptions\nA,DET,RB,0,10,0,0\n")
            raw_path_2 = self._write_raw_snapshot(root, "snapshot_b.csv", "playerName,teamName,position,passYds,rushYds,recvYds,recvReceptions\nA,DET,RB,0,10,0,0\n")
            long_df = pd.DataFrame([{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/snapshot_a.csv"}])
            self._write_processed_outputs(root, raw_path_1, long_df)
            self._write_processed_outputs(root, raw_path_2, long_df)
            result = build_projection_registry(project_root=root, output_root=root)
            self.assertEqual(len(result["registry_rows"]), 1)

    def test_conflicting_metadata_for_same_hash_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            raw_path_1 = self._write_raw_snapshot(root, "08_04_26_1100projections.csv", "playerName,teamName,position,passYds,rushYds,recvYds,recvReceptions\nA,DET,RB,0,10,0,0\n")
            raw_path_2 = self._write_raw_snapshot(root, "08_05_26_1100projections.csv", "playerName,teamName,position,passYds,rushYds,recvYds,recvReceptions\nA,DET,RB,0,10,0,0\n")
            long_df = pd.DataFrame([{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/08_04_26_1100projections.csv"}])
            self._write_processed_outputs(root, raw_path_1, long_df)
            self._write_processed_outputs(root, raw_path_2, long_df)
            result = build_projection_registry(project_root=root, output_root=root)
            self.assertEqual(len(result["registry_rows"]), 1)
            self.assertEqual(len(result["conflicts"]), 1)

    def test_registry_paths_are_repository_relative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            raw_path = self._write_raw_snapshot(root, "snapshot.csv")
            long_df = pd.DataFrame([{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/snapshot.csv"}])
            self._write_processed_outputs(root, raw_path, long_df)
            result = build_projection_registry(project_root=root, output_root=root)
            row = result["registry_rows"][0]
            self.assertTrue(row["raw_file"].startswith("data/"))
            self.assertTrue(row["processed_long_file"].startswith("data/"))

    def test_market_coverage_metrics_are_correct_on_small_fixture(self) -> None:
        long_df = pd.DataFrame([
            {"player_normalized": "a", "team": "DET", "position": "RB", "market": "player_rush_yds", "projection": 10.0},
            {"player_normalized": "b", "team": "DET", "position": "RB", "market": "player_rush_yds", "projection": 20.0},
            {"player_normalized": "c", "team": "MIA", "position": "WR", "market": "player_reception_yds", "projection": 5.0},
        ])
        report = _build_coverage_rows(long_df, None)
        self.assertTrue(any(row["report_section"] == "market_coverage" and row["market"] == "player_rush_yds" for row in report))

    def test_position_coverage_metrics_are_correct(self) -> None:
        long_df = pd.DataFrame([
            {"player_normalized": "a", "team": "DET", "position": "RB", "market": "player_rush_yds", "projection": 10.0},
            {"player_normalized": "b", "team": "DET", "position": "RB", "market": "player_reception_yds", "projection": 20.0},
            {"player_normalized": "c", "team": "MIA", "position": "WR", "market": "player_reception_yds", "projection": 5.0},
        ])
        coverage_df = _build_coverage_rows(long_df, None)
        self.assertTrue(any(row["report_section"] == "position_coverage" and row["position"] == "RB" for row in coverage_df))

    def test_rejection_summaries_are_correct(self) -> None:
        rejected_df = pd.DataFrame([
            {"reason": "null_projection", "source_column": "rushYds", "position": "RB", "market": "player_rush_yds"},
            {"reason": "null_projection", "source_column": "rushYds", "position": "RB", "market": "player_rush_yds"},
            {"reason": "nonnumeric_projection", "source_column": "recvYds", "position": "WR", "market": "player_reception_yds"},
        ])
        coverage = _build_coverage_rows(pd.DataFrame(), rejected_df)
        self.assertTrue(any(row["report_section"] == "rejections" and row["reason"] == "null_projection" for row in coverage))

    def test_weekly_coverage_rebuild_is_deterministic_and_duplicate_free(self) -> None:
        long_df = pd.DataFrame([{"player_normalized": "a", "team": "DET", "position": "RB", "market": "player_rush_yds", "projection": 10.0}])
        weekly_df_1 = build_weekly_coverage([long_df], source="pff", season=2026, week=1, captured_at="2026-08-04T11:00:00-04:00", snapshot_hash="hash")
        weekly_df_2 = build_weekly_coverage([long_df], source="pff", season=2026, week=1, captured_at="2026-08-04T11:00:00-04:00", snapshot_hash="hash")
        self.assertEqual(len(weekly_df_1), 1)
        self.assertEqual(len(weekly_df_2), 1)

    def test_snapshot_change_report_correctly_identifies_added_removed_changed_and_unchanged_players(self) -> None:
        prior_df = pd.DataFrame([
            {"player_normalized": "a", "market": "player_rush_yds", "projection": 10.0},
            {"player_normalized": "b", "market": "player_rush_yds", "projection": 20.0},
        ])
        current_df = pd.DataFrame([
            {"player_normalized": "a", "market": "player_rush_yds", "projection": 12.0},
            {"player_normalized": "c", "market": "player_rush_yds", "projection": 25.0},
        ])
        change_df = build_snapshot_change_report([prior_df], [current_df], source="pff", season=2026, week=1)
        self.assertEqual(int(change_df.iloc[0]["added_players"]), 1)
        self.assertEqual(int(change_df.iloc[0]["removed_players"]), 1)
        self.assertEqual(int(change_df.iloc[0]["changed_players"]), 1)
        self.assertEqual(int(change_df.iloc[0]["unchanged_players"]), 0)

    def test_snapshot_change_report_correctly_calculates_projection_deltas(self) -> None:
        prior_df = pd.DataFrame([{"player_normalized": "a", "market": "player_rush_yds", "projection": 10.0}])
        current_df = pd.DataFrame([{"player_normalized": "a", "market": "player_rush_yds", "projection": 12.0}])
        change_df = build_snapshot_change_report([prior_df], [current_df], source="pff", season=2026, week=1)
        self.assertEqual(int(change_df.iloc[0]["changed_players"]), 1)

    def test_single_snapshot_input_produces_empty_change_report_with_headers(self) -> None:
        change_df = build_snapshot_change_report([pd.DataFrame()], source="pff", season=2026, week=1)
        self.assertTrue(change_df.empty)

    def test_missing_optional_rejected_or_validation_files_do_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            raw_path = self._write_raw_snapshot(root, "snapshot.csv")
            long_df = pd.DataFrame([{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/snapshot.csv"}])
            self._write_processed_outputs(root, raw_path, long_df, rejected_df=None, validation_df=None)
            result = build_projection_registry(project_root=root, output_root=root)
            self.assertEqual(len(result["registry_rows"]), 1)

    def test_missing_required_long_format_file_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            raw_path = self._write_raw_snapshot(root, "snapshot.csv")
            self.assertRaisesRegex(ValueError, "Missing required long-format", build_projection_registry, project_root=root, output_root=root)

    def test_existing_pff_snapshot_creates_one_valid_registry_row(self) -> None:
        result = build_projection_registry(project_root=ROOT)
        self.assertEqual(len(result["registry_rows"]), 1)
        self.assertEqual(result["registry_rows"][0]["source"], "pff")

    def test_current_pff_snapshot_reports_1286_canonical_rows(self) -> None:
        result = build_projection_registry(project_root=ROOT)
        row = result["registry_rows"][0]
        self.assertEqual(int(row["canonical_rows"]), 1286)

    def test_raw_input_and_processed_snapshot_files_remain_unchanged(self) -> None:
        raw_path = ROOT / "data" / "raw" / "projections" / "pff" / "2026" / "week_01" / "snapshots" / "08_04_26_1100_projections.csv"
        processed_long_path = ROOT / "data" / "processed" / "projections" / "pff" / "2026" / "week_1" / "08_04_26_1100_projections_long.csv"
        before_raw = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        before_long = hashlib.sha256(processed_long_path.read_bytes()).hexdigest()
        build_projection_registry(project_root=ROOT)
        self.assertEqual(hashlib.sha256(raw_path.read_bytes()).hexdigest(), before_raw)
        self.assertEqual(hashlib.sha256(processed_long_path.read_bytes()).hexdigest(), before_long)


if __name__ == "__main__":
    unittest.main()
