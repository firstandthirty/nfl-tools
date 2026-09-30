from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from injury_tracker.scripts.official_injury_reports import (  # noqa: E402
    FetchResult,
    fetch_page,
    infer_table_team,
    parse_official_report,
    save_raw_fetch,
    team_name_lookup,
    write_processed_outputs,
)
import injury_tracker.scripts.official_injury_reports as official  # noqa: E402
from injury_tracker.scripts.schedule_context import ScheduleGameContext  # noqa: E402


STANDARD_HTML = """
<html>
  <body>
    <select>
      <option value="/team/injury-report/week/REG-2">WEEK 2</option>
      <option value="/team/injury-report/week/REG-3" selected>WEEK 3</option>
    </select>
    <h2>New England Patriots</h2>
    <table>
      <tr><th>Player</th><th>Position</th><th>Injury</th><th>Wed</th><th>Thu</th><th>Fri</th><th>Game Status</th></tr>
      <tr><td>Example Edge Jr.</td><td>LB</td><td>Knee</td><td>Did Not Participate</td><td>Limited Participation</td><td>Full Participation</td><td>Questionable</td></tr>
      <tr><td>Example Tackle</td><td>LT</td><td>Ankle</td><td>DNP</td><td>LP</td><td>FP</td><td>Out</td></tr>
    </table>
    <h2>New York Jets</h2>
    <table>
      <tr><th>Player</th><th>Position</th><th>Injury</th><th>Wed</th><th>Thu</th><th>Fri</th><th>Game Status</th></tr>
      <tr><td>Same Name</td><td>WR</td><td>Hamstring</td><td>LP</td><td></td><td></td><td>UNSPECIFIED</td></tr>
    </table>
  </body>
</html>
"""


