from __future__ import annotations

import re
from typing import Any

import pandas as pd


COMMON_RENAMES = {
    "player": "player_name",
    "id": "game_id",
    "home_franchise_id": "home_team_id",
    "away_franchise_id": "away_team_id",
}

DATASET_RENAMES = {
    "pass_blocking": {
        "snap_counts_pass_block": "pass_block_snaps",
        "pbe": "pass_blocking_efficiency",
    },
    "pass_rush": {
        "snap_counts_pass_rush": "pass_rush_snaps",
        "prp": "pass_rush_productivity",
    },
    "run_defense": {
        "snap_counts_run": "run_defense_snaps",
        "stop_percent": "run_stop_percent",
    },
    "coverage": {
        "snap_counts_coverage": "coverage_snaps",
        "qb_rating_against": "passer_rating_when_targeted",
        "touchdowns": "touchdowns_allowed",
    },
}


def snake_case(value: str) -> str:
    text = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", str(value))
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return text.lower()


def extract_table(body: Any, preferred_table: str | None = None) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(body, dict):
        return "", []
    if preferred_table and isinstance(body.get(preferred_table), list):
        return preferred_table, body[preferred_table]
    for key, value in body.items():
        if isinstance(value, list):
            rows = [row for row in value if isinstance(row, dict)]
            return key, rows
    return "", []


def normalize_rows(
    dataset: str,
    body: Any,
    *,
    table: str | None = None,
    season: int | None = None,
    week: int | None = None,
    team_games: dict[str, dict[str, Any]] | None = None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    raw_table, rows = extract_table(body, table)
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(), {}
    original_columns = list(df.columns)
    df.columns = [snake_case(col) for col in df.columns]
    if dataset == "games":
        df = flatten_games(df)
    rename_map = {snake_case(src): dst for src, dst in COMMON_RENAMES.items()}
    rename_map.update({snake_case(src): dst for src, dst in DATASET_RENAMES.get(dataset, {}).items()})
    df = df.rename(columns={src: dst for src, dst in rename_map.items() if src in df.columns})
    column_map = {raw: df_col for raw, df_col in zip(original_columns, [snake_case(col) for col in original_columns])}
    for raw, normalized in COMMON_RENAMES.items():
        if snake_case(raw) in column_map.values():
            column_map[raw] = normalized
    for raw, normalized in DATASET_RENAMES.get(dataset, {}).items():
        column_map[raw] = normalized
    if "player_id" not in df.columns and "playerid" in df.columns:
        df = df.rename(columns={"playerid": "player_id"})
    if season is not None and "season" not in df.columns:
        df["season"] = season
    if week is not None and "week" not in df.columns:
        df["week"] = week
    if dataset != "games" and team_games:
        df = add_team_game_context(df, team_games)
    df = add_derived_fields(dataset, coerce_numeric(df))
    return order_columns(df), column_map


def coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for column in out.columns:
        if column in {"player_name", "team", "team_name", "position", "home_team", "away_team", "opponent", "start", "score"}:
            continue
        converted = pd.to_numeric(out[column], errors="coerce")
        if out[column].notna().sum() == 0 or converted.notna().sum() > 0:
            out[column] = converted
    return out


def flatten_games(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for side in ["home_team", "away_team"]:
        if side in out.columns:
            out[f"{side}_name"] = out[side].map(_team_name)
            out[f"{side}_slug"] = out[side].map(lambda value: value.get("slug") if isinstance(value, dict) else None)
            out[side] = out[side].map(_team_abbreviation)
    if "score" in out.columns:
        out["home_score"] = out["score"].map(lambda value: value.get("home_team") if isinstance(value, dict) else None)
        out["away_score"] = out["score"].map(lambda value: value.get("away_team") if isinstance(value, dict) else None)
    return out


def _team_abbreviation(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("abbreviation") or value.get("display_abbreviation") or value.get("slug")
    return value


def _team_name(value: Any) -> Any:
    if isinstance(value, dict):
        city = value.get("city")
        nickname = value.get("nickname")
        if city and nickname:
            return f"{city} {nickname}"
        return nickname or city or value.get("slug")
    return value


def add_team_game_context(df: pd.DataFrame, team_games: dict[str, dict[str, Any]]) -> pd.DataFrame:
    out = df.copy()
    if "team" not in out.columns:
        return out
    out["opponent"] = out["team"].map(lambda team: team_games.get(str(team), {}).get("opponent"))
    out["game_id"] = out["team"].map(lambda team: team_games.get(str(team), {}).get("game_id"))
    return out


def build_team_games(games: pd.DataFrame) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    if games.empty or not {"home_team", "away_team", "game_id"}.issubset(games.columns):
        return mapping
    for row in games.to_dict("records"):
        home = row.get("home_team")
        away = row.get("away_team")
        if home:
            mapping[str(home)] = {"opponent": away, "game_id": row.get("game_id")}
        if away:
            mapping[str(away)] = {"opponent": home, "game_id": row.get("game_id")}
    return mapping


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denom = pd.to_numeric(denominator, errors="coerce")
    num = pd.to_numeric(numerator, errors="coerce")
    return num.where(denom > 0) / denom.where(denom > 0)


def add_derived_fields(dataset: str, df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "draft_season" in out.columns and "season" in out.columns:
        out["rookie"] = pd.to_numeric(out["draft_season"], errors="coerce") == pd.to_numeric(out["season"], errors="coerce")
    if dataset == "rushing" and {"yards_after_contact", "attempts"}.issubset(out.columns):
        out["yards_after_contact_per_attempt"] = safe_divide(out["yards_after_contact"], out["attempts"])
    if dataset == "receiving" and {"targets", "routes"}.issubset(out.columns):
        out["targets_per_route_run"] = safe_divide(out["targets"], out["routes"])
    if dataset == "pass_blocking" and {"pressures_allowed", "pass_block_snaps"}.issubset(out.columns):
        out["pressure_rate_allowed"] = safe_divide(out["pressures_allowed"], out["pass_block_snaps"])
    if dataset == "pass_rush" and {"total_pressures", "pass_rush_snaps"}.issubset(out.columns):
        out["pressure_rate"] = safe_divide(out["total_pressures"], out["pass_rush_snaps"])
    if dataset == "run_defense" and {"stops", "run_defense_snaps"}.issubset(out.columns):
        out["run_stop_rate"] = safe_divide(out["stops"], out["run_defense_snaps"])
    if dataset == "coverage" and {"forced_incompletes", "targets"}.issubset(out.columns):
        out["forced_incompletion_rate_derived"] = safe_divide(out["forced_incompletes"], out["targets"])
    return out


def order_columns(df: pd.DataFrame) -> pd.DataFrame:
    preferred = [
        "season",
        "week",
        "game_id",
        "player_id",
        "player_name",
        "team",
        "opponent",
        "position",
        "draft_season",
        "rookie",
    ]
    cols = [col for col in preferred if col in df.columns]
    cols.extend(col for col in df.columns if col not in cols)
    return df[cols]
