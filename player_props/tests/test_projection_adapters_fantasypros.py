from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "01_ingest"))
sys.path.insert(0, str(ROOT / "scripts" / "02_processing"))
sys.path.insert(0, str(ROOT / "scripts" / "04_analysis"))

import audit_fantasypros_api_vs_csv as fp_audit
from audit_fantasypros_api_vs_csv import build_fantasypros_snapshot_audit
from download_fantasypros_projections import fetch_fantasypros_projections
from ingest_projection_snapshots import ingest_fantasypros_api_snapshot, ingest_fantasypros_snapshot
from projection_adapters.common import SnapshotMetadata, parse_snapshot_metadata
from projection_adapters.fantasypros import transform_fantasypros_api_snapshot, transform_fantasypros_file, transform_fantasypros_snapshot
from projection_consensus.aggregation import build_consensus_rows
from projection_consensus.loader import load_snapshot_registry
from projection_registry.registry import build_projection_registry


QB_CSV = '''"Player","Team","ATT","CMP","YDS","TDS","INTS","ATT","YDS","TDS","FL","FPTS"
"Test QB","BUF","30","20","240.5","2","1","5","22.5","0","0","18"
'''

FLEX_CSV = '''"Player","Team","POS","ATT","YDS","TDS","REC","YDS","TDS","FL","FPTS"
"Test RB","DET","RB1","12","55.5","1","4","31.5","0","0","15"
"Test WR","MIA","WR1","0","0","0","6","72.5","1","0","16"
'''

API_PAYLOAD = {
    "season": "2026",
    "week": "1",
    "count": "2",
    "positions": "QB,RB,WR,TE",
    "scoring": "STD",
    "players": [
        {
            "fpid": 1,
            "name": "Test QB",
            "position_id": "QB",
            "team_id": "BUF",
            "stats": {"pass_yds": 240.5, "rush_yds": 22.5, "rec_rec": 0, "rec_yds": 0},
        },
        {
            "fpid": 2,
            "name": "Test WR",
            "position_id": "WR",
            "team_id": "MIA",
            "stats": {"pass_yds": 0, "rush_yds": 0, "rec_rec": 6, "rec_yds": 72.5},
        },
    ],
}


