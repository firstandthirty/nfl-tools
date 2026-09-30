from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .injury_schema import (
    PROJECT_ROOT,
    load_manual_overrides,
    load_position_config,
    load_json,
    normalize_player_name,
    resolve_position,
)
from .schedule_context import normalize_team


REPO_ROOT = PROJECT_ROOT.parent
PFF_PROCESSED_ROOT = REPO_ROOT / "pff_content" / "data" / "processed" / "pff"
PFF_DIRECTORY_ROOT = REPO_ROOT / "pff_content" / "data" / "processed" / "pff_player_directory"
PROCESSED_ROOT = PROJECT_ROOT / "data" / "processed"
MANUAL_ROOT = PROJECT_ROOT / "data" / "manual"
PFF_MAPPING_PATH = MANUAL_ROOT / "pff_player_mappings.csv"
PFF_INDEX_ROOT = PROCESSED_ROOT / "pff_player_index"

FACET_DATASETS = (
    "passing",
    "receiving",
    "rushing",
    "pass_blocking",
    "pass_rush",
    "run_defense",
    "coverage",
)

OFFENSE_GROUPS = {"QB", "RB", "WR", "TE", "OL"}
DEFENSE_GROUPS = {"EDGE", "DL", "LB", "CB", "S"}
SPECIAL_TEAMS_POSITIONS = {"K", "P", "LS"}


@dataclass
class PFFGameUsage:
    season: int
    week: int
    player_id: str
    player_name: str
    normalized_player_name: str
    teams: set[str] = field(default_factory=set)
    positions: Counter[str] = field(default_factory=Counter)
    offensive_snaps: int = 0
    defensive_snaps: int = 0
    special_teams_snaps: int = 0
    team_offensive_snaps: int = 0
    team_defensive_snaps: int = 0
    offensive_snap_pct: float | None = None
    defensive_snap_pct: float | None = None
    special_teams_snap_pct: float | None = None
    source_datasets: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "week": self.week,
            "player_id": self.player_id,
            "player_name": self.player_name,
            "normalized_player_name": self.normalized_player_name,
            "teams": sorted(self.teams),
            "positions": dict(self.positions),
            "offensive_snaps": self.offensive_snaps,
            "defensive_snaps": self.defensive_snaps,
            "special_teams_snaps": self.special_teams_snaps,
            "team_offensive_snaps": self.team_offensive_snaps,
            "team_defensive_snaps": self.team_defensive_snaps,
            "offensive_snap_pct": self.offensive_snap_pct,
            "defensive_snap_pct": self.defensive_snap_pct,
            "special_teams_snap_pct": self.special_teams_snap_pct,
            "source_datasets": sorted(self.source_datasets),
        }


@dataclass
class PFFPlayerProfile:
    player_id: str
    player_name: str
    normalized_player_name: str
    teams: set[str] = field(default_factory=set)
    positions: Counter[str] = field(default_factory=Counter)
    games: dict[int, PFFGameUsage] = field(default_factory=dict)
    aliases: set[str] = field(default_factory=set)
    identity_sources: set[str] = field(default_factory=set)

    def primary_position(self) -> str | None:
        return self.positions.most_common(1)[0][0] if self.positions else None

    def display_team(self) -> str | None:
        return sorted(self.teams)[-1] if self.teams else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "player_name": self.player_name,
            "normalized_player_name": self.normalized_player_name,
            "teams": sorted(self.teams),
            "positions": dict(self.positions),
            "primary_position": self.primary_position(),
            "aliases": sorted(self.aliases),
            "identity_sources": sorted(self.identity_sources),
            "games": [self.games[week].to_dict() for week in sorted(self.games)],
        }


@dataclass(frozen=True)
class MatchResult:
    status: str
    method: str | None
    profile: PFFPlayerProfile | None
    candidates: list[dict[str, Any]]


def latest_official_run_dir(season: int, week: int) -> Path:
    base = PROCESSED_ROOT / str(season) / f"week_{week:02d}"
    runs = sorted(path for path in base.iterdir() if path.is_dir() and (path / "official_injury_reports.json").exists())
    if not runs:
        raise FileNotFoundError(f"No official injury runs found under {base}")
    return runs[-1]


def build_pff_player_index(season: int, through_week: int, *, directory_week: int | None = None) -> dict[str, PFFPlayerProfile]:
    profiles = build_snap_player_index(season, through_week)
    if not profiles:
        profiles = build_facet_player_index(season, through_week)
    merge_directory_profiles(profiles, load_latest_generated_index(season, through_week))
    merge_directory_profiles(profiles, build_directory_player_index(season, directory_week or through_week))
    return profiles


