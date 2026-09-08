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

from ingest_projection_snapshots import ingest_fourforfour_snapshot
from projection_adapters.common import parse_snapshot_metadata
from projection_adapters.fourforfour import EXPECTED_COLUMNS, SOURCE, build_validation_report, transform_fourforfour_snapshot
from projection_consensus.aggregation import build_consensus_rows
from projection_consensus.loader import load_snapshot_registry
from projection_registry.registry import build_projection_registry
from prospective_projection_signal import load_policy

TMP_ROOT = ROOT / "tests" / "fixtures_tmp_fourforfour"


@contextmanager
def _repo_tmp():
    root = TMP_ROOT / f"case_{datetime.now(ZoneInfo('UTC')).strftime('%H%M%S%f')}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        if root.exists():
            shutil.rmtree(root)


def _row(**overrides):
    values = {
        "Season": 2026,
        "Week": 1,
        "PID": "player1",
        "Player": "Test Player",
        "Pos": "RB",
        "Team": "ARI",
        "Opp": "@NYG",
        "aFPA": 1,
        "aFPA Rk": 1,
        "FFPts": 10,
        "Comp": 0,
        "Pass Att": 0,
        "Pass Yds": 0,
        "Pass TD": 0,
        "INT": 0,
        "Rush Att": 10,
        "Rush Yds": 50.5,
        "Rush TD": 0,
        "Rec": 3.5,
        "Rec Yds": 24.5,
        "Rec TD": 0,
        "Pa1D": 0,
        "Ru1D": 0,
        "Rec1D": 0,
        "Fum": 0,
        "XP": 0,
        "FG": 0,
        "Grade": "A",
    }
    values.update(overrides)
    return values


def _metadata(path: Path | str = "09_07_26_2000_4for4_W1_projections.csv"):
    return parse_snapshot_metadata(Path(path), source=SOURCE, season=2026, week=1)


def _write_snapshot(root: Path, rows: list[dict] | None = None) -> Path:
    path = root / "data" / "raw" / "projections" / SOURCE / "2026" / "week_01" / "snapshots" / "09_07_26_2000_4for4_W1_projections.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows or [_row()])[EXPECTED_COLUMNS].to_csv(path, index=False)
    return path


