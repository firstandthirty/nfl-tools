from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from injury_tracker.scripts.injury_schema import normalize_player_name  # noqa: E402
from injury_tracker.scripts.official_roster_reserves import (  # noqa: E402
    canonicalize_status,
    enrich_reserve_records,
    parse_roster_page,
    strip_enrichment_fields,
)
from injury_tracker.scripts.pff_enrichment import PFFGameUsage, PFFPlayerProfile  # noqa: E402
import injury_tracker.scripts.official_roster_reserves as reserves  # noqa: E402


ROSTER_HTML = """
<html><body>
  <h4>Active</h4>
  <table>
    <tr><th>Player</th><th>#</th><th>Pos</th><th>HT</th><th>WT</th></tr>
    <tr><td><a href="/team/players-roster/active-player/">Active Player</a></td><td>1</td><td>WR</td><td>6-0</td><td>200</td></tr>
  </table>
  <h4>Active/Physically Unable to Perform</h4>
  <table>
    <tr><th>Player</th><th>#</th><th>Pos</th><th>HT</th><th>WT</th></tr>
    <tr><td><a href="/team/players-roster/active-pup/">Active Pup</a></td><td>2</td><td>CB</td><td>6-0</td><td>190</td></tr>
  </table>
  <h4>Reserve/Injured</h4>
  <table>
    <tr><th>Player</th><th>#</th><th>Pos</th><th>HT</th><th>WT</th></tr>
    <tr><td><a href="/team/players-roster/high-snap-ir/">High Snap IR Jr.</a></td><td>3</td><td>LB</td><td>6-2</td><td>240</td></tr>
    <tr><td><a href="/team/players-roster/low-role-ir/">Low Role IR</a></td><td>4</td><td>WR</td><td>6-1</td><td>205</td></tr>
  </table>
  <h4>Reserve/Injured; Designated for Return</h4>
  <table>
    <tr><th>Player</th><th>#</th><th>Pos</th><th>HT</th><th>WT</th></tr>
    <tr><td><a href="/team/players-roster/dfr-player/">DFR Player</a></td><td>5</td><td>WR</td><td>6-1</td><td>205</td></tr>
  </table>
  <h4>Reserve/Non-Football Injury</h4>
  <table>
    <tr><th>Player</th><th>#</th><th>Pos</th><th>HT</th><th>WT</th></tr>
    <tr><td><a href="/team/players-roster/nfi-player/">NFI Player</a></td><td>6</td><td>S</td><td>6-0</td><td>205</td></tr>
  </table>
  <h4>Reserve/Physically Unable to Perform</h4>
  <table>
    <tr><th>Player</th><th>#</th><th>Pos</th><th>HT</th><th>WT</th></tr>
    <tr><td><a href="/team/players-roster/pup-player/">PUP Player</a></td><td>7</td><td>TE</td><td>6-5</td><td>250</td></tr>
  </table>
  <h4>Reserve/Suspended by Commissioner</h4>
  <table>
    <tr><th>Player</th><th>#</th><th>Pos</th><th>HT</th><th>WT</th></tr>
    <tr><td><a href="/team/players-roster/suspended-player/">Suspended Player</a></td><td>8</td><td>EDGE</td><td>6-4</td><td>260</td></tr>
  </table>
</body></html>
"""


def profile(
    player_id: str,
    name: str,
    *,
    season: int = 2026,
    week: int = 1,
    team: str = "NE",
    position: str = "WR",
    off_pct: float | None = None,
    def_pct: float | None = None,
    st: int = 0,
) -> PFFPlayerProfile:
    item = PFFPlayerProfile(
        player_id=player_id,
        player_name=name,
        normalized_player_name=normalize_player_name(name),
        teams={team},
        positions=Counter({position: 1}),
    )
    item.games[week] = PFFGameUsage(
        season=season,
        week=week,
        player_id=player_id,
        player_name=name,
        normalized_player_name=normalize_player_name(name),
        teams={team},
        positions=Counter({position: 1}),
        offensive_snaps=int(off_pct * 100) if off_pct is not None else 0,
        team_offensive_snaps=100 if off_pct is not None else 0,
        offensive_snap_pct=off_pct,
        defensive_snaps=int(def_pct * 100) if def_pct is not None else 0,
        team_defensive_snaps=100 if def_pct is not None else 0,
        defensive_snap_pct=def_pct,
        special_teams_snaps=st,
    )
    return item


