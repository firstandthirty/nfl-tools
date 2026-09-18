from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import week_status_path


@dataclass(frozen=True)
class WeekCompleteness:
    season: int
    week: int
    checked_at: str
    total_games: int
    games_with_stats: int
    games_without_stats: int
    is_complete: bool
    incomplete_game_ids: list[int]
    incomplete_matchups: list[str]
    data_fetched_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "week": self.week,
            "checked_at": self.checked_at,
            "total_games": self.total_games,
            "games_with_stats": self.games_with_stats,
            "games_without_stats": self.games_without_stats,
            "is_complete": self.is_complete,
            "incomplete_game_ids": self.incomplete_game_ids,
            "incomplete_matchups": self.incomplete_matchups,
            "data_fetched_at": self.data_fetched_at,
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def completeness_from_games_body(
    body: Any,
    *,
    season: int,
    week: int,
    checked_at: str | None = None,
    data_fetched_at: str | None = None,
) -> WeekCompleteness:
    rows = _extract_games(body)
    incomplete = [row for row in rows if row.get("has_stats") is not True]
    return WeekCompleteness(
        season=season,
        week=week,
        checked_at=checked_at or utc_now(),
        total_games=len(rows),
        games_with_stats=len(rows) - len(incomplete),
        games_without_stats=len(incomplete),
        is_complete=len(rows) > 0 and not incomplete,
        incomplete_game_ids=[int(row["id"]) for row in incomplete if row.get("id") is not None],
        incomplete_matchups=[_matchup(row) for row in incomplete],
        data_fetched_at=data_fetched_at,
    )


def read_week_status(season: int, week: int, *, path: Path | None = None) -> WeekCompleteness | None:
    status_path = path or week_status_path(season, week)
    if not status_path.exists():
        return None
    data = json.loads(status_path.read_text(encoding="utf-8"))
    return WeekCompleteness(
        season=int(data["season"]),
        week=int(data["week"]),
        checked_at=str(data["checked_at"]),
        total_games=int(data["total_games"]),
        games_with_stats=int(data["games_with_stats"]),
        games_without_stats=int(data["games_without_stats"]),
        is_complete=bool(data["is_complete"]),
        incomplete_game_ids=[int(value) for value in data.get("incomplete_game_ids", [])],
        incomplete_matchups=[str(value) for value in data.get("incomplete_matchups", [])],
        data_fetched_at=data.get("data_fetched_at"),
    )


def write_week_status(status: WeekCompleteness, *, path: Path | None = None) -> Path:
    status_path = path or week_status_path(status.season, status.week)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return status_path


def status_summary(status: WeekCompleteness) -> str:
    return f"{status.games_with_stats}/{status.total_games} games have stats"


def assert_finalized_week(season: int, week: int, *, allow_incomplete: bool = False) -> WeekCompleteness:
    status = read_week_status(season, week)
    if status is None:
        raise RuntimeError(
            f"Week {week} PFF completeness metadata is missing. "
            "Run scripts/fetch_week.py before building publishable outputs."
        )
    if not status.is_complete and not allow_incomplete:
        raise RuntimeError(
            f"Week {week} PFF data is incomplete ({status_summary(status)}). "
            "Run fetch_week.py again after PFF processes the remaining game."
        )
    return status


def decide_cache_policy(
    *,
    refresh: bool,
    all_cache_exists: bool,
    saved_status: WeekCompleteness | None,
    cached_games_status: WeekCompleteness | None,
    current_games_status: WeekCompleteness | None = None,
) -> str:
    if refresh:
        return "refresh_all"
    if not all_cache_exists:
        return "fetch_all"

    previous = saved_status or cached_games_status
    if previous is not None and previous.is_complete:
        return "reuse_finalized"

    if current_games_status is None:
        return "check_current_games"
    if current_games_status.is_complete:
        return "refresh_all_finalized"
    return "reuse_provisional"


def _extract_games(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        return []
    rows = body.get("games", [])
    return [row for row in rows if isinstance(row, dict)]


def _matchup(row: dict[str, Any]) -> str:
    home = _team_abbreviation(row.get("home_team"))
    away = _team_abbreviation(row.get("away_team"))
    if home and away:
        return f"{home} vs {away}"
    game_id = row.get("id", "unknown")
    return f"game {game_id}"


def _team_abbreviation(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("abbreviation") or value.get("display_abbreviation") or value.get("slug")
    if value is None:
        return None
    return str(value)