def build_snap_player_index(season: int, through_week: int) -> dict[str, PFFPlayerProfile]:
    profiles: dict[str, PFFPlayerProfile] = {}
    for week in range(1, through_week + 1):
        path = PFF_PROCESSED_ROOT / str(season) / f"week_{week:02d}" / "snap_participation.csv"
        if not path.exists():
            continue
        for row in read_csv_dicts(path):
            player_id = clean_id(row.get("player_id"))
            player_name = clean_text(row.get("player_name"))
            if not player_id or not player_name:
                continue
            usage = PFFGameUsage(
                season=season,
                week=week,
                player_id=player_id,
                player_name=player_name,
                normalized_player_name=normalize_player_name(player_name),
                offensive_snaps=int_number(row.get("offensive_snaps")),
                defensive_snaps=int_number(row.get("defensive_snaps")),
                special_teams_snaps=int_number(row.get("special_teams_snaps")),
                team_offensive_snaps=int_number(row.get("team_offensive_snaps")),
                team_defensive_snaps=int_number(row.get("team_defensive_snaps")),
                offensive_snap_pct=pct(row.get("offensive_snap_pct")),
                defensive_snap_pct=pct(row.get("defensive_snap_pct")),
                special_teams_snap_pct=pct(row.get("special_teams_snap_pct")),
            )
            usage.source_datasets.update((row.get("source_datasets") or "snap_participation").split("|"))
            team = normalize_team(row.get("team"))
            position = clean_position(row.get("pff_position"))
            if team:
                usage.teams.add(team)
            if position:
                usage.positions[position] += 1
            profile = profiles.get(player_id)
            if profile is None:
                profile = PFFPlayerProfile(
                    player_id=player_id,
                    player_name=player_name,
                    normalized_player_name=usage.normalized_player_name,
                )
                profiles[player_id] = profile
            profile.identity_sources.add("snap_participation")
            profile.teams.update(usage.teams)
            profile.positions.update(usage.positions)
            profile.games[week] = usage
    return profiles


def build_facet_player_index(season: int, through_week: int) -> dict[str, PFFPlayerProfile]:
    profiles: dict[str, PFFPlayerProfile] = {}
    for week in range(1, through_week + 1):
        week_dir = PFF_PROCESSED_ROOT / str(season) / f"week_{week:02d}"
        if not week_dir.exists():
            continue
        games: dict[str, PFFGameUsage] = {}
        for dataset in FACET_DATASETS:
            path = week_dir / f"{dataset}.csv"
            if not path.exists():
                continue
            for row in read_csv_dicts(path):
                player_id = clean_id(row.get("player_id"))
                player_name = clean_text(row.get("player_name"))
                if not player_id or not player_name:
                    continue
                team = normalize_team(row.get("team"))
                position = clean_position(row.get("position"))
                key = f"{week}:{player_id}"
                usage = games.get(key)
                if usage is None:
                    usage = PFFGameUsage(
                        season=season,
                        week=week,
                        player_id=player_id,
                        player_name=player_name,
                        normalized_player_name=normalize_player_name(player_name),
                    )
                    games[key] = usage
                if team:
                    usage.teams.add(team)
                if position:
                    usage.positions[position] += 1
                usage.source_datasets.add(dataset)
                apply_usage_from_row(usage, row, dataset)
        for usage in games.values():
            profile = profiles.get(usage.player_id)
            if profile is None:
                profile = PFFPlayerProfile(
                    player_id=usage.player_id,
                    player_name=usage.player_name,
                    normalized_player_name=usage.normalized_player_name,
                )
                profiles[usage.player_id] = profile
            profile.identity_sources.add("facet_participation")
            profile.teams.update(usage.teams)
            profile.positions.update(usage.positions)
            profile.games[usage.week] = usage
    return profiles


def build_directory_player_index(season: int, week: int) -> dict[str, PFFPlayerProfile]:
    path = PFF_DIRECTORY_ROOT / str(season) / f"week_{week:02d}" / "players.csv"
    if not path.exists():
        return {}
    profiles: dict[str, PFFPlayerProfile] = {}
    for row in read_csv_dicts(path):
        player_id = clean_id(row.get("pff_player_id") or row.get("id"))
        player_name = clean_text(row.get("pff_player_name") or row.get("player_name"))
        if not player_id or not player_name:
            continue
        profile = profiles.get(player_id)
        if profile is None:
            profile = PFFPlayerProfile(
                player_id=player_id,
                player_name=player_name,
                normalized_player_name=normalize_player_name(player_name),
            )
            profiles[player_id] = profile
        team = normalize_team(row.get("team") or row.get("pff_team"))
        position = clean_position(row.get("pff_position") or row.get("position"))
        if team:
            profile.teams.add(team)
        if position:
            profile.positions[position] += 1
        profile.identity_sources.add("player_directory")
        for alias in split_pipe(row.get("aliases")):
            normalized = normalize_player_name(alias)
            if normalized:
                profile.aliases.add(normalized)
        for field_name in ["query_name", "official_name", "query_names", "official_names"]:
            for alias in split_pipe(row.get(field_name)):
                normalized = normalize_player_name(alias)
                if normalized and normalized != profile.normalized_player_name:
                    profile.aliases.add(normalized)
    return profiles


def merge_directory_profiles(base: dict[str, PFFPlayerProfile], directory: dict[str, PFFPlayerProfile]) -> None:
    for player_id, incoming in directory.items():
        profile = base.get(player_id)
        if profile is None:
            base[player_id] = incoming
            continue
        profile.teams.update(incoming.teams)
        profile.positions.update(incoming.positions)
        profile.aliases.update(incoming.aliases)
        profile.identity_sources.update(incoming.identity_sources)


def load_latest_generated_index(season: int, through_week: int) -> dict[str, PFFPlayerProfile]:
    if not PFF_INDEX_ROOT.exists():
        return {}
    candidates = []
    for path in PFF_INDEX_ROOT.glob(f"{season}_through_week_*.json"):
        try:
            week_value = int(path.stem.rsplit("_", 1)[-1])
        except ValueError:
            continue
        if week_value <= through_week:
            candidates.append((week_value, path))
    if not candidates:
        return {}
    _, path = sorted(candidates)[-1]
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return profiles_from_index_rows(rows if isinstance(rows, list) else [])


