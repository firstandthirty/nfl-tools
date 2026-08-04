from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "02_processing"))

from projection_consensus.agreement import evaluate_directional_agreement
from projection_consensus.asof import parse_as_of
from projection_consensus.loader import load_snapshot_registry, load_selected_source_rows
from projection_consensus.aggregation import build_consensus_rows
from projection_consensus.reporting import build_consensus_outputs


class ProjectionConsensusTests(unittest.TestCase):
    def _make_fixture_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "repo"
        (root / "data" / "processed" / "projections").mkdir(parents=True, exist_ok=True)
        return root

    def _write_registry(self, root: Path, rows: list[dict]) -> Path:
        registry_path = root / "data" / "processed" / "projections" / "snapshot_registry.csv"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(registry_path, index=False)
        return registry_path

    def _write_processed_long(self, root: Path, source: str, season: int, week: int, file_name: str, rows: list[dict]) -> Path:
        output_dir = root / "data" / "processed" / "projections" / source / str(season) / f"week_{week}"
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / file_name
        pd.DataFrame(rows).to_csv(path, index=False)
        return path

    def _make_registry_row(self, *, source: str, season: int, week: int, captured_at: str, processed_file: str, raw_file: str, canonical_rows: int = 2) -> dict:
        return {
            "source": source,
            "season": season,
            "week": week,
            "captured_at": captured_at,
            "captured_at_source": "filename",
            "raw_file": raw_file,
            "raw_file_name": Path(raw_file).name,
            "raw_file_sha256": hashlib.sha256(raw_file.encode("utf-8")).hexdigest(),
            "raw_file_size_bytes": 1,
            "processed_long_file": processed_file,
            "processed_rejected_file": "",
            "processed_validation_file": "",
            "processed_file_sha256": hashlib.sha256(processed_file.encode("utf-8")).hexdigest(),
            "ingested_at": captured_at,
            "registry_updated_at": captured_at,
            "raw_rows": canonical_rows,
            "canonical_rows": canonical_rows,
            "unique_players": canonical_rows,
            "unique_teams": 1,
            "positions_covered": "RB",
            "markets_covered": "player_rush_yds",
            "market_count": 1,
            "rejected_rows": 0,
            "rejection_rate": 0.0,
            "duplicate_canonical_keys": 0,
            "validation_status": "passed",
            "warning_count": 0,
            "warnings": "",
            "adapter_version": "adapter_v1",
            "schema_version": "projection_long_v1",
            "days_before_week_start": "",
            "snapshot_stage": "unknown",
        }

    def test_naive_as_of_is_localized_to_america_new_york(self) -> None:
        dt = parse_as_of("2026-08-04T13:00:00")
        self.assertEqual(dt.tzinfo.key, "America/New_York")

    def test_aware_as_of_preserves_the_correct_instant(self) -> None:
        dt = parse_as_of("2026-08-04T17:00:00+00:00")
        self.assertEqual(dt.astimezone(ZoneInfo("UTC")).isoformat(), "2026-08-04T17:00:00+00:00")

    def test_future_snapshots_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            self._write_registry(root, [
                self._make_registry_row(source="pff", season=2026, week=1, captured_at="2026-08-04T14:00:00-04:00", processed_file="data/processed/projections/pff/2026/week_1/pff_long.csv", raw_file="data/raw/projections/pff/2026/week_01/snapshots/a.csv"),
            ])
            self._write_processed_long(root, "pff", 2026, 1, "pff_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T14:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/a.csv"}])
            registry = load_snapshot_registry(root / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=root)
            selected = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-04T13:00:00-04:00", sources=["pff"])
            self.assertEqual(len(selected["selected_snapshots"]), 1)
            self.assertEqual(selected["selected_snapshots"].iloc[0]["selection_status"], "no_snapshot_before_as_of")

    def test_latest_eligible_snapshot_is_selected_per_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            registry_rows = [
                self._make_registry_row(source="pff", season=2026, week=1, captured_at="2026-08-04T10:00:00-04:00", processed_file="data/processed/projections/pff/2026/week_1/pff_old.csv", raw_file="data/raw/projections/pff/2026/week_01/snapshots/old.csv"),
                self._make_registry_row(source="pff", season=2026, week=1, captured_at="2026-08-04T12:00:00-04:00", processed_file="data/processed/projections/pff/2026/week_1/pff_new.csv", raw_file="data/raw/projections/pff/2026/week_01/snapshots/new.csv"),
            ]
            self._write_registry(root, registry_rows)
            self._write_processed_long(root, "pff", 2026, 1, "pff_old.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T10:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/old.csv"}])
            self._write_processed_long(root, "pff", 2026, 1, "pff_new.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":11.0,"captured_at":"2026-08-04T12:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/new.csv"}])
            registry = load_snapshot_registry(root / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=root)
            selected = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-04T13:00:00-04:00", sources=["pff"])
            self.assertEqual(selected["selected_snapshots"].iloc[0]["selected_processed_file"], "data/processed/projections/pff/2026/week_1/pff_new.csv")

    def test_source_without_eligible_snapshot_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            self._write_registry(root, [
                self._make_registry_row(source="pff", season=2026, week=1, captured_at="2026-08-04T10:00:00-04:00", processed_file="data/processed/projections/pff/2026/week_1/pff_long.csv", raw_file="data/raw/projections/pff/2026/week_01/snapshots/a.csv"),
            ])
            self._write_processed_long(root, "pff", 2026, 1, "pff_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T10:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/a.csv"}])
            registry = load_snapshot_registry(root / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=root)
            selected = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-04T09:00:00-04:00", sources=["pff", "fantasypros"])
            self.assertEqual(selected["selected_snapshots"].loc[selected["selected_snapshots"]["source"] == "fantasypros"].iloc[0]["selection_status"], "source_not_available")

    def test_exact_timestamp_equality_is_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            self._write_registry(root, [
                self._make_registry_row(source="pff", season=2026, week=1, captured_at="2026-08-04T13:00:00-04:00", processed_file="data/processed/projections/pff/2026/week_1/pff_long.csv", raw_file="data/raw/projections/pff/2026/week_01/snapshots/a.csv"),
            ])
            self._write_processed_long(root, "pff", 2026, 1, "pff_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T13:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/a.csv"}])
            registry = load_snapshot_registry(root / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=root)
            selected = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-04T13:00:00-04:00", sources=["pff"])
            self.assertEqual(selected["selected_snapshots"].iloc[0]["selection_status"], "selected")

    def test_single_source_consensus_has_count_one_and_std_blank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            self._write_registry(root, [
                self._make_registry_row(source="pff", season=2026, week=1, captured_at="2026-08-04T13:00:00-04:00", processed_file="data/processed/projections/pff/2026/week_1/pff_long.csv", raw_file="data/raw/projections/pff/2026/week_01/snapshots/a.csv"),
            ])
            self._write_processed_long(root, "pff", 2026, 1, "pff_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T13:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/a.csv"}])
            registry = load_snapshot_registry(root / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=root)
            selected = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-04T13:30:00-04:00", sources=["pff"])
            consensus = build_consensus_outputs(selected)
            row = consensus["consensus_rows"].iloc[0]
            self.assertEqual(int(row["projection_count"]), 1)
            self.assertTrue(pd.isna(row["projection_std"]))
            self.assertFalse(row["meets_min_sources"])

    def test_three_source_consensus_calculates_summary_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            registry_rows = [
                self._make_registry_row(source="pff", season=2026, week=1, captured_at="2026-08-04T11:00:00-04:00", processed_file="data/processed/projections/pff/2026/week_1/pff_long.csv", raw_file="data/raw/projections/pff/2026/week_01/snapshots/pff.csv"),
                self._make_registry_row(source="fantasypros", season=2026, week=1, captured_at="2026-08-04T12:00:00-04:00", processed_file="data/processed/projections/fantasypros/2026/week_1/fp_long.csv", raw_file="data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"),
                self._make_registry_row(source="source_c", season=2026, week=1, captured_at="2026-08-04T13:00:00-04:00", processed_file="data/processed/projections/source_c/2026/week_1/sc_long.csv", raw_file="data/raw/projections/source_c/2026/week_01/snapshots/sc.csv"),
            ]
            self._write_registry(root, registry_rows)
            self._write_processed_long(root, "pff", 2026, 1, "pff_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/pff.csv"}])
            self._write_processed_long(root, "fantasypros", 2026, 1, "fp_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"fantasypros","market":"player_rush_yds","projection":12.0,"captured_at":"2026-08-04T12:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"}])
            self._write_processed_long(root, "source_c", 2026, 1, "sc_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"source_c","market":"player_rush_yds","projection":14.0,"captured_at":"2026-08-04T13:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/source_c/2026/week_01/snapshots/sc.csv"}])
            registry = load_snapshot_registry(root / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=root)
            selected = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-04T13:30:00-04:00", sources=["pff", "fantasypros", "source_c"])
            consensus = build_consensus_outputs(selected)
            row = consensus["consensus_rows"].iloc[0]
            self.assertEqual(int(row["projection_count"]), 3)
            self.assertEqual(float(row["projection_mean"]), 12.0)
            self.assertEqual(float(row["projection_median"]), 12.0)
            self.assertEqual(float(row["projection_std"]), 2.0)
            self.assertEqual(float(row["projection_min"]), 10.0)
            self.assertEqual(float(row["projection_max"]), 14.0)
            self.assertEqual(float(row["projection_range"]), 4.0)

    def test_sources_and_source_values_are_sorted_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            self._write_registry(root, [
                self._make_registry_row(source="source_c", season=2026, week=1, captured_at="2026-08-04T13:00:00-04:00", processed_file="data/processed/projections/source_c/2026/week_1/sc_long.csv", raw_file="data/raw/projections/source_c/2026/week_01/snapshots/sc.csv"),
                self._make_registry_row(source="fantasypros", season=2026, week=1, captured_at="2026-08-04T12:00:00-04:00", processed_file="data/processed/projections/fantasypros/2026/week_1/fp_long.csv", raw_file="data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"),
                self._make_registry_row(source="pff", season=2026, week=1, captured_at="2026-08-04T11:00:00-04:00", processed_file="data/processed/projections/pff/2026/week_1/pff_long.csv", raw_file="data/raw/projections/pff/2026/week_01/snapshots/pff.csv"),
            ])
            for source, file_name in [("pff", "pff_long.csv"), ("fantasypros", "fp_long.csv"), ("source_c", "sc_long.csv")]:
                self._write_processed_long(root, source, 2026, 1, file_name, [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":source,"market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/source_c/2026/week_01/snapshots/sc.csv"}])
            registry = load_snapshot_registry(root / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=root)
            selected = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-04T13:30:00-04:00", sources=["source_c", "fantasypros", "pff"])
            consensus = build_consensus_outputs(selected)
            self.assertEqual(consensus["consensus_rows"].iloc[0]["sources"], "fantasypros|pff|source_c")
            self.assertEqual(consensus["consensus_rows"].iloc[0]["source_values"], "fantasypros=10|pff=10|source_c=10")

    def test_same_source_is_not_counted_twice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            self._write_registry(root, [
                self._make_registry_row(source="pff", season=2026, week=1, captured_at="2026-08-04T11:00:00-04:00", processed_file="data/processed/projections/pff/2026/week_1/pff_long.csv", raw_file="data/raw/projections/pff/2026/week_01/snapshots/pff.csv"),
            ])
            self._write_processed_long(root, "pff", 2026, 1, "pff_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/pff.csv"}])
            registry = load_snapshot_registry(root / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=root)
            selected = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-04T13:30:00-04:00", sources=["pff", "pff"])
            self.assertEqual(int(selected["consensus_rows"].iloc[0]["projection_count"]), 1)

    def test_duplicate_canonical_keys_are_audited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            self._write_registry(root, [
                self._make_registry_row(source="pff", season=2026, week=1, captured_at="2026-08-04T11:00:00-04:00", processed_file="data/processed/projections/pff/2026/week_1/pff_long.csv", raw_file="data/raw/projections/pff/2026/week_01/snapshots/pff.csv"),
            ])
            self._write_processed_long(root, "pff", 2026, 1, "pff_long.csv", [
                {"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/pff.csv"},
                {"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":11.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/pff.csv"},
            ])
            registry = load_snapshot_registry(root / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=root)
            selected = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-04T13:30:00-04:00", sources=["pff"])
            self.assertIn("duplicate_canonical_keys", selected["warnings"])

    def test_player_name_conflicts_are_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            self._write_registry(root, [
                self._make_registry_row(source="pff", season=2026, week=1, captured_at="2026-08-04T11:00:00-04:00", processed_file="data/processed/projections/pff/2026/week_1/pff_long.csv", raw_file="data/raw/projections/pff/2026/week_01/snapshots/pff.csv"),
                self._make_registry_row(source="fantasypros", season=2026, week=1, captured_at="2026-08-04T12:00:00-04:00", processed_file="data/processed/projections/fantasypros/2026/week_1/fp_long.csv", raw_file="data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"),
            ])
            self._write_processed_long(root, "pff", 2026, 1, "pff_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/pff.csv"}])
            self._write_processed_long(root, "fantasypros", 2026, 1, "fp_long.csv", [{"player":"B","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"fantasypros","market":"player_rush_yds","projection":12.0,"captured_at":"2026-08-04T12:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"}])
            registry = load_snapshot_registry(root / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=root)
            selected = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-04T13:30:00-04:00", sources=["pff", "fantasypros"])
            consensus = build_consensus_outputs(selected)
            self.assertTrue(consensus["consensus_rows"].iloc[0]["name_conflict"])

    def test_team_conflicts_are_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            self._write_registry(root, [
                self._make_registry_row(source="pff", season=2026, week=1, captured_at="2026-08-04T11:00:00-04:00", processed_file="data/processed/projections/pff/2026/week_1/pff_long.csv", raw_file="data/raw/projections/pff/2026/week_01/snapshots/pff.csv"),
                self._make_registry_row(source="fantasypros", season=2026, week=1, captured_at="2026-08-04T12:00:00-04:00", processed_file="data/processed/projections/fantasypros/2026/week_1/fp_long.csv", raw_file="data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"),
            ])
            self._write_processed_long(root, "pff", 2026, 1, "pff_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/pff.csv"}])
            self._write_processed_long(root, "fantasypros", 2026, 1, "fp_long.csv", [{"player":"A","player_normalized":"a","team":"GB","position":"RB","season":2026,"week":1,"source":"fantasypros","market":"player_rush_yds","projection":12.0,"captured_at":"2026-08-04T12:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"}])
            registry = load_snapshot_registry(root / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=root)
            selected = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-04T13:30:00-04:00", sources=["pff", "fantasypros"])
            consensus = build_consensus_outputs(selected)
            self.assertTrue(consensus["consensus_rows"].iloc[0]["team_conflict"])

    def test_position_conflicts_are_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            self._write_registry(root, [
                self._make_registry_row(source="pff", season=2026, week=1, captured_at="2026-08-04T11:00:00-04:00", processed_file="data/processed/projections/pff/2026/week_1/pff_long.csv", raw_file="data/raw/projections/pff/2026/week_01/snapshots/pff.csv"),
                self._make_registry_row(source="fantasypros", season=2026, week=1, captured_at="2026-08-04T12:00:00-04:00", processed_file="data/processed/projections/fantasypros/2026/week_1/fp_long.csv", raw_file="data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"),
            ])
            self._write_processed_long(root, "pff", 2026, 1, "pff_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/pff.csv"}])
            self._write_processed_long(root, "fantasypros", 2026, 1, "fp_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"WR","season":2026,"week":1,"source":"fantasypros","market":"player_rush_yds","projection":12.0,"captured_at":"2026-08-04T12:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"}])
            registry = load_snapshot_registry(root / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=root)
            selected = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-04T13:30:00-04:00", sources=["pff", "fantasypros"])
            consensus = build_consensus_outputs(selected)
            self.assertTrue(consensus["consensus_rows"].iloc[0]["position_conflict"])

    def test_pairwise_differences_are_correct(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            self._write_registry(root, [
                self._make_registry_row(source="pff", season=2026, week=1, captured_at="2026-08-04T11:00:00-04:00", processed_file="data/processed/projections/pff/2026/week_1/pff_long.csv", raw_file="data/raw/projections/pff/2026/week_01/snapshots/pff.csv"),
                self._make_registry_row(source="fantasypros", season=2026, week=1, captured_at="2026-08-04T12:00:00-04:00", processed_file="data/processed/projections/fantasypros/2026/week_1/fp_long.csv", raw_file="data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"),
            ])
            self._write_processed_long(root, "pff", 2026, 1, "pff_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/pff.csv"}])
            self._write_processed_long(root, "fantasypros", 2026, 1, "fp_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"fantasypros","market":"player_rush_yds","projection":14.0,"captured_at":"2026-08-04T12:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"}])
            registry = load_snapshot_registry(root / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=root)
            selected = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-04T13:30:00-04:00", sources=["pff", "fantasypros"])
            consensus = build_consensus_outputs(selected)
            diff = consensus["pairwise_differences"]
            self.assertEqual(len(diff), 1)
            self.assertEqual(float(diff.iloc[0]["signed_difference_a_minus_b"]), -4.0)

    def test_pairwise_source_ordering_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            self._write_registry(root, [
                self._make_registry_row(source="source_c", season=2026, week=1, captured_at="2026-08-04T13:00:00-04:00", processed_file="data/processed/projections/source_c/2026/week_1/sc_long.csv", raw_file="data/raw/projections/source_c/2026/week_01/snapshots/sc.csv"),
                self._make_registry_row(source="fantasypros", season=2026, week=1, captured_at="2026-08-04T12:00:00-04:00", processed_file="data/processed/projections/fantasypros/2026/week_1/fp_long.csv", raw_file="data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"),
                self._make_registry_row(source="pff", season=2026, week=1, captured_at="2026-08-04T11:00:00-04:00", processed_file="data/processed/projections/pff/2026/week_1/pff_long.csv", raw_file="data/raw/projections/pff/2026/week_01/snapshots/pff.csv"),
            ])
            for source, file_name in [("pff", "pff_long.csv"), ("fantasypros", "fp_long.csv"), ("source_c", "sc_long.csv")]:
                self._write_processed_long(root, source, 2026, 1, file_name, [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":source,"market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/source_c/2026/week_01/snapshots/sc.csv"}])
            registry = load_snapshot_registry(root / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=root)
            selected = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-04T13:30:00-04:00", sources=["source_c", "fantasypros", "pff"])
            consensus = build_consensus_outputs(selected)
            pairwise = consensus["pairwise_differences"]
            self.assertEqual(pairwise.iloc[0]["source_a"], "fantasypros")
            self.assertEqual(pairwise.iloc[0]["source_b"], "pff")

    def test_overlap_metrics_are_correct(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            self._write_registry(root, [
                self._make_registry_row(source="pff", season=2026, week=1, captured_at="2026-08-04T11:00:00-04:00", processed_file="data/processed/projections/pff/2026/week_1/pff_long.csv", raw_file="data/raw/projections/pff/2026/week_01/snapshots/pff.csv"),
                self._make_registry_row(source="fantasypros", season=2026, week=1, captured_at="2026-08-04T12:00:00-04:00", processed_file="data/processed/projections/fantasypros/2026/week_1/fp_long.csv", raw_file="data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"),
            ])
            self._write_processed_long(root, "pff", 2026, 1, "pff_long.csv", [
                {"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/pff.csv"},
                {"player":"B","player_normalized":"b","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/pff.csv"},
            ])
            self._write_processed_long(root, "fantasypros", 2026, 1, "fp_long.csv", [
                {"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"fantasypros","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T12:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"},
                {"player":"C","player_normalized":"c","team":"DET","position":"RB","season":2026,"week":1,"source":"fantasypros","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T12:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"},
            ])
            registry = load_snapshot_registry(root / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=root)
            selected = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-04T13:30:00-04:00", sources=["pff", "fantasypros"])
            consensus = build_consensus_outputs(selected)
            overlap = consensus["source_overlap"]
            self.assertEqual(int(overlap.iloc[0]["shared_players"]), 1)
            self.assertEqual(float(overlap.iloc[0]["jaccard_similarity"]), 0.5)

    def test_minimum_source_eligibility_works(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            self._write_registry(root, [
                self._make_registry_row(source="pff", season=2026, week=1, captured_at="2026-08-04T11:00:00-04:00", processed_file="data/processed/projections/pff/2026/week_1/pff_long.csv", raw_file="data/raw/projections/pff/2026/week_01/snapshots/pff.csv"),
            ])
            self._write_processed_long(root, "pff", 2026, 1, "pff_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/pff.csv"}])
            registry = load_snapshot_registry(root / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=root)
            selected = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-04T13:30:00-04:00", sources=["pff"], min_sources=3)
            consensus = build_consensus_outputs(selected)
            self.assertFalse(consensus["consensus_rows"].iloc[0]["meets_min_sources"])
            self.assertFalse(consensus["consensus_rows"].iloc[0]["consensus_eligible"])

    def test_max_projection_std_eligibility_works(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            self._write_registry(root, [
                self._make_registry_row(source="pff", season=2026, week=1, captured_at="2026-08-04T11:00:00-04:00", processed_file="data/processed/projections/pff/2026/week_1/pff_long.csv", raw_file="data/raw/projections/pff/2026/week_01/snapshots/pff.csv"),
                self._make_registry_row(source="fantasypros", season=2026, week=1, captured_at="2026-08-04T12:00:00-04:00", processed_file="data/processed/projections/fantasypros/2026/week_1/fp_long.csv", raw_file="data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"),
            ])
            self._write_processed_long(root, "pff", 2026, 1, "pff_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/pff.csv"}])
            self._write_processed_long(root, "fantasypros", 2026, 1, "fp_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"fantasypros","market":"player_rush_yds","projection":20.0,"captured_at":"2026-08-04T12:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"}])
            registry = load_snapshot_registry(root / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=root)
            selected = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-04T13:30:00-04:00", sources=["pff", "fantasypros"], max_projection_std=1.0)
            consensus = build_consensus_outputs(selected)
            self.assertFalse(consensus["consensus_rows"].iloc[0]["meets_max_std"])

    def test_max_projection_range_eligibility_works(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            self._write_registry(root, [
                self._make_registry_row(source="pff", season=2026, week=1, captured_at="2026-08-04T11:00:00-04:00", processed_file="data/processed/projections/pff/2026/week_1/pff_long.csv", raw_file="data/raw/projections/pff/2026/week_01/snapshots/pff.csv"),
                self._make_registry_row(source="fantasypros", season=2026, week=1, captured_at="2026-08-04T12:00:00-04:00", processed_file="data/processed/projections/fantasypros/2026/week_1/fp_long.csv", raw_file="data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"),
            ])
            self._write_processed_long(root, "pff", 2026, 1, "pff_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/pff.csv"}])
            self._write_processed_long(root, "fantasypros", 2026, 1, "fp_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"fantasypros","market":"player_rush_yds","projection":20.0,"captured_at":"2026-08-04T12:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"}])
            registry = load_snapshot_registry(root / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=root)
            selected = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-04T13:30:00-04:00", sources=["pff", "fantasypros"], max_projection_range=5.0)
            consensus = build_consensus_outputs(selected)
            self.assertFalse(consensus["consensus_rows"].iloc[0]["meets_max_range"])

    def test_required_source_eligibility_works(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            self._write_registry(root, [
                self._make_registry_row(source="pff", season=2026, week=1, captured_at="2026-08-04T11:00:00-04:00", processed_file="data/processed/projections/pff/2026/week_1/pff_long.csv", raw_file="data/raw/projections/pff/2026/week_01/snapshots/pff.csv"),
                self._make_registry_row(source="fantasypros", season=2026, week=1, captured_at="2026-08-04T12:00:00-04:00", processed_file="data/processed/projections/fantasypros/2026/week_1/fp_long.csv", raw_file="data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"),
            ])
            self._write_processed_long(root, "pff", 2026, 1, "pff_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/pff.csv"}])
            self._write_processed_long(root, "fantasypros", 2026, 1, "fp_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"fantasypros","market":"player_rush_yds","projection":20.0,"captured_at":"2026-08-04T12:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"}])
            registry = load_snapshot_registry(root / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=root)
            selected = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-04T13:30:00-04:00", sources=["pff", "fantasypros"], required_sources=["source_c"])
            consensus = build_consensus_outputs(selected)
            self.assertFalse(consensus["consensus_rows"].iloc[0]["has_required_sources"])

    def test_snapshot_age_eligibility_works_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            self._write_registry(root, [
                self._make_registry_row(source="pff", season=2026, week=1, captured_at="2026-08-04T11:00:00-04:00", processed_file="data/processed/projections/pff/2026/week_1/pff_long.csv", raw_file="data/raw/projections/pff/2026/week_01/snapshots/pff.csv"),
                self._make_registry_row(source="fantasypros", season=2026, week=1, captured_at="2026-08-04T12:00:00-04:00", processed_file="data/processed/projections/fantasypros/2026/week_1/fp_long.csv", raw_file="data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"),
            ])
            self._write_processed_long(root, "pff", 2026, 1, "pff_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/pff.csv"}])
            self._write_processed_long(root, "fantasypros", 2026, 1, "fp_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"fantasypros","market":"player_rush_yds","projection":20.0,"captured_at":"2026-08-04T12:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"}])
            registry = load_snapshot_registry(root / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=root)
            selected = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-04T13:00:00-04:00", sources=["pff", "fantasypros"], max_snapshot_age_hours=2.0)
            consensus = build_consensus_outputs(selected)
            self.assertFalse(consensus["consensus_rows"].iloc[0]["meets_max_snapshot_age"])

    def test_source_time_gap_eligibility_works_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._make_fixture_root(Path(tmp_dir))
            self._write_registry(root, [
                self._make_registry_row(source="pff", season=2026, week=1, captured_at="2026-08-04T11:00:00-04:00", processed_file="data/processed/projections/pff/2026/week_1/pff_long.csv", raw_file="data/raw/projections/pff/2026/week_01/snapshots/pff.csv"),
                self._make_registry_row(source="fantasypros", season=2026, week=1, captured_at="2026-08-04T12:00:00-04:00", processed_file="data/processed/projections/fantasypros/2026/week_1/fp_long.csv", raw_file="data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"),
            ])
            self._write_processed_long(root, "pff", 2026, 1, "pff_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"pff","market":"player_rush_yds","projection":10.0,"captured_at":"2026-08-04T11:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/pff/2026/week_01/snapshots/pff.csv"}])
            self._write_processed_long(root, "fantasypros", 2026, 1, "fp_long.csv", [{"player":"A","player_normalized":"a","team":"DET","position":"RB","season":2026,"week":1,"source":"fantasypros","market":"player_rush_yds","projection":20.0,"captured_at":"2026-08-04T12:00:00-04:00","captured_at_source":"filename","raw_file":"data/raw/projections/fantasypros/2026/week_01/snapshots/fp.csv"}])
            registry = load_snapshot_registry(root / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=root)
            selected = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-04T13:00:00-04:00", sources=["pff", "fantasypros"], max_source_time_gap_hours=0.5)
            consensus = build_consensus_outputs(selected)
            self.assertFalse(consensus["consensus_rows"].iloc[0]["meets_max_source_time_gap"])

    def test_directional_agreement_helper_is_unanimous_over(self) -> None:
        result = evaluate_directional_agreement([10.0, 11.0, 12.0], 9.0)
        self.assertEqual(result["above_count"], 3)
        self.assertTrue(result["unanimous_over"])

    def test_directional_agreement_helper_is_unanimous_under(self) -> None:
        result = evaluate_directional_agreement([10.0, 11.0, 12.0], 13.0)
        self.assertTrue(result["unanimous_under"])

    def test_directional_agreement_helper_handles_split_sources(self) -> None:
        result = evaluate_directional_agreement([10.0, 12.0], 11.0)
        self.assertEqual(result["above_count"], 1)
        self.assertEqual(result["below_count"], 1)

    def test_directional_agreement_helper_handles_exact_equal(self) -> None:
        result = evaluate_directional_agreement([10.0, 10.0], 10.0)
        self.assertEqual(result["equal_count"], 2)

    def test_real_pff_data_produces_single_source_ineligible_consensus(self) -> None:
        registry = load_snapshot_registry(ROOT / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=ROOT)
        selected = build_consensus_rows(registry=registry, project_root=ROOT, season=2026, week=1, as_of="2026-08-04T13:30:00-04:00", sources=["pff"], min_sources=3)
        consensus = build_consensus_outputs(selected)
        self.assertEqual(int(consensus["consensus_rows"].iloc[0]["projection_count"]), 1)
        self.assertFalse(consensus["consensus_rows"].iloc[0]["meets_min_sources"])
        self.assertFalse(consensus["consensus_rows"].iloc[0]["consensus_eligible"])

    def test_source_files_and_registry_remain_unchanged(self) -> None:
        registry_path = ROOT / "data" / "processed" / "projections" / "snapshot_registry.csv"
        long_path = ROOT / "data" / "processed" / "projections" / "pff" / "2026" / "week_1" / "projections_long.csv"
        before_registry = hashlib.sha256(registry_path.read_bytes()).hexdigest()
        before_long = hashlib.sha256(long_path.read_bytes()).hexdigest()
        registry = load_snapshot_registry(registry_path, project_root=ROOT)
        build_consensus_rows(registry=registry, project_root=ROOT, season=2026, week=1, as_of="2026-08-04T13:30:00-04:00", sources=["pff"], min_sources=3)
        self.assertEqual(hashlib.sha256(registry_path.read_bytes()).hexdigest(), before_registry)
        self.assertEqual(hashlib.sha256(long_path.read_bytes()).hexdigest(), before_long)


if __name__ == "__main__":
    unittest.main()