class FourForFourProjectionAdapterTests(unittest.TestCase):
    def test_csv_schema_parsed_correctly(self) -> None:
        with _repo_tmp() as root:
            path = _write_snapshot(root)
            self.assertEqual(list(pd.read_csv(path).columns), EXPECTED_COLUMNS)

    def test_source_key_exactly_4for4(self) -> None:
        self.assertEqual(SOURCE, "4for4")

    def test_captured_at_parsed_from_filename(self) -> None:
        self.assertEqual(_metadata().captured_at.isoformat(), "2026-09-07T20:00:00-04:00")

    def test_pass_yds_mapping(self) -> None:
        frame = pd.DataFrame([_row(Pos="QB", **{"Pass Yds": 233.2})])[EXPECTED_COLUMNS]
        rows, _, _ = transform_fourforfour_snapshot(frame, raw_file="09_07_26_2000_4for4_W1_projections.csv", metadata=_metadata())
        self.assertEqual({r["market"]: r["projection"] for r in rows}["player_pass_yds"], 233.2)

    def test_rush_yds_mapping(self) -> None:
        rows, _, _ = transform_fourforfour_snapshot(pd.DataFrame([_row()])[EXPECTED_COLUMNS], raw_file="09_07_26_2000_4for4_W1_projections.csv", metadata=_metadata())
        self.assertEqual({r["market"]: r["projection"] for r in rows}["player_rush_yds"], 50.5)

    def test_rec_yds_mapping(self) -> None:
        rows, _, _ = transform_fourforfour_snapshot(pd.DataFrame([_row()])[EXPECTED_COLUMNS], raw_file="09_07_26_2000_4for4_W1_projections.csv", metadata=_metadata())
        self.assertEqual({r["market"]: r["projection"] for r in rows}["player_reception_yds"], 24.5)

    def test_rec_mapping(self) -> None:
        rows, _, _ = transform_fourforfour_snapshot(pd.DataFrame([_row()])[EXPECTED_COLUMNS], raw_file="09_07_26_2000_4for4_W1_projections.csv", metadata=_metadata())
        self.assertEqual({r["market"]: r["projection"] for r in rows}["player_receptions"], 3.5)

    def test_structural_pass_yds_zero_skipped(self) -> None:
        rows, _, skipped = transform_fourforfour_snapshot(pd.DataFrame([_row(**{"Pass Yds": 0})])[EXPECTED_COLUMNS], raw_file="09_07_26_2000_4for4_W1_projections.csv", metadata=_metadata())
        self.assertNotIn("player_pass_yds", {r["market"] for r in rows})
        self.assertIn("player_pass_yds", {r["market"] for r in skipped})

    def test_structural_rush_yds_zero_skipped(self) -> None:
        rows, _, skipped = transform_fourforfour_snapshot(pd.DataFrame([_row(**{"Rush Yds": 0})])[EXPECTED_COLUMNS], raw_file="09_07_26_2000_4for4_W1_projections.csv", metadata=_metadata())
        self.assertNotIn("player_rush_yds", {r["market"] for r in rows})
        self.assertIn("player_rush_yds", {r["market"] for r in skipped})

    def test_structural_rec_zero_skipped(self) -> None:
        rows, _, skipped = transform_fourforfour_snapshot(pd.DataFrame([_row(Rec=0)])[EXPECTED_COLUMNS], raw_file="09_07_26_2000_4for4_W1_projections.csv", metadata=_metadata())
        self.assertNotIn("player_receptions", {r["market"] for r in rows})
        self.assertIn("player_receptions", {r["market"] for r in skipped})

    def test_structural_rec_yds_zero_skipped(self) -> None:
        rows, _, skipped = transform_fourforfour_snapshot(pd.DataFrame([_row(**{"Rec Yds": 0})])[EXPECTED_COLUMNS], raw_file="09_07_26_2000_4for4_W1_projections.csv", metadata=_metadata())
        self.assertNotIn("player_reception_yds", {r["market"] for r in rows})
        self.assertIn("player_reception_yds", {r["market"] for r in skipped})

    def test_zero_placeholders_are_not_malformed_rejects(self) -> None:
        _, rejected, skipped = transform_fourforfour_snapshot(pd.DataFrame([_row(**{"Pass Yds": 0, "Rush Yds": 0, "Rec": 0, "Rec Yds": 0})])[EXPECTED_COLUMNS], raw_file="09_07_26_2000_4for4_W1_projections.csv", metadata=_metadata())
        self.assertFalse(rejected)
        self.assertEqual(len(skipped), 4)

    def test_malformed_nonblank_numeric_value_rejected(self) -> None:
        _, rejected, _ = transform_fourforfour_snapshot(pd.DataFrame([_row(**{"Rush Yds": "bad"})])[EXPECTED_COLUMNS], raw_file="09_07_26_2000_4for4_W1_projections.csv", metadata=_metadata())
        self.assertEqual(rejected[0]["reason"], "malformed_numeric_projection")

    def test_kicker_produces_no_canonical_rows(self) -> None:
        rows, rejected, skipped = transform_fourforfour_snapshot(pd.DataFrame([_row(Pos="K", **{"Rush Yds": 0, "Rec": 0, "Rec Yds": 0, "Pass Yds": 0})])[EXPECTED_COLUMNS], raw_file="09_07_26_2000_4for4_W1_projections.csv", metadata=_metadata())
        self.assertFalse(rows)
        self.assertFalse(rejected)
        self.assertEqual(len(skipped), 4)

    def test_player_normalization_reused(self) -> None:
        rows, _, _ = transform_fourforfour_snapshot(pd.DataFrame([_row(Player="Test Jr.")])[EXPECTED_COLUMNS], raw_file="09_07_26_2000_4for4_W1_projections.csv", metadata=_metadata())
        self.assertEqual(rows[0]["player_normalized"], "test")

    def test_team_normalization_reused(self) -> None:
        rows, _, _ = transform_fourforfour_snapshot(pd.DataFrame([_row(Team="Arizona Cardinals")])[EXPECTED_COLUMNS], raw_file="09_07_26_2000_4for4_W1_projections.csv", metadata=_metadata())
        self.assertEqual(rows[0]["team"], "ARI")

    def test_raw_lineage_retained(self) -> None:
        rows, _, _ = transform_fourforfour_snapshot(pd.DataFrame([_row(PID="abc123")])[EXPECTED_COLUMNS], raw_file="09_07_26_2000_4for4_W1_projections.csv", metadata=_metadata())
        self.assertEqual(rows[0]["source_player_id"], "abc123")
        self.assertIn("4for4", rows[0]["raw_file"])

    def test_duplicate_player_market_source_prevented(self) -> None:
        frame = pd.DataFrame([_row(), _row()])[EXPECTED_COLUMNS]
        rows, rejected, _ = transform_fourforfour_snapshot(frame, raw_file="09_07_26_2000_4for4_W1_projections.csv", metadata=_metadata())
        self.assertEqual(len({(r["player_normalized"], r["market"]) for r in rows}), len(rows))
        self.assertIn("duplicate_logical_projection", {r["reason"] for r in rejected})

    def test_registry_source_is_4for4(self) -> None:
        with _repo_tmp() as root:
            path = _write_snapshot(root)
            ingest_fourforfour_snapshot(path, season=2026, week=1, output_root=root, skip_registry_update=True)
            result = build_projection_registry(root, output_root=root, source=SOURCE, season=2026, week=1)
            self.assertEqual(result["registry_rows"][0]["source"], SOURCE)

    def test_registry_timestamp_correct(self) -> None:
        with _repo_tmp() as root:
            path = _write_snapshot(root)
            ingest_fourforfour_snapshot(path, season=2026, week=1, output_root=root, skip_registry_update=True)
            result = build_projection_registry(root, output_root=root, source=SOURCE, season=2026, week=1)
            self.assertEqual(result["registry_rows"][0]["captured_at"], "2026-09-07T20:00:00-04:00")

    def test_consensus_source_count_can_reach_four(self) -> None:
        result = self._four_source_consensus()
        self.assertEqual(int(result["consensus_rows"].iloc[0]["projection_count"]), 4)

    def test_source_count_cannot_exceed_four_with_current_providers(self) -> None:
        result = self._four_source_consensus()
        self.assertLessEqual(int(result["consensus_rows"]["projection_count"].max()), 4)

    def test_4for4_counts_once(self) -> None:
        result = self._four_source_consensus()
        self.assertEqual(result["consensus_rows"].iloc[0]["sources"].split("|").count(SOURCE), 1)

    def test_required_source_count_remains_five(self) -> None:
        self.assertEqual(load_policy(ROOT / "config" / "projection_signal_sources.json").required_source_count, 5)

    def test_minimum_agreement_count_remains_four(self) -> None:
        self.assertEqual(load_policy(ROOT / "config" / "projection_signal_sources.json").minimum_agreement_count, 4)

    def test_active_sources_include_fourforfour(self) -> None:
        self.assertEqual(load_policy(ROOT / "config" / "projection_signal_sources.json").active_sources, ("pff", "fantasypros", "ftn", "4for4"))

    def test_staleness_policy_applies_normally(self) -> None:
        self.assertEqual(load_policy(ROOT / "config" / "projection_signal_sources.json").staleness_policy["maximum_projection_age_hours"], 72)

    def test_no_probability_fields_added(self) -> None:
        rows, _, _ = transform_fourforfour_snapshot(pd.DataFrame([_row()])[EXPECTED_COLUMNS], raw_file="09_07_26_2000_4for4_W1_projections.csv", metadata=_metadata())
        self.assertFalse(any("prob" in key.lower() for key in rows[0]))

    def test_no_ev_fields_added(self) -> None:
        rows, _, _ = transform_fourforfour_snapshot(pd.DataFrame([_row()])[EXPECTED_COLUMNS], raw_file="09_07_26_2000_4for4_W1_projections.csv", metadata=_metadata())
        self.assertFalse(any(key.lower() == "ev" or "expected_value" in key.lower() for key in rows[0]))

    def test_no_api_network_calls(self) -> None:
        text = (ROOT / "scripts" / "01_ingest" / "projection_adapters" / "fourforfour.py").read_text(encoding="utf-8")
        self.assertNotIn("requests", text)
        self.assertNotIn("urllib", text)

    def test_no_outcome_data_used(self) -> None:
        text = (ROOT / "scripts" / "01_ingest" / "projection_adapters" / "fourforfour.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("outcome", text)
        self.assertNotIn("box_score", text)
        self.assertNotIn("stathead", text)

    def test_validation_report_counts_zero_placeholders(self) -> None:
        frame = pd.DataFrame([_row(**{"Pass Yds": 0})])[EXPECTED_COLUMNS]
        rows, rejected, skipped = transform_fourforfour_snapshot(frame, raw_file="09_07_26_2000_4for4_W1_projections.csv", metadata=_metadata())
        report = build_validation_report(frame, rows, rejected, skipped, _metadata(), [])
        self.assertIn("skipped_fields", set(report["metric"]))

    def _four_source_consensus(self):
        with _repo_tmp() as root:
            processed = root / "data" / "processed" / "projections"
            registry_rows = []
            for source in ["pff", "fantasypros", "ftn", SOURCE]:
                output_dir = processed / source / "2026" / "week_01"
                output_dir.mkdir(parents=True, exist_ok=True)
                long_file = output_dir / f"{source}_long.csv"
                pd.DataFrame([{"player": "A", "player_normalized": "a", "team": "ARI", "position": "RB", "season": 2026, "week": 1, "source": source, "market": "player_rush_yds", "projection": 10, "captured_at": "2026-09-07T20:00:00-04:00", "captured_at_source": "filename", "raw_file": f"data/raw/projections/{source}/source.csv"}]).to_csv(long_file, index=False)
                registry_rows.append({"source": source, "season": 2026, "week": 1, "captured_at": "2026-09-07T20:00:00-04:00", "processed_long_file": str(long_file.relative_to(root)).replace("\\", "/"), "raw_file": f"data/raw/projections/{source}/source.csv", "raw_file_sha256": source})
            registry_path = processed / "snapshot_registry.csv"
            pd.DataFrame(registry_rows).to_csv(registry_path, index=False)
            registry = load_snapshot_registry(registry_path, project_root=root)
            return build_consensus_rows(registry=registry, project_root=root, season=2026, week=1, as_of="2026-09-07T20:05:00-04:00", sources=["pff", "fantasypros", "ftn", SOURCE])


if __name__ == "__main__":
    unittest.main()