def profiles_from_index_rows(rows: list[dict[str, Any]]) -> dict[str, PFFPlayerProfile]:
    profiles: dict[str, PFFPlayerProfile] = {}
    for row in rows:
        player_id = clean_id(row.get("player_id") or row.get("pff_player_id"))
        player_name = clean_text(row.get("player_name") or row.get("pff_player_name"))
        if not player_id or not player_name:
            continue
        profile = PFFPlayerProfile(
            player_id=player_id,
            player_name=player_name,
            normalized_player_name=normalize_player_name(row.get("normalized_player_name") or player_name),
        )
        profile.teams.update(normalize_team(team) for team in row.get("teams", []) if normalize_team(team))
        positions = row.get("positions") or {}
        if isinstance(positions, dict):
            profile.positions.update({clean_position(position): count for position, count in positions.items() if clean_position(position)})
        profile.aliases.update(normalize_player_name(alias) for alias in row.get("aliases", []) if normalize_player_name(alias))
        profile.identity_sources.update(row.get("identity_sources") or ["generated_pff_index"])
        profile.identity_sources.add("generated_pff_index")
        profiles[player_id] = profile
    return profiles


def apply_usage_from_row(usage: PFFGameUsage, row: dict[str, str], dataset: str) -> None:
    if dataset == "passing":
        usage.offensive_snaps = max(usage.offensive_snaps, int_number(row.get("passing_snaps")))
    elif dataset == "receiving":
        usage.offensive_snaps = max(usage.offensive_snaps, int_number(row.get("routes")) + int_number(row.get("pass_blocks")))
        usage.offensive_snap_pct = max_optional(usage.offensive_snap_pct, pct(row.get("route_rate")))
    elif dataset == "rushing":
        usage.offensive_snaps = max(
            usage.offensive_snaps,
            int_number(row.get("routes")) + int_number(row.get("run_plays")),
        )
    elif dataset == "pass_blocking":
        usage.offensive_snaps = max(usage.offensive_snaps, int_number(row.get("pass_block_snaps")))
        usage.offensive_snap_pct = max_optional(usage.offensive_snap_pct, pct(row.get("pass_block_percent")))
    elif dataset == "coverage":
        usage.defensive_snaps = max(usage.defensive_snaps, int_number(row.get("coverage_snaps")))
        usage.defensive_snap_pct = max_optional(usage.defensive_snap_pct, pct(row.get("coverage_percent")))
    elif dataset == "pass_rush":
        usage.defensive_snaps = max(usage.defensive_snaps, int_number(row.get("pass_rush_snaps")))
        usage.defensive_snap_pct = max_optional(usage.defensive_snap_pct, pct(row.get("pass_rush_percent")))
    elif dataset == "run_defense":
        usage.defensive_snaps = max(usage.defensive_snaps, int_number(row.get("run_defense_snaps")))


def persist_pff_index(profiles: dict[str, PFFPlayerProfile], *, season: int, through_week: int) -> tuple[Path, Path]:
    PFF_INDEX_ROOT.mkdir(parents=True, exist_ok=True)
    json_path = PFF_INDEX_ROOT / f"{season}_through_week_{through_week:02d}.json"
    csv_path = PFF_INDEX_ROOT / f"{season}_through_week_{through_week:02d}.csv"
    rows = [profiles[player_id].to_dict() for player_id in sorted(profiles, key=int)]
    json_path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "pff_player_id",
                "pff_player_name",
                "normalized_player_name",
                "teams",
                "primary_position",
                "weeks",
            ],
        )
        writer.writeheader()
        for profile in sorted(profiles.values(), key=lambda item: (item.normalized_player_name, int(item.player_id))):
            writer.writerow(
                {
                    "pff_player_id": profile.player_id,
                    "pff_player_name": profile.player_name,
                    "normalized_player_name": profile.normalized_player_name,
                    "teams": "|".join(sorted(profile.teams)),
                    "primary_position": profile.primary_position(),
                    "weeks": "|".join(str(week) for week in sorted(profile.games)),
                }
            )
    return json_path, csv_path


def enrich_official_run(
    *,
    season: int,
    week: int,
    official_run_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], Path]:
    run_dir = official_run_dir or latest_official_run_dir(season, week)
    official_path = run_dir / "official_injury_reports.json"
    official_records = load_json(official_path)
    through_week = week - 1
    previous_enriched = load_previous_enrichment(run_dir)
    profiles = build_pff_player_index(season, through_week, directory_week=week)
    index_json, index_csv = persist_pff_index(profiles, season=season, through_week=through_week)
    profile_by_name = profiles_by_normalized_name(profiles)
    profile_by_exact_name = profiles_by_exact_normalized_name(profiles)
    profile_by_alias = profiles_by_alias(profiles)
    persisted = load_persisted_mappings()
    manual_overrides = load_manual_override_map()
    relevance_rules = load_json(PROJECT_ROOT / "config" / "relevance_rules.json")

    enriched = []
    for record in official_records:
        match = match_player(
            record,
            profiles=profiles,
            by_name=profile_by_name,
            by_exact_name=profile_by_exact_name,
            by_alias=profile_by_alias,
            persisted=persisted,
        )
        manual = manual_overrides.get((record["team"], record["normalized_player_name"]), {})
        enriched.append(enrich_record(record, match, manual, relevance_rules))
    comparison = compare_enrichment_outputs(previous_enriched, enriched)

    manifest = build_manifest(
        enriched,
        comparison=comparison,
        official_records=official_records,
        run_dir=run_dir,
        season=season,
        week=week,
        through_week=through_week,
        index_json=index_json,
        index_csv=index_csv,
    )
    write_enrichment_outputs(run_dir, enriched, manifest, comparison)
    return enriched, manifest, run_dir


