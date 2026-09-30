from __future__ import annotations

import csv
import json
import sys
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from injury_tracker.scripts.review import (  # noqa: E402
    MANUAL_PLAYERS_COLUMNS,
    REVIEW_DECISION_COLUMNS,
    REVIEW_STATUS_COLUMNS,
    ReviewPaths,
    append_manual_player,
    build_unified_source_records,
    game_source_fingerprint,
    load_review_bundle,
    save_decision,
    save_ft_note,
    save_review_status,
)
from injury_tracker.scripts.schedule_context import ScheduleGameContext  # noqa: E402


def write_json(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


def write_header(path: Path, columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=columns).writeheader()


def injury_row(
    player: str,
    *,
    team: str = "NE",
    pff_id: str = "1",
    candidate: bool = True,
    position_group: str = "WR",
    reasons: list[str] | None = None,
) -> dict:
    return {
        "season": 2026,
        "week": 3,
        "team": team,
        "player_name": player,
        "normalized_player_name": player.lower().replace(" ", ""),
        "pff_player_id": pff_id,
        "pff_player_name": player,
        "pff_position": position_group,
        "canonical_position": position_group,
        "position_group": position_group,
        "source_position": position_group,
        "injury": "Knee",
        "practice_by_day": {"Friday": "LP"},
        "practice_observations": [{"day": "Friday", "participation": "LP"}],
        "game_status": "Questionable",
        "season_relevant_snap_pct": 0.67,
        "participation_source_season": 2026,
        "snap_data_status": "OFFENSE_DEFENSE",
        "key_candidate": candidate,
        "candidate_reasons": reasons or ["season_snap_pct=67.0"],
    }


def reserve_row(
    player: str,
    *,
    team: str = "NE",
    pff_id: str = "2",
    candidate: bool = True,
    position_group: str = "RB",
    fallback: bool = False,
) -> dict:
    return {
        "season": 2026,
        "week": 3,
        "team": team,
        "player_name": player,
        "normalized_player_name": player.lower().replace(" ", ""),
        "pff_player_id": pff_id,
        "pff_player_name": player,
        "pff_position": position_group,
        "canonical_position": position_group,
        "position_group": position_group,
        "source_position": position_group,
        "raw_roster_status": "Reserve/Injured",
        "canonical_roster_status": "IR",
        "designated_for_return": False,
        "reserve_transaction_date": "2026-09-01",
        "participation_source_season": 2025 if fallback else 2026,
        "season_relevant_snap_pct": None if fallback else 0.31,
        "prior_season_relevant_snap_pct": 0.42 if fallback else None,
        "snap_data_status": "NO_DATA" if fallback else "OFFENSE_DEFENSE",
        "prior_season_snap_data_status": "OFFENSE_DEFENSE" if fallback else None,
        "key_candidate": candidate,
        "candidate_reasons": ["prior_season_snap_pct=42.0"] if fallback else ["season_snap_pct=31.0"],
    }


class ReviewWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT / ".tmp_tests"
        tmp_root.mkdir(exist_ok=True)
        root = tmp_root / f"review_{uuid.uuid4().hex}"
        root.mkdir()
        self.tmp_root = root
        self.injury_path = root / "injury.json"
        self.reserve_path = root / "reserve.json"
        self.output_dir = root / "reviewed"
        self.decisions_path = root / "review_decisions.csv"
        self.status_path = root / "review_status.csv"
        self.manual_path = root / "manual_players.csv"
        write_header(self.decisions_path, REVIEW_DECISION_COLUMNS)
        write_header(self.status_path, REVIEW_STATUS_COLUMNS)
        write_header(self.manual_path, MANUAL_PLAYERS_COLUMNS)
        self.paths = ReviewPaths(
            injury_path=self.injury_path,
            reserve_path=self.reserve_path,
            output_dir=self.output_dir,
            review_decisions_path=self.decisions_path,
            review_status_path=self.status_path,
            manual_players_path=self.manual_path,
        )
        self.contexts = [
            ScheduleGameContext(
                season=2026,
                week=3,
                team="NE",
                opponent="NYJ",
                home_away="HOME",
                game_date="2026-09-27",
                kickoff="2026-09-27T17:00:00Z",
                schedule_source="fixture",
                home_team="NE",
                away_team="NYJ",
            ),
            ScheduleGameContext(
                season=2026,
                week=3,
                team="NYJ",
                opponent="NE",
                home_away="AWAY",
                game_date="2026-09-27",
                kickoff="2026-09-27T17:00:00Z",
                schedule_source="fixture",
                home_team="NE",
                away_team="NYJ",
            ),
        ]

    def tearDown(self) -> None:
        return

    def seed(self, injury_rows: list[dict] | None = None, reserve_rows: list[dict] | None = None) -> None:
        write_json(self.injury_path, injury_rows or [])
        write_json(self.reserve_path, reserve_rows or [])

    def bundle(self) -> dict:
        return load_review_bundle(2026, 3, self.paths, contexts=self.contexts)

    def test_injury_reserve_identity_dedupes_and_preserves_provenance(self) -> None:
        self.seed(
            [injury_row("Same Player", pff_id="10")],
            [reserve_row("Same Player", pff_id="10")],
        )

        bundle = self.bundle()

        self.assertEqual(len(bundle["records"]), 1)
        record = bundle["records"][0]
        self.assertTrue(record["source_memberships"]["injury_report"])
        self.assertTrue(record["source_memberships"]["reserve_roster"])
        self.assertEqual(bundle["summary"]["source_split"], {"both": 1})

    def test_position_grouping_and_matchup_organization(self) -> None:
        self.seed(
            [
                injury_row("Wide Receiver", team="NE", pff_id="11", position_group="WR"),
                injury_row("Quarterback", team="NYJ", pff_id="12", position_group="QB"),
            ],
            [],
        )

        grouped = self.bundle()["grouped"]

        self.assertEqual(len(grouped), 1)
        self.assertEqual([team["team"] for team in grouped[0]["teams"]], ["NYJ", "NE"])
        groups = {team["team"]: [group["position_group"] for group in team["groups"]] for team in grouped[0]["teams"]}
        self.assertEqual(groups["NYJ"], ["QB"])
        self.assertEqual(groups["NE"], ["WR"])

    def test_automated_yes_defaults_included_and_no_absent_from_primary(self) -> None:
        self.seed(
            [injury_row("Candidate Yes", pff_id="21", candidate=True)],
            [reserve_row("Candidate No", pff_id="22", candidate=False)],
        )

        bundle = self.bundle()

        self.assertEqual({row["player_name"] for row in bundle["primary_records"]}, {"Candidate Yes"})
        self.assertEqual({row["player_name"] for row in bundle["manual_add_options"]}, {"Candidate No"})

    def test_manual_exclude_overrides_yes_and_include_overrides_no(self) -> None:
        self.seed(
            [injury_row("Auto Yes", pff_id="31", candidate=True)],
            [reserve_row("Auto No", pff_id="32", candidate=False)],
        )
        save_decision(
            season=2026,
            week=3,
            team="NE",
            player_name="Auto Yes",
            normalized_player_name="autoyes",
            pff_player_id="31",
            decision="EXCLUDE",
            path=self.decisions_path,
        )
        save_decision(
            season=2026,
            week=3,
            team="NE",
            player_name="Auto No",
            normalized_player_name="autono",
            pff_player_id="32",
            decision="INCLUDE",
            path=self.decisions_path,
        )

        records = {row["player_name"]: row for row in self.bundle()["records"]}

        self.assertFalse(records["Auto Yes"]["final_include"])
        self.assertTrue(records["Auto No"]["final_include"])
        self.assertEqual(records["Auto Yes"]["review_state"], "MANUAL_EXCLUDE")
        self.assertEqual(records["Auto No"]["review_state"], "MANUAL_INCLUDE")

    def test_rebuild_persistence_game_status_new_candidate_and_disappeared_player(self) -> None:
        self.seed(
            [injury_row("Excluded Fixture", pff_id="41"), injury_row("Disappears", pff_id="42")],
            [reserve_row("Included Fixture", pff_id="43", candidate=False)],
        )
        save_decision(
            season=2026,
            week=3,
            team="NE",
            player_name="Excluded Fixture",
            normalized_player_name="excludedfixture",
            pff_player_id="41",
            decision="EXCLUDE",
            path=self.decisions_path,
        )
        save_decision(
            season=2026,
            week=3,
            team="NE",
            player_name="Included Fixture",
            normalized_player_name="includedfixture",
            pff_player_id="43",
            decision="INCLUDE",
            path=self.decisions_path,
        )
        save_review_status(
            season=2026,
            week=3,
            scope="GAME",
            game_id="2026-W03-NE-NYJ",
            reviewed=True,
            path=self.status_path,
        )

        self.seed(
            [injury_row("Excluded Fixture", pff_id="41"), injury_row("New Candidate", pff_id="44")],
            [reserve_row("Included Fixture", pff_id="43", candidate=False)],
        )

        bundle = self.bundle()
        records = {row["player_name"]: row for row in bundle["records"]}

        self.assertFalse(records["Excluded Fixture"]["final_include"])
        self.assertTrue(records["Included Fixture"]["final_include"])
        self.assertTrue(bundle["grouped"][0]["reviewed"])
        self.assertTrue(records["New Candidate"]["final_include"])
        self.assertFalse(records["New Candidate"]["explicitly_reviewed"])
        self.assertNotIn("Disappears", records)
        with self.decisions_path.open(newline="", encoding="utf-8") as handle:
            self.assertEqual(sum(1 for _ in csv.DictReader(handle)), 2)

    def test_manual_player_survives_rebuild_and_is_included(self) -> None:
        self.seed([], [])
        append_manual_player(
            season=2026,
            week=3,
            team="NE",
            player_name="Manual Missing",
            source_position="CB",
            injury="Hamstring",
            note="watch",
            path=self.manual_path,
        )
        save_decision(
            season=2026,
            week=3,
            team="NE",
            player_name="Manual Missing",
            normalized_player_name="manual missing",
            pff_player_id=None,
            decision="INCLUDE",
            path=self.decisions_path,
        )

        self.seed([injury_row("Other Player", pff_id="51")], [])
        records = {row["player_name"]: row for row in self.bundle()["records"]}

        self.assertTrue(records["Manual Missing"]["source_memberships"]["manual_player"])
        self.assertTrue(records["Manual Missing"]["final_include"])

    def test_2025_fallback_displayed_and_reviewed_output_generated(self) -> None:
        self.seed([], [reserve_row("Fallback Player", pff_id="61", fallback=True)])

        bundle = self.bundle()
        record = bundle["primary_records"][0]
        reviewed_path = self.output_dir / "reviewed_players.json"
        reviewed_rows = json.loads(reviewed_path.read_text(encoding="utf-8"))

        self.assertTrue(record["prior_season_fallback_used"])
        self.assertEqual(record["participation_source_season"], 2025)
        self.assertEqual(len(reviewed_rows), 1)
        self.assertTrue(reviewed_rows[0]["prior_season_fallback_used"])
        self.assertEqual(reviewed_rows[0]["source_memberships"], "reserve_roster")

    def test_ft_note_persists_survives_rebuild_and_reaches_output(self) -> None:
        self.seed([injury_row("Note Player", pff_id="81")], [])
        save_ft_note(
            season=2026,
            week=3,
            team="NE",
            player_name="Note Player",
            normalized_player_name="noteplayer",
            pff_player_id="81",
            ft_note="Expected to play.",
            path=self.decisions_path,
        )

        first = self.bundle()
        self.seed([injury_row("Note Player", pff_id="81", reasons=["previous_game_snap_pct=80.0"])], [])
        second = self.bundle()
        record = second["records"][0]
        reviewed_rows = json.loads((self.output_dir / "reviewed_players.json").read_text(encoding="utf-8"))

        self.assertEqual(first["records"][0]["ft_note"], "Expected to play.")
        self.assertEqual(record["ft_note"], "Expected to play.")
        self.assertTrue(record["final_include"])
        self.assertFalse(record["explicitly_reviewed"])
        self.assertEqual(reviewed_rows[0]["ft_note"], "Expected to play.")
        self.assertEqual(reviewed_rows[0]["ft_note_source"], "manual_review")

    def test_ft_note_does_not_change_existing_include_exclude_decision(self) -> None:
        self.seed([injury_row("Excluded Note", pff_id="82")], [])
        save_decision(
            season=2026,
            week=3,
            team="NE",
            player_name="Excluded Note",
            normalized_player_name="excludednote",
            pff_player_id="82",
            decision="EXCLUDE",
            path=self.decisions_path,
        )
        save_ft_note(
            season=2026,
            week=3,
            team="NE",
            player_name="Excluded Note",
            normalized_player_name="excludednote",
            pff_player_id="82",
            ft_note="Monitor pregame warmups.",
            path=self.decisions_path,
        )

        record = self.bundle()["records"][0]

        self.assertEqual(record["manual_decision"], "EXCLUDE")
        self.assertFalse(record["final_include"])
        self.assertEqual(record["ft_note"], "Monitor pregame warmups.")

    def test_ft_note_and_decision_are_week_scoped(self) -> None:
        self.seed([injury_row("Scoped Player", pff_id="83")], [])
        save_decision(
            season=2026,
            week=4,
            team="NE",
            player_name="Scoped Player",
            normalized_player_name="scopedplayer",
            pff_player_id="83",
            decision="EXCLUDE",
            path=self.decisions_path,
        )
        save_ft_note(
            season=2026,
            week=4,
            team="NE",
            player_name="Scoped Player",
            normalized_player_name="scopedplayer",
            pff_player_id="83",
            ft_note="Week 4 only.",
            path=self.decisions_path,
        )

        record = self.bundle()["records"][0]

        self.assertIsNone(record["manual_decision"])
        self.assertIsNone(record["ft_note"])
        self.assertTrue(record["final_include"])

    def test_mark_game_reviewed_fingerprint_stays_current_on_identical_rebuild(self) -> None:
        self.seed([injury_row("Stable Player", pff_id="801")], [])
        records = self.bundle()["records"]
        save_review_status(
            season=2026,
            week=3,
            scope="GAME",
            game_id="2026-W03-NE-NYJ",
            source_fingerprint=game_source_fingerprint(records, "2026-W03-NE-NYJ"),
            path=self.status_path,
        )

        summary = self.bundle()["summary"]

        self.assertEqual(summary["games_reviewed"], 1)
        self.assertEqual(summary["games_stale"], 0)

    def test_source_changes_make_review_stale_and_rereview_restores_current(self) -> None:
        self.seed([injury_row("Changing Player", pff_id="811")], [])
        original = self.bundle()["records"]
        save_review_status(
            season=2026,
            week=3,
            scope="GAME",
            game_id="2026-W03-NE-NYJ",
            source_fingerprint=game_source_fingerprint(original, "2026-W03-NE-NYJ"),
            path=self.status_path,
        )
        changed = injury_row("Changing Player", pff_id="811")
        changed["injury"] = "Shoulder"
        changed["practice_by_day"] = {"Friday": "DNP"}
        changed["practice_observations"] = [{"day": "Friday", "participation": "DNP"}]
        changed["game_status"] = "Out"
        self.seed([changed], [])

        stale_bundle = self.bundle()

        self.assertEqual(stale_bundle["summary"]["games_reviewed"], 0)
        self.assertEqual(stale_bundle["summary"]["games_stale"], 1)
        save_review_status(
            season=2026,
            week=3,
            scope="GAME",
            game_id="2026-W03-NE-NYJ",
            source_fingerprint=game_source_fingerprint(stale_bundle["records"], "2026-W03-NE-NYJ"),
            path=self.status_path,
        )
        self.assertEqual(self.bundle()["summary"]["games_stale"], 0)

    def test_new_candidate_and_reserve_state_change_make_review_stale(self) -> None:
        self.seed([injury_row("Reviewed Player", pff_id="821")], [reserve_row("Reserve Player", pff_id="822")])
        original = self.bundle()["records"]
        save_review_status(
            season=2026,
            week=3,
            scope="GAME",
            game_id="2026-W03-NE-NYJ",
            source_fingerprint=game_source_fingerprint(original, "2026-W03-NE-NYJ"),
            path=self.status_path,
        )
        changed_reserve = reserve_row("Reserve Player", pff_id="822")
        changed_reserve["raw_roster_status"] = "Reserve/Injured; Designated for Return"
        changed_reserve["designated_for_return"] = True
        self.seed(
            [injury_row("Reviewed Player", pff_id="821"), injury_row("New Candidate", pff_id="823")],
            [changed_reserve],
        )

        self.assertEqual(self.bundle()["summary"]["games_stale"], 1)

    def test_unrelated_game_change_does_not_stale_reviewed_game(self) -> None:
        self.seed([injury_row("Reviewed Player", pff_id="841")], [])
        original = self.bundle()["records"]
        save_review_status(
            season=2026,
            week=3,
            scope="GAME",
            game_id="2026-W03-NE-NYJ",
            source_fingerprint=game_source_fingerprint(original, "2026-W03-NE-NYJ"),
            path=self.status_path,
        )
        unrelated = injury_row("Other Game Player", team="ATL", pff_id="842")
        unrelated["injury"] = "Ankle"
        self.seed([injury_row("Reviewed Player", pff_id="841"), unrelated], [])

        self.assertEqual(self.bundle()["summary"]["games_stale"], 0)

    def test_ft_note_change_does_not_stale_review(self) -> None:
        self.seed([injury_row("Noted Player", pff_id="831")], [])
        records = self.bundle()["records"]
        save_review_status(
            season=2026,
            week=3,
            scope="GAME",
            game_id="2026-W03-NE-NYJ",
            source_fingerprint=game_source_fingerprint(records, "2026-W03-NE-NYJ"),
            path=self.status_path,
        )
        save_ft_note(
            season=2026,
            week=3,
            team="NE",
            player_name="Noted Player",
            normalized_player_name="notedplayer",
            pff_player_id="831",
            ft_note="Editorial note only.",
            path=self.decisions_path,
        )

        summary = self.bundle()["summary"]

        self.assertEqual(summary["games_reviewed"], 1)
        self.assertEqual(summary["games_stale"], 0)

    def test_source_data_not_mutated(self) -> None:
        injury = [injury_row("Immutable", pff_id="71")]
        reserve = [reserve_row("Immutable Reserve", pff_id="72")]
        self.seed(injury, reserve)
        before_injury = self.injury_path.read_text(encoding="utf-8")
        before_reserve = self.reserve_path.read_text(encoding="utf-8")

        self.bundle()

        self.assertEqual(self.injury_path.read_text(encoding="utf-8"), before_injury)
        self.assertEqual(self.reserve_path.read_text(encoding="utf-8"), before_reserve)


if __name__ == "__main__":
    unittest.main()