def identity_profile(player_id: str, name: str, *, team: str = "NE", position: str = "WR") -> PFFPlayerProfile:
    item = PFFPlayerProfile(
        player_id=player_id,
        player_name=name,
        normalized_player_name=normalize_player_name(name),
        teams={team},
        positions=Counter({position: 1}),
    )
    item.identity_sources.add("player_directory")
    return item


class OfficialRosterReserveTests(unittest.TestCase):
    def test_canonical_status_model_preserves_active_pup_distinction(self) -> None:
        active = canonicalize_status("Active/Physically Unable to Perform")
        reserve = canonicalize_status("Reserve/Physically Unable to Perform")

        self.assertEqual(active["canonical_roster_status"], "ACTIVE")
        self.assertTrue(active["active_roster"])
        self.assertFalse(active["reserve_list"])
        self.assertTrue(active["pup_related"])
        self.assertEqual(reserve["canonical_roster_status"], "PUP")
        self.assertTrue(reserve["reserve_list"])
        self.assertFalse(reserve["active_roster"])

    def test_common_club_roster_parser_and_injury_filtering(self) -> None:
        reserve_rows, source_rows, manifest = parse_roster_page(
            ROSTER_HTML,
            team="NE",
            season=2026,
            week=3,
            source_url="https://www.patriots.com/team/players-roster/",
            fetched_at="2026-09-28T12:00:00+00:00",
            raw_snapshot="raw.html",
        )

        statuses = Counter(row["canonical_roster_status"] for row in reserve_rows)
        self.assertEqual(manifest.parse_status, "OK")
        self.assertEqual(len(source_rows), 8)
        self.assertEqual(len(reserve_rows), 5)
        self.assertEqual(statuses["IR"], 3)
        self.assertEqual(statuses["PUP"], 1)
        self.assertEqual(statuses["NFI"], 1)
        self.assertEqual(manifest.ir_designated_for_return, 1)
        self.assertEqual(manifest.active_pup_like, 1)
        self.assertEqual(manifest.other_non_injury_reserve, 1)
        self.assertTrue(all(row["raw_roster_status"] for row in source_rows))
        self.assertTrue(any(row["player_profile_url"].endswith("/high-snap-ir/") for row in reserve_rows))
        self.assertFalse(any(row["player_name"] == "Suspended Player" for row in reserve_rows))

    def test_pff_identity_position_and_candidate_relevance_are_reused(self) -> None:
        reserve_rows, _source_rows, _manifest = parse_roster_page(
            ROSTER_HTML,
            team="NE",
            season=2026,
            week=3,
            source_url="https://www.patriots.com/team/players-roster/",
            fetched_at="2026-09-28T12:00:00+00:00",
        )
        profiles = {
            "1": profile("1", "High Snap IR Jr.", position="ED", def_pct=0.82),
            "2": profile("2", "Low Role IR", position="WR", off_pct=0.02),
            "3": profile("3", "DFR Player", position="WR", off_pct=0.4),
            "4": profile("4", "PUP Player", position="TE", off_pct=None, st=12),
        }
        original_build = reserves.build_pff_player_index
        original_persist = reserves.persist_pff_index
        try:
            reserves.build_pff_player_index = lambda *args, **kwargs: profiles
            reserves.persist_pff_index = lambda *args, **kwargs: (Path("index.json"), Path("index.csv"))
            enriched, manifest = enrich_reserve_records(reserve_rows, season=2026, week=3)
        finally:
            reserves.build_pff_player_index = original_build
            reserves.persist_pff_index = original_persist

        by_name = {row["normalized_player_name"]: row for row in enriched}
        high = by_name[normalize_player_name("High Snap IR Jr.")]
        low = by_name[normalize_player_name("Low Role IR")]
        pup = by_name[normalize_player_name("PUP Player")]
        nfi = by_name[normalize_player_name("NFI Player")]

        self.assertEqual(high["pff_position"], "ED")
        self.assertEqual(high["canonical_position"], "ED")
        self.assertEqual(high["position_source"], "pff")
        self.assertTrue(high["key_candidate"])
        self.assertIn("recent_healthy_snap_pct=82.0", high["candidate_reasons"])
        self.assertFalse(low["key_candidate"])
        self.assertIn("low_role", low["candidate_reasons"])
        self.assertFalse(pup["key_candidate"])
        self.assertIn("special_teams_only", pup["candidate_reasons"])
        self.assertEqual(nfi["snap_data_status"], "NO_DATA")
        self.assertFalse(nfi["key_candidate"])
        self.assertEqual(manifest["pff_identity_unmatched"], 1)

    def test_manual_include_exclude_precedence_for_reserve_rows(self) -> None:
        reserve_rows, _source_rows, _manifest = parse_roster_page(
            ROSTER_HTML,
            team="NE",
            season=2026,
            week=3,
            source_url="https://www.patriots.com/team/players-roster/",
            fetched_at="2026-09-28T12:00:00+00:00",
        )
        profiles = {
            "1": profile("1", "High Snap IR Jr.", position="ED", def_pct=0.82),
            "2": profile("2", "Low Role IR", position="WR", off_pct=0.02),
        }
        original_build = reserves.build_pff_player_index
        original_persist = reserves.persist_pff_index
        original_manual = reserves.load_manual_override_map
        try:
            reserves.build_pff_player_index = lambda *args, **kwargs: profiles
            reserves.persist_pff_index = lambda *args, **kwargs: (Path("index.json"), Path("index.csv"))
            reserves.load_manual_override_map = lambda: {
                ("NE", normalize_player_name("High Snap IR Jr.")): {"publish": "exclude"},
                ("NE", normalize_player_name("Low Role IR")): {"publish": "include"},
            }
            enriched, _manifest = enrich_reserve_records(reserve_rows, season=2026, week=3)
        finally:
            reserves.build_pff_player_index = original_build
            reserves.persist_pff_index = original_persist
            reserves.load_manual_override_map = original_manual

        by_name = {row["normalized_player_name"]: row for row in enriched}
        self.assertFalse(by_name[normalize_player_name("High Snap IR Jr.")]["key_candidate"])
        self.assertIn("manual_exclude", by_name[normalize_player_name("High Snap IR Jr.")]["candidate_reasons"])
        self.assertTrue(by_name[normalize_player_name("Low Role IR")]["key_candidate"])
        self.assertIn("manual_include", by_name[normalize_player_name("Low Role IR")]["candidate_reasons"])

    def test_reserve_only_player_resolves_through_directory_profile_with_snap_join(self) -> None:
        reserve_rows, _source_rows, _manifest = parse_roster_page(
            ROSTER_HTML,
            team="NE",
            season=2026,
            week=3,
            source_url="https://www.patriots.com/team/players-roster/",
            fetched_at="2026-09-28T12:00:00+00:00",
        )
        profiles = {
            "42": profile("42", "DFR Player", position="WR", off_pct=0.45),
        }
        profiles["42"].identity_sources.add("player_directory")
        original_build = reserves.build_pff_player_index
        original_persist = reserves.persist_pff_index
        try:
            reserves.build_pff_player_index = lambda *args, **kwargs: profiles
            reserves.persist_pff_index = lambda *args, **kwargs: (Path("index.json"), Path("index.csv"))
            enriched, _manifest = enrich_reserve_records([strip_enrichment_fields(row) for row in reserve_rows], season=2026, week=3)
        finally:
            reserves.build_pff_player_index = original_build
            reserves.persist_pff_index = original_persist

        dfr = {row["normalized_player_name"]: row for row in enriched}[normalize_player_name("DFR Player")]
        self.assertEqual(dfr["pff_identity_status"], "MATCHED")
        self.assertEqual(dfr["pff_position"], "WR")
        self.assertEqual(dfr["snap_data_status"], "OFFENSE_DEFENSE")
        self.assertEqual(dfr["raw_roster_status"], "Reserve/Injured; Designated for Return")
        self.assertTrue(dfr["designated_for_return"])

    def test_safe_alias_resolution_for_reserve_player(self) -> None:
        reserve_rows, _source_rows, _manifest = parse_roster_page(
            ROSTER_HTML.replace("High Snap IR Jr.", "Snap Alias"),
            team="NE",
            season=2026,
            week=3,
            source_url="https://www.patriots.com/team/players-roster/",
            fetched_at="2026-09-28T12:00:00+00:00",
        )
        p = profile("55", "High Snap IR Jr.", position="ED", def_pct=0.7)
        p.aliases.add(normalize_player_name("Snap Alias"))
        p.identity_sources.add("player_directory")
        original_build = reserves.build_pff_player_index
        original_persist = reserves.persist_pff_index
        try:
            reserves.build_pff_player_index = lambda *args, **kwargs: {"55": p}
            reserves.persist_pff_index = lambda *args, **kwargs: (Path("index.json"), Path("index.csv"))
            enriched, _manifest = enrich_reserve_records([strip_enrichment_fields(row) for row in reserve_rows], season=2026, week=3)
        finally:
            reserves.build_pff_player_index = original_build
            reserves.persist_pff_index = original_persist

        row = {item["normalized_player_name"]: item for item in enriched}[normalize_player_name("Snap Alias")]
        self.assertEqual(row["pff_identity_status"], "MATCHED")
        self.assertEqual(row["match_method"], "safe_directory_alias_current_team")

    def test_duplicate_reserve_directory_identity_remains_review_required(self) -> None:
        reserve_rows, _source_rows, _manifest = parse_roster_page(
            ROSTER_HTML,
            team="NE",
            season=2026,
            week=3,
            source_url="https://www.patriots.com/team/players-roster/",
            fetched_at="2026-09-28T12:00:00+00:00",
        )
        profiles = {
            "1": profile("1", "Low Role IR", team="DAL", position="WR", off_pct=0.1),
            "2": profile("2", "Low Role IR", team="NYJ", position="CB", def_pct=0.1),
        }
        original_build = reserves.build_pff_player_index
        original_persist = reserves.persist_pff_index
        try:
            reserves.build_pff_player_index = lambda *args, **kwargs: profiles
            reserves.persist_pff_index = lambda *args, **kwargs: (Path("index.json"), Path("index.csv"))
            enriched, _manifest = enrich_reserve_records([strip_enrichment_fields(row) for row in reserve_rows], season=2026, week=3)
        finally:
            reserves.build_pff_player_index = original_build
            reserves.persist_pff_index = original_persist

        row = {item["normalized_player_name"]: item for item in enriched}[normalize_player_name("Low Role IR")]
        self.assertEqual(row["pff_identity_status"], "REVIEW_REQUIRED")
        self.assertEqual(row["match_status"], "REVIEW_REQUIRED")

    def test_matched_reserve_player_without_participation_remains_no_data(self) -> None:
        reserve_rows, _source_rows, _manifest = parse_roster_page(
            ROSTER_HTML,
            team="NE",
            season=2026,
            week=3,
            source_url="https://www.patriots.com/team/players-roster/",
            fetched_at="2026-09-28T12:00:00+00:00",
        )
        p = PFFPlayerProfile(
            player_id="88",
            player_name="NFI Player",
            normalized_player_name=normalize_player_name("NFI Player"),
            teams={"NE"},
            positions=Counter({"S": 1}),
            identity_sources={"player_directory"},
        )
        original_build = reserves.build_pff_player_index
        original_persist = reserves.persist_pff_index
        try:
            reserves.build_pff_player_index = lambda *args, **kwargs: {"88": p}
            reserves.persist_pff_index = lambda *args, **kwargs: (Path("index.json"), Path("index.csv"))
            enriched, _manifest = enrich_reserve_records([strip_enrichment_fields(row) for row in reserve_rows], season=2026, week=3)
        finally:
            reserves.build_pff_player_index = original_build
            reserves.persist_pff_index = original_persist

        row = {item["normalized_player_name"]: item for item in enriched}[normalize_player_name("NFI Player")]
        self.assertEqual(row["pff_identity_status"], "MATCHED")
        self.assertEqual(row["snap_data_status"], "NO_DATA")
        self.assertEqual(row["canonical_roster_status"], "NFI")

    def test_prior_season_fallback_promotes_reserve_no_data_player(self) -> None:
        reserve_rows, _source_rows, _manifest = parse_roster_page(
            ROSTER_HTML,
            team="NE",
            season=2026,
            week=3,
            source_url="https://www.patriots.com/team/players-roster/",
            fetched_at="2026-09-28T12:00:00+00:00",
        )
        current_profiles = {"2": identity_profile("2", "Low Role IR", team="NE", position="WR")}
        prior_profiles = {"2": profile("2", "Low Role IR", season=2025, week=7, team="DAL", position="WR", off_pct=0.72)}
        enriched = self.enrich_with_profiles(reserve_rows, current_profiles, prior_profiles)
        row = {item["normalized_player_name"]: item for item in enriched}[normalize_player_name("Low Role IR")]

        self.assertTrue(row["key_candidate"])
        self.assertEqual(row["snap_data_status"], "NO_DATA")
        self.assertEqual(row["prior_season_snap_data_status"], "OFFENSE_DEFENSE")
        self.assertEqual(row["prior_season_team"], "DAL")
        self.assertEqual(row["participation_source_season"], 2025)
        self.assertTrue(any(reason.startswith("prior_season_snap_pct=") for reason in row["candidate_reasons"]))

    def test_current_season_participation_takes_precedence_over_prior_season(self) -> None:
        reserve_rows, _source_rows, _manifest = parse_roster_page(
            ROSTER_HTML,
            team="NE",
            season=2026,
            week=3,
            source_url="https://www.patriots.com/team/players-roster/",
            fetched_at="2026-09-28T12:00:00+00:00",
        )
        current_profiles = {"2": profile("2", "Low Role IR", season=2026, week=1, team="NE", position="WR", off_pct=0.02)}
        prior_profiles = {"2": profile("2", "Low Role IR", season=2025, week=7, team="DAL", position="WR", off_pct=0.90)}
        enriched = self.enrich_with_profiles(reserve_rows, current_profiles, prior_profiles)
        row = {item["normalized_player_name"]: item for item in enriched}[normalize_player_name("Low Role IR")]

        self.assertFalse(row["key_candidate"])
        self.assertEqual(row["snap_data_status"], "OFFENSE_DEFENSE")
        self.assertEqual(row["participation_source_season"], 2026)
        self.assertNotIn("prior_season_snap_pct=90.0", row["candidate_reasons"])

    def test_prior_season_below_threshold_does_not_promote(self) -> None:
        reserve_rows, _source_rows, _manifest = parse_roster_page(
            ROSTER_HTML,
            team="NE",
            season=2026,
            week=3,
            source_url="https://www.patriots.com/team/players-roster/",
            fetched_at="2026-09-28T12:00:00+00:00",
        )
        current_profiles = {"2": identity_profile("2", "Low Role IR", team="NE", position="WR")}
        prior_profiles = {"2": profile("2", "Low Role IR", season=2025, week=7, team="DAL", position="WR", off_pct=0.12)}
        enriched = self.enrich_with_profiles(reserve_rows, current_profiles, prior_profiles)
        row = {item["normalized_player_name"]: item for item in enriched}[normalize_player_name("Low Role IR")]

        self.assertFalse(row["key_candidate"])
        self.assertEqual(row["prior_season_snap_data_status"], "OFFENSE_DEFENSE")
        self.assertEqual(row["candidate_reasons"], ["low_role"])

    def test_prior_season_st_only_does_not_promote(self) -> None:
        reserve_rows, _source_rows, _manifest = parse_roster_page(
            ROSTER_HTML,
            team="NE",
            season=2026,
            week=3,
            source_url="https://www.patriots.com/team/players-roster/",
            fetched_at="2026-09-28T12:00:00+00:00",
        )
        current_profiles = {"2": identity_profile("2", "Low Role IR", team="NE", position="WR")}
        prior_profiles = {"2": profile("2", "Low Role IR", season=2025, week=7, team="DAL", position="WR", st=18)}
        enriched = self.enrich_with_profiles(reserve_rows, current_profiles, prior_profiles)
        row = {item["normalized_player_name"]: item for item in enriched}[normalize_player_name("Low Role IR")]

        self.assertFalse(row["key_candidate"])
        self.assertEqual(row["prior_season_snap_data_status"], "ST_ONLY")
        self.assertEqual(row["candidate_reasons"], ["low_role"])

    def test_prior_season_no_data_is_not_treated_as_zero(self) -> None:
        reserve_rows, _source_rows, _manifest = parse_roster_page(
            ROSTER_HTML,
            team="NE",
            season=2026,
            week=3,
            source_url="https://www.patriots.com/team/players-roster/",
            fetched_at="2026-09-28T12:00:00+00:00",
        )
        current_profiles = {"2": identity_profile("2", "Low Role IR", team="NE", position="WR")}
        prior_profiles = {"2": identity_profile("2", "Low Role IR", team="DAL", position="WR")}
        enriched = self.enrich_with_profiles(reserve_rows, current_profiles, prior_profiles)
        row = {item["normalized_player_name"]: item for item in enriched}[normalize_player_name("Low Role IR")]

        self.assertFalse(row["key_candidate"])
        self.assertEqual(row["prior_season_snap_data_status"], "NO_DATA")
        self.assertIsNone(row["prior_season_relevant_snap_pct"])
        self.assertEqual(row["candidate_reasons"], ["low_role"])

    def test_manual_and_qb_rules_still_win_with_prior_season_fallback(self) -> None:
        reserve_rows, _source_rows, _manifest = parse_roster_page(
            ROSTER_HTML,
            team="NE",
            season=2026,
            week=3,
            source_url="https://www.patriots.com/team/players-roster/",
            fetched_at="2026-09-28T12:00:00+00:00",
        )
        current_profiles = {
            "2": identity_profile("2", "Low Role IR", team="NE", position="WR"),
            "9": identity_profile("9", "NFI Player", team="NE", position="QB"),
        }
        prior_profiles = {
            "2": profile("2", "Low Role IR", season=2025, week=7, team="DAL", position="WR", off_pct=0.90),
            "9": identity_profile("9", "NFI Player", team="DAL", position="QB"),
        }
        original_manual = reserves.load_manual_override_map
        try:
            reserves.load_manual_override_map = lambda: {
                ("NE", normalize_player_name("Low Role IR")): {"publish": "exclude"},
            }
            enriched = self.enrich_with_profiles(reserve_rows, current_profiles, prior_profiles)
        finally:
            reserves.load_manual_override_map = original_manual
        by_name = {item["normalized_player_name"]: item for item in enriched}

        manual = by_name[normalize_player_name("Low Role IR")]
        qb = by_name[normalize_player_name("NFI Player")]
        self.assertFalse(manual["key_candidate"])
        self.assertEqual(manual["candidate_reasons"], ["manual_exclude"])
        self.assertTrue(qb["key_candidate"])
        self.assertEqual(qb["candidate_reasons"], ["QB"])
        self.assertEqual(qb["canonical_roster_status"], "NFI")

    def test_injury_report_enrich_record_does_not_use_prior_season_without_flag(self) -> None:
        from injury_tracker.scripts.pff_enrichment import MatchResult, enrich_record

        current = identity_profile("2", "Low Role IR", team="NE", position="WR")
        prior = profile("2", "Low Role IR", season=2025, week=7, team="DAL", position="WR", off_pct=0.90)
        record = {
            "season": 2026,
            "week": 3,
            "team": "NE",
            "player_name": "Low Role IR",
            "normalized_player_name": normalize_player_name("Low Role IR"),
            "source_position": "WR",
            "game_status": None,
            "injury": "Hamstring",
        }
        row = enrich_record(
            record,
            MatchResult("EXACT", "test", current, []),
            {},
            {"candidate_rules": {"season_snap_pct_threshold": 0.25, "qb_always_candidate": True, "include_out_or_doubtful_players": True, "exclude_special_teams_by_default": True}, "review_flags": {"flag_missing_pff_match": True}},
            prior_season_profile=prior,
            prior_season=2025,
            enable_prior_season_fallback=False,
        )

        self.assertFalse(row["key_candidate"])
        self.assertEqual(row["candidate_reasons"], ["low_role"])
        self.assertEqual(row["participation_source_season"], 2026)

    def enrich_with_profiles(
        self,
        reserve_rows,
        current_profiles: dict[str, PFFPlayerProfile],
        prior_profiles: dict[str, PFFPlayerProfile],
    ):
        original_build = reserves.build_pff_player_index
        original_persist = reserves.persist_pff_index
        try:
            reserves.build_pff_player_index = lambda season, *args, **kwargs: current_profiles if season == 2026 else prior_profiles
            reserves.persist_pff_index = lambda *args, **kwargs: (Path("index.json"), Path("index.csv"))
            enriched, _manifest = enrich_reserve_records([strip_enrichment_fields(row) for row in reserve_rows], season=2026, week=3)
        finally:
            reserves.build_pff_player_index = original_build
            reserves.persist_pff_index = original_persist
        return enriched


if __name__ == "__main__":
    unittest.main()