def match_player(
    record: dict[str, Any],
    *,
    profiles: dict[str, PFFPlayerProfile],
    by_name: dict[str, list[PFFPlayerProfile]],
    by_exact_name: dict[str, list[PFFPlayerProfile]] | None = None,
    by_alias: dict[str, list[PFFPlayerProfile]] | None = None,
    persisted: dict[tuple[str, str], str],
) -> MatchResult:
    team = record["team"]
    norm = record["normalized_player_name"]
    mapping_id = persisted.get((team, norm))
    if mapping_id and mapping_id in profiles:
        return MatchResult("PERSISTED", "persisted_official_team_player", profiles[mapping_id], [])

    exact_matches = exact_lookup(by_exact_name or by_name, norm)
    current_team = [profile for profile in exact_matches if team in profile.teams]
    if len(current_team) == 1:
        return MatchResult("EXACT", "normalized_name_current_team", current_team[0], [])
    if len(current_team) > 1:
        return MatchResult("REVIEW_REQUIRED", "ambiguous_normalized_name_current_team", None, candidate_dicts(current_team))
    if len(exact_matches) == 1:
        method = "unique_directory_identity" if "player_directory" in exact_matches[0].identity_sources else "unique_normalized_name_prior_team"
        return MatchResult("NORMALIZED", method, exact_matches[0], [])
    if len(exact_matches) > 1:
        return MatchResult("REVIEW_REQUIRED", "ambiguous_normalized_name", None, candidate_dicts(exact_matches))

    alias_matches = exact_lookup(by_alias or {}, norm)
    alias_current_team = [profile for profile in alias_matches if team in profile.teams]
    if len(alias_current_team) == 1:
        return MatchResult("NORMALIZED", "safe_directory_alias_current_team", alias_current_team[0], [])
    if len(alias_current_team) > 1:
        return MatchResult("REVIEW_REQUIRED", "ambiguous_directory_alias_current_team", None, candidate_dicts(alias_current_team))
    if len(alias_matches) == 1:
        return MatchResult("NORMALIZED", "safe_directory_alias_unique", alias_matches[0], [])
    if len(alias_matches) > 1:
        return MatchResult("REVIEW_REQUIRED", "ambiguous_directory_alias", None, candidate_dicts(alias_matches))
    return MatchResult("UNMATCHED", None, None, [])


def enrich_record(
    record: dict[str, Any],
    match: MatchResult,
    manual: dict[str, str],
    relevance_rules: dict[str, Any],
    *,
    prior_season_profile: PFFPlayerProfile | None = None,
    prior_season: int | None = None,
    enable_prior_season_fallback: bool = False,
) -> dict[str, Any]:
    profile = match.profile
    usage = usage_summary(profile, record["week"]) if profile else empty_usage_summary()
    prior_usage = usage_summary(prior_season_profile, 99) if prior_season_profile else empty_usage_summary()
    pff_position = profile.primary_position() if profile else None
    position = resolve_position(
        pff_position=pff_position,
        source_position=record.get("source_position"),
        manual_position_override=manual.get("position_override"),
    )
    candidate = evaluate_candidate(
        record,
        position,
        usage,
        manual,
        relevance_rules,
        match,
        prior_usage=prior_usage,
        enable_prior_season_fallback=enable_prior_season_fallback,
    )
    current_snap_status = snap_data_status(usage)
    prior_snap_status = snap_data_status(prior_usage)
    participation_source_season = record.get("season")
    if (
        enable_prior_season_fallback
        and current_snap_status == "NO_DATA"
        and any(str(reason).startswith("prior_season_snap_pct=") for reason in candidate["candidate_reasons"])
        and prior_season is not None
    ):
        participation_source_season = prior_season
    out = dict(record)
    out.update(
        {
            "pff_player_id": profile.player_id if profile else None,
            "pff_player_name": profile.player_name if profile else None,
            "pff_position": position.pff_position,
            "canonical_position": position.canonical_position,
            "position_group": position.position_group,
            "position_source": position.position_source,
            "match_status": match.status,
            "match_method": match.method,
            "match_candidates": match.candidates,
            "pff_identity_status": identity_status(match),
            "snap_data_status": current_snap_status,
            "season_offensive_snaps": usage["season_offensive_snaps"],
            "season_defensive_snaps": usage["season_defensive_snaps"],
            "season_special_teams_snaps": usage["season_special_teams_snaps"],
            "season_relevant_snaps": usage["season_relevant_snaps"],
            "season_relevant_team_snaps": usage["season_relevant_team_snaps"],
            "season_relevant_snap_pct": usage["season_relevant_snap_pct"],
            "previous_game_offensive_snaps": usage["previous_game_offensive_snaps"],
            "previous_game_defensive_snaps": usage["previous_game_defensive_snaps"],
            "previous_game_special_teams_snaps": usage["previous_game_special_teams_snaps"],
            "previous_game_relevant_snap_pct": usage["previous_game_relevant_snap_pct"],
            "recent_healthy_snap_pct": usage["recent_healthy_snap_pct"],
            "games_appeared": usage["games_appeared"],
            "last_week_played": usage["last_week_played"],
            "primary_unit": usage["primary_unit"],
            "st_only": usage["st_only"],
            "prior_season": prior_season,
            "prior_season_snap_data_status": prior_snap_status,
            "prior_season_relevant_unit": prior_usage["primary_unit"],
            "prior_season_relevant_snap_pct": prior_usage["season_relevant_snap_pct"],
            "prior_season_team": "|".join(sorted(prior_season_profile.teams)) if prior_season_profile else None,
            "prior_season_games_appeared": prior_usage["games_appeared"],
            "prior_season_st_only": prior_usage["st_only"],
            "participation_source_season": participation_source_season,
            "key_candidate": candidate["key_candidate"],
            "candidate_reasons": candidate["candidate_reasons"],
            "out_doubtful_only_candidate": candidate["out_doubtful_only_candidate"],
            "manual_note": manual.get("manual_note") or None,
            "manual_publish": manual.get("publish") or None,
            "manual_position_override": manual.get("position_override") or None,
            "pff_enrichment_metadata": {
                "source": "pff_snap_participation_from_offense_defense_special_summaries",
                "pff_weeks_used": usage["weeks_used"],
                "snap_pct_method": "true relevant-unit player snaps divided by team unit snaps; recent healthy uses max of last three pre-current-week true relevant percentages",
            },
        }
    )
    return out


