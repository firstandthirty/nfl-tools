from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .injury_schema import load_teams, validate_team_abbr


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent

DEFAULT_SCHEDULE_PATHS = [
    REPO_ROOT / "player_props" / "data" / "processed" / "game_context.csv",
    REPO_ROOT
    / "power_rankings"
    / "data"
    / "analysis"
    / "power_ratings"
    / "2026"
    / "market_diagnostics"
    / "week_03"
    / "future_board_inventory"
    / "future_games_inventory.csv",
]

TEAM_ALIASES = {
    "ARI": "ARI",
    "ARZ": "ARI",
    "ATL": "ATL",
    "BAL": "BAL",
    "BLT": "BAL",
    "BUF": "BUF",
    "CAR": "CAR",
    "CHI": "CHI",
    "CIN": "CIN",
    "CLE": "CLE",
    "CLV": "CLE",
    "DAL": "DAL",
    "DEN": "DEN",
    "DET": "DET",
    "GB": "GB",
    "GNB": "GB",
    "HOU": "HOU",
    "HST": "HOU",
    "IND": "IND",
    "JAX": "JAX",
    "JAC": "JAX",
    "KC": "KC",
    "KAN": "KC",
    "LA": "LAR",
    "LAR": "LAR",
    "LAC": "LAC",
    "LV": "LV",
    "MIA": "MIA",
    "MIN": "MIN",
    "NE": "NE",
    "NWE": "NE",
    "NO": "NO",
    "NOR": "NO",
    "NYG": "NYG",
    "NYJ": "NYJ",
    "PHI": "PHI",
    "PIT": "PIT",
    "SEA": "SEA",
    "SF": "SF",
    "SFO": "SF",
    "TB": "TB",
    "TAM": "TB",
    "TEN": "TEN",
    "WAS": "WAS",
    "WSH": "WAS",
}


@dataclass(frozen=True)
class ScheduleGameContext:
    season: int
    week: int
    team: str
    opponent: str
    home_away: str
    game_date: str | None
    kickoff: str | None
    schedule_source: str
    home_team: str
    away_team: str


def normalize_team(value: Any, *, teams: list[dict[str, Any]] | None = None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    upper = text.upper()
    if upper in TEAM_ALIASES:
        return TEAM_ALIASES[upper]

    all_teams = teams or load_teams()
    lowered = text.lower()
    for team in all_teams:
        labels = [team["abbr"], team["full_name"], *team.get("aliases", [])]
        if lowered in {str(label).strip().lower() for label in labels}:
            return team["abbr"]
    return None


def load_schedule_context(
    *,
    paths: list[Path] | None = None,
    teams: list[dict[str, Any]] | None = None,
) -> list[ScheduleGameContext]:
    all_teams = teams or load_teams()
    games: list[ScheduleGameContext] = []
    for path in paths or DEFAULT_SCHEDULE_PATHS:
        if not path.exists():
            continue
        games.extend(_load_file(path, teams=all_teams))
    return games


def schedule_for_team(
    season: int,
    week: int,
    team: str,
    *,
    contexts: list[ScheduleGameContext] | None = None,
    paths: list[Path] | None = None,
    teams: list[dict[str, Any]] | None = None,
) -> ScheduleGameContext | None:
    team = validate_team_abbr(team)
    candidates = contexts if contexts is not None else load_schedule_context(paths=paths, teams=teams)
    matches = [
        game
        for game in candidates
        if game.season == int(season) and game.week == int(week) and game.team == team
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda game: _source_priority(game.schedule_source))[0]


def _source_priority(source: str) -> int:
    if "player_props" in source:
        return 0
    if "future_games_inventory" in source:
        return 1
    return 9


def _load_file(path: Path, *, teams: list[dict[str, Any]]) -> list[ScheduleGameContext]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    output: list[ScheduleGameContext] = []
    for row in rows:
        if {"season", "week", "home_team_abbr", "away_team_abbr"}.issubset(row):
            output.extend(_contexts_from_row(row, path=path, teams=teams, home_key="home_team_abbr", away_key="away_team_abbr"))
        elif {"week", "home_team", "away_team"}.issubset(row):
            output.extend(_contexts_from_row(row, path=path, teams=teams, home_key="home_team", away_key="away_team"))
    return output


def _contexts_from_row(
    row: dict[str, str],
    *,
    path: Path,
    teams: list[dict[str, Any]],
    home_key: str,
    away_key: str,
) -> list[ScheduleGameContext]:
    home = normalize_team(row.get(home_key), teams=teams)
    away = normalize_team(row.get(away_key), teams=teams)
    if home is None or away is None:
        return []
    try:
        season = int(row.get("season") or _season_from_path(path))
        week = int(row["week"])
    except (TypeError, ValueError):
        return []
    kickoff = row.get("commence_time") or None
    game_date = row.get("gameday") or _date_from_kickoff(kickoff)
    source = str(path)
    return [
        ScheduleGameContext(
            season=season,
            week=week,
            team=home,
            opponent=away,
            home_away="HOME",
            game_date=game_date,
            kickoff=kickoff,
            schedule_source=source,
            home_team=home,
            away_team=away,
        ),
        ScheduleGameContext(
            season=season,
            week=week,
            team=away,
            opponent=home,
            home_away="AWAY",
            game_date=game_date,
            kickoff=kickoff,
            schedule_source=source,
            home_team=home,
            away_team=away,
        ),
    ]


def _season_from_path(path: Path) -> int | None:
    for part in reversed(path.parts):
        if part.isdigit() and len(part) == 4:
            return int(part)
    return None


def _date_from_kickoff(kickoff: str | None) -> str | None:
    if not kickoff:
        return None
    if "T" in kickoff:
        return kickoff.split("T", 1)[0]
    return kickoff[:10] or None
