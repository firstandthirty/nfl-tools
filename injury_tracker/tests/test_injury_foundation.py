from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from injury_schema import (  # noqa: E402
    InjuryPlayerRecord,
    load_manual_overrides,
    load_manual_players,
    load_teams,
    resolve_position,
    validate_team_abbr,
)


class InjuryFoundationTests(unittest.TestCase):
    def test_exactly_32_teams_exist(self) -> None:
        self.assertEqual(len(load_teams()), 32)

    def test_team_abbreviations_are_unique(self) -> None:
        abbreviations = [team["abbr"] for team in load_teams()]
        self.assertEqual(len(abbreviations), len(set(abbreviations)))

    def test_every_team_has_required_urls(self) -> None:
        for team in load_teams():
            self.assertTrue(team["injury_report_url"].startswith("https://"))
            self.assertTrue(team["injury_report_url"].endswith("/team/injury-report/"))
            self.assertTrue(team["roster_url"].startswith("https://"))
            self.assertTrue(team["roster_url"].endswith("/team/players-roster/"))

    def test_missing_supplied_team_was_added(self) -> None:
        teams = {team["abbr"]: team for team in load_teams()}
        self.assertEqual(teams["CIN"]["full_name"], "Cincinnati Bengals")
        self.assertEqual(teams["CIN"]["injury_report_url"], "https://www.bengals.com/team/injury-report/")

    def test_invalid_team_abbreviation_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_team_abbr("XYZ")

    def test_pff_position_takes_precedence_over_official_position(self) -> None:
        result = resolve_position(pff_position="EDGE", source_position="LB")
        self.assertEqual(result.canonical_position, "EDGE")
        self.assertEqual(result.position_group, "EDGE")
        self.assertEqual(result.position_source, "pff")
        self.assertEqual(result.source_position, "LB")

    def test_manual_override_takes_precedence_over_pff(self) -> None:
        result = resolve_position(
            pff_position="LB",
            source_position="LB",
            manual_position_override="EDGE",
        )
        self.assertEqual(result.canonical_position, "EDGE")
        self.assertEqual(result.position_group, "EDGE")
        self.assertEqual(result.position_source, "manual")

    def test_official_position_is_used_when_pff_unavailable(self) -> None:
        result = resolve_position(source_position="WR")
        self.assertEqual(result.canonical_position, "WR")
        self.assertEqual(result.position_group, "WR")
        self.assertEqual(result.position_source, "official_team")

    def test_offensive_line_positions_map_to_ol(self) -> None:
        for position in ["LT", "LG", "C", "RG", "RT"]:
            with self.subTest(position=position):
                self.assertEqual(resolve_position(source_position=position).position_group, "OL")

    def test_pff_edge_and_lb_remain_distinct(self) -> None:
        self.assertEqual(resolve_position(pff_position="EDGE", source_position="OLB").position_group, "EDGE")
        self.assertEqual(resolve_position(pff_position="LB", source_position="OLB").position_group, "LB")

    def test_pff_interior_defensive_line_maps_to_dl(self) -> None:
        result = resolve_position(pff_position="DI", source_position="DT")
        self.assertEqual(result.canonical_position, "DI")
        self.assertEqual(result.position_group, "DL")

    def test_special_teams_positions_map_to_st(self) -> None:
        for position in ["K", "P", "LS"]:
            with self.subTest(position=position):
                self.assertEqual(resolve_position(source_position=position).position_group, "ST")

    def test_canonical_record_preserves_position_audit_fields(self) -> None:
        position = resolve_position(pff_position="EDGE", source_position="LB")
        record = InjuryPlayerRecord(
            season=2026,
            week=3,
            player_name="Example Player Jr.",
            team="KC",
            pff_player_id="pff-123",
            pff_position=position.pff_position,
            source_position=position.source_position,
            canonical_position=position.canonical_position,
            position_group=position.position_group,
            position_source=position.position_source,
            source_metadata={"official_team": {"field": "position"}},
            fetched_at=datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc),
        )

        data = record.to_dict()
        self.assertEqual(data["normalized_player_name"], "example player")
        self.assertEqual(data["source_position"], "LB")
        self.assertEqual(data["canonical_position"], "EDGE")
        self.assertEqual(data["position_source"], "pff")
        self.assertEqual(data["fetched_at"], "2026-09-24T12:00:00+00:00")

    def test_canonical_injury_record_serializes_to_json(self) -> None:
        record = InjuryPlayerRecord(season=2026, week=3, player_name="Jane Doe", team="BUF")
        payload = json.loads(record.to_json())
        self.assertEqual(payload["team"], "BUF")
        self.assertIsNone(payload["injury"])

    def test_manual_csv_schemas_load(self) -> None:
        self.assertEqual(load_manual_overrides(), [])
        manual_players = load_manual_players()
        self.assertIsInstance(manual_players, list)
        for row in manual_players:
            self.assertIn("season", row)
            self.assertIn("week", row)
            self.assertIn("team", row)
            self.assertIn("player", row)


if __name__ == "__main__":
    unittest.main()