def usage_summary(profile: PFFPlayerProfile | None, current_week: int) -> dict[str, Any]:
    if profile is None:
        return empty_usage_summary()
    games = [profile.games[week] for week in sorted(profile.games) if week < current_week]
    if not games:
        return empty_usage_summary()
    position_group = resolve_position(pff_position=profile.primary_position()).position_group
    relevant_pcts = [relevant_pct(game, position_group) for game in games]
    available_pcts = [value for value in relevant_pcts if value is not None]
    previous = games[-1]
    previous_pct = relevant_pct(previous, position_group)
    recent_window = [value for value in available_pcts[-3:] if value is not None]
    relevant_snaps = [relevant_snaps_for_game(game, position_group) for game in games]
    relevant_denominators = [relevant_denominator_for_game(game, position_group) for game in games]
    season_relevant_snaps = sum(relevant_snaps)
    season_relevant_denominator = sum(relevant_denominators)
    season_pct = season_relevant_snaps / season_relevant_denominator if season_relevant_denominator else (max(available_pcts) if available_pcts else None)
    st_snaps = sum(game.special_teams_snaps for game in games)
    primary_unit = primary_unit_for_group(position_group)
    return {
        "season_offensive_snaps": sum(game.offensive_snaps for game in games),
        "season_defensive_snaps": sum(game.defensive_snaps for game in games),
        "season_special_teams_snaps": st_snaps,
        "season_relevant_snaps": season_relevant_snaps,
        "season_relevant_team_snaps": season_relevant_denominator,
        "season_relevant_snap_pct": season_pct,
        "previous_game_offensive_snaps": previous.offensive_snaps,
        "previous_game_defensive_snaps": previous.defensive_snaps,
        "previous_game_special_teams_snaps": previous.special_teams_snaps,
        "previous_game_relevant_snap_pct": previous_pct,
        "recent_healthy_snap_pct": max(recent_window) if recent_window else None,
        "games_appeared": sum(1 for game in games if game.offensive_snaps or game.defensive_snaps or game.special_teams_snaps),
        "last_week_played": max((game.week for game in games if game.offensive_snaps or game.defensive_snaps or game.special_teams_snaps), default=None),
        "primary_unit": primary_unit,
        "st_only": is_special_teams_only(games, position_group),
        "weeks_used": [game.week for game in games],
    }


def empty_usage_summary() -> dict[str, Any]:
    return {
        "season_offensive_snaps": None,
        "season_defensive_snaps": None,
        "season_special_teams_snaps": None,
        "season_relevant_snaps": None,
        "season_relevant_team_snaps": None,
        "season_relevant_snap_pct": None,
        "previous_game_offensive_snaps": None,
        "previous_game_defensive_snaps": None,
        "previous_game_special_teams_snaps": None,
        "previous_game_relevant_snap_pct": None,
        "recent_healthy_snap_pct": None,
        "games_appeared": 0,
        "last_week_played": None,
        "primary_unit": None,
        "st_only": False,
        "weeks_used": [],
    }


def relevant_pct(game: PFFGameUsage, position_group: str | None) -> float | None:
    if position_group in OFFENSE_GROUPS:
        return game.offensive_snap_pct
    if position_group in DEFENSE_GROUPS:
        return game.defensive_snap_pct
    return None


def relevant_snaps_for_game(game: PFFGameUsage, position_group: str | None) -> int:
    if position_group in OFFENSE_GROUPS:
        return game.offensive_snaps
    if position_group in DEFENSE_GROUPS:
        return game.defensive_snaps
    if position_group == "ST":
        return game.special_teams_snaps
    return 0


def relevant_denominator_for_game(game: PFFGameUsage, position_group: str | None) -> int:
    if position_group in OFFENSE_GROUPS:
        return game.team_offensive_snaps
    if position_group in DEFENSE_GROUPS:
        return game.team_defensive_snaps
    return 0


def primary_unit_for_group(position_group: str | None) -> str | None:
    if position_group in OFFENSE_GROUPS:
        return "offense"
    if position_group in DEFENSE_GROUPS:
        return "defense"
    if position_group == "ST":
        return "special_teams"
    return None


def is_special_teams_only(games: list[PFFGameUsage], position_group: str | None) -> bool:
    if position_group == "ST":
        return True
    offense = sum(game.offensive_snaps for game in games)
    defense = sum(game.defensive_snaps for game in games)
    special = sum(game.special_teams_snaps for game in games)
    return special > 0 and offense <= 3 and defense <= 3


