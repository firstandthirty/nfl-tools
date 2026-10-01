from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .injury_schema import (
    MANUAL_DIR,
    MANUAL_PLAYERS_COLUMNS,
    PROJECT_ROOT,
    load_manual_players,
    normalize_player_name,
    resolve_position,
)
from .schedule_context import ScheduleGameContext, load_schedule_context, schedule_for_team


POSITION_GROUP_ORDER = ["QB", "RB", "WR", "TE", "OL", "EDGE", "DL", "LB", "CB", "S", "ST"]
POSITION_GROUP_RANK = {group: index for index, group in enumerate(POSITION_GROUP_ORDER)}

REVIEW_DECISION_COLUMNS = [
    "season",
    "week",
    "team",
    "player_name",
    "normalized_player_name",
    "pff_player_id",
    "decision",
    "ft_note",
    "note",
    "display_position",
    "display_injury",
    "reviewed_at",
]

REVIEW_STATUS_COLUMNS = [
    "season",
    "week",
    "scope",
    "game_id",
    "team",
    "opponent",
    "reviewed",
    "note",
    "source_fingerprint",
    "reviewed_at",
]

FINGERPRINT_VERSION = "review-source-v1"
FINGERPRINT_FIELDS = [
    "record_id",
    "team",
    "opponent",
    "player_name",
    "normalized_player_name",
    "pff_player_id",
    "canonical_position",
    "position_group",
    "source_labels",
    "injury",
    "practice_by_day",
    "latest_practice",
    "game_status",
    "raw_roster_status",
    "canonical_roster_status",
    "designated_for_return",
    "reserve_transaction_date",
    "reserve_transaction_type",
    "automated_candidate",
    "candidate_reasons",
    "participation_source_season",
    "snap_data_status",
    "relevant_snap_pct",
]


@dataclass(frozen=True)
class ReviewPaths:
    injury_path: Path
    reserve_path: Path
    output_dir: Path
    review_decisions_path: Path = MANUAL_DIR / "review_decisions.csv"
    review_status_path: Path = MANUAL_DIR / "review_status.csv"
    manual_players_path: Path = MANUAL_DIR / "manual_players.csv"


def default_review_paths(season: int, week: int) -> ReviewPaths:
    return ReviewPaths(
        injury_path=latest_processed_file(season, week, "pff_enriched_injuries.json"),
        reserve_path=latest_processed_file(season, week, "reserve_players_with_transaction_history.json"),
        output_dir=PROJECT_ROOT / "data" / "reviewed" / str(season) / f"week_{week:02d}",
    )


def latest_processed_file(season: int, week: int, filename: str) -> Path:
    week_dir = PROJECT_ROOT / "data" / "processed" / str(season) / f"week_{week:02d}"
    candidates = sorted(path / filename for path in week_dir.iterdir() if (path / filename).exists())
    if not candidates:
        raise FileNotFoundError(f"No {filename} found under {week_dir}")
    return candidates[-1]


def load_review_bundle(
    season: int,
    week: int,
    paths: ReviewPaths | None = None,
    *,
    contexts: list[ScheduleGameContext] | None = None,
) -> dict[str, Any]:
    paths = paths or default_review_paths(season, week)
    ensure_manual_review_files(paths)
    contexts = contexts if contexts is not None else load_schedule_context()
    source_records = build_unified_source_records(season, week, paths=paths, contexts=contexts)
    decisions = load_review_decisions(paths.review_decisions_path)
    statuses = load_review_status(paths.review_status_path)
    records = apply_review_decisions(source_records, decisions)
    stale_info = build_stale_review_info(records, statuses, paths=paths)
    orphaned_decisions = find_orphaned_decisions(records, decisions)
    primary_records = [record for record in records if record["final_include"]]
    manual_add_options = sorted(
        [manual_add_option_record(record) for record in records if manual_add_option(record)],
        key=record_sort_key,
    )
    grouped = group_for_review(primary_records, statuses, stale_info=stale_info)
    manual_excluded_grouped = group_for_review(
        [record for record in records if record.get("manual_decision") == "EXCLUDE"],
        statuses,
        stale_info=stale_info,
    )
    reviewed = generate_reviewed_outputs(records, paths=paths)
    summary = build_review_summary(records, statuses, reviewed, paths=paths, stale_info=stale_info)
    return {
        "season": season,
        "week": week,
        "paths": paths,
        "records": records,
        "primary_records": primary_records,
        "manual_add_options": manual_add_options,
        "grouped": grouped,
        "manual_excluded_grouped": manual_excluded_grouped,
        "summary": summary,
        "stale_info": stale_info,
        "orphaned_decisions": orphaned_decisions,
    }


