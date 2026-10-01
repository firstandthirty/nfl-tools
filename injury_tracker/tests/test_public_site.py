from __future__ import annotations

import csv
import json
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from injury_tracker.scripts.build_public_site import (  # noqa: E402
    build_public_site,
    build_public_view_model,
    render_html,
)
from injury_tracker.scripts.publish_public_site import copy_public_outputs  # noqa: E402
from injury_tracker.scripts.review import REVIEW_STATUS_COLUMNS, game_source_fingerprint, save_review_status  # noqa: E402
from injury_tracker.scripts.review import (  # noqa: E402
    MANUAL_PLAYERS_COLUMNS,
    REVIEW_DECISION_COLUMNS,
    ReviewPaths,
    load_review_bundle,
    save_decision,
    save_ft_note,
    save_injury_override,
)
from injury_tracker.scripts.review_app import HTML as REVIEW_HTML, team_info  # noqa: E402
from injury_tracker.scripts.schedule_context import ScheduleGameContext  # noqa: E402


def write_json(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


def write_header(path: Path, columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=columns).writeheader()


def reviewed_player(
    name: str,
    *,
    team: str = "PIT",
    opponent: str = "CLE",
    game_id: str = "2026-W04-CLE-PIT",
    position: str = "CB",
    group: str = "CB",
    injury: str | None = "Hamstring",
    display_injury: str | None = None,
    practice: str | None = "LP",
    designation: str | None = "Questionable",
    reserve_status: str | None = None,
    raw_roster_status: str | None = None,
    dfr: bool = False,
    transaction_date: str | None = None,
    ft_note: str | None = None,
    source: str = "injury_report",
) -> dict:
    return {
        "season": 2026,
        "week": 4,
        "game_id": game_id,
        "game_date": "2026-10-02",
        "kickoff": "2026-10-02T00:15:00Z",
        "team": team,
        "opponent": opponent,
        "home_away": "AWAY" if team == "PIT" else "HOME",
        "player_name": name,
        "normalized_player_name": name.lower().replace(" ", ""),
        "pff_player_id": "secret-id",
        "pff_player_name": name,
        "canonical_position": position,
        "display_position": position,
        "position_group": group,
        "pff_position": position,
        "injury": injury,
        "manual_injury_override": display_injury if display_injury and display_injury != injury else None,
        "display_injury": injury if display_injury is None else display_injury,
        "latest_practice": practice,
        "game_status": designation,
        "reserve_status": reserve_status,
        "raw_roster_status": raw_roster_status,
        "designated_for_return": dfr,
        "reserve_transaction_date": transaction_date,
        "participation_source_season": 2026,
        "prior_season_fallback_used": False,
        "relevant_snap_pct": 0.99,
        "snap_data_status": "OFFENSE_DEFENSE",
        "source_memberships": source,
        "automated_candidate": True,
        "candidate_reasons": "season_snap_pct=99.0",
        "manual_decision": None,
        "manual_note": None,
        "ft_note": ft_note,
        "ft_note_source": "manual_review" if ft_note else None,
        "review_state": "UNREVIEWED_DEFAULT",
        "explicitly_reviewed": False,
        "final_include": True,
    }


def source_injury_row(player: str, *, injury: str | None = "Knee", pff_id: str = "source-1") -> dict:
    return {
        "season": 2026,
        "week": 4,
        "team": "PIT",
        "player_name": player,
        "normalized_player_name": player.lower().replace(" ", ""),
        "pff_player_id": pff_id,
        "pff_player_name": player,
        "pff_position": "CB",
        "canonical_position": "CB",
        "position_group": "CB",
        "source_position": "CB",
        "injury": injury,
        "practice_by_day": {"Wednesday": "LP"},
        "practice_observations": [{"day": "Wednesday", "participation": "LP"}],
        "game_status": "Questionable",
        "season_relevant_snap_pct": 0.81,
        "participation_source_season": 2026,
        "snap_data_status": "OFFENSE_DEFENSE",
        "key_candidate": True,
        "candidate_reasons": ["season_snap_pct=81.0"],
    }


def source_reserve_row(player: str, *, pff_id: str = "source-2") -> dict:
    return {
        "season": 2026,
        "week": 4,
        "team": "CLE",
        "player_name": player,
        "normalized_player_name": player.lower().replace(" ", ""),
        "pff_player_id": pff_id,
        "pff_player_name": player,
        "pff_position": "EDGE",
        "canonical_position": "EDGE",
        "position_group": "EDGE",
        "source_position": "EDGE",
        "raw_roster_status": "Reserve/Injured",
        "canonical_roster_status": "IR",
        "designated_for_return": True,
        "reserve_transaction_date": "2026-09-01",
        "reserve_transaction_type": "PLACED_ON_IR",
        "participation_source_season": 2025,
        "prior_season_relevant_snap_pct": 0.61,
        "snap_data_status": "NO_DATA",
        "prior_season_snap_data_status": "OFFENSE_DEFENSE",
        "key_candidate": True,
        "candidate_reasons": ["prior_season_snap_pct=61.0"],
    }


class PublicSiteTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT / ".tmp_tests"
        tmp_root.mkdir(exist_ok=True)
        self.root = tmp_root / f"public_{uuid.uuid4().hex}"
        self.root.mkdir()
        self.reviewed_path = self.root / "reviewed_players.json"
        self.status_path = self.root / "review_status.csv"
        self.manifest_path = self.root / "manifest.json"
        self.output_root = self.root / "docs" / "injuries"
        write_header(self.status_path, REVIEW_STATUS_COLUMNS)
        self.contexts = [
            ScheduleGameContext(2026, 4, "CLE", "PIT", "HOME", "2026-10-02", "2026-10-02T00:15:00Z", "fixture", "CLE", "PIT"),
            ScheduleGameContext(2026, 4, "PIT", "CLE", "AWAY", "2026-10-02", "2026-10-02T00:15:00Z", "fixture", "CLE", "PIT"),
            ScheduleGameContext(2026, 4, "NYG", "ARI", "HOME", "2026-10-04", "2026-10-04T17:00:00Z", "fixture", "NYG", "ARI"),
            ScheduleGameContext(2026, 4, "ARI", "NYG", "AWAY", "2026-10-04", "2026-10-04T17:00:00Z", "fixture", "NYG", "ARI"),
        ]
        write_json(
            self.manifest_path,
            [
                {"team": "PIT", "current_week_status": "SUCCESS_CURRENT"},
                {"team": "CLE", "current_week_status": "SUCCESS_CURRENT"},
                {"team": "ARI", "current_week_status": "NO_REPORT_YET"},
                {"team": "NYG", "current_week_status": "NO_REPORT_YET"},
            ],
        )

    def mark_pit_cle_reviewed(self) -> None:
        rows = json.loads(self.reviewed_path.read_text(encoding="utf-8")) if self.reviewed_path.exists() else []
        save_review_status(
            season=2026,
            week=4,
            scope="GAME",
            game_id="2026-W04-CLE-PIT",
            source_fingerprint=game_source_fingerprint(rows, "2026-W04-CLE-PIT"),
            path=self.status_path,
        )

    def build_model(self, rows: list[dict]) -> dict:
        write_json(self.reviewed_path, rows)
        self.mark_pit_cle_reviewed()
        summary = build_public_site(
            2026,
            4,
            reviewed_path=self.reviewed_path,
            review_status_path=self.status_path,
            output_root=self.output_root,
            contexts=self.contexts,
            manifest_path=self.manifest_path,
            generated_at=datetime(2026, 9, 30, 14, 30, tzinfo=timezone.utc),
            print_summary=False,
        )
        return json.loads(Path(summary["archive_view_model"]).read_text(encoding="utf-8"))

    def test_reviewed_game_renders_and_unreviewed_game_hides_players(self) -> None:
        rows = [
            reviewed_player("Joey Porter Jr.", ft_note="Likely <return>."),
            reviewed_player("Hidden Giant", team="NYG", opponent="ARI", game_id="2026-W04-ARI-NYG"),
        ]

        model = self.build_model(rows)
        html = (self.output_root / "2026" / "week_04" / "index.html").read_text(encoding="utf-8")

        self.assertIn("Joey Porter Jr.", html)
        self.assertNotIn("Hidden Giant", html)
        self.assertIn("Pending First &amp; Thirty review.", html)
        self.assertIn('name="viewport"', html)
        self.assertEqual(model["games"][0]["matchup"], "PIT at CLE")

    def test_public_title_subtitle_and_no_reviewed_badge(self) -> None:
        model = self.build_model([reviewed_player("Joey Porter Jr.")])
        html = render_html(model)

        self.assertIn("NFL Week 4 Injury Tracker", html)
        self.assertIn("Key injuries, practice participation, reserve status, and First &amp; Thirty notes for every Week 4 matchup.", html)
        self.assertNotIn(">Reviewed<", html)
        self.assertIn(">Pending<", html)

    def test_current_injuries_render_before_reserve_and_dfr_is_visible(self) -> None:
        rows = [
            reviewed_player("DeShon Elliott", reserve_status="IR", raw_roster_status="Reserve/Injured", transaction_date="2026-09-01", injury=None, practice=None, designation=None),
            reviewed_player("Jalen Ramsey", position="S", group="S", injury="Wrist", practice="LP", designation="(-)"),
            reviewed_player("Designated Player", reserve_status="IR", raw_roster_status="Reserve/Injured; Designated for Return", dfr=True, injury=None, practice=None, designation=None),
        ]

        html = render_html(self.build_model(rows))

        self.assertLess(html.index("Current injuries"), html.index("Reserve / IR"))
        self.assertIn("DeShon Elliott", html)
        self.assertIn("Designated for return", html)
        self.assertNotIn("(-)", html)
        self.assertIn("Practice: LP", html)

    def test_ft_notes_are_escaped_and_blank_notes_are_omitted(self) -> None:
        rows = [
            reviewed_player("Note Player", ft_note="Return <script>alert(1)</script> soon."),
            reviewed_player("Blank Note", ft_note=""),
        ]

        html = render_html(self.build_model(rows))

        self.assertIn("F&amp;T Note:", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertEqual(html.count("F&amp;T Note:"), 1)

    def test_report_unavailable_and_no_injury_messages_are_distinct(self) -> None:
        model = self.build_model([reviewed_player("One Current")])
        html = render_html(model)

        self.assertIn("No tracked current injuries.", html)
        self.assertIn("Official injury report not yet available. Player list pending review.", html)

    def test_public_view_model_excludes_internal_review_and_pff_fields(self) -> None:
        model = self.build_model([reviewed_player("Public Player")])
        serialized = json.dumps(model)

        self.assertNotIn("pff_player_id", serialized)
        self.assertNotIn("candidate_reasons", serialized)
        self.assertNotIn("relevant_snap_pct", serialized)
        self.assertNotIn("review_state", serialized)
        player = model["games"][0]["teams"][0]["current_injuries"][0]
        self.assertEqual(set(player).difference({"player_name", "team", "opponent", "position", "position_group", "section", "injury", "practice", "designation", "reserve_status", "reserve_transaction_date", "designated_for_return", "source", "ft_note"}), set())

    def test_public_site_uses_effective_injury_without_override_provenance(self) -> None:
        model = self.build_model([reviewed_player("Override Player", injury="Ankle", display_injury="Knee")])
        html = render_html(model)
        serialized = json.dumps(model)
        player = model["games"][0]["teams"][0]["current_injuries"][0]

        self.assertEqual(player["injury"], "Knee")
        self.assertIn("Knee", html)
        self.assertNotIn("Ankle", html)
        self.assertNotIn("manual_injury_override", serialized)
        self.assertNotIn("display_injury", serialized)

    def test_nav_and_current_archive_outputs_are_generated_without_mutating_manual_file(self) -> None:
        rows = [reviewed_player("Nav Player")]
        write_json(self.reviewed_path, rows)
        self.mark_pit_cle_reviewed()
        before = self.status_path.read_text(encoding="utf-8")

        summary = build_public_site(
            2026,
            4,
            reviewed_path=self.reviewed_path,
            review_status_path=self.status_path,
            output_root=self.output_root,
            contexts=self.contexts,
            manifest_path=self.manifest_path,
            generated_at=datetime(2026, 9, 30, 14, 30, tzinfo=timezone.utc),
            print_summary=False,
        )

        self.assertTrue(Path(summary["archive_html"]).exists())
        self.assertTrue(Path(summary["current_html"]).exists())
        self.assertTrue((self.output_root / "public_view_model.json").exists())
        self.assertIn("#2026-w04-cle-pit", Path(summary["current_html"]).read_text(encoding="utf-8"))
        self.assertEqual(before, self.status_path.read_text(encoding="utf-8"))

    def test_public_team_link_uses_configured_official_url_safely(self) -> None:
        model = self.build_model([reviewed_player("Linked Player")])
        html = render_html(model)

        self.assertIn('href="https://www.steelers.com/team/injury-report/"', html)
        self.assertIn('target="_blank" rel="noopener noreferrer"', html)

    def test_public_missing_url_falls_back_to_text(self) -> None:
        model = self.build_model([reviewed_player("Linked Player")])
        model["games"][0]["teams"][0]["injury_report_url"] = "javascript:bad()"
        html = render_html(model)

        self.assertNotIn("javascript:bad()", html)
        self.assertIn("<h3>PIT", html)

    def test_stale_review_hides_changed_players_publicly(self) -> None:
        original = [reviewed_player("Original Player")]
        write_json(self.reviewed_path, original)
        save_review_status(
            season=2026,
            week=4,
            scope="GAME",
            game_id="2026-W04-CLE-PIT",
            source_fingerprint=game_source_fingerprint(original, "2026-W04-CLE-PIT"),
            path=self.status_path,
        )
        changed = [reviewed_player("Original Player", injury="Shoulder"), reviewed_player("New Candidate")]
        write_json(self.reviewed_path, changed)

        summary = build_public_site(
            2026,
            4,
            reviewed_path=self.reviewed_path,
            review_population_path=self.reviewed_path,
            review_status_path=self.status_path,
            output_root=self.output_root,
            contexts=self.contexts,
            manifest_path=self.manifest_path,
            generated_at=datetime(2026, 9, 30, 14, 30, tzinfo=timezone.utc),
            print_summary=False,
        )
        html = Path(summary["archive_html"]).read_text(encoding="utf-8")

        self.assertIn("Updated injury information is pending First &amp; Thirty review.", html)
        self.assertNotIn("New Candidate", html)

    def test_public_builder_uses_canonical_review_population_fingerprint(self) -> None:
        root = self.root / "canonical"
        root.mkdir()
        injury_path = root / "injury.json"
        reserve_path = root / "reserve.json"
        decisions_path = root / "review_decisions.csv"
        status_path = root / "review_status.csv"
        manual_path = root / "manual_players.csv"
        output_dir = root / "reviewed"
        write_json(injury_path, [source_injury_row("Canonical Injury")])
        write_json(reserve_path, [source_reserve_row("Canonical Reserve")])
        write_header(decisions_path, REVIEW_DECISION_COLUMNS)
        write_header(status_path, REVIEW_STATUS_COLUMNS)
        write_header(manual_path, MANUAL_PLAYERS_COLUMNS)
        paths = ReviewPaths(
            injury_path=injury_path,
            reserve_path=reserve_path,
            output_dir=output_dir,
            review_decisions_path=decisions_path,
            review_status_path=status_path,
            manual_players_path=manual_path,
        )
        bundle = load_review_bundle(2026, 4, paths, contexts=self.contexts)
        save_review_status(
            season=2026,
            week=4,
            scope="GAME",
            game_id="2026-W04-CLE-PIT",
            source_fingerprint=game_source_fingerprint(bundle["records"], "2026-W04-CLE-PIT"),
            path=status_path,
        )

        model = self.public_model_from_paths(paths, status_path)

        pit_cle = next(game for game in model["games"] if game["game_id"] == "2026-W04-CLE-PIT")
        self.assertTrue(pit_cle["reviewed"])
        self.assertFalse(pit_cle["stale_review"])
        self.assertEqual(sum(len(team["current_injuries"]) + len(team["reserve_players"]) for team in pit_cle["teams"]), 2)

    def test_public_builder_stale_state_tracks_source_not_editorial_changes(self) -> None:
        root = self.root / "editorial"
        root.mkdir()
        injury_path = root / "injury.json"
        reserve_path = root / "reserve.json"
        decisions_path = root / "review_decisions.csv"
        status_path = root / "review_status.csv"
        manual_path = root / "manual_players.csv"
        output_dir = root / "reviewed"
        write_json(injury_path, [source_injury_row("Editorial Injury", pff_id="source-3")])
        write_json(reserve_path, [])
        write_header(decisions_path, REVIEW_DECISION_COLUMNS)
        write_header(status_path, REVIEW_STATUS_COLUMNS)
        write_header(manual_path, MANUAL_PLAYERS_COLUMNS)
        paths = ReviewPaths(
            injury_path=injury_path,
            reserve_path=reserve_path,
            output_dir=output_dir,
            review_decisions_path=decisions_path,
            review_status_path=status_path,
            manual_players_path=manual_path,
        )
        original = load_review_bundle(2026, 4, paths, contexts=self.contexts)
        save_review_status(
            season=2026,
            week=4,
            scope="GAME",
            game_id="2026-W04-CLE-PIT",
            source_fingerprint=game_source_fingerprint(original["records"], "2026-W04-CLE-PIT"),
            path=status_path,
        )
        save_ft_note(
            season=2026,
            week=4,
            team="PIT",
            player_name="Editorial Injury",
            normalized_player_name="editorialinjury",
            pff_player_id="source-3",
            ft_note="Editorial only.",
            path=decisions_path,
        )
        save_injury_override(
            season=2026,
            week=4,
            team="PIT",
            player_name="Editorial Injury",
            normalized_player_name="editorialinjury",
            pff_player_id="source-3",
            display_injury="Manual Knee",
            path=decisions_path,
        )
        save_decision(
            season=2026,
            week=4,
            team="PIT",
            player_name="Editorial Injury",
            normalized_player_name="editorialinjury",
            pff_player_id="source-3",
            decision="EXCLUDE",
            path=decisions_path,
        )
        save_decision(
            season=2026,
            week=4,
            team="PIT",
            player_name="Editorial Injury",
            normalized_player_name="editorialinjury",
            pff_player_id="source-3",
            decision="INCLUDE",
            path=decisions_path,
        )
        load_review_bundle(2026, 4, paths, contexts=self.contexts)
        editorial_model = self.public_model_from_paths(paths, status_path)
        editorial_game = next(game for game in editorial_model["games"] if game["game_id"] == "2026-W04-CLE-PIT")

        self.assertTrue(editorial_game["reviewed"])
        self.assertFalse(editorial_game["stale_review"])

        changed = source_injury_row("Editorial Injury", pff_id="source-3")
        changed["injury"] = "Shoulder"
        write_json(injury_path, [changed])
        load_review_bundle(2026, 4, paths, contexts=self.contexts)
        stale_model = self.public_model_from_paths(paths, status_path)
        stale_game = next(game for game in stale_model["games"] if game["game_id"] == "2026-W04-CLE-PIT")

        self.assertFalse(stale_game["reviewed"])
        self.assertTrue(stale_game["stale_review"])

    def test_internal_review_app_team_link_data_and_safe_attributes_exist(self) -> None:
        info = team_info()

        self.assertEqual(info["PIT"]["injury_report_url"], "https://www.steelers.com/team/injury-report/")
        self.assertIn('target="_blank" rel="noopener noreferrer"', REVIEW_HTML)
        self.assertIn("teamLink(team.team)", REVIEW_HTML)

    def public_model_from_paths(self, paths: ReviewPaths, status_path: Path) -> dict:
        summary = build_public_site(
            2026,
            4,
            reviewed_path=paths.output_dir / "reviewed_players.json",
            review_population_path=paths.output_dir / "review_population.json",
            review_status_path=status_path,
            output_root=paths.output_dir / "docs",
            contexts=self.contexts,
            manifest_path=self.manifest_path,
            generated_at=datetime(2026, 9, 30, 14, 30, tzinfo=timezone.utc),
            print_summary=False,
        )
        return json.loads(Path(summary["archive_view_model"]).read_text(encoding="utf-8"))

    def test_publish_copy_updates_current_archive_preserves_unrelated_and_skips_json(self) -> None:
        local_root = self.root / "local_public"
        (local_root / "2026" / "week_04").mkdir(parents=True)
        (local_root / "index.html").write_text("current", encoding="utf-8")
        (local_root / "public_view_model.json").write_text("{}", encoding="utf-8")
        (local_root / "2026" / "week_04" / "index.html").write_text("archive", encoding="utf-8")
        (local_root / "2026" / "week_04" / "public_view_model.json").write_text("{}", encoding="utf-8")
        pages_root = self.root / "pages" / "injuries"
        pages_root.mkdir(parents=True)
        unrelated = pages_root / "keep.txt"
        unrelated.write_text("do not touch", encoding="utf-8")

        changed = copy_public_outputs(local_root, pages_root, 2026, 4)

        self.assertIn(str((pages_root / "index.html").relative_to(ROOT.parent)), changed)
        self.assertEqual((pages_root / "index.html").read_text(encoding="utf-8"), "current")
        self.assertEqual((pages_root / "2026" / "week_04" / "index.html").read_text(encoding="utf-8"), "archive")
        self.assertFalse((pages_root / "public_view_model.json").exists())
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "do not touch")


if __name__ == "__main__":
    unittest.main()
