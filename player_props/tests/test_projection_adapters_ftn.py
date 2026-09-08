from __future__ import annotations

import json
import shutil
import sys
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "01_ingest"))
sys.path.insert(0, str(ROOT / "scripts" / "02_processing"))
sys.path.insert(0, str(ROOT / "scripts" / "03_modeling"))

from ingest_projection_snapshots import _group_ftn_files, ingest_ftn_snapshot
from projection_adapters.common import SnapshotMetadata, discover_snapshot_files, parse_snapshot_metadata
from projection_adapters.ftn import (
    EXPECTED_COLUMNS,
    build_validation_report,
    identify_source_file_type,
    read_ftn_csv,
    transform_ftn_file,
    transform_ftn_snapshot,
)
from projection_consensus.aggregation import build_consensus_rows
from projection_consensus.loader import load_snapshot_registry
from projection_registry.registry import build_projection_registry
from prospective_projection_signal import load_policy


FTN_HEADER = (
    "PLAYER INFO,PLAYER INFO,PLAYER INFO,PLAYER INFO,PLAYER INFO,STATS,STATS,STATS,STATS,STATS,STATS,STATS,STATS,STATS,STATS,STATS,STATS,STATS,STATS\n"
    "Player,Position,Team,Opp.,Auction,PaCom,PaAtt,PaYds,PaTD,PaINT,RuAtt,RuYds,RuTD,Fum.,Tar,Rec,ReYds,ReTD,FPTS\n"
)
FTN_QB = FTN_HEADER + "Test QB,QB,BUF,NYJ,,20,30,240.5,2,1,5,22.5,0,0,,,,,18\n"
FTN_FLEX = (
    FTN_HEADER
    + "Test RB,RB,DET,NO,,,,,,,12,55.5,1,0,5,4,31.5,0,15\n"
    + "Test WR,WR,MIA,NE,,,,,,,0,0,0,0,8,6,72.5,1,16\n"
)
TMP_ROOT = ROOT / "tests" / "fixtures_tmp_ftn"


@contextmanager
def _repo_tmp():
    name = f"case_{datetime.now(ZoneInfo('UTC')).strftime('%H%M%S%f')}"
    root = TMP_ROOT / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield str(root)
    finally:
        if root.exists():
            shutil.rmtree(root)


def _metadata(path: Path | str = "09_07_26_2000_projections.csv") -> SnapshotMetadata:
    return parse_snapshot_metadata(Path(path), source="ftn", season=2026, week=1)


def _write_ftn_snapshot(root: Path, *, season_snapshots: bool = True) -> tuple[Path, Path]:
    if season_snapshots:
        snapshots = root / "data" / "raw" / "projections" / "ftn" / "2026" / "snapshots"
    else:
        snapshots = root / "data" / "raw" / "projections" / "ftn" / "2026" / "week_01"
    snapshots.mkdir(parents=True, exist_ok=True)
    qb = snapshots / "09_07_26_2000_NFL Fantasy Football Player Projections (2026 Season) QB.csv"
    flex = snapshots / "09_07_26_2000_NFL Fantasy Football Player Projections (2026 Season) FLEX.csv"
    qb.write_text(FTN_QB, encoding="utf-8")
    flex.write_text(FTN_FLEX, encoding="utf-8")
    return qb, flex