def ensure_manual_review_files(paths: ReviewPaths) -> None:
    paths.review_decisions_path.parent.mkdir(parents=True, exist_ok=True)
    ensure_csv(paths.review_decisions_path, REVIEW_DECISION_COLUMNS)
    ensure_csv(paths.review_status_path, REVIEW_STATUS_COLUMNS)
    ensure_csv(paths.manual_players_path, MANUAL_PLAYERS_COLUMNS)


def ensure_csv(path: Path, columns: list[str]) -> None:
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            existing = reader.fieldnames or []
            rows = list(reader)
        missing = [column for column in columns if column not in existing]
        if missing:
            rewritten = []
            for row in rows:
                rewritten.append({column: row.get(column, "") for column in columns})
            write_csv(path, rewritten, columns)
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=columns).writeheader()


def build_unified_source_records(
    season: int,
    week: int,
    *,
    paths: ReviewPaths,
    contexts: list[ScheduleGameContext] | None = None,
) -> list[dict[str, Any]]:
    injury_rows = load_json_rows(paths.injury_path)
    reserve_rows = load_json_rows(paths.reserve_path)
    manual_rows = [
        row
        for row in load_manual_players(paths.manual_players_path)
        if int_or_none(row.get("season")) == season and int_or_none(row.get("week")) == week
    ]

    records: dict[str, dict[str, Any]] = {}
    for row in injury_rows:
        if int_or_none(row.get("season")) != season or int_or_none(row.get("week")) != week:
            continue
        merge_source_record(records, normalize_source_record(row, "injury_report", contexts=contexts))
    for row in reserve_rows:
        if int_or_none(row.get("season")) != season or int_or_none(row.get("week")) != week:
            continue
        merge_source_record(records, normalize_source_record(row, "reserve_roster", contexts=contexts))
    for row in manual_rows:
        merge_source_record(records, normalize_manual_player(row, contexts=contexts))

    return sorted(records.values(), key=record_sort_key)


