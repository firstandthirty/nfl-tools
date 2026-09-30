from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
MANUAL_DIR = PROJECT_ROOT / "data" / "manual"

OVERRIDES_COLUMNS = ["team", "player", "publish", "manual_note", "position_override"]
MANUAL_PLAYERS_COLUMNS = [
    "season",
    "week",
    "team",
    "player",
    "source_position",
    "injury",
    "roster_status",
    "game_status",
    "manual_note",
    "publish",
    "position_override",
]

NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


@dataclass(frozen=True)
class PositionResolution:
    pff_position: str | None
    source_position: str | None
    canonical_position: str | None
    position_group: str | None
    position_source: str | None


@dataclass
class InjuryPlayerRecord:
    season: int
    week: int
    player_name: str
    team: str
    normalized_player_name: str | None = None
    pff_player_id: str | None = None
    pff_position: str | None = None
    source_position: str | None = None
    canonical_position: str | None = None
    position_group: str | None = None
    position_source: str | None = None
    injury: str | None = None
    roster_status: str | None = None
    game_status: str | None = None
    practice_wed: str | None = None
    practice_thu: str | None = None
    practice_fri: str | None = None
    practice_sat: str | None = None
    ir_date: str | date | None = None
    last_played_week: int | None = None
    games_missed: int | None = None
    season_snap_pct: float | None = None
    previous_game_snap_pct: float | None = None
    key_candidate: bool | None = None
    publish: bool | None = None
    latest_news: str | None = None
    latest_news_date: str | date | datetime | None = None
    manual_note: str | None = None
    manual_override: dict[str, Any] | None = None
    source_metadata: dict[str, Any] = field(default_factory=dict)
    fetched_at: str | datetime | None = None

    def __post_init__(self) -> None:
        self.team = validate_team_abbr(self.team)
        if self.normalized_player_name is None:
            self.normalized_player_name = normalize_player_name(self.player_name)

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


def load_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_teams(path: Path | str | None = None) -> list[dict[str, Any]]:
    teams = load_json(path or CONFIG_DIR / "teams.json")
    validate_teams(teams)
    return teams


def team_abbreviations(path: Path | str | None = None) -> set[str]:
    return {team["abbr"] for team in load_teams(path)}


def validate_team_abbr(value: str, teams_path: Path | str | None = None) -> str:
    abbr = str(value).strip().upper()
    if abbr not in team_abbreviations(teams_path):
        raise ValueError(f"Unknown team abbreviation: {value!r}")
    return abbr


def validate_teams(teams: list[dict[str, Any]]) -> None:
    if len(teams) != 32:
        raise ValueError(f"Expected exactly 32 teams, found {len(teams)}.")
    abbreviations = [str(team.get("abbr", "")).strip().upper() for team in teams]
    if len(set(abbreviations)) != 32:
        raise ValueError("Team abbreviations must be unique.")
    for team in teams:
        for column in ["abbr", "full_name", "injury_report_url", "roster_url"]:
            if not str(team.get(column, "")).strip():
                raise ValueError(f"Team entry missing {column}: {team}")


def load_position_config(path: Path | str | None = None) -> dict[str, Any]:
    return load_json(path or CONFIG_DIR / "position_groups.json")


def clean_position(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def resolve_position(
    *,
    pff_position: Any = None,
    source_position: Any = None,
    manual_position_override: Any = None,
    position_config: dict[str, Any] | None = None,
) -> PositionResolution:
    config = position_config or load_position_config()
    manual = clean_position(manual_position_override)
    pff = clean_position(pff_position)
    source = clean_position(source_position)

    if manual:
        canonical = manual
        source_label = "manual"
        mapping_name = "official_fallback_mappings"
    elif pff:
        canonical = pff
        source_label = "pff"
        mapping_name = "pff_mappings"
    elif source:
        canonical = source
        source_label = "official_team"
        mapping_name = "official_fallback_mappings"
    else:
        canonical = None
        source_label = None
        mapping_name = "official_fallback_mappings"

    group = None
    if canonical:
        group = config[mapping_name].get(canonical)

    return PositionResolution(
        pff_position=pff,
        source_position=source,
        canonical_position=canonical,
        position_group=group,
        position_source=source_label,
    )


def normalize_player_name(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value).strip().lower())
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    parts = text.split()
    while parts and parts[-1] in NAME_SUFFIXES:
        parts.pop()
    return " ".join(parts)


def load_manual_overrides(path: Path | str | None = None) -> list[dict[str, str]]:
    return load_manual_csv(path or MANUAL_DIR / "overrides.csv", OVERRIDES_COLUMNS)


def load_manual_players(path: Path | str | None = None) -> list[dict[str, str]]:
    return load_manual_csv(path or MANUAL_DIR / "manual_players.csv", MANUAL_PLAYERS_COLUMNS)


def load_manual_csv(path: Path | str, required_columns: list[str]) -> list[dict[str, str]]:
    csv_path = Path(path)
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        missing = [column for column in required_columns if column not in fieldnames]
        if missing:
            raise ValueError(f"{csv_path} missing required columns: {missing}")
        return [dict(row) for row in reader]


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value
