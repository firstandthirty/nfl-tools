from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from injury_tracker.scripts.pff_enrichment import (  # noqa: E402
    MatchResult,
    PFFGameUsage,
    PFFPlayerProfile,
    compare_enrichment_outputs,
    enrich_record,
    match_player,
    profiles_from_index_rows,
    profiles_by_alias,
    profiles_by_normalized_name,
    usage_summary,
)
from injury_tracker.scripts.injury_schema import normalize_player_name  # noqa: E402


RULES = {
    "candidate_rules": {
        "qb_always_candidate": True,
        "season_snap_pct_threshold": 0.25,
        "previous_game_snap_pct_threshold": 0.25,
        "include_out_or_doubtful_players": True,
        "exclude_special_teams_by_default": True,
    },
    "review_flags": {
        "flag_missing_pff_match": True,
    },
}


def profile(
    player_id: str,
    name: str,
    team: str = "NE",
    position: str = "CB",
    weeks: list[tuple[int, float | None, float | None]] | None = None,
) -> PFFPlayerProfile:
    item = PFFPlayerProfile(
        player_id=player_id,
        player_name=name,
        normalized_player_name=normalize_player_name(name),
        teams={team},
        positions=Counter({position: 1}),
    )
    for week, off_pct, def_pct in weeks or [(1, None, 0.95)]:
        game = PFFGameUsage(
            season=2026,
            week=week,
            player_id=player_id,
            player_name=name,
            normalized_player_name=normalize_player_name(name),
            teams={team},
            positions=Counter({position: 1}),
            offensive_snaps=50 if off_pct is not None else 0,
            defensive_snaps=50 if def_pct is not None else 0,
            offensive_snap_pct=off_pct,
            defensive_snap_pct=def_pct,
        )
        item.games[week] = game
    return item


def true_snap_profile(
    player_id: str,
    name: str,
    team: str,
    position: str,
    weeks: list[tuple[int, int, int, int, int, int]],
) -> PFFPlayerProfile:
    item = PFFPlayerProfile(
        player_id=player_id,
        player_name=name,
        normalized_player_name=normalize_player_name(name),
        teams={team},
        positions=Counter({position: 1}),
    )
    for week, off, team_off, defense, team_def, st in weeks:
        item.games[week] = PFFGameUsage(
            season=2026,
            week=week,
            player_id=player_id,
            player_name=name,
            normalized_player_name=normalize_player_name(name),
            teams={team},
            positions=Counter({position: 1}),
            offensive_snaps=off,
            team_offensive_snaps=team_off,
            offensive_snap_pct=off / team_off if team_off else None,
            defensive_snaps=defense,
            team_defensive_snaps=team_def,
            defensive_snap_pct=defense / team_def if team_def else None,
            special_teams_snaps=st,
        )
    return item


def official(name: str, team: str = "NE", source_position: str = "CB", game_status: str | None = "Questionable") -> dict:
    return {
        "season": 2026,
        "week": 3,
        "team": team,
        "player_name": name,
        "normalized_player_name": normalize_player_name(name),
        "source_position": source_position,
        "injury": "Knee",
        "game_status": game_status,
    }