def load_json_rows(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_source_record(
    row: dict[str, Any],
    source: str,
    *,
    contexts: list[ScheduleGameContext] | None = None,
) -> dict[str, Any]:
    season = int(row["season"])
    week = int(row["week"])
    team = str(row["team"]).strip().upper()
    schedule = schedule_for_team(season, week, team, contexts=contexts)
    source_memberships = {
        "injury_report": source == "injury_report",
        "reserve_roster": source == "reserve_roster",
        "manual_player": False,
    }
    return base_review_record(
        season=season,
        week=week,
        team=team,
        player_name=row.get("player_name"),
        normalized_player_name=row.get("normalized_player_name"),
        pff_player_id=row.get("pff_player_id"),
        pff_player_name=row.get("pff_player_name"),
        pff_position=row.get("pff_position"),
        canonical_position=row.get("canonical_position"),
        position_group=row.get("position_group"),
        source_position=row.get("source_position"),
        schedule=schedule,
        source_memberships=source_memberships,
        source_record=row,
    )


def normalize_manual_player(
    row: dict[str, Any],
    *,
    contexts: list[ScheduleGameContext] | None = None,
) -> dict[str, Any]:
    season = int(row["season"])
    week = int(row["week"])
    team = str(row["team"]).strip().upper()
    schedule = schedule_for_team(season, week, team, contexts=contexts)
    position = resolve_position(source_position=row.get("source_position"), manual_position_override=row.get("position_override"))
    record = base_review_record(
        season=season,
        week=week,
        team=team,
        player_name=row.get("player"),
        normalized_player_name=normalize_player_name(row.get("player")),
        pff_player_id=None,
        pff_player_name=None,
        pff_position=None,
        canonical_position=position.canonical_position,
        position_group=position.position_group,
        source_position=row.get("source_position"),
        schedule=schedule,
        source_memberships={"injury_report": False, "reserve_roster": False, "manual_player": True},
        source_record=row,
    )
    record.update(
        {
            "injury": row.get("injury") or None,
            "game_status": row.get("game_status") or None,
            "raw_roster_status": row.get("roster_status") or None,
            "candidate_reasons": ["manual_player"],
            "automated_candidate": falsey(row.get("publish")) is False,
            "manual_source_note": row.get("manual_note") or None,
        }
    )
    return record


def base_review_record(
    *,
    season: int,
    week: int,
    team: str,
    player_name: Any,
    normalized_player_name: Any,
    pff_player_id: Any,
    pff_player_name: Any,
    pff_position: Any,
    canonical_position: Any,
    position_group: Any,
    source_position: Any,
    schedule: ScheduleGameContext | None,
    source_memberships: dict[str, bool],
    source_record: dict[str, Any],
) -> dict[str, Any]:
    normalized = str(normalized_player_name or normalize_player_name(player_name)).strip()
    opponent = schedule.opponent if schedule else None
    home_away = schedule.home_away if schedule else None
    game_id = build_game_id(season, week, schedule, team, opponent)
    source_names = [name for name, enabled in source_memberships.items() if enabled]
    return {
        "record_id": identity_key(season, week, team, normalized, pff_player_id),
        "season": season,
        "week": week,
        "team": team,
        "opponent": opponent,
        "home_away": home_away,
        "game_id": game_id,
        "game_date": schedule.game_date if schedule else None,
        "kickoff": schedule.kickoff if schedule else None,
        "home_team": schedule.home_team if schedule else None,
        "away_team": schedule.away_team if schedule else None,
        "player_name": player_name,
        "normalized_player_name": normalized,
        "pff_player_id": blank_to_none(pff_player_id),
        "pff_player_name": blank_to_none(pff_player_name),
        "pff_position": blank_to_none(pff_position),
        "source_position": blank_to_none(source_position),
        "canonical_position": blank_to_none(canonical_position),
        "position_group": blank_to_none(position_group) or "ST",
        "source_memberships": source_memberships.copy(),
        "source_labels": source_names,
        "injury": source_record.get("injury"),
        "practice_by_day": source_record.get("practice_by_day") or {},
        "latest_practice": latest_practice(source_record),
        "game_status": source_record.get("game_status"),
        "raw_roster_status": source_record.get("raw_roster_status") or source_record.get("roster_status"),
        "canonical_roster_status": source_record.get("canonical_roster_status"),
        "designated_for_return": bool(source_record.get("designated_for_return")),
        "reserve_transaction_date": source_record.get("reserve_transaction_date"),
        "reserve_transaction_type": source_record.get("reserve_transaction_type"),
        "participation_source_season": source_record.get("participation_source_season") or season,
        "snap_data_status": source_record.get("snap_data_status"),
        "season_relevant_snap_pct": source_record.get("season_relevant_snap_pct"),
        "prior_season_relevant_snap_pct": source_record.get("prior_season_relevant_snap_pct"),
        "prior_season_snap_data_status": source_record.get("prior_season_snap_data_status"),
        "relevant_snap_pct": relevant_snap_pct(source_record, season),
        "candidate_reasons": normalize_reasons(source_record.get("candidate_reasons")),
        "automated_candidate": bool(source_record.get("key_candidate")),
        "manual_source_note": source_record.get("manual_note"),
        "source_records": {source_names[0] if source_names else "unknown": source_record},
    }


def merge_source_record(records: dict[str, dict[str, Any]], incoming: dict[str, Any]) -> None:
    key = incoming["record_id"]
    if key not in records:
        records[key] = incoming
        return
    current = records[key]
    for source_name, enabled in incoming["source_memberships"].items():
        current["source_memberships"][source_name] = current["source_memberships"].get(source_name, False) or enabled
    current["source_labels"] = [name for name, enabled in current["source_memberships"].items() if enabled]
    current["automated_candidate"] = current["automated_candidate"] or incoming["automated_candidate"]
    current["candidate_reasons"] = ordered_unique(current["candidate_reasons"] + incoming["candidate_reasons"])
    current["source_records"].update(incoming["source_records"])
    for field in [
        "injury",
        "practice_by_day",
        "latest_practice",
        "game_status",
        "raw_roster_status",
        "canonical_roster_status",
        "designated_for_return",
        "reserve_transaction_date",
        "reserve_transaction_type",
        "participation_source_season",
        "snap_data_status",
        "season_relevant_snap_pct",
        "prior_season_relevant_snap_pct",
        "prior_season_snap_data_status",
        "relevant_snap_pct",
    ]:
        if empty_value(current.get(field)) and not empty_value(incoming.get(field)):
            current[field] = incoming[field]


def apply_review_decisions(records: list[dict[str, Any]], decisions: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    output = []
    for record in records:
        decision = find_decision(record, decisions)
        manual_decision = (decision or {}).get("decision") or None
        final_include = record["automated_candidate"]
        review_state = "UNREVIEWED_DEFAULT"
        if manual_decision == "INCLUDE":
            final_include = True
            review_state = "MANUAL_INCLUDE"
        elif manual_decision == "EXCLUDE":
            final_include = False
            review_state = "MANUAL_EXCLUDE"
        display_position = (decision or {}).get("display_position") or record.get("canonical_position")
        manual_injury_override = (decision or {}).get("display_injury") or None
        display_injury = manual_injury_override or record.get("injury")
        enriched = dict(record)
        enriched.update(
            {
                "manual_decision": manual_decision,
                "manual_note": (decision or {}).get("note") or None,
                "ft_note": (decision or {}).get("ft_note") or None,
                "ft_note_source": "manual_review" if (decision or {}).get("ft_note") else None,
                "manual_injury_override": manual_injury_override,
                "reviewed_at": (decision or {}).get("reviewed_at") or None,
                "review_state": review_state,
                "explicitly_reviewed": manual_decision in {"INCLUDE", "EXCLUDE"},
                "final_include": bool(final_include),
                "display_position": display_position,
                "display_injury": display_injury,
                "prior_season_fallback_used": str(record.get("participation_source_season")) not in {"", "None", str(record["season"])},
            }
        )
        output.append(enriched)
    return sorted(output, key=record_sort_key)


def generate_reviewed_outputs(records: list[dict[str, Any]], *, paths: ReviewPaths) -> list[dict[str, Any]]:
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    reviewed = [reviewed_row(record) for record in records if record["final_include"]]
    (paths.output_dir / "reviewed_players.json").write_text(json.dumps(reviewed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_csv(paths.output_dir / "reviewed_players.csv", reviewed)
    population = [reviewed_row(record, include_excluded=True) for record in records]
    (paths.output_dir / "review_population.json").write_text(json.dumps(population, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_csv(paths.output_dir / "review_population.csv", population)
    return reviewed


def reviewed_row(record: dict[str, Any], *, include_excluded: bool = False) -> dict[str, Any]:
    row = {
        "record_id": record.get("record_id"),
        "season": record["season"],
        "week": record["week"],
        "game_id": record["game_id"],
        "game_date": record.get("game_date"),
        "kickoff": record.get("kickoff"),
        "team": record["team"],
        "opponent": record.get("opponent"),
        "home_away": record.get("home_away"),
        "player_name": record["player_name"],
        "normalized_player_name": record["normalized_player_name"],
        "pff_player_id": record.get("pff_player_id"),
        "pff_player_name": record.get("pff_player_name"),
        "canonical_position": record.get("canonical_position"),
        "display_position": record.get("display_position"),
        "position_group": record.get("position_group"),
        "pff_position": record.get("pff_position"),
        "injury": record.get("injury"),
        "practice_by_day": record.get("practice_by_day") or {},
        "manual_injury_override": record.get("manual_injury_override"),
        "display_injury": record.get("display_injury"),
        "latest_practice": record.get("latest_practice"),
        "game_status": record.get("game_status"),
        "canonical_roster_status": record.get("canonical_roster_status"),
        "reserve_status": record.get("canonical_roster_status"),
        "raw_roster_status": record.get("raw_roster_status"),
        "designated_for_return": record.get("designated_for_return"),
        "reserve_transaction_date": record.get("reserve_transaction_date"),
        "reserve_transaction_type": record.get("reserve_transaction_type"),
        "participation_source_season": record.get("participation_source_season"),
        "prior_season_fallback_used": record.get("prior_season_fallback_used"),
        "relevant_snap_pct": record.get("relevant_snap_pct"),
        "snap_data_status": record.get("snap_data_status"),
        "source_labels": record.get("source_labels") or [],
        "source_memberships": "|".join(record.get("source_labels") or []),
        "automated_candidate": record.get("automated_candidate"),
        "candidate_reasons": record.get("candidate_reasons") or [],
        "manual_decision": record.get("manual_decision"),
        "manual_note": record.get("manual_note"),
        "ft_note": record.get("ft_note"),
        "ft_note_source": record.get("ft_note_source"),
        "review_state": record.get("review_state"),
        "explicitly_reviewed": record.get("explicitly_reviewed"),
        "final_include": record.get("final_include"),
    }
    if include_excluded:
        return row
    return row


def group_for_review(
    records: list[dict[str, Any]],
    statuses: dict[str, dict[str, str]],
    *,
    stale_info: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    by_game: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_game[record["game_id"]].append(record)
    games = []
    for game_id, game_records in by_game.items():
        first = game_records[0]
        teams = []
        for team in ordered_game_teams(first, game_records):
            team_records = [record for record in game_records if record["team"] == team]
            groups = []
            for group in POSITION_GROUP_ORDER:
                players = [record for record in team_records if record.get("position_group") == group]
                if players:
                    groups.append({"position_group": group, "players": sorted(players, key=player_name_key)})
            teams.append(
                {
                    "team": team,
                    "opponent": first.get("opponent") if first.get("team") == team else opponent_for_team(team, game_records),
                    "reviewed": status_reviewed(statuses.get(status_key(first["season"], first["week"], "TEAM", game_id, team))),
                    "groups": groups,
                }
            )
        games.append(
            {
                "game_id": game_id,
                "week": first["week"],
                "game_date": first.get("game_date"),
                "kickoff": first.get("kickoff"),
                "home_team": first.get("home_team"),
                "away_team": first.get("away_team"),
                "reviewed": status_reviewed(statuses.get(status_key(first["season"], first["week"], "GAME", game_id, ""))),
                "stale_review": bool((stale_info or {}).get(game_id, {}).get("stale")),
                "review_status_label": (stale_info or {}).get(game_id, {}).get("label") or "UNREVIEWED",
                "teams": teams,
            }
        )
    return sorted(games, key=lambda game: (game.get("game_date") or "", game.get("kickoff") or "", game["game_id"]))


def save_decision(
    *,
    season: int,
    week: int,
    team: str,
    player_name: str,
    normalized_player_name: str | None,
    pff_player_id: str | None,
    decision: str,
    note: str | None = None,
    ft_note: str | None = None,
    display_position: str | None = None,
    display_injury: str | None = None,
    path: Path = MANUAL_DIR / "review_decisions.csv",
) -> dict[str, str]:
    ensure_csv(path, REVIEW_DECISION_COLUMNS)
    decision = decision.strip().upper()
    if decision not in {"INCLUDE", "EXCLUDE"}:
        raise ValueError("decision must be INCLUDE or EXCLUDE")
    now = datetime.now(timezone.utc).isoformat()
    existing = find_existing_decision_row(
        path,
        season=season,
        week=week,
        team=team,
        player_name=player_name,
        normalized_player_name=normalized_player_name or normalize_player_name(player_name),
        pff_player_id=pff_player_id,
    )
    row = {
        "season": str(season),
        "week": str(week),
        "team": team,
        "player_name": player_name,
        "normalized_player_name": normalized_player_name or normalize_player_name(player_name),
        "pff_player_id": pff_player_id or "",
        "decision": decision,
        "ft_note": ft_note if ft_note is not None else (existing or {}).get("ft_note", ""),
        "note": note if note is not None else (existing or {}).get("note", ""),
        "display_position": display_position if display_position is not None else (existing or {}).get("display_position", ""),
        "display_injury": display_injury if display_injury is not None else (existing or {}).get("display_injury", ""),
        "reviewed_at": now,
    }
    upsert_csv(path, REVIEW_DECISION_COLUMNS, row, lambda old: decision_matches_row(row, old))
    return row


def restore_review_record(record: dict[str, Any], *, path: Path = MANUAL_DIR / "review_decisions.csv") -> dict[str, str]:
    return save_decision(
        season=int(record["season"]),
        week=int(record["week"]),
        team=str(record["team"]),
        player_name=str(record["player_name"]),
        normalized_player_name=record.get("normalized_player_name"),
        pff_player_id=record.get("pff_player_id"),
        decision="INCLUDE",
        path=path,
    )


def save_ft_note(
    *,
    season: int,
    week: int,
    team: str,
    player_name: str,
    normalized_player_name: str | None,
    pff_player_id: str | None,
    ft_note: str,
    path: Path = MANUAL_DIR / "review_decisions.csv",
) -> dict[str, str]:
    ensure_csv(path, REVIEW_DECISION_COLUMNS)
    normalized = normalized_player_name or normalize_player_name(player_name)
    existing = find_existing_decision_row(
        path,
        season=season,
        week=week,
        team=team,
        player_name=player_name,
        normalized_player_name=normalized,
        pff_player_id=pff_player_id,
    )
    row = {
        "season": str(season),
        "week": str(week),
        "team": team,
        "player_name": player_name,
        "normalized_player_name": normalized,
        "pff_player_id": pff_player_id or "",
        "decision": (existing or {}).get("decision", ""),
        "ft_note": ft_note or "",
        "note": (existing or {}).get("note", ""),
        "display_position": (existing or {}).get("display_position", ""),
        "display_injury": (existing or {}).get("display_injury", ""),
        "reviewed_at": (existing or {}).get("reviewed_at", ""),
    }
    upsert_csv(path, REVIEW_DECISION_COLUMNS, row, lambda old: decision_matches_row(row, old))
    return row


def save_injury_override(
    *,
    season: int,
    week: int,
    team: str,
    player_name: str,
    normalized_player_name: str | None,
    pff_player_id: str | None,
    display_injury: str,
    path: Path = MANUAL_DIR / "review_decisions.csv",
) -> dict[str, str]:
    ensure_csv(path, REVIEW_DECISION_COLUMNS)
    normalized = normalized_player_name or normalize_player_name(player_name)
    existing = find_existing_decision_row(
        path,
        season=season,
        week=week,
        team=team,
        player_name=player_name,
        normalized_player_name=normalized,
        pff_player_id=pff_player_id,
    )
    row = {
        "season": str(season),
        "week": str(week),
        "team": team,
        "player_name": player_name,
        "normalized_player_name": normalized,
        "pff_player_id": pff_player_id or "",
        "decision": (existing or {}).get("decision", ""),
        "ft_note": (existing or {}).get("ft_note", ""),
        "note": (existing or {}).get("note", ""),
        "display_position": (existing or {}).get("display_position", ""),
        "display_injury": display_injury.strip(),
        "reviewed_at": (existing or {}).get("reviewed_at", ""),
    }
    upsert_csv(path, REVIEW_DECISION_COLUMNS, row, lambda old: decision_matches_row(row, old))
    return row


def save_review_status(
    *,
    season: int,
    week: int,
    scope: str,
    game_id: str,
    team: str = "",
    opponent: str = "",
    reviewed: bool = True,
    note: str | None = None,
    source_fingerprint: str | None = None,
    path: Path = MANUAL_DIR / "review_status.csv",
) -> dict[str, str]:
    ensure_csv(path, REVIEW_STATUS_COLUMNS)
    scope = scope.strip().upper()
    if scope not in {"GAME", "TEAM"}:
        raise ValueError("scope must be GAME or TEAM")
    row = {
        "season": str(season),
        "week": str(week),
        "scope": scope,
        "game_id": game_id,
        "team": team,
        "opponent": opponent,
        "reviewed": "True" if reviewed else "False",
        "note": note or "",
        "source_fingerprint": source_fingerprint or "",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    upsert_csv(path, REVIEW_STATUS_COLUMNS, row, lambda old: status_key_from_row(old) == status_key_from_row(row))
    return row


def append_manual_player(
    *,
    season: int,
    week: int,
    team: str,
    player_name: str,
    source_position: str | None = None,
    injury: str | None = None,
    roster_status: str | None = None,
    game_status: str | None = None,
    note: str | None = None,
    position_override: str | None = None,
    path: Path = MANUAL_DIR / "manual_players.csv",
) -> dict[str, str]:
    ensure_csv(path, MANUAL_PLAYERS_COLUMNS)
    row = {
        "season": str(season),
        "week": str(week),
        "team": team,
        "player": player_name,
        "source_position": source_position or "",
        "injury": injury or "",
        "roster_status": roster_status or "",
        "game_status": game_status or "",
        "manual_note": note or "",
        "publish": "include",
        "position_override": position_override or "",
    }
    upsert_csv(
        path,
        MANUAL_PLAYERS_COLUMNS,
        row,
        lambda old: old.get("season") == row["season"]
        and old.get("week") == row["week"]
        and old.get("team") == row["team"]
        and normalize_player_name(old.get("player")) == normalize_player_name(row["player"]),
    )
    return row


def load_review_decisions(path: Path) -> dict[str, dict[str, str]]:
    ensure_csv(path, REVIEW_DECISION_COLUMNS)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    decisions = {}
    for row in rows:
        decision = row.get("decision", "").strip().upper()
        has_review_content = any(row.get(field) for field in ["ft_note", "note", "display_position", "display_injury"])
        if decision not in {"INCLUDE", "EXCLUDE"} and not has_review_content:
            continue
        key = decision_lookup_key(row)
        decisions[key] = {**row, "decision": decision if decision in {"INCLUDE", "EXCLUDE"} else ""}
    return decisions


def find_orphaned_decisions(records: list[dict[str, Any]], decisions: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    active_keys = set()
    for record in records:
        if record.get("pff_player_id"):
            active_keys.add(f'{record["season"]}|{record["week"]}|pff:{record["pff_player_id"]}')
        active_keys.add(f'{record["season"]}|{record["week"]}|team:{record["team"]}|name:{record["normalized_player_name"]}')
    return [row for key, row in sorted(decisions.items()) if key not in active_keys]


def manual_add_option(record: dict[str, Any]) -> bool:
    if record.get("final_include"):
        return False
    if record.get("manual_decision") == "EXCLUDE":
        return True
    return not bool(record.get("automated_candidate"))


def manual_add_option_record(record: dict[str, Any]) -> dict[str, Any]:
    output = dict(record)
    if record.get("manual_decision") == "EXCLUDE":
        output["manual_add_label"] = "manually_excluded"
    else:
        output["manual_add_label"] = "|".join(record.get("candidate_reasons") or []) or "known_player"
    return output


def find_existing_decision_row(
    path: Path,
    *,
    season: int,
    week: int,
    team: str,
    player_name: str,
    normalized_player_name: str,
    pff_player_id: str | None,
) -> dict[str, str] | None:
    rows = load_review_decisions(path)
    probe = {
        "season": str(season),
        "week": str(week),
        "team": team,
        "player_name": player_name,
        "normalized_player_name": normalized_player_name,
        "pff_player_id": pff_player_id or "",
    }
    return rows.get(decision_lookup_key(probe))


def load_review_status(path: Path) -> dict[str, dict[str, str]]:
    ensure_csv(path, REVIEW_STATUS_COLUMNS)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return {status_key_from_row(row): row for row in rows}


def find_decision(record: dict[str, Any], decisions: dict[str, dict[str, str]]) -> dict[str, str] | None:
    keys = []
    if record.get("pff_player_id"):
        keys.append(f'{record["season"]}|{record["week"]}|pff:{record["pff_player_id"]}')
    keys.append(
        f'{record["season"]}|{record["week"]}|team:{record["team"]}|name:{record["normalized_player_name"]}'
    )
    for key in keys:
        if key in decisions:
            return decisions[key]
    return None


def decision_lookup_key(row: dict[str, str]) -> str:
    if row.get("pff_player_id"):
        return f'{row["season"]}|{row["week"]}|pff:{row["pff_player_id"]}'
    return f'{row["season"]}|{row["week"]}|team:{row["team"]}|name:{row.get("normalized_player_name") or normalize_player_name(row.get("player_name"))}'


def identity_key(season: int, week: int, team: str, normalized_name: str, pff_player_id: Any) -> str:
    if not empty_value(pff_player_id):
        return f"{season}|{week}|pff:{pff_player_id}"
    return f"{season}|{week}|team:{team}|name:{normalized_name}"


def status_key(season: int, week: int, scope: str, game_id: str, team: str) -> str:
    return f"{season}|{week}|{scope.upper()}|{game_id}|{team or ''}"


def status_key_from_row(row: dict[str, str]) -> str:
    return status_key(int(row["season"]), int(row["week"]), row["scope"], row["game_id"], row.get("team") or "")


def status_reviewed(row: dict[str, str] | None) -> bool:
    return bool(row and str(row.get("reviewed")).strip().lower() == "true")


def game_source_fingerprint(records: list[dict[str, Any]], game_id: str) -> str:
    source_rows = []
    for record in records:
        if record.get("game_id") != game_id:
            continue
        source_rows.append({field: fingerprint_value(record.get(field)) for field in FINGERPRINT_FIELDS})
    payload = {
        "version": FINGERPRINT_VERSION,
        "game_id": game_id,
        "records": sorted(source_rows, key=lambda row: (str(row.get("team") or ""), str(row.get("record_id") or ""), str(row.get("player_name") or ""))),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def fingerprint_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): fingerprint_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [fingerprint_value(item) for item in value]
    if isinstance(value, float):
        return round(value, 6)
    if value in {"", "None", "nan"}:
        return None
    return value


def build_stale_review_info(
    records: list[dict[str, Any]],
    statuses: dict[str, dict[str, str]],
    *,
    paths: ReviewPaths,
) -> dict[str, dict[str, Any]]:
    game_ids = {record["game_id"] for record in records}
    source_updated_at = source_inputs_updated_at(paths)
    info: dict[str, dict[str, Any]] = {}
    for game_id in game_ids:
        status = statuses.get(status_key(records[0]["season"], records[0]["week"], "GAME", game_id, "")) if records else None
        current = game_source_fingerprint(records, game_id)
        reviewed = status_reviewed(status)
        saved = (status or {}).get("source_fingerprint") or ""
        stale = False
        label = "UNREVIEWED"
        reason = ""
        if reviewed and saved:
            stale = saved != current
            label = "STALE" if stale else "CURRENT"
            reason = "source fingerprint changed" if stale else ""
        elif reviewed:
            reviewed_at = parse_datetime((status or {}).get("reviewed_at"))
            if reviewed_at and source_updated_at and reviewed_at >= source_updated_at:
                stale = False
                label = "LEGACY_CURRENT"
                reason = "legacy review predates fingerprint support; source files have not changed since review"
            else:
                stale = True
                label = "STALE_LEGACY"
                reason = "review predates fingerprint support and source freshness cannot be verified"
        info[game_id] = {
            "reviewed": reviewed,
            "stale": stale,
            "label": label,
            "reason": reason,
            "current_fingerprint": current,
            "saved_fingerprint": saved,
        }
    return info


def source_inputs_updated_at(paths: ReviewPaths) -> datetime | None:
    mtimes = [path.stat().st_mtime for path in [paths.injury_path, paths.reserve_path] if path.exists()]
    if not mtimes:
        return None
    return datetime.fromtimestamp(max(mtimes), timezone.utc)


def parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def upsert_csv(path: Path, columns: list[str], row: dict[str, str], predicate: Any) -> None:
    ensure_csv(path, columns)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    output = []
    replaced = False
    for old in rows:
        if predicate(old):
            output.append({column: row.get(column, "") for column in columns})
            replaced = True
        else:
            output.append({column: old.get(column, "") for column in columns})
    if not replaced:
        output.append({column: row.get(column, "") for column in columns})
    write_csv(path, output, columns)


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    if columns is None:
        columns = []
        for row in rows:
            for key in row:
                if key not in columns:
                    columns.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: csv_value(row.get(column)) for column in columns})


def build_review_summary(
    records: list[dict[str, Any]],
    statuses: dict[str, dict[str, str]],
    reviewed: list[dict[str, Any]],
    *,
    paths: ReviewPaths,
    stale_info: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    source_split = Counter(source_split_label(record) for record in records if record["final_include"])
    all_game_ids = {record["game_id"] for record in records if record["final_include"]}
    reviewed_games = {row["game_id"] for row in statuses.values() if row.get("scope") == "GAME" and status_reviewed(row)}
    stale_games = {game_id for game_id, info in (stale_info or {}).items() if info.get("stale")}
    current_reviewed_games = reviewed_games - stale_games
    updated_at = data_updated_at(paths)
    return {
        "total_source_players": len(records),
        "automated_candidates": sum(1 for record in records if record["automated_candidate"]),
        "included": sum(1 for record in records if record["final_include"]),
        "excluded": sum(1 for record in records if not record["final_include"]),
        "explicit_manual_include": sum(1 for record in records if record.get("manual_decision") == "INCLUDE"),
        "explicit_manual_exclude": sum(1 for record in records if record.get("manual_decision") == "EXCLUDE"),
        "unreviewed_default_include": sum(
            1 for record in records if record["final_include"] and record["review_state"] == "UNREVIEWED_DEFAULT"
        ),
        "prior_season_fallback": sum(1 for record in records if record["final_include"] and record["prior_season_fallback_used"]),
        "source_split": dict(source_split),
        "games_represented": len(all_game_ids),
        "teams_represented": len({record["team"] for record in records if record["final_include"]}),
        "games_reviewed": len(current_reviewed_games & all_game_ids),
        "games_stale": len(stale_games & all_game_ids),
        "week_fully_reviewed": bool(all_game_ids) and all_game_ids.issubset(current_reviewed_games),
        "reviewed_output_rows": len(reviewed),
        "data_updated_at_utc": updated_at["utc"],
        "data_updated_at_et": updated_at["et"],
    }


def data_updated_at(paths: ReviewPaths) -> dict[str, str | None]:
    candidates = [
        paths.injury_path,
        paths.reserve_path,
        paths.review_decisions_path,
        paths.review_status_path,
        paths.output_dir / "review_population.json",
        paths.output_dir / "reviewed_players.json",
    ]
    mtimes = [path.stat().st_mtime for path in candidates if path.exists()]
    if not mtimes:
        return {"utc": None, "et": None}
    dt_utc = datetime.fromtimestamp(max(mtimes), timezone.utc)
    dt_et = dt_utc.astimezone(ZoneInfo("America/New_York"))
    return {
        "utc": dt_utc.isoformat(),
        "et": dt_et.strftime("%Y-%m-%d %H:%M %Z"),
    }


def source_split_label(record: dict[str, Any]) -> str:
    injury = record["source_memberships"].get("injury_report")
    reserve = record["source_memberships"].get("reserve_roster")
    manual = record["source_memberships"].get("manual_player")
    if injury and reserve:
        return "both"
    if injury:
        return "injury_report"
    if reserve:
        return "reserve_roster"
    if manual:
        return "manual_player"
    return "unknown"


def build_game_id(season: int, week: int, schedule: ScheduleGameContext | None, team: str, opponent: str | None) -> str:
    if schedule:
        teams = "-".join(sorted([schedule.home_team, schedule.away_team]))
        return f"{season}-W{week:02d}-{teams}"
    return f"{season}-W{week:02d}-{team}-{opponent or 'UNK'}"


def ordered_game_teams(first: dict[str, Any], records: list[dict[str, Any]]) -> list[str]:
    if first.get("away_team") and first.get("home_team"):
        return [first["away_team"], first["home_team"]]
    return sorted({record["team"] for record in records})


def opponent_for_team(team: str, records: list[dict[str, Any]]) -> str | None:
    for record in records:
        if record["team"] == team:
            return record.get("opponent")
    return None


def record_sort_key(record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        record.get("game_date") or "",
        record.get("kickoff") or "",
        record.get("game_id") or "",
        record.get("team") or "",
        POSITION_GROUP_RANK.get(record.get("position_group") or "ST", 99),
        str(record.get("player_name") or ""),
    )


def player_name_key(record: dict[str, Any]) -> str:
    return str(record.get("player_name") or "")


def latest_practice(row: dict[str, Any]) -> str | None:
    observations = row.get("practice_observations") or []
    if observations:
        return observations[-1].get("participation")
    by_day = row.get("practice_by_day") or {}
    for day in ["Saturday", "Friday", "Thursday", "Wednesday", "Tuesday", "Monday"]:
        if by_day.get(day):
            return by_day[day]
    return None


def relevant_snap_pct(row: dict[str, Any], season: int) -> Any:
    if str(row.get("participation_source_season") or season) != str(season):
        return row.get("prior_season_relevant_snap_pct")
    return row.get("season_relevant_snap_pct")


def normalize_reasons(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass
    return [item for item in text.split("|") if item]


def ordered_unique(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        if value not in seen:
            output.append(value)
            seen.add(value)
    return output


def int_or_none(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def blank_to_none(value: Any) -> Any:
    if value in ("", None):
        return None
    return value


def empty_value(value: Any) -> bool:
    return value is None or value == "" or value == {} or value == []


def falsey(value: Any) -> bool:
    return str(value or "").strip().lower() in {"", "exclude", "no", "n", "false", "0"}


def csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    if value is None:
        return ""
    return value


def decision_matches_row(new: dict[str, str], old: dict[str, str]) -> bool:
    return decision_lookup_key(new) == decision_lookup_key(old)