def evaluate_candidate(
    record: dict[str, Any],
    position: Any,
    usage: dict[str, Any],
    manual: dict[str, str],
    relevance_rules: dict[str, Any],
    match: MatchResult,
    *,
    prior_usage: dict[str, Any] | None = None,
    enable_prior_season_fallback: bool = False,
) -> dict[str, Any]:
    publish = str(manual.get("publish") or "").strip().lower()
    if publish in {"include", "yes", "y", "true", "1", "publish"}:
        return {"key_candidate": True, "candidate_reasons": ["manual_include"], "out_doubtful_only_candidate": False}
    if publish in {"exclude", "no", "n", "false", "0"}:
        return {"key_candidate": False, "candidate_reasons": ["manual_exclude"], "out_doubtful_only_candidate": False}

    threshold = float(relevance_rules["candidate_rules"].get("season_snap_pct_threshold", 0.25))
    reasons: list[str] = []
    if position.position_group == "QB" and relevance_rules["candidate_rules"].get("qb_always_candidate", True):
        reasons.append("QB")
    for field_name, label in [
        ("season_relevant_snap_pct", "season_snap_pct"),
        ("recent_healthy_snap_pct", "recent_healthy_snap_pct"),
        ("previous_game_relevant_snap_pct", "previous_game_snap_pct"),
    ]:
        value = usage.get(field_name)
        if value is not None and value >= threshold:
            reasons.append(f"{label}={value * 100:.1f}")
    status = record.get("game_status")
    if status in {"Out", "Doubtful"} and relevance_rules["candidate_rules"].get("include_out_or_doubtful_players", True):
        reasons.append(f"game_status={status}")
    unmatched_reason = []
    if match.status == "UNMATCHED" and relevance_rules["review_flags"].get("flag_missing_pff_match", True):
        unmatched_reason.append("pff_unmatched")
    if match.status == "REVIEW_REQUIRED":
        reasons.append("pff_match_review_required")

    if usage.get("st_only") and relevance_rules["candidate_rules"].get("exclude_special_teams_by_default", True):
        return {"key_candidate": False, "candidate_reasons": ["special_teams_only"], "out_doubtful_only_candidate": False}
    prior_usage = prior_usage or empty_usage_summary()
    if (
        enable_prior_season_fallback
        and not reasons
        and snap_data_status(usage) == "NO_DATA"
        and not prior_usage.get("st_only")
    ):
        prior_pct = prior_usage.get("season_relevant_snap_pct")
        if prior_pct is not None and prior_pct >= threshold:
            reasons.append(f"prior_season_snap_pct={prior_pct * 100:.1f}")
    if reasons:
        non_status_reasons = [reason for reason in reasons if not reason.startswith("game_status=")]
        return {
            "key_candidate": True,
            "candidate_reasons": reasons + unmatched_reason,
            "out_doubtful_only_candidate": bool(reasons) and not non_status_reasons and bool([reason for reason in reasons if reason.startswith("game_status=")]),
        }
    return {"key_candidate": False, "candidate_reasons": unmatched_reason or ["low_role"], "out_doubtful_only_candidate": False}


def build_manifest(
    enriched: list[dict[str, Any]],
    *,
    comparison: list[dict[str, Any]],
    official_records: list[dict[str, Any]],
    run_dir: Path,
    season: int,
    week: int,
    through_week: int,
    index_json: Path,
    index_csv: Path,
) -> dict[str, Any]:
    match_counts = Counter(row["match_status"] for row in enriched)
    movement_counts = Counter(row["candidate_change"] for row in comparison)
    identity_counts = Counter(row["pff_identity_status"] for row in enriched)
    snap_counts = Counter(row["snap_data_status"] for row in enriched)
    team_quality: dict[str, Counter[str]] = defaultdict(Counter)
    for row in enriched:
        if row["match_status"] in {"UNMATCHED", "REVIEW_REQUIRED"}:
            team_quality[row["team"]][row["match_status"]] += 1
    return {
        "season": season,
        "week": week,
        "official_run_dir": str(run_dir),
        "official_record_count": len(official_records),
        "pff_processed_root": str(PFF_PROCESSED_ROOT),
        "pff_directory_root": str(PFF_DIRECTORY_ROOT),
        "pff_weeks_used": list(range(1, through_week + 1)),
        "pff_index_json": str(index_json),
        "pff_index_csv": str(index_csv),
        "enriched_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_meaningful_injured_players": len(enriched),
        "pff_matched": identity_counts["MATCHED"],
        "identity_matched": identity_counts["MATCHED"],
        "identity_unmatched": identity_counts["UNMATCHED"],
        "identity_review_required": identity_counts["REVIEW_REQUIRED"],
        "exact_matches": match_counts["EXACT"],
        "normalized_matches": match_counts["NORMALIZED"],
        "persisted_matches": match_counts["PERSISTED"],
        "review_required_matches": match_counts["REVIEW_REQUIRED"],
        "unmatched": match_counts["UNMATCHED"],
        "candidates": sum(1 for row in enriched if row["key_candidate"]),
        "non_candidates": sum(1 for row in enriched if not row["key_candidate"]),
        "identity_matched_with_offense_or_defense_snaps": snap_counts["OFFENSE_DEFENSE"],
        "identity_matched_with_st_only_snaps": snap_counts["ST_ONLY"],
        "identity_matched_with_no_current_season_snap_data": snap_counts["NO_DATA"],
        "players_with_true_offense_or_defense_snap_data": snap_counts["OFFENSE_DEFENSE"],
        "players_with_only_special_teams_snap_data": snap_counts["ST_ONLY"],
        "players_with_no_snap_data": snap_counts["NO_DATA"],
        "out_doubtful_only_candidates": sum(1 for row in enriched if row.get("out_doubtful_only_candidate")),
        "candidate_movement": dict(sorted(movement_counts.items())),
        "unmatched_or_review_required_by_team": {team: dict(counter) for team, counter in sorted(team_quality.items())},
    }