class PFFEnrichmentTests(unittest.TestCase):
    def test_exact_name_team_match(self) -> None:
        profiles = {"1": profile("1", "Christian Gonzalez", "NE")}
        match = match_player(
            official("Christian Gonzalez"),
            profiles=profiles,
            by_name=profiles_by_normalized_name(profiles),
            persisted={},
        )

        self.assertEqual(match.status, "EXACT")
        self.assertEqual(match.profile.player_id, "1")

    def test_normalized_suffix_and_punctuation_match(self) -> None:
        profiles = {"1": profile("1", "Example O'Player Jr.", "NE")}
        match = match_player(
            official("Example O Player", "NE"),
            profiles=profiles,
            by_name=profiles_by_normalized_name(profiles),
            persisted={},
        )

        self.assertEqual(match.status, "EXACT")

    def test_ambiguous_player_is_review_required(self) -> None:
        profiles = {
            "1": profile("1", "Same Name", "NE"),
            "2": profile("2", "Same Name", "NE"),
        }
        match = match_player(
            official("Same Name"),
            profiles=profiles,
            by_name=profiles_by_normalized_name(profiles),
            persisted={},
        )

        self.assertEqual(match.status, "REVIEW_REQUIRED")
        self.assertEqual(len(match.candidates), 2)

    def test_unmatched_player_is_not_silently_dropped(self) -> None:
        enriched = enrich_record(official("Missing Player"), MatchResult("UNMATCHED", None, None, []), {}, RULES)

        self.assertEqual(enriched["match_status"], "UNMATCHED")
        self.assertEqual(enriched["pff_identity_status"], "UNMATCHED")
        self.assertFalse(enriched["key_candidate"])
        self.assertIn("pff_unmatched", enriched["candidate_reasons"])

    def test_exact_unique_directory_identity_without_snap_data(self) -> None:
        p = PFFPlayerProfile(
            player_id="10",
            player_name="Directory Player",
            normalized_player_name=normalize_player_name("Directory Player"),
            teams={"NE"},
            positions=Counter({"CB": 1}),
            identity_sources={"player_directory"},
        )
        profiles = {"10": p}
        match = match_player(
            official("Directory Player"),
            profiles=profiles,
            by_name=profiles_by_normalized_name(profiles),
            persisted={},
        )
        enriched = enrich_record(official("Directory Player"), match, {}, RULES)

        self.assertEqual(match.status, "EXACT")
        self.assertEqual(enriched["pff_identity_status"], "MATCHED")
        self.assertEqual(enriched["snap_data_status"], "NO_DATA")
        self.assertEqual(enriched["pff_position"], "CB")
        self.assertIsNone(enriched["season_relevant_snap_pct"])

    def test_pff_position_overrides_official_source_position(self) -> None:
        p = profile("1", "Edge Guy", "NE", "ED")
        enriched = enrich_record(
            official("Edge Guy", source_position="LB"),
            MatchResult("EXACT", "test", p, []),
            {},
            RULES,
        )

        self.assertEqual(enriched["pff_position"], "ED")
        self.assertEqual(enriched["canonical_position"], "ED")
        self.assertEqual(enriched["position_group"], "EDGE")
        self.assertEqual(enriched["position_source"], "pff")

    def test_manual_position_override_wins_over_pff(self) -> None:
        p = profile("1", "Override Guy", "NE", "CB")
        enriched = enrich_record(
            official("Override Guy", source_position="CB"),
            MatchResult("EXACT", "test", p, []),
            {"position_override": "S"},
            RULES,
        )

        self.assertEqual(enriched["canonical_position"], "S")
        self.assertEqual(enriched["position_group"], "S")
        self.assertEqual(enriched["position_source"], "manual")

    def test_prior_team_historical_data_retained_after_unique_identity_match(self) -> None:
        profiles = {"1": profile("1", "Team Changer", "DAL", "CB")}
        match = match_player(
            official("Team Changer", "NE"),
            profiles=profiles,
            by_name=profiles_by_normalized_name(profiles),
            persisted={},
        )

        self.assertEqual(match.status, "NORMALIZED")
        self.assertEqual(match.profile.player_id, "1")

    def test_persisted_pff_id_wins_when_current_snap_team_differs(self) -> None:
        profiles = {"1": profile("1", "Mapped Player", "DAL", "CB")}
        match = match_player(
            official("Mapped Player", "NE"),
            profiles=profiles,
            by_name=profiles_by_normalized_name(profiles),
            persisted={("NE", normalize_player_name("Mapped Player")): "1"},
        )

        self.assertEqual(match.status, "PERSISTED")
        self.assertEqual(match.profile.player_id, "1")

    def test_generated_identity_index_can_be_reused(self) -> None:
        profiles = profiles_from_index_rows(
            [
                {
                    "player_id": "42",
                    "player_name": "Indexed Player",
                    "normalized_player_name": "indexed player",
                    "teams": ["NE"],
                    "positions": {"CB": 1},
                    "aliases": ["alias player"],
                    "identity_sources": ["player_directory"],
                }
            ]
        )

        self.assertIn("42", profiles)
        self.assertIn("generated_pff_index", profiles["42"].identity_sources)
        self.assertIn("alias player", profiles["42"].aliases)

    def test_duplicate_exact_directory_identities_become_review_required(self) -> None:
        profiles = {
            "1": PFFPlayerProfile("1", "Same Name", normalize_player_name("Same Name"), teams={"DAL"}, positions=Counter({"CB": 1}), identity_sources={"player_directory"}),
            "2": PFFPlayerProfile("2", "Same Name", normalize_player_name("Same Name"), teams={"NYJ"}, positions=Counter({"S": 1}), identity_sources={"player_directory"}),
        }
        match = match_player(
            official("Same Name", "NE"),
            profiles=profiles,
            by_name=profiles_by_normalized_name(profiles),
            persisted={},
        )

        self.assertEqual(match.status, "REVIEW_REQUIRED")
        self.assertEqual(match.method, "ambiguous_normalized_name")

    def test_manual_mapping_resolves_duplicate_directory_identity(self) -> None:
        profiles = {
            "1": PFFPlayerProfile("1", "Same Name", normalize_player_name("Same Name"), teams={"DAL"}, positions=Counter({"CB": 1}), identity_sources={"player_directory"}),
            "2": PFFPlayerProfile("2", "Same Name", normalize_player_name("Same Name"), teams={"NYJ"}, positions=Counter({"S": 1}), identity_sources={"player_directory"}),
        }
        match = match_player(
            official("Same Name", "NE"),
            profiles=profiles,
            by_name=profiles_by_normalized_name(profiles),
            persisted={("NE", normalize_player_name("Same Name")): "2"},
        )

        self.assertEqual(match.status, "PERSISTED")
        self.assertEqual(match.profile.player_id, "2")

    def test_safe_directory_alias_can_match_current_team(self) -> None:
        p = PFFPlayerProfile(
            player_id="1",
            player_name="Robert Beal Jr.",
            normalized_player_name=normalize_player_name("Robert Beal Jr."),
            teams={"MIA"},
            positions=Counter({"ED": 1}),
            aliases={normalize_player_name("Rob Beal Jr.")},
            identity_sources={"player_directory"},
        )
        profiles = {"1": p}
        match = match_player(
            official("Rob Beal Jr.", "MIA", "EDGE"),
            profiles=profiles,
            by_name=profiles_by_normalized_name(profiles),
            by_alias=profiles_by_alias(profiles),
            persisted={},
        )

        self.assertEqual(match.status, "NORMALIZED")
        self.assertEqual(match.method, "safe_directory_alias_current_team")
        self.assertEqual(match.profile.player_id, "1")

    def test_offensive_player_uses_offensive_snaps(self) -> None:
        p = profile("1", "Wide Receiver", "NE", "WR", [(1, 0.82, None)])
        usage = usage_summary(p, 3)

        self.assertEqual(usage["season_relevant_snap_pct"], 0.82)

    def test_true_snap_season_participation_uses_counts_and_denominators(self) -> None:
        p = true_snap_profile("1", "Count Player", "NE", "WR", [(1, 30, 60, 0, 0, 0), (2, 40, 80, 0, 0, 0)])
        usage = usage_summary(p, 3)

        self.assertEqual(usage["season_relevant_snaps"], 70)
        self.assertEqual(usage["season_relevant_team_snaps"], 140)
        self.assertEqual(usage["season_relevant_snap_pct"], 0.5)

    def test_true_snap_defense_uses_defensive_unit(self) -> None:
        p = true_snap_profile("1", "Defender", "NE", "S", [(1, 0, 0, 54, 60, 4)])
        usage = usage_summary(p, 3)

        self.assertEqual(usage["primary_unit"], "defense")
        self.assertEqual(usage["season_relevant_snap_pct"], 0.9)

    def test_true_snap_special_teams_does_not_inflate_defensive_relevance(self) -> None:
        p = true_snap_profile("1", "Coverage Only", "NE", "LB", [(1, 0, 0, 1, 60, 20), (2, 0, 0, 0, 55, 18)])
        usage = usage_summary(p, 3)

        self.assertTrue(usage["st_only"])
        self.assertLess(usage["season_relevant_snap_pct"], 0.25)

    def test_defensive_player_uses_defensive_snaps(self) -> None:
        p = profile("1", "Corner Back", "NE", "CB", [(1, None, 0.91)])
        usage = usage_summary(p, 3)

        self.assertEqual(usage["season_relevant_snap_pct"], 0.91)

    def test_special_teams_position_is_excluded_by_default(self) -> None:
        p = profile("1", "Long Snapper", "NE", "LS", [(1, None, None)])
        enriched = enrich_record(
            official("Long Snapper", source_position="LS"),
            MatchResult("EXACT", "test", p, []),
            {},
            RULES,
        )

        self.assertFalse(enriched["key_candidate"])
        self.assertIn("special_teams_only", enriched["candidate_reasons"])

    def test_qb_automatically_candidate(self) -> None:
        p = profile("1", "Quarter Back", "NE", "QB", [(1, None, None)])
        enriched = enrich_record(official("Quarter Back", source_position="QB"), MatchResult("EXACT", "test", p, []), {}, RULES)

        self.assertTrue(enriched["key_candidate"])
        self.assertIn("QB", enriched["candidate_reasons"])

    def test_significant_season_role_becomes_candidate(self) -> None:
        p = profile("1", "Role Player", "NE", "CB", [(1, None, 0.31)])
        enriched = enrich_record(official("Role Player"), MatchResult("EXACT", "test", p, []), {}, RULES)

        self.assertTrue(enriched["key_candidate"])
        self.assertTrue(any(reason.startswith("season_snap_pct=") for reason in enriched["candidate_reasons"]))

    def test_significant_recent_healthy_role_becomes_candidate(self) -> None:
        p = profile("1", "Healthy Role", "NE", "CB", [(1, None, 0.91), (2, None, 0.05)])
        enriched = enrich_record(official("Healthy Role"), MatchResult("EXACT", "test", p, []), {}, RULES)

        self.assertTrue(enriched["key_candidate"])
        self.assertIn("recent_healthy_snap_pct=91.0", enriched["candidate_reasons"])

    def test_injury_game_low_snap_does_not_erase_established_role(self) -> None:
        p = profile("1", "Injury Game", "NE", "CB", [(1, None, 0.95), (2, None, 0.08)])
        usage = usage_summary(p, 3)

        self.assertEqual(usage["previous_game_relevant_snap_pct"], 0.08)
        self.assertEqual(usage["recent_healthy_snap_pct"], 0.95)

    def test_true_snap_recent_healthy_max_over_last_three(self) -> None:
        p = true_snap_profile("1", "Recent Healthy", "NE", "CB", [(1, 0, 0, 50, 50, 0), (2, 0, 0, 4, 50, 2)])
        usage = usage_summary(p, 3)

        self.assertEqual(usage["previous_game_relevant_snap_pct"], 0.08)
        self.assertEqual(usage["recent_healthy_snap_pct"], 1.0)

    def test_low_use_backup_excluded(self) -> None:
        p = profile("1", "Backup", "NE", "CB", [(1, None, 0.04), (2, None, 0.08)])
        enriched = enrich_record(official("Backup", game_status="Questionable"), MatchResult("EXACT", "test", p, []), {}, RULES)

        self.assertFalse(enriched["key_candidate"])
        self.assertEqual(enriched["candidate_reasons"], ["low_role"])

    def test_matched_player_with_no_snap_data_is_not_candidate_by_default(self) -> None:
        p = PFFPlayerProfile(
            player_id="1",
            player_name="No Usage",
            normalized_player_name=normalize_player_name("No Usage"),
            teams={"NE"},
            positions=Counter({"CB": 1}),
        )
        enriched = enrich_record(official("No Usage", game_status="Questionable"), MatchResult("EXACT", "test", p, []), {}, RULES)

        self.assertFalse(enriched["key_candidate"])
        self.assertEqual(enriched["candidate_reasons"], ["low_role"])
        self.assertEqual(enriched["games_appeared"], 0)
        self.assertEqual(enriched["snap_data_status"], "NO_DATA")
        self.assertIsNone(enriched["season_relevant_snap_pct"])

    def test_manual_include_wins(self) -> None:
        p = profile("1", "Manual Include", "NE", "CB", [(1, None, 0.01)])
        enriched = enrich_record(official("Manual Include"), MatchResult("EXACT", "test", p, []), {"publish": "include"}, RULES)

        self.assertTrue(enriched["key_candidate"])
        self.assertEqual(enriched["candidate_reasons"], ["manual_include"])

    def test_manual_exclude_wins(self) -> None:
        p = profile("1", "Manual Exclude", "NE", "QB", [(1, None, None)])
        enriched = enrich_record(official("Manual Exclude", source_position="QB"), MatchResult("EXACT", "test", p, []), {"publish": "exclude"}, RULES)

        self.assertFalse(enriched["key_candidate"])
        self.assertEqual(enriched["candidate_reasons"], ["manual_exclude"])

    def test_old_new_candidate_comparison(self) -> None:
        old = [{"team": "NE", "normalized_player_name": "one player", "player_name": "One Player", "key_candidate": True, "match_status": "EXACT", "season_relevant_snap_pct": 0.9}]
        new = [{"team": "NE", "normalized_player_name": "one player", "player_name": "One Player", "key_candidate": False, "match_status": "EXACT", "season_relevant_snap_pct": 0.1}]
        comparison = compare_enrichment_outputs(old, new)

        self.assertEqual(comparison[0]["candidate_change"], "YES_TO_NO")

    def test_out_doubtful_only_candidate_classification(self) -> None:
        p = true_snap_profile("1", "Out Only", "NE", "CB", [(1, 0, 0, 2, 60, 0)])
        enriched = enrich_record(official("Out Only", game_status="Out"), MatchResult("EXACT", "test", p, []), {}, RULES)

        self.assertTrue(enriched["key_candidate"])
        self.assertTrue(enriched["out_doubtful_only_candidate"])


if __name__ == "__main__":
    unittest.main()