class OfficialInjuryIngestionTests(unittest.TestCase):
    def test_standard_table_parsing_and_normalization(self) -> None:
        records, manifest = parse_official_report(
            STANDARD_HTML,
            requested_team="NE",
            season=2026,
            week=3,
            source_url="https://www.patriots.com/team/injury-report/",
            fetched_at="2026-09-24T12:00:00+00:00",
        )
        ne_records = [record for record in records if record["team"] == "NE"]

        self.assertEqual(manifest.parse_status, "OK")
        self.assertEqual(manifest.current_week_status, "SUCCESS_CURRENT")
        self.assertEqual(manifest.players_found, 2)
        self.assertEqual(manifest.opponent, "NYJ")
        self.assertEqual(manifest.match_validation, "MATCH_CONTEXT_UNAVAILABLE")
        self.assertEqual(ne_records[0]["source_position"], "LB")
        self.assertEqual(ne_records[0]["injury"], "Knee")
        self.assertEqual(ne_records[0]["game_status"], "Questionable")
        self.assertEqual(ne_records[0]["practice_by_day"]["Wednesday"], "DNP")
        self.assertEqual(ne_records[0]["practice_by_day"]["Thursday"], "LP")
        self.assertEqual(ne_records[0]["practice_by_day"]["Friday"], "FP")
        self.assertEqual(ne_records[0]["normalized_player_name"], "example edge")

    def test_multiple_table_rows_for_one_player_are_combined(self) -> None:
        html = """
        <html><body><option value="/team/injury-report/week/REG-3" selected>WEEK 3</option>
        <h2>New England Patriots</h2>
        <table>
        <tr><th>Player</th><th>Position</th><th>Injury</th><th>Wed</th><th>Game Status</th></tr>
        <tr><td>One Player</td><td>WR</td><td>Knee</td><td>DNP</td><td></td></tr>
        </table>
        <h2>New England Patriots</h2>
        <table>
        <tr><th>Player</th><th>Position</th><th>Injury</th><th>Thu</th><th>Game Status</th></tr>
        <tr><td>One Player</td><td>WR</td><td>Knee</td><td>LP</td><td>Questionable</td></tr>
        </table></body></html>
        """
        records, _manifest = parse_official_report(
            html,
            requested_team="NE",
            season=2026,
            week=3,
            source_url="url",
            fetched_at="now",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["practice_by_day"]["Wednesday"], "DNP")
        self.assertEqual(records[0]["practice_by_day"]["Thursday"], "LP")
        self.assertEqual(records[0]["game_status"], "Questionable")

    def test_team_scoped_player_matching(self) -> None:
        html = """
        <html><body><option value="/team/injury-report/week/REG-3" selected>WEEK 3</option>
        <h2>New England Patriots</h2>
        <table><tr><th>Player</th><th>Position</th><th>Injury</th><th>Wed</th></tr>
        <tr><td>Same Name</td><td>WR</td><td>Knee</td><td>DNP</td></tr></table>
        <h2>New York Jets</h2>
        <table><tr><th>Player</th><th>Position</th><th>Injury</th><th>Wed</th></tr>
        <tr><td>Same Name</td><td>CB</td><td>Ankle</td><td>LP</td></tr></table>
        </body></html>
        """
        records, _manifest = parse_official_report(
            html,
            requested_team="NE",
            season=2026,
            week=3,
            source_url="url",
            fetched_at="now",
        )

        self.assertEqual(len(records), 2)
        self.assertEqual({record["team"] for record in records}, {"NE", "NYJ"})

    def test_blank_no_report_page(self) -> None:
        records, manifest = parse_official_report(
            "<html><body><h1>Injury Report</h1><p>No report currently available.</p></body></html>",
            requested_team="NE",
            season=2026,
            week=3,
            source_url="url",
            fetched_at="now",
        )

        self.assertEqual(records, [])
        self.assertEqual(manifest.parse_status, "NO_REPORT_YET")
        self.assertEqual(manifest.current_week_status, "NO_REPORT_YET")

    def test_table_with_only_blank_rows_is_not_counted_as_current_report(self) -> None:
        html = """
        <html><body><option value="/team/injury-report/week/REG-3" selected>WEEK 3</option>
        <h2>New England Patriots</h2>
        <table><tr><th>Player</th><th>Position</th><th>Injury</th><th>Wed</th><th>Game Status</th></tr>
        <tr><td>Placeholder Player</td><td>WR</td><td></td><td></td><td>UNSPECIFIED</td></tr></table>
        </body></html>
        """
        records, manifest = parse_official_report(
            html,
            requested_team="NE",
            season=2026,
            week=3,
            source_url="url",
            fetched_at="now",
        )

        self.assertEqual(len(records), 1)
        self.assertFalse(records[0]["has_report_data"])
        self.assertEqual(manifest.players_found, 0)
        self.assertEqual(manifest.current_week_status, "NO_REPORT_YET")
        self.assertTrue(manifest.warnings)

    def test_stale_report_detection(self) -> None:
        html = STANDARD_HTML.replace("REG-3\" selected", "REG-2\" selected")
        _records, manifest = parse_official_report(
            html,
            requested_team="NE",
            season=2026,
            week=3,
            source_url="url",
            fetched_at="now",
        )

        self.assertEqual(manifest.selected_week, 2)
        self.assertEqual(manifest.current_week_status, "SUCCESS_BUT_STALE")

    def test_schedule_match_confirmation_and_practice_date_inference(self) -> None:
        schedule = ScheduleGameContext(
            season=2026,
            week=3,
            team="NE",
            opponent="NYJ",
            home_away="HOME",
            game_date="2026-09-27",
            kickoff="2026-09-27T17:00:00Z",
            schedule_source="fixture.csv",
            home_team="NE",
            away_team="NYJ",
        )
        records, manifest = parse_official_report(
            STANDARD_HTML,
            requested_team="NE",
            season=2026,
            week=3,
            source_url="url",
            fetched_at="now",
            schedule_context=schedule,
        )

        self.assertEqual(manifest.match_validation, "MATCH_CONFIRMED")
        self.assertEqual(manifest.schedule_opponent, "NYJ")
        self.assertEqual(records[0]["practice_observations"][0]["date"], "2026-09-23")
        self.assertEqual(records[0]["practice_observations"][0]["practice_date_source"], "schedule_inferred")

    def test_schedule_mismatch_marks_report_stale(self) -> None:
        schedule = ScheduleGameContext(
            season=2026,
            week=3,
            team="NE",
            opponent="BUF",
            home_away="HOME",
            game_date="2026-09-27",
            kickoff=None,
            schedule_source="fixture.csv",
            home_team="NE",
            away_team="BUF",
        )
        _records, manifest = parse_official_report(
            STANDARD_HTML,
            requested_team="NE",
            season=2026,
            week=3,
            source_url="url",
            fetched_at="now",
            schedule_context=schedule,
        )

        self.assertEqual(manifest.match_validation, "MATCH_MISMATCH")
        self.assertEqual(manifest.current_week_status, "SUCCESS_BUT_STALE")

    def test_malformed_unexpected_page_handling(self) -> None:
        records, manifest = parse_official_report(
            "<html><body><table><tr><td>Not an injury table</td></tr></table>",
            requested_team="NE",
            season=2026,
            week=3,
            source_url="url",
            fetched_at="now",
        )

        self.assertEqual(records, [])
        self.assertIn(manifest.parse_status, {"NO_REPORT_YET", "PARSE_FAILED"})
        self.assertTrue(manifest.warnings)

    def test_raw_snapshot_metadata(self) -> None:
        scratch = ROOT / "data" / "raw" / "_test_raw_snapshot_metadata"
        original_root = official.RAW_ROOT
        try:
            if scratch.exists():
                shutil.rmtree(scratch)
            official.RAW_ROOT = scratch
            fetch = FetchResult(
                team="NE",
                url="https://www.patriots.com/team/injury-report/",
                status="OK",
                fetched_at="2026-09-24T12:00:00+00:00",
                http_status=200,
                content_type="text/html",
                body="<html>ok</html>",
            )
            raw_path, metadata_path = save_raw_fetch(fetch, season=2026, week=3, run_id="run")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

            self.assertTrue(raw_path.exists())
            self.assertEqual(metadata["team"], "NE")
            self.assertEqual(metadata["http_status"], 200)
            self.assertEqual(metadata["parser_version"], "official_team_common_table_v1")
        finally:
            official.RAW_ROOT = original_root
            if scratch.exists():
                shutil.rmtree(scratch)

    def test_fetch_failure_status_can_be_created_without_live_network(self) -> None:
        self.assertTrue(callable(fetch_page))

    def test_team_inference_does_not_match_abbreviation_inside_name(self) -> None:
        lookup = team_name_lookup([
            {"abbr": "CHI", "full_name": "Chicago Bears", "aliases": []},
            {"abbr": "KC", "full_name": "Kansas City Chiefs", "aliases": ["Chiefs"]},
        ])

        self.assertEqual(infer_table_team("WEEK 3 Kansas City Chiefs", lookup), "KC")

    def test_processed_outputs_separate_meaningful_records_from_source_rows(self) -> None:
        scratch = ROOT / "data" / "processed" / "_test_output_split"
        original_root = official.PROCESSED_ROOT
        meaningful = {
            "season": 2026,
            "week": 3,
            "team": "NE",
            "player_name": "Real Player",
            "normalized_player_name": "real player",
            "source_position": "WR",
            "injury": "Knee",
            "game_status": None,
            "game_status_raw": None,
            "practice_observations": [],
            "practice_by_day": {},
            "has_report_data": True,
            "source_url": "url",
            "fetched_at": "now",
        }
        blank = dict(meaningful)
        blank.update(
            {
                "player_name": "Blank Player",
                "normalized_player_name": "blank player",
                "injury": None,
                "has_report_data": False,
            }
        )
        try:
            if scratch.exists():
                shutil.rmtree(scratch)
            official.PROCESSED_ROOT = scratch
            out_dir = write_processed_outputs(
                season=2026,
                week=3,
                run_id="run",
                records=[meaningful],
                source_rows=[meaningful, blank],
                manifest=[],
            )
            canonical = json.loads((out_dir / "official_injury_reports.json").read_text(encoding="utf-8"))
            source_rows = json.loads((out_dir / "official_injury_source_rows.json").read_text(encoding="utf-8"))

            self.assertEqual(len(canonical), 1)
            self.assertEqual(len(source_rows), 2)
        finally:
            official.PROCESSED_ROOT = original_root
            if scratch.exists():
                shutil.rmtree(scratch)


if __name__ == "__main__":
    unittest.main()