class FantasyProsProjectionAdapterTests(unittest.TestCase):
    def _metadata(self, raw_file: Path) -> SnapshotMetadata:
        return parse_snapshot_metadata(raw_file, source="fantasypros", season=2026, week=1)

    def _write_snapshot(self, root: Path) -> tuple[Path, Path]:
        snapshots = root / "data" / "raw" / "projections" / "fantasypros" / "2026" / "week_01" / "snapshots"
        snapshots.mkdir(parents=True, exist_ok=True)
        qb_path = snapshots / "08_19_26_1200_FantasyPros_Fantasy_Football_Projections_QB.csv"
        flex_path = snapshots / "08_19_26_1200_FantasyPros_Fantasy_Football_Projections_FLX.csv"
        qb_path.write_text(QB_CSV, encoding="utf-8")
        flex_path.write_text(FLEX_CSV, encoding="utf-8")
        return qb_path, flex_path

    def test_qb_duplicate_headers_parse_and_map_yards_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            qb_path, _ = self._write_snapshot(Path(tmp_dir))
            rows, rejected = transform_fantasypros_file(pd.read_csv(qb_path), raw_file=qb_path, metadata=self._metadata(qb_path))
            self.assertFalse(rejected)
            values = {row["market"]: row["projection"] for row in rows}
            self.assertEqual(values["player_pass_yds"], 240.5)
            self.assertEqual(values["player_rush_yds"], 22.5)
            self.assertTrue(all(row["position"] == "QB" for row in rows))

    def test_flex_duplicate_headers_parse_and_map_markets_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _, flex_path = self._write_snapshot(Path(tmp_dir))
            rows, _ = transform_fantasypros_file(pd.read_csv(flex_path), raw_file=flex_path, metadata=self._metadata(flex_path))
            rb = {row["market"]: row["projection"] for row in rows if row["player_normalized"] == "test rb"}
            wr = {row["market"]: row["projection"] for row in rows if row["player_normalized"] == "test wr"}
            self.assertEqual(rb["player_rush_yds"], 55.5)
            self.assertEqual(rb["player_receptions"], 4.0)
            self.assertEqual(rb["player_reception_yds"], 31.5)
            self.assertNotIn("player_rush_yds", wr)
            self.assertEqual(wr["player_receptions"], 6.0)
            self.assertEqual(wr["player_reception_yds"], 72.5)

    def test_qb_and_flex_same_timestamp_become_one_logical_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            qb_path, flex_path = self._write_snapshot(root)
            result = ingest_fantasypros_snapshot([qb_path, flex_path], season=2026, week=1, output_root=root, skip_registry_update=True)
            self.assertEqual(result["rows_written"], 7)
            long_path = root / "data" / "processed" / "projections" / "fantasypros" / "2026" / "week_01" / "08_19_26_1200_projections_long.csv"
            weekly_path = long_path.parent / "projections_long.csv"
            self.assertTrue(long_path.exists())
            self.assertTrue(weekly_path.exists())
            weekly_df = pd.read_csv(weekly_path)
            self.assertEqual(len(weekly_df), 7)
            self.assertEqual(set(weekly_df["source"]), {"fantasypros"})

    def test_reingestion_is_duplicate_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            qb_path, flex_path = self._write_snapshot(root)
            first = ingest_fantasypros_snapshot([qb_path, flex_path], season=2026, week=1, output_root=root, skip_registry_update=True)
            second = ingest_fantasypros_snapshot([qb_path, flex_path], season=2026, week=1, output_root=root, skip_registry_update=True)
            weekly_df = pd.read_csv(root / "data" / "processed" / "projections" / "fantasypros" / "2026" / "week_01" / "projections_long.csv")
            self.assertEqual(first["rows_written"], second["rows_written"])
            self.assertEqual(len(weekly_df), first["rows_written"])
            self.assertFalse(weekly_df.duplicated(subset=["source", "season", "week", "captured_at", "player_normalized", "market"]).any())

    def test_raw_files_remain_unchanged(self) -> None:
        real_files = [
            ROOT / "data" / "raw" / "projections" / "fantasypros" / "2026" / "week_01" / "snapshots" / "08_19_26_1200_FantasyPros_Fantasy_Football_Projections_QB.csv",
            ROOT / "data" / "raw" / "projections" / "fantasypros" / "2026" / "week_01" / "snapshots" / "08_19_26_1200_FantasyPros_Fantasy_Football_Projections_FLX.csv",
        ]
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in real_files}
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            copied = []
            for path in real_files:
                target = root / path.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                copied.append(target)
            ingest_fantasypros_snapshot(copied, season=2026, week=1, output_root=root, skip_registry_update=True)
        after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in real_files}
        self.assertEqual(after, before)

    def test_unexpected_duplicate_header_layout_fails_clearly(self) -> None:
        frame = pd.DataFrame(columns=["Player", "Team", "YDS", "YDS.1"])
        with self.assertRaisesRegex(ValueError, "Unexpected FantasyPros QB duplicate-header layout"):
            transform_fantasypros_file(frame, raw_file="08_19_26_1200_QB.csv", metadata=self._metadata(Path("08_19_26_1200_QB.csv")))

    def test_missing_required_qb_columns_fail_clearly(self) -> None:
        frame = pd.DataFrame(columns=["Player", "Team", "ATT", "CMP", "YDS"])
        with self.assertRaisesRegex(ValueError, "Unexpected FantasyPros QB"):
            transform_fantasypros_file(frame, raw_file="08_19_26_1200_QB.csv", metadata=self._metadata(Path("08_19_26_1200_QB.csv")))

    def test_missing_required_flex_columns_fail_clearly(self) -> None:
        frame = pd.DataFrame(columns=["Player", "Team", "POS", "YDS"])
        with self.assertRaisesRegex(ValueError, "Unexpected FantasyPros FLEX"):
            transform_fantasypros_file(frame, raw_file="08_19_26_1200_FLX.csv", metadata=self._metadata(Path("08_19_26_1200_FLX.csv")))

    def test_player_normalization_matches_project_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            qb_path, _ = self._write_snapshot(Path(tmp_dir))
            rows, _ = transform_fantasypros_file(pd.read_csv(qb_path), raw_file=qb_path, metadata=self._metadata(qb_path))
            self.assertEqual(rows[0]["player_normalized"], "test qb")

    def test_registry_records_fantasypros_as_one_source_with_components(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            qb_path, flex_path = self._write_snapshot(root)
            ingest_fantasypros_snapshot([qb_path, flex_path], season=2026, week=1, output_root=root, skip_registry_update=True)
            result = build_projection_registry(project_root=root, output_root=root, source="fantasypros", season=2026, week=1)
            self.assertEqual(len(result["registry_rows"]), 1)
            row = result["registry_rows"][0]
            self.assertEqual(row["source"], "fantasypros")
            self.assertIn("QB.csv", row["component_raw_file_names"])
            self.assertIn("FLX.csv", row["component_raw_file_names"])
            self.assertEqual(row["raw_file_sha256"], row["logical_snapshot_hash"])

    def test_two_source_consensus_stays_ineligible_with_default_min_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            processed_root = root / "data" / "processed" / "projections"
            processed_root.mkdir(parents=True)
            for source in ["pff", "fantasypros"]:
                source_dir = processed_root / source / "2026" / ("week_1" if source == "pff" else "week_01")
                source_dir.mkdir(parents=True)
                long_path = source_dir / f"{source}_long.csv"
                pd.DataFrame(
                    [
                        {
                            "player": "Test RB",
                            "player_normalized": "test rb",
                            "team": "DET",
                            "position": "RB",
                            "season": 2026,
                            "week": 1,
                            "source": source,
                            "market": "player_rush_yds",
                            "projection": 10.0 if source == "pff" else 12.0,
                            "captured_at": "2026-08-19T12:00:00-04:00",
                            "captured_at_source": "filename",
                            "raw_file": f"data/raw/projections/{source}/2026/week_01/snapshots/source.csv",
                        }
                    ]
                ).to_csv(long_path, index=False)
            registry_path = processed_root / "snapshot_registry.csv"
            pd.DataFrame(
                [
                    {
                        "source": "pff",
                        "season": 2026,
                        "week": 1,
                        "captured_at": "2026-08-19T12:00:00-04:00",
                        "processed_long_file": "data/processed/projections/pff/2026/week_1/pff_long.csv",
                        "raw_file": "data/raw/projections/pff/2026/week_01/snapshots/source.csv",
                        "raw_file_sha256": "pffhash",
                    },
                    {
                        "source": "fantasypros",
                        "season": 2026,
                        "week": 1,
                        "captured_at": "2026-08-19T12:00:00-04:00",
                        "processed_long_file": "data/processed/projections/fantasypros/2026/week_01/fantasypros_long.csv",
                        "raw_file": "data/raw/projections/fantasypros/2026/week_01/snapshots/source.csv",
                        "raw_file_sha256": "fphash",
                    },
                ]
            ).to_csv(registry_path, index=False)
            registry = load_snapshot_registry(registry_path, project_root=root)
            selected = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-19T13:00:00-04:00", sources=["pff", "fantasypros"])
            row = selected["consensus_rows"].iloc[0]
            self.assertEqual(int(row["projection_count"]), 2)
            self.assertFalse(row["consensus_eligible"])
            diff = selected["pairwise_differences"].iloc[0]
            self.assertEqual(float(diff["absolute_difference"]), 2.0)
            overlap = selected["source_overlap"].loc[selected["source_overlap"]["market"] == "player_rush_yds"].iloc[0]
            self.assertEqual(int(overlap["shared_players"]), 1)

    def test_missing_logical_component_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            qb_path, _ = self._write_snapshot(Path(tmp_dir))
            raw_frame = pd.read_csv(qb_path)
            raw_frame.attrs["raw_file"] = str(qb_path)
            with self.assertRaisesRegex(ValueError, "Incomplete FantasyPros logical snapshot"):
                transform_fantasypros_snapshot({"qb": raw_frame}, metadata=self._metadata(qb_path))

    def test_api_response_maps_to_canonical_markets_and_keeps_fantasypros_source(self) -> None:
        metadata = SnapshotMetadata(
            source="fantasypros",
            season=2026,
            week=1,
            raw_file=Path("api.json"),
            captured_at=datetime(2026, 9, 3, 10, 45, tzinfo=ZoneInfo("America/New_York")),
            captured_at_source="api_request",
        )
        rows, rejected = transform_fantasypros_api_snapshot(API_PAYLOAD, raw_file="api.json", metadata=metadata)
        values = {(row["player_normalized"], row["market"]): row["projection"] for row in rows}
        self.assertEqual(values[("test qb", "player_pass_yds")], 240.5)
        self.assertEqual(values[("test qb", "player_rush_yds")], 22.5)
        self.assertEqual(values[("test wr", "player_receptions")], 6.0)
        self.assertEqual(values[("test wr", "player_reception_yds")], 72.5)
        self.assertNotIn(("test wr", "player_pass_yds"), values)
        self.assertTrue(all(row["source"] == "fantasypros" for row in rows))
        self.assertTrue(all(row["source_format"] == "api" for row in rows))
        self.assertTrue(any(row["reason"] == "not_applicable" for row in rejected))

    def test_api_ingest_preserves_raw_json_bytes_and_writes_snapshot_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            raw_dir = root / "data" / "raw" / "projections" / "fantasypros" / "2026" / "week_01" / "snapshots"
            raw_dir.mkdir(parents=True)
            raw_path = raw_dir / "09_03_26_1045_api_projections.json"
            raw_text = json.dumps(API_PAYLOAD, separators=(",", ":"))
            raw_path.write_text(raw_text, encoding="utf-8")
            captured_at = datetime(2026, 9, 3, 10, 45, tzinfo=ZoneInfo("America/New_York"))
            before = hashlib.sha256(raw_path.read_bytes()).hexdigest()
            result = ingest_fantasypros_api_snapshot(raw_path, season=2026, week=1, captured_at=captured_at, output_root=root, skip_registry_update=True)
            self.assertEqual(hashlib.sha256(raw_path.read_bytes()).hexdigest(), before)
            self.assertEqual(result["rows_written"], 4)
            long_df = pd.read_csv(result["output_paths"]["long"])
            self.assertEqual(set(long_df["source"]), {"fantasypros"})
            self.assertEqual(set(long_df["captured_at_source"]), {"api_request"})

    def test_downloader_uses_header_auth_without_putting_key_in_url(self) -> None:
        response = Mock()
        response.status_code = 200
        response.content = json.dumps(API_PAYLOAD).encode("utf-8")
        response.headers = {"x-ratelimit-remaining": "99"}
        with patch("download_fantasypros_projections.requests.get", return_value=response) as get:
            _, metadata = fetch_fantasypros_projections(api_key="secret-key", season=2026, week=1, positions="QB:RB", scoring="STD", timeout=1)
        _, kwargs = get.call_args
        self.assertEqual(kwargs["headers"]["x-api-key"], "secret-key")
        self.assertNotIn("secret-key", metadata["endpoint_path"])
        self.assertEqual(metadata["rate_limit_headers"]["x-ratelimit-remaining"], "99")

    def test_registry_discovers_api_json_as_fantasypros_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            raw_dir = root / "data" / "raw" / "projections" / "fantasypros" / "2026" / "week_01" / "snapshots"
            raw_dir.mkdir(parents=True)
            raw_path = raw_dir / "09_03_26_1045_api_projections.json"
            raw_path.write_text(json.dumps(API_PAYLOAD), encoding="utf-8")
            sidecar = raw_path.with_suffix(raw_path.suffix + ".metadata.json")
            sidecar.write_text(
                json.dumps(
                    {
                        "source": "fantasypros",
                        "source_format": "api",
                        "season": 2026,
                        "week": 1,
                        "captured_at": "2026-09-03T10:45:00-04:00",
                        "captured_at_source": "api_request",
                        "endpoint_path": "/public/v2/json/nfl/2026/projections?week=1&positions=QB%3ARB&scoring=STD",
                        "status_code": 200,
                        "rate_limit_headers": {"x-ratelimit-remaining": "99"},
                    }
                ),
                encoding="utf-8",
            )
            ingest_fantasypros_api_snapshot(raw_path, season=2026, week=1, captured_at=datetime(2026, 9, 3, 10, 45, tzinfo=ZoneInfo("America/New_York")), output_root=root, skip_registry_update=True)
            result = build_projection_registry(project_root=root, output_root=root, source="fantasypros", season=2026, week=1)
            row = result["registry_rows"][0]
            self.assertEqual(row["source"], "fantasypros")
            self.assertEqual(row["source_format"], "api")
            self.assertEqual(row["captured_at_source"], "api_request")
            self.assertEqual(int(row["canonical_rows"]), 4)

    def test_csv_then_api_same_source_latest_snapshot_wins_in_consensus_and_audit_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            qb_path, flex_path = self._write_snapshot(root)
            ingest_fantasypros_snapshot([qb_path, flex_path], season=2026, week=1, output_root=root, skip_registry_update=True)
            raw_dir = root / "data" / "raw" / "projections" / "fantasypros" / "2026" / "week_01" / "snapshots"
            raw_path = raw_dir / "09_03_26_1045_api_projections.json"
            raw_path.write_text(json.dumps(API_PAYLOAD), encoding="utf-8")
            sidecar = raw_path.with_suffix(raw_path.suffix + ".metadata.json")
            sidecar.write_text(json.dumps({"source": "fantasypros", "season": 2026, "week": 1, "captured_at": "2026-09-03T10:45:00-04:00", "captured_at_source": "api_request"}), encoding="utf-8")
            ingest_fantasypros_api_snapshot(raw_path, season=2026, week=1, captured_at=datetime(2026, 9, 3, 10, 45, tzinfo=ZoneInfo("America/New_York")), output_root=root, skip_registry_update=True)
            build_projection_registry(project_root=root, output_root=root, source="fantasypros", season=2026, week=1)
            registry = load_snapshot_registry(root / "data" / "processed" / "projections" / "snapshot_registry.csv", project_root=root)
            before = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-08-20T12:00:00-04:00", sources=["fantasypros"])
            after = build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-09-03T11:00:00-04:00", sources=["fantasypros"])
            self.assertIn("08_19_26_1200", before["selected_snapshots"].iloc[0]["selected_processed_file"])
            self.assertIn("09_03_26_1045", after["selected_snapshots"].iloc[0]["selected_processed_file"])
            self.assertEqual(int(after["consensus_rows"].iloc[0]["projection_count"]), 1)
            audit = build_fantasypros_snapshot_audit(project_root=root, season=2026, week=1)
            self.assertFalse(audit["market_coverage"].empty)

    def test_audit_uses_actual_registry_schema_without_selection_eligible(self) -> None:
        registry = pd.DataFrame(
            [
                {
                    "source": "fantasypros",
                    "season": 2026,
                    "week": 1,
                    "source_format": "csv",
                    "captured_at": "2026-08-19T12:00:00-04:00",
                    "captured_at_dt": datetime(2026, 8, 19, 12, 0, tzinfo=ZoneInfo("America/New_York")),
                    "raw_file": "data/raw/projections/fantasypros/2026/week_01/snapshots/08_19_26_1200_projections.csv",
                    "raw_file_name": "08_19_26_1200_projections.csv",
                    "raw_file_sha256": "csvhash",
                    "processed_long_file": "data/processed/projections/fantasypros/2026/week_01/08_19_26_1200_projections_long.csv",
                    "canonical_rows": 1,
                    "validation_status": "passed_with_warnings",
                },
                {
                    "source": "fantasypros",
                    "season": 2026,
                    "week": 1,
                    "source_format": "api",
                    "captured_at": "2026-09-03T10:45:00-04:00",
                    "captured_at_dt": datetime(2026, 9, 3, 10, 45, tzinfo=ZoneInfo("America/New_York")),
                    "raw_file": "data/raw/projections/fantasypros/2026/week_01/snapshots/09_03_26_1045_api_projections.json",
                    "raw_file_name": "09_03_26_1045_api_projections.json",
                    "raw_file_sha256": "apihash",
                    "processed_long_file": "data/processed/projections/fantasypros/2026/week_01/09_03_26_1045_api_projections_long.csv",
                    "canonical_rows": 1,
                    "validation_status": "passed_with_warnings",
                },
            ]
        )
        base_long = {
            "player": "Test QB",
            "player_normalized": "test qb",
            "team": "BUF",
            "position": "QB",
            "season": 2026,
            "week": 1,
            "source": "fantasypros",
            "market": "player_pass_yds",
        }
        csv_long = pd.DataFrame([{**base_long, "projection": 240.5, "captured_at": "2026-08-19T12:00:00-04:00"}])
        api_long = pd.DataFrame([{**base_long, "projection": 250.5, "captured_at": "2026-09-03T10:45:00-04:00"}])

        with patch.object(fp_audit, "load_snapshot_registry", return_value=registry), patch.object(fp_audit, "_is_usable_snapshot", return_value=True), patch.object(fp_audit, "_read_long", side_effect=[csv_long, api_long]):
            audit = build_fantasypros_snapshot_audit(project_root=ROOT, season=2026, week=1)
            self.assertEqual(set(audit["selected_snapshots"]["audit_source_format"]), {"csv", "api"})
            self.assertEqual(len(audit["overlap"]), 1)
            self.assertEqual(float(audit["overlap"].iloc[0]["signed_change"]), 10.0)


if __name__ == "__main__":
    unittest.main()