def write_enrichment_outputs(run_dir: Path, enriched: list[dict[str, Any]], manifest: dict[str, Any], comparison: list[dict[str, Any]]) -> None:
    (run_dir / "pff_enriched_injuries.json").write_text(
        json.dumps(enriched, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "pff_match_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_enriched_csv(run_dir / "pff_enriched_injuries.csv", enriched)
    (run_dir / "pff_enrichment_comparison.json").write_text(
        json.dumps(comparison, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_comparison_csv(run_dir / "pff_enrichment_comparison.csv", comparison)
    write_candidate_report(run_dir / "pff_candidate_report.md", enriched, manifest)


def write_enriched_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "team",
        "player_name",
        "source_position",
        "pff_player_id",
        "pff_player_name",
        "pff_position",
        "canonical_position",
        "position_group",
        "position_source",
        "match_status",
        "match_method",
        "pff_identity_status",
        "snap_data_status",
        "injury",
        "game_status",
        "season_offensive_snaps",
        "season_defensive_snaps",
        "season_special_teams_snaps",
        "season_relevant_snaps",
        "season_relevant_team_snaps",
        "season_relevant_snap_pct",
        "previous_game_offensive_snaps",
        "previous_game_defensive_snaps",
        "previous_game_special_teams_snaps",
        "previous_game_relevant_snap_pct",
        "recent_healthy_snap_pct",
        "games_appeared",
        "last_week_played",
        "primary_unit",
        "st_only",
        "key_candidate",
        "out_doubtful_only_candidate",
        "candidate_reasons",
        "manual_note",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            item = {column: row.get(column) for column in columns}
            item["candidate_reasons"] = "|".join(row.get("candidate_reasons") or [])
            writer.writerow(item)


def load_previous_enrichment(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "pff_enriched_injuries.json"
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def compare_enrichment_outputs(old_rows: list[dict[str, Any]], new_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    old_by_key = {(row.get("team"), row.get("normalized_player_name")): row for row in old_rows}
    comparison = []
    for new in new_rows:
        key = (new.get("team"), new.get("normalized_player_name"))
        old = old_by_key.get(key, {})
        old_candidate = old.get("key_candidate")
        new_candidate = new.get("key_candidate")
        if old_candidate is True and new_candidate is True:
            change = "YES_TO_YES"
        elif old_candidate is True and new_candidate is False:
            change = "YES_TO_NO"
        elif old_candidate is False and new_candidate is True:
            change = "NO_TO_YES"
        elif old_candidate is False and new_candidate is False:
            change = "NO_TO_NO"
        else:
            change = "NO_OLD_COMPARISON"
        comparison.append(
            {
                "team": new.get("team"),
                "player_name": new.get("player_name"),
                "normalized_player_name": new.get("normalized_player_name"),
                "old_match_status": old.get("match_status"),
                "new_match_status": new.get("match_status"),
                "old_candidate": old_candidate,
                "new_candidate": new_candidate,
                "candidate_change": change,
                "old_season_relevant_snap_pct": old.get("season_relevant_snap_pct"),
                "new_season_relevant_snap_pct": new.get("season_relevant_snap_pct"),
                "old_recent_healthy_snap_pct": old.get("recent_healthy_snap_pct"),
                "new_recent_healthy_snap_pct": new.get("recent_healthy_snap_pct"),
                "old_previous_game_relevant_snap_pct": old.get("previous_game_relevant_snap_pct"),
                "new_previous_game_relevant_snap_pct": new.get("previous_game_relevant_snap_pct"),
                "change_reason": compare_reason(old, new, change),
            }
        )
    return comparison


def compare_reason(old: dict[str, Any], new: dict[str, Any], change: str) -> str:
    reasons = []
    if old.get("match_status") != new.get("match_status"):
        reasons.append(f"match {old.get('match_status')}->{new.get('match_status')}")
    if old.get("pff_player_id") != new.get("pff_player_id"):
        reasons.append("identity changed")
    if old.get("season_relevant_snap_pct") != new.get("season_relevant_snap_pct"):
        reasons.append("season snap pct changed")
    if old.get("recent_healthy_snap_pct") != new.get("recent_healthy_snap_pct"):
        reasons.append("recent healthy changed")
    if change in {"YES_TO_NO", "NO_TO_YES"}:
        reasons.append("candidate changed")
    return "; ".join(reasons) or "unchanged"


def write_comparison_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "team",
        "player_name",
        "old_match_status",
        "new_match_status",
        "old_candidate",
        "new_candidate",
        "candidate_change",
        "old_season_relevant_snap_pct",
        "new_season_relevant_snap_pct",
        "old_recent_healthy_snap_pct",
        "new_recent_healthy_snap_pct",
        "old_previous_game_relevant_snap_pct",
        "new_previous_game_relevant_snap_pct",
        "change_reason",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) for column in columns})


def write_candidate_report(path: Path, rows: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    lines = [
        "# PFF Injury Enrichment Candidate Report",
        "",
        f"- Official meaningful players: {manifest['total_meaningful_injured_players']}",
        f"- PFF matched: {manifest['pff_matched']}",
        f"- Review required: {manifest['review_required_matches']}",
        f"- Unmatched: {manifest['unmatched']}",
        f"- Candidates: {manifest['candidates']}",
        f"- Non-candidates: {manifest['non_candidates']}",
        "",
    ]
    for team in sorted({row["team"] for row in rows}):
        lines.extend([f"## {team}", ""])
        team_rows = [row for row in rows if row["team"] == team]
        for group in sorted({row.get("position_group") or "UNKNOWN" for row in team_rows}):
            lines.extend([f"### {group}", ""])
            for row in sorted([item for item in team_rows if (item.get("position_group") or "UNKNOWN") == group], key=lambda item: item["player_name"]):
                candidate = "YES" if row["key_candidate"] else "NO"
                lines.extend(
                    [
                        f"- {row['player_name']}",
                        f"  - PFF: {row.get('pff_player_name') or 'unmatched'} / {row.get('pff_position') or 'unknown'}",
                        f"  - Match: {row['match_status']} ({row.get('match_method') or 'n/a'})",
                        f"  - Season snaps: off={row.get('season_offensive_snaps')} def={row.get('season_defensive_snaps')}",
                        f"  - Snap %: season={fmt_pct(row.get('season_relevant_snap_pct'))} previous={fmt_pct(row.get('previous_game_relevant_snap_pct'))} recent_healthy={fmt_pct(row.get('recent_healthy_snap_pct'))}",
                        f"  - Candidate: {candidate}",
                        f"  - Reason: {', '.join(row.get('candidate_reasons') or [])}",
                    ]
                )
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def profiles_by_normalized_name(profiles: dict[str, PFFPlayerProfile]) -> dict[str, list[PFFPlayerProfile]]:
    output: dict[str, list[PFFPlayerProfile]] = defaultdict(list)
    for profile in profiles.values():
        output[profile.normalized_player_name].append(profile)
        compact = compact_name(profile.normalized_player_name)
        if compact != profile.normalized_player_name:
            output[compact].append(profile)
    return output


def profiles_by_exact_normalized_name(profiles: dict[str, PFFPlayerProfile]) -> dict[str, list[PFFPlayerProfile]]:
    output: dict[str, list[PFFPlayerProfile]] = defaultdict(list)
    for profile in profiles.values():
        output[profile.normalized_player_name].append(profile)
        compact = compact_name(profile.normalized_player_name)
        if compact != profile.normalized_player_name:
            output[compact].append(profile)
    return output


def profiles_by_alias(profiles: dict[str, PFFPlayerProfile]) -> dict[str, list[PFFPlayerProfile]]:
    output: dict[str, list[PFFPlayerProfile]] = defaultdict(list)
    for profile in profiles.values():
        for alias in profile.aliases:
            output[alias].append(profile)
            compact = compact_name(alias)
            if compact != alias:
                output[compact].append(profile)
    return output


def exact_lookup(index: dict[str, list[PFFPlayerProfile]], norm: str) -> list[PFFPlayerProfile]:
    matches = index.get(norm, [])
    if not matches:
        matches = index.get(compact_name(norm), [])
    return dedupe_profiles(matches)


def dedupe_profiles(profiles: list[PFFPlayerProfile]) -> list[PFFPlayerProfile]:
    output: dict[str, PFFPlayerProfile] = {}
    for profile in profiles:
        output[profile.player_id] = profile
    return list(output.values())


def candidate_dicts(profiles: list[PFFPlayerProfile]) -> list[dict[str, Any]]:
    return [
        {
            "pff_player_id": profile.player_id,
            "pff_player_name": profile.player_name,
            "teams": sorted(profile.teams),
            "positions": dict(profile.positions),
            "aliases": sorted(profile.aliases),
            "identity_sources": sorted(profile.identity_sources),
        }
        for profile in sorted(profiles, key=lambda item: int(item.player_id))
    ]


def identity_status(match: MatchResult) -> str:
    if match.status in {"PERSISTED", "EXACT", "NORMALIZED"}:
        return "MATCHED"
    if match.status == "REVIEW_REQUIRED":
        return "REVIEW_REQUIRED"
    return "UNMATCHED"


def snap_data_status(usage: dict[str, Any]) -> str:
    offense = usage.get("season_offensive_snaps")
    defense = usage.get("season_defensive_snaps")
    special = usage.get("season_special_teams_snaps")
    if offense is None and defense is None and special is None:
        return "NO_DATA"
    if (offense or 0) > 0 or (defense or 0) > 0:
        return "OFFENSE_DEFENSE"
    if (special or 0) > 0:
        return "ST_ONLY"
    return "NO_DATA"


def load_persisted_mappings(path: Path = PFF_MAPPING_PATH) -> dict[tuple[str, str], str]:
    if not path.exists():
        return {}
    output = {}
    for row in read_csv_dicts(path):
        team = normalize_team(row.get("team"))
        player = normalize_player_name(row.get("official_player"))
        pff_id = clean_id(row.get("pff_player_id"))
        if team and player and pff_id:
            output[(team, player)] = pff_id
    return output


def compact_name(value: str) -> str:
    return str(value).replace(" ", "")


def split_pipe(value: Any) -> list[str]:
    return [item.strip() for item in str(value or "").split("|") if item.strip()]


def load_manual_override_map() -> dict[tuple[str, str], dict[str, str]]:
    output = {}
    for row in load_manual_overrides():
        team = normalize_team(row.get("team"))
        player = normalize_player_name(row.get("player"))
        if team and player:
            output[(team, player)] = row
    return output


def read_csv_dicts(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.1f}%"


def clean_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(".0"):
        text = text[:-2]
    return text


def clean_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def clean_position(value: Any) -> str | None:
    text = clean_text(value).upper()
    return text or None


def int_number(value: Any) -> int:
    try:
        if value is None or str(value).strip() == "":
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def pct(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number > 1:
        return number / 100.0
    return number


def max_optional(left: float | None, right: float | None) -> float | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)
