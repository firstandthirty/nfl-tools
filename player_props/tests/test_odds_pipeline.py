from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "odds_api" / "sample_odds_snapshot.json"
CONFLICT_FIXTURE = ROOT / "tests" / "fixtures" / "odds_api" / "conflicting_duplicate_snapshot.json"
sys.path.insert(0, str(ROOT / "scripts" / "01_ingest"))
sys.path.insert(0, str(ROOT / "scripts" / "02_processing"))

from ingest_odds_snapshots import ingest_snapshot_file
from odds_adapters.common import parse_snapshot_metadata
from odds_adapters.odds_api import load_json_payload, transform_odds_api_snapshot
from odds_registry.hashing import hash_file
from odds_registry.registry import build_odds_registry
from odds_asof.loader import load_odds_registry
from odds_asof.selection import select_odds_asof
from odds_join import join_projections_to_odds
from odds_math import (
    american_implied_probability,
    american_to_decimal,
    break_even_probability,
    decimal_to_american,
    expected_value_per_unit_risked,
    profit_per_unit_risked,
)


class OddsPipelineTests(unittest.TestCase):
    def _copy_fixture(self, root: Path, name: str = "provider_snapshot.json", fixture: Path = FIXTURE) -> Path:
        raw_dir = root / "data" / "raw" / "odds" / "odds_api" / "2026" / "week_01" / "snapshots"
        raw_dir.mkdir(parents=True, exist_ok=True)
        target = raw_dir / name
        shutil.copy2(fixture, target)
        return target

    def _metadata(self, path: Path, captured_at: str = "2026-09-01T13:00:00-04:00"):
        return parse_snapshot_metadata(path, source="odds_api", season=2026, week=1, captured_at=captured_at)

    def _rows(self) -> tuple[list[dict], list[dict], list[dict]]:
        return transform_odds_api_snapshot(load_json_payload(FIXTURE), metadata=self._metadata(FIXTURE), project_root=ROOT)

    def test_raw_json_file_remains_unchanged(self) -> None:
        before = FIXTURE.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            ingest_snapshot_file(FIXTURE, source="odds_api", season=2026, week=1, output_root=Path(tmp), captured_at="2026-09-01T13:00:00-04:00", skip_registry_update=True)
        self.assertEqual(FIXTURE.read_bytes(), before)

    def test_provider_controlled_filenames_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._copy_fixture(Path(tmp), "book_payload_any_name.json")
            result = ingest_snapshot_file(path, source="odds_api", season=2026, week=1, output_root=Path(tmp), captured_at="2026-09-01T13:00:00-04:00", skip_registry_update=True)
            self.assertGreater(result["rows_written"], 0)

    def test_explicit_captured_timestamp_is_used_when_supplied(self) -> None:
        metadata = parse_snapshot_metadata(FIXTURE, source="odds_api", season=2026, week=1, captured_at="2026-09-01T13:00:00-04:00")
        self.assertEqual(metadata.captured_at_source, "explicit")
        self.assertEqual(metadata.captured_at.isoformat(), "2026-09-01T13:00:00-04:00")

    def test_filename_timestamp_parsing_works_for_documented_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._copy_fixture(Path(tmp), "20260901T130000_odds.json")
            metadata = parse_snapshot_metadata(path, source="odds_api", season=2026, week=1)
            self.assertEqual(metadata.captured_at_source, "filename")
            self.assertEqual(metadata.captured_at.strftime("%Y-%m-%d %H:%M:%S%z"), "2026-09-01 13:00:00-0400")

    def test_filesystem_mtime_fallback_works(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._copy_fixture(Path(tmp), "unparseable.json")
            os.utime(path, (1_700_000_000, 1_700_000_000))
            metadata = parse_snapshot_metadata(path, source="odds_api", season=2026, week=1)
            self.assertEqual(metadata.captured_at_source, "filesystem_mtime")
            self.assertEqual(metadata.captured_at.year, 2023)

    def test_main_market_mappings_work(self) -> None:
        rows, _, _ = self._rows()
        markets = {row["market"] for row in rows}
        self.assertIn("player_pass_yds", markets)
        self.assertIn("player_rush_yds", markets)
        self.assertIn("player_reception_yds", markets)
        self.assertIn("player_receptions", markets)

    def test_alternate_market_mapping_and_lines_work(self) -> None:
        rows, _, _ = self._rows()
        alternates = [row for row in rows if row["is_alternate"]]
        self.assertGreaterEqual(len(alternates), 10)
        goff_alt_lines = sorted({row["line"] for row in alternates if row["player_normalized"] == "jared goff"})
        self.assertEqual(goff_alt_lines, [224.5, 274.5])

    def test_over_and_under_sides_normalize_and_american_odds_are_preserved(self) -> None:
        rows, _, _ = self._rows()
        self.assertTrue({"over", "under"}.issubset({row["side"] for row in rows}))
        prices = {row["price"] for row in rows if row["player_normalized"] == "jared goff"}
        self.assertIn(-110, prices)
        self.assertIn(135, prices)

    def test_malformed_outcomes_are_rejected_with_reasons(self) -> None:
        _, rejected, _ = self._rows()
        reasons = {row["reason"] for row in rejected}
        self.assertIn("unrecognized_side", reasons)
        self.assertIn("missing_market_mapping", reasons)
        self.assertIn("missing_player_name", reasons)
        self.assertIn("missing_or_invalid_price", reasons)
        self.assertIn("missing_or_nonnumeric_line", reasons)

    def test_canonical_keys_are_unique_and_duplicate_prices_are_consolidated(self) -> None:
        rows, _, _ = self._rows()
        keys = [(row["source"], row["sportsbook"], row["season"], row["week"], row["captured_at"], row["event_id"], row["player_normalized"], row["market"], row["line"], row["side"]) for row in rows]
        self.assertEqual(len(keys), len(set(keys)))
        consolidated_rows, rejected, conflicts = transform_odds_api_snapshot(load_json_payload(CONFLICT_FIXTURE), metadata=self._metadata(CONFLICT_FIXTURE), project_root=ROOT)
        self.assertEqual(len(consolidated_rows), 2)
        self.assertTrue(conflicts)
        self.assertEqual(rejected, [])
        self.assertEqual({row["reason"] for row in conflicts}, {"consolidated_duplicate_price"})
        goff_over = [row for row in consolidated_rows if row["player_normalized"] == "jared goff" and row["side"] == "over"][0]
        self.assertEqual(goff_over["price"], -110)
        self.assertEqual(goff_over["consolidated_duplicate_count"], 1)

    def test_reingesting_a_snapshot_is_duplicate_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = self._copy_fixture(root, "snapshot.json")
            result_1 = ingest_snapshot_file(raw, source="odds_api", season=2026, week=1, output_root=root, captured_at="2026-09-01T13:00:00-04:00", skip_registry_update=True)
            result_2 = ingest_snapshot_file(raw, source="odds_api", season=2026, week=1, output_root=root, captured_at="2026-09-01T13:00:00-04:00", skip_registry_update=True)
            weekly = pd.read_csv(root / "data" / "processed" / "odds" / "odds_api" / "2026" / "week_01" / "odds_long.csv")
            self.assertGreater(result_1["rows_written"], 0)
            self.assertTrue(result_2["skipped"])
            self.assertEqual(len(weekly), result_1["rows_written"])

    def test_sha256_registry_identity_and_rebuild_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = self._copy_fixture(root, "20260901T130000_snapshot.json")
            expected_hash = hashlib.sha256(raw.read_bytes()).hexdigest()
            self.assertEqual(hash_file(raw), expected_hash)
            ingest_snapshot_file(raw, source="odds_api", season=2026, week=1, output_root=root, skip_registry_update=True)
            result_1 = build_odds_registry(project_root=root, output_root=root, source="odds_api", season=2026, week=1, rebuild=True)
            result_2 = build_odds_registry(project_root=root, output_root=root, source="odds_api", season=2026, week=1, rebuild=True)
            self.assertEqual(len(result_1["registry_rows"]), 1)
            self.assertEqual(len(result_2["registry_rows"]), 1)
            self.assertEqual(result_1["registry_rows"][0]["raw_file_sha256"], expected_hash)

    def test_asof_selection_excludes_future_and_allows_exact_equality(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = self._copy_fixture(root, "20260901T130000_snapshot.json")
            ingest_snapshot_file(raw, source="odds_api", season=2026, week=1, output_root=root, skip_registry_update=True)
            build_odds_registry(project_root=root, output_root=root, source="odds_api", season=2026, week=1, rebuild=True)
            registry = load_odds_registry(root / "data" / "processed" / "odds" / "snapshot_registry.csv", project_root=root)
            future_excluded = select_odds_asof(registry=registry, project_root=root, season=2026, week=1, as_of="2026-09-01T12:59:00-04:00", sportsbooks=["fanduel"])
            exact = select_odds_asof(registry=registry, project_root=root, season=2026, week=1, as_of="2026-09-01T13:00:00-04:00", sportsbooks=["fanduel"])
            self.assertEqual(future_excluded["selected_snapshots"].iloc[0]["selection_status"], "no_snapshot_before_as_of")
            self.assertEqual(exact["selected_snapshots"].iloc[0]["selection_status"], "selected")
            self.assertGreater(len(exact["selected_odds"]), 0)

    def test_latest_eligible_snapshot_is_selected_independently_per_sportsbook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fd_path = root / "fd.csv"
            dk_path = root / "dk.csv"
            pd.DataFrame([{"sportsbook":"fanduel","season":2026,"week":1,"event_id":"a","player_normalized":"x","market":"player_pass_yds","is_alternate":False}]).to_csv(fd_path, index=False)
            pd.DataFrame([{"sportsbook":"draftkings","season":2026,"week":1,"event_id":"b","player_normalized":"x","market":"player_pass_yds","is_alternate":False}]).to_csv(dk_path, index=False)
            registry = pd.DataFrame([
                {"source":"odds_api","season":2026,"week":1,"captured_at":"2026-09-01T12:00:00-04:00","captured_at_dt":pd.Timestamp("2026-09-01T12:00:00-04:00"),"sportsbooks":"fanduel","markets_covered":"player_pass_yds","raw_file_repo":"old.json","processed_long_file_repo":"fd.csv","processed_long_file":fd_path,"raw_file_sha256":"a"},
                {"source":"odds_api","season":2026,"week":1,"captured_at":"2026-09-01T13:00:00-04:00","captured_at_dt":pd.Timestamp("2026-09-01T13:00:00-04:00"),"sportsbooks":"draftkings","markets_covered":"player_pass_yds","raw_file_repo":"dk.json","processed_long_file_repo":"dk.csv","processed_long_file":dk_path,"raw_file_sha256":"b"},
            ])
            result = select_odds_asof(registry=registry, project_root=root, season=2026, week=1, as_of="2026-09-01T13:30:00-04:00", sportsbooks=["fanduel", "draftkings"])
            statuses = dict(zip(result["selected_snapshots"]["sportsbook"], result["selected_snapshots"]["selected_captured_at"]))
            self.assertEqual(statuses["fanduel"], "2026-09-01T12:00:00-04:00")
            self.assertEqual(statuses["draftkings"], "2026-09-01T13:00:00-04:00")

    def test_odds_math_functions(self) -> None:
        self.assertAlmostEqual(american_to_decimal(-110), 1.9090909)
        self.assertEqual(decimal_to_american(2.5), 150)
        self.assertAlmostEqual(american_implied_probability(-110), 0.5238095)
        self.assertAlmostEqual(break_even_probability(150), 0.4)
        self.assertAlmostEqual(profit_per_unit_risked(150), 1.5)
        self.assertAlmostEqual(expected_value_per_unit_risked(0.55, 150), 0.375)

    def test_projection_join_preserves_all_main_alternate_and_sportsbooks(self) -> None:
        rows, _, _ = self._rows()
        odds = pd.DataFrame([row for row in rows if row["player_normalized"] == "jared goff" and row["market"] == "player_pass_yds"])
        projections = pd.DataFrame([{"season": 2026, "week": 1, "player": "Jared Goff", "player_normalized": "jared goff", "team": "DET", "market": "player_pass_yds", "projection_mean": 251.0}])
        result = join_projections_to_odds(projections, odds)
        self.assertEqual(len(result["joined"]), len(odds))
        self.assertGreaterEqual(result["joined"]["sportsbook"].nunique(), 2)
        self.assertTrue((result["joined"]["is_alternate"] == True).any())
        self.assertTrue((result["joined"]["is_alternate"] == False).any())

    def test_unmatched_players_and_markets_are_audited(self) -> None:
        rows, _, _ = self._rows()
        odds = pd.DataFrame(rows)
        projections = pd.DataFrame([
            {"season": 2026, "week": 1, "player_normalized": "not a player", "market": "player_pass_yds", "projection_mean": 1.0},
            {"season": 2026, "week": 1, "player_normalized": "jared goff", "market": "player_sacks", "projection_mean": 1.0},
        ])
        result = join_projections_to_odds(projections, odds)
        self.assertEqual(len(result["unmatched_projection"]), 2)
        self.assertIn("unmatched", set(result["unmatched_projection"]["player_match_status"]))
        self.assertIn("unmatched", set(result["unmatched_projection"]["market_match_status"]))


if __name__ == "__main__":
    unittest.main()