class FTNProjectionAdapterTests(unittest.TestCase):
    def test_identifies_qb_file_type(self) -> None:
        self.assertEqual(identify_source_file_type("09_07_26_2000_NFL QB.csv"), "qb")

    def test_identifies_flex_file_type(self) -> None:
        self.assertEqual(identify_source_file_type("09_07_26_2000_NFL FLEX.csv"), "flex")

    def test_unknown_file_type_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "Could not identify FTN source file type"):
            identify_source_file_type("09_07_26_2000_NFL DEF.csv")

    def test_read_ftn_csv_uses_second_header_row(self) -> None:
        with _repo_tmp() as tmp:
            qb, _ = _write_ftn_snapshot(Path(tmp))
            frame = read_ftn_csv(qb)
            self.assertEqual(list(frame.columns), EXPECTED_COLUMNS)
            self.assertEqual(frame.iloc[0]["Player"], "Test QB")

    def test_timestamp_parses_from_ftn_filename(self) -> None:
        metadata = _metadata("09_07_26_2000_projections.csv")
        self.assertEqual(metadata.captured_at.isoformat(), "2026-09-07T20:00:00-04:00")
        self.assertEqual(metadata.captured_at_source, "filename")

    def test_qb_maps_passing_yards(self) -> None:
        with _repo_tmp() as tmp:
            qb, _ = _write_ftn_snapshot(Path(tmp))
            rows, _ = transform_ftn_file(read_ftn_csv(qb), raw_file=qb, metadata=_metadata(qb))
            values = {row["market"]: row["projection"] for row in rows}
            self.assertEqual(values["player_pass_yds"], 240.5)

    def test_qb_maps_rushing_yards(self) -> None:
        with _repo_tmp() as tmp:
            qb, _ = _write_ftn_snapshot(Path(tmp))
            rows, _ = transform_ftn_file(read_ftn_csv(qb), raw_file=qb, metadata=_metadata(qb))
            values = {row["market"]: row["projection"] for row in rows}
            self.assertEqual(values["player_rush_yds"], 22.5)

    def test_flex_maps_receiving_yards(self) -> None:
        with _repo_tmp() as tmp:
            _, flex = _write_ftn_snapshot(Path(tmp))
            rows, _ = transform_ftn_file(read_ftn_csv(flex), raw_file=flex, metadata=_metadata(flex))
            wr = {row["market"]: row["projection"] for row in rows if row["player_normalized"] == "test wr"}
            self.assertEqual(wr["player_reception_yds"], 72.5)

    def test_flex_maps_receptions(self) -> None:
        with _repo_tmp() as tmp:
            _, flex = _write_ftn_snapshot(Path(tmp))
            rows, _ = transform_ftn_file(read_ftn_csv(flex), raw_file=flex, metadata=_metadata(flex))
            wr = {row["market"]: row["projection"] for row in rows if row["player_normalized"] == "test wr"}
            self.assertEqual(wr["player_receptions"], 6.0)

    def test_ignores_fpts_column(self) -> None:
        with _repo_tmp() as tmp:
            _, flex = _write_ftn_snapshot(Path(tmp))
            rows, _ = transform_ftn_file(read_ftn_csv(flex), raw_file=flex, metadata=_metadata(flex))
            self.assertNotIn("FPTS", {row["source_column"] for row in rows})

    def test_preserves_raw_player_and_normalized_player(self) -> None:
        with _repo_tmp() as tmp:
            qb, _ = _write_ftn_snapshot(Path(tmp))
            row = transform_ftn_file(read_ftn_csv(qb), raw_file=qb, metadata=_metadata(qb))[0][0]
            self.assertEqual(row["player"], "Test QB")
            self.assertEqual(row["player_normalized"], "test qb")

    def test_preserves_team_and_opponent_lineage(self) -> None:
        with _repo_tmp() as tmp:
            _, flex = _write_ftn_snapshot(Path(tmp))
            row = transform_ftn_file(read_ftn_csv(flex), raw_file=flex, metadata=_metadata(flex))[0][0]
            self.assertEqual(row["team_raw"], "DET")
            self.assertEqual(row["opponent_raw"], "NO")

    def test_non_numeric_projection_is_rejected(self) -> None:
        frame = pd.DataFrame([["Player"] * len(EXPECTED_COLUMNS)], columns=EXPECTED_COLUMNS)
        frame.loc[0, ["Player", "Position", "Team", "Opp.", "PaYds"]] = ["Bad QB", "QB", "BUF", "NYJ", "N/A"]
        rows, rejected = transform_ftn_file(frame, raw_file="09_07_26_2000_QB.csv", metadata=_metadata())
        self.assertFalse(any(row["market"] == "player_pass_yds" for row in rows))
        self.assertIn("nonnumeric_projection", {row["reason"] for row in rejected})

    def test_non_applicable_zero_is_rejected(self) -> None:
        with _repo_tmp() as tmp:
            _, flex = _write_ftn_snapshot(Path(tmp))
            rows, rejected = transform_ftn_file(read_ftn_csv(flex), raw_file=flex, metadata=_metadata(flex))
            self.assertNotIn(("test wr", "player_rush_yds"), {(row["player_normalized"], row["market"]) for row in rows})
            self.assertIn("not_applicable", {row["reason"] for row in rejected})

    def test_missing_player_is_rejected(self) -> None:
        frame = pd.DataFrame([[""] * len(EXPECTED_COLUMNS)], columns=EXPECTED_COLUMNS)
        rows, rejected = transform_ftn_file(frame, raw_file="09_07_26_2000_QB.csv", metadata=_metadata())
        self.assertFalse(rows)
        self.assertEqual(rejected[0]["reason"], "missing_player")

    def test_unexpected_header_fails_clearly(self) -> None:
        frame = pd.DataFrame(columns=["Player", "Team", "PaYds"])
        with self.assertRaisesRegex(ValueError, "Unexpected FTN QB"):
            transform_ftn_file(frame, raw_file="09_07_26_2000_QB.csv", metadata=_metadata())

    def test_qb_and_flex_form_one_logical_snapshot(self) -> None:
        with _repo_tmp() as tmp:
            qb, flex = _write_ftn_snapshot(Path(tmp))
            self.assertEqual(_group_ftn_files([qb, flex]), [[qb, flex]])

    def test_missing_logical_component_fails_clearly(self) -> None:
        with _repo_tmp() as tmp:
            qb, _ = _write_ftn_snapshot(Path(tmp))
            with self.assertRaisesRegex(ValueError, "Incomplete FTN logical snapshot"):
                _group_ftn_files([qb])

    def test_transform_snapshot_uses_single_ftn_source(self) -> None:
        with _repo_tmp() as tmp:
            qb, flex = _write_ftn_snapshot(Path(tmp))
            rows, _ = transform_ftn_snapshot({"qb": read_ftn_csv(qb), "flex": read_ftn_csv(flex)}, metadata=_metadata(qb))
            self.assertEqual({row["source"] for row in rows}, {"ftn"})

    def test_duplicate_player_market_across_components_is_not_double_counted(self) -> None:
        with _repo_tmp() as tmp:
            qb, flex = _write_ftn_snapshot(Path(tmp))
            with flex.open("a", encoding="utf-8") as handle:
                handle.write("Test QB,QB,BUF,NYJ,,20,30,241,2,1,5,23,0,0,,,,,18\n")
            rows, rejected = transform_ftn_snapshot({"qb": read_ftn_csv(qb), "flex": read_ftn_csv(flex)}, metadata=_metadata(qb))
            keys = [(row["player_normalized"], row["market"]) for row in rows]
            self.assertEqual(len(keys), len(set(keys)))
            self.assertIn("duplicate_logical_projection", {row["reason"] for row in rejected})

    def test_ingest_writes_week_01_output(self) -> None:
        with _repo_tmp() as tmp:
            root = Path(tmp)
            qb, flex = _write_ftn_snapshot(root)
            result = ingest_ftn_snapshot([qb, flex], season=2026, week=1, output_root=root, skip_registry_update=True)
            long_path = root / "data" / "processed" / "projections" / "ftn" / "2026" / "week_01" / "09_07_26_2000_projections_long.csv"
            self.assertEqual(result["output_paths"]["long"], str(long_path))
            self.assertTrue(long_path.exists())

    def test_ingest_is_idempotent_by_component_key(self) -> None:
        with _repo_tmp() as tmp:
            root = Path(tmp)
            qb, flex = _write_ftn_snapshot(root)
            first = ingest_ftn_snapshot([qb, flex], season=2026, week=1, output_root=root, skip_registry_update=True)
            second = ingest_ftn_snapshot([qb, flex], season=2026, week=1, output_root=root, skip_registry_update=True)
            self.assertEqual(first["rows_written"], second["rows_written"])
            self.assertTrue(second["skipped"])

    def test_registry_records_ftn_as_one_source_with_components(self) -> None:
        with _repo_tmp() as tmp:
            root = Path(tmp)
            qb, flex = _write_ftn_snapshot(root)
            ingest_ftn_snapshot([qb, flex], season=2026, week=1, output_root=root, skip_registry_update=True)
            result = build_projection_registry(project_root=root, output_root=root, source="ftn", season=2026, week=1)
            self.assertEqual(len(result["registry_rows"]), 1)
            row = result["registry_rows"][0]
            self.assertEqual(row["source"], "ftn")
            self.assertIn("QB.csv", row["component_raw_file_names"])
            self.assertIn("FLEX.csv", row["component_raw_file_names"])

    def test_discovery_prefers_season_snapshots_over_week_copies(self) -> None:
        with _repo_tmp() as tmp:
            root = Path(tmp)
            _write_ftn_snapshot(root, season_snapshots=True)
            _write_ftn_snapshot(root, season_snapshots=False)
            discovered = discover_snapshot_files(root, source="ftn", season=2026, week=1)
            self.assertEqual(len(discovered), 2)
            self.assertTrue(all("snapshots" in str(path) for path in discovered))

    def test_consensus_counts_ftn_as_third_logical_source(self) -> None:
        with _repo_tmp() as tmp:
            root = Path(tmp)
            processed = root / "data" / "processed" / "projections"
            registry_rows = []
            for source, projection in [("pff", 10.0), ("fantasypros", 11.0), ("ftn", 12.0)]:
                output_dir = processed / source / "2026" / "week_01"
                output_dir.mkdir(parents=True, exist_ok=True)
                long_file = output_dir / f"{source}_long.csv"
                pd.DataFrame([{"player": "A", "player_normalized": "a", "team": "BUF", "position": "RB", "season": 2026, "week": 1, "source": source, "market": "player_rush_yds", "projection": projection, "captured_at": "2026-09-07T20:00:00-04:00", "captured_at_source": "filename", "raw_file": f"data/raw/projections/{source}/source.csv"}]).to_csv(long_file, index=False)
                registry_rows.append({"source": source, "season": 2026, "week": 1, "captured_at": "2026-09-07T20:00:00-04:00", "processed_long_file": str(long_file.relative_to(root)).replace("\\", "/"), "raw_file": f"data/raw/projections/{source}/source.csv", "raw_file_sha256": source, "canonical_rows": 1})
            registry_path = processed / "snapshot_registry.csv"
            pd.DataFrame(registry_rows).to_csv(registry_path, index=False)
            registry = load_snapshot_registry(registry_path, project_root=root)
            result = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-09-07T20:05:00-04:00", sources=["pff", "fantasypros", "ftn"])
            self.assertEqual(int(result["consensus_rows"].iloc[0]["projection_count"]), 3)

    def test_default_min_sources_three_makes_three_source_consensus_eligible(self) -> None:
        with _repo_tmp() as tmp:
            root = Path(tmp)
            processed = root / "data" / "processed" / "projections"
            rows = []
            for source in ["pff", "fantasypros", "ftn"]:
                output_dir = processed / source / "2026" / "week_01"
                output_dir.mkdir(parents=True, exist_ok=True)
                long_file = output_dir / f"{source}_long.csv"
                pd.DataFrame([{"player": "A", "player_normalized": "a", "team": "BUF", "position": "RB", "season": 2026, "week": 1, "source": source, "market": "player_rush_yds", "projection": 10, "captured_at": "2026-09-07T20:00:00-04:00", "captured_at_source": "filename", "raw_file": f"data/raw/projections/{source}/source.csv"}]).to_csv(long_file, index=False)
                rows.append({"source": source, "season": 2026, "week": 1, "captured_at": "2026-09-07T20:00:00-04:00", "processed_long_file": str(long_file.relative_to(root)).replace("\\", "/"), "raw_file": f"data/raw/projections/{source}/source.csv", "raw_file_sha256": source})
            registry_path = processed / "snapshot_registry.csv"
            pd.DataFrame(rows).to_csv(registry_path, index=False)
            registry = load_snapshot_registry(registry_path, project_root=root)
            result = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-09-07T20:05:00-04:00", sources=["pff", "fantasypros", "ftn"])
            self.assertTrue(result["consensus_rows"].iloc[0]["consensus_eligible"])

    def test_signal_config_has_ftn_but_keeps_five_required_four_agreement(self) -> None:
        policy = load_policy(ROOT / "config" / "projection_signal_sources.json")
        self.assertEqual(policy.active_sources, ("pff", "fantasypros", "ftn"))
        self.assertEqual(policy.required_source_count, 5)
        self.assertEqual(policy.minimum_agreement_count, 4)

    def test_validation_report_includes_ftn_market_counts(self) -> None:
        with _repo_tmp() as tmp:
            qb, flex = _write_ftn_snapshot(Path(tmp))
            frames = {"qb": read_ftn_csv(qb), "flex": read_ftn_csv(flex)}
            rows, rejected = transform_ftn_snapshot(frames, metadata=_metadata(qb))
            report = build_validation_report(frames, rows, rejected, _metadata(qb), [])
            self.assertIn("rows_by_market", set(report["metric"]))

    def test_adapter_does_not_import_network_clients(self) -> None:
        text = (ROOT / "scripts" / "01_ingest" / "projection_adapters" / "ftn.py").read_text(encoding="utf-8")
        self.assertNotIn("requests", text)
        self.assertNotIn("urllib", text)

    def test_config_json_remains_valid(self) -> None:
        payload = json.loads((ROOT / "config" / "projection_signal_sources.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["required_source_count"], 5)
        self.assertEqual(payload["minimum_agreement_count"], 4)

    def test_metadata_is_timezone_aware(self) -> None:
        self.assertIsNotNone(_metadata().captured_at.tzinfo)
        self.assertEqual(_metadata().captured_at.astimezone(ZoneInfo("UTC")).isoformat(), "2026-09-08T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
