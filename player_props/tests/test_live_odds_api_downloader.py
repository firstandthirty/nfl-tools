from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "01_ingest"))
sys.path.insert(0, str(ROOT / "scripts" / "02_processing"))

import download_odds_api_player_props as downloader
from odds_adapters.common import discover_snapshot_files
from odds_adapters.odds_api import transform_odds_api_snapshot
from odds_adapters.common import parse_snapshot_metadata


class FakeResponse:
    def __init__(self, content: bytes, *, status_code: int = 200, headers: dict | None = None) -> None:
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}
        self.text = content.decode("utf-8", errors="replace")


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls = []

    def get(self, url: str, *, params: dict, timeout: int) -> FakeResponse:
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return self.response


class LiveOddsApiDownloaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_root = ROOT / ".tmp_live_odds_downloader_tests"
        if self.tmp_root.exists():
            shutil.rmtree(self.tmp_root)
        self.tmp_root.mkdir(parents=True)

    def tearDown(self) -> None:
        if self.tmp_root.exists():
            shutil.rmtree(self.tmp_root)

    def test_main_makes_no_http_without_execute_flag(self) -> None:
        argv = ["download_odds_api_player_props.py", "--season", "2026", "--week", "1"]
        with patch.object(sys, "argv", argv), patch.object(downloader, "run_live_download") as run_live:
            downloader.main()
        run_live.assert_not_called()

    def test_api_key_is_loaded_from_env_without_logging_value(self) -> None:
        with patch.dict(os.environ, {"ODDS_API_KEY": "secret_key_for_test"}, clear=False):
            self.assertEqual(downloader.load_api_key(self.tmp_root), "secret_key_for_test")

    def test_week_one_filter_excludes_preseason_and_week_two(self) -> None:
        events = [
            {"id": "pre", "commence_time": "2026-08-29T23:00:00Z"},
            {"id": "w1a", "commence_time": "2026-09-10T00:20:00Z"},
            {"id": "w1b", "commence_time": "2026-09-14T00:15:00Z"},
            {"id": "w2", "commence_time": "2026-09-17T00:15:00Z"},
        ]
        selected = downloader.filter_events_for_week(events, season=2026, week=1)
        self.assertEqual([event["id"] for event in selected], ["w1a", "w1b"])

    def test_raw_response_is_written_before_json_parse(self) -> None:
        raw_file = self.tmp_root / "bad.json"
        session = FakeSession(FakeResponse(b"{not-json", headers={"x-requests-last": "4"}))
        with self.assertRaises(json.JSONDecodeError):
            downloader.call_odds_api(session, "https://example.test", params={"apiKey": "secret"}, raw_file=raw_file)
        self.assertEqual(raw_file.read_bytes(), b"{not-json")

    def test_component_files_are_not_discovered_as_ingestable_snapshots(self) -> None:
        snapshot_dir = self.tmp_root / "data" / "raw" / "odds" / "odds_api" / "2026" / "week_01" / "snapshots"
        snapshot_dir.mkdir(parents=True)
        for name in ["20260903T120000_events.json", "20260903T120000_event_01_abc_odds.json", "20260903T120000_manifest.json"]:
            (snapshot_dir / name).write_text("{}", encoding="utf-8")
        bundle = snapshot_dir / "20260903T120000_odds_bundle.json"
        bundle.write_text("[]", encoding="utf-8")
        discovered = discover_snapshot_files(self.tmp_root, source="odds_api", season=2026, week=1)
        self.assertEqual(discovered, [bundle])

    def test_main_and_alternate_outcomes_survive_from_bundle(self) -> None:
        payload = [
            {
                "id": "event-1",
                "commence_time": "2026-09-04T00:20:00Z",
                "home_team": "Home",
                "away_team": "Away",
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "title": "DraftKings",
                        "last_update": "2026-09-03T16:00:00Z",
                        "markets": [
                            {
                                "key": "player_pass_yds",
                                "last_update": "2026-09-03T16:00:00Z",
                                "outcomes": [
                                    {"name": "Over", "description": "Jane QB", "point": 250.5, "price": -110},
                                    {"name": "Under", "description": "Jane QB", "point": 250.5, "price": -110},
                                ],
                            },
                            {
                                "key": "player_pass_yds_alternate",
                                "last_update": "2026-09-03T16:00:00Z",
                                "outcomes": [
                                    {"name": "Over", "description": "Jane QB", "point": 224.5, "price": -140},
                                    {"name": "Under", "description": "Jane QB", "point": 224.5, "price": 110},
                                    {"name": "Over", "description": "Jane QB", "point": 274.5, "price": 125},
                                    {"name": "Under", "description": "Jane QB", "point": 274.5, "price": -155},
                                ],
                            },
                        ],
                    },
                    {
                        "key": "fanduel",
                        "title": "FanDuel",
                        "last_update": "2026-09-03T16:00:01Z",
                        "markets": [
                            {
                                "key": "player_pass_yds",
                                "last_update": "2026-09-03T16:00:01Z",
                                "outcomes": [
                                    {"name": "Over", "description": "Jane QB", "point": 250.5, "price": -112},
                                    {"name": "Under", "description": "Jane QB", "point": 250.5, "price": -108},
                                ],
                            }
                        ],
                    },
                ],
            }
        ]
        raw_file = self.tmp_root / "bundle.json"
        raw_file.write_text(json.dumps(payload), encoding="utf-8")
        metadata = parse_snapshot_metadata(raw_file, source="odds_api", season=2026, week=1, captured_at="2026-09-03T12:00:00-04:00")
        rows, rejected, conflicts = transform_odds_api_snapshot(payload, metadata=metadata, project_root=self.tmp_root)
        self.assertEqual(rejected, [])
        self.assertEqual(conflicts, [])
        self.assertEqual({row["sportsbook"] for row in rows}, {"draftkings", "fanduel"})
        self.assertEqual({row["side"] for row in rows}, {"over", "under"})
        self.assertEqual(sorted({row["line"] for row in rows}), [224.5, 250.5, 274.5])
        self.assertTrue(any(row["is_alternate"] for row in rows))
        self.assertTrue(any(not row["is_alternate"] for row in rows))

    def _duplicate_payload(
        self,
        *,
        main_price: int,
        alternate_price: int,
        side: str = "Over",
        main_line: float = 25.5,
        alternate_line: float = 25.5,
        main_book: str = "draftkings",
        alternate_book: str = "draftkings",
        second_alternate_price: int | None = None,
    ) -> list[dict]:
        alt_outcomes = [{"name": side, "description": "Jane Runner", "point": alternate_line, "price": alternate_price}]
        if second_alternate_price is not None:
            alt_outcomes.append({"name": side, "description": "Jane Runner", "point": alternate_line, "price": second_alternate_price})
        books = [
            {
                "key": main_book,
                "title": main_book,
                "markets": [
                    {
                        "key": "player_rush_yds",
                        "last_update": "2026-09-03T16:00:00Z",
                        "outcomes": [{"name": side, "description": "Jane Runner", "point": main_line, "price": main_price}],
                    }
                ],
            }
        ]
        if alternate_book == main_book:
            books[0]["markets"].append({
                "key": "player_rush_yds_alternate",
                "last_update": "2026-09-03T16:00:01Z",
                "outcomes": alt_outcomes,
            })
        else:
            books.append({
                "key": alternate_book,
                "title": alternate_book,
                "markets": [{
                    "key": "player_rush_yds_alternate",
                    "last_update": "2026-09-03T16:00:01Z",
                    "outcomes": alt_outcomes,
                }],
            })
        return [{
            "id": "event-dup",
            "commence_time": "2026-09-10T00:20:00Z",
            "home_team": "Home",
            "away_team": "Away",
            "bookmakers": books,
        }]

    def _dedupe_rows(self, payload: list[dict], captured_at: str = "2026-09-03T12:00:00-04:00") -> tuple[list[dict], list[dict], list[dict]]:
        raw_file = self.tmp_root / "dedupe.json"
        raw_file.write_text(json.dumps(payload), encoding="utf-8")
        metadata = parse_snapshot_metadata(raw_file, source="odds_api", season=2026, week=1, captured_at=captured_at)
        return transform_odds_api_snapshot(payload, metadata=metadata, project_root=self.tmp_root)

    def test_duplicate_main_minus_113_alt_minus_111_retains_alt_price(self) -> None:
        rows, rejected, conflicts = self._dedupe_rows(self._duplicate_payload(main_price=-113, alternate_price=-111))
        self.assertEqual(rejected, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["price"], -111)
        self.assertTrue(rows[0]["is_alternate"])
        self.assertEqual(rows[0]["consolidated_duplicate_count"], 1)
        self.assertIn("player_rush_yds|player_rush_yds_alternate", rows[0]["contributing_market_source_keys"])
        self.assertEqual(conflicts[0]["reason"], "consolidated_duplicate_price")

    def test_duplicate_main_plus_102_alt_plus_104_retains_alt_price(self) -> None:
        rows, _, _ = self._dedupe_rows(self._duplicate_payload(main_price=102, alternate_price=104))
        self.assertEqual(rows[0]["price"], 104)
        self.assertTrue(rows[0]["is_alternate"])

    def test_duplicate_main_minus_105_alt_minus_115_retains_main_price(self) -> None:
        rows, _, _ = self._dedupe_rows(self._duplicate_payload(main_price=-105, alternate_price=-115))
        self.assertEqual(rows[0]["price"], -105)
        self.assertFalse(rows[0]["is_alternate"])

    def test_duplicate_equal_price_prefers_main_market(self) -> None:
        rows, _, _ = self._dedupe_rows(self._duplicate_payload(main_price=-110, alternate_price=-110))
        self.assertEqual(rows[0]["price"], -110)
        self.assertFalse(rows[0]["is_alternate"])
        self.assertEqual(rows[0]["market_source_key"], "player_rush_yds")

    def test_different_lines_are_not_deduped(self) -> None:
        rows, _, _ = self._dedupe_rows(self._duplicate_payload(main_price=-110, alternate_price=-110, alternate_line=26.5))
        self.assertEqual(len(rows), 2)
        self.assertEqual(sorted(row["line"] for row in rows), [25.5, 26.5])

    def test_different_sides_are_not_deduped(self) -> None:
        payload = self._duplicate_payload(main_price=-110, alternate_price=-110)
        payload[0]["bookmakers"][0]["markets"][1]["outcomes"][0]["name"] = "Under"
        rows, _, _ = self._dedupe_rows(payload)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["side"] for row in rows}, {"over", "under"})

    def test_different_sportsbooks_are_not_deduped(self) -> None:
        rows, _, _ = self._dedupe_rows(self._duplicate_payload(main_price=-110, alternate_price=-105, alternate_book="fanduel"))
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["sportsbook"] for row in rows}, {"draftkings", "fanduel"})

    def test_different_timestamps_are_not_deduped(self) -> None:
        payload = self._duplicate_payload(main_price=-110, alternate_price=-105)
        rows_1, _, _ = self._dedupe_rows(payload, captured_at="2026-09-03T12:00:00-04:00")
        rows_2, _, _ = self._dedupe_rows(payload, captured_at="2026-09-03T12:01:00-04:00")
        self.assertEqual(len(rows_1), 1)
        self.assertEqual(len(rows_2), 1)
        self.assertNotEqual(rows_1[0]["captured_at"], rows_2[0]["captured_at"])

    def test_multiple_duplicate_candidates_retain_single_best_price(self) -> None:
        rows, rejected, conflicts = self._dedupe_rows(
            self._duplicate_payload(main_price=-113, alternate_price=-111, second_alternate_price=-105)
        )
        self.assertEqual(rejected, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["price"], -105)
        self.assertEqual(rows[0]["consolidated_duplicate_count"], 2)
        self.assertEqual(len(conflicts), 2)


if __name__ == "__main__":
    unittest.main()
