from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .paths import processed_week_dir


ST_SNAP_COLUMNS = [
    "snap_counts_field_goal",
    "snap_counts_field_goal_blocking",
    "snap_counts_kickoff",
    "snap_counts_kickoff_return",
    "snap_counts_punt_coverage",
    "snap_counts_punt_return",
]


def build_week_snap_participation(season: int, week: int) -> pd.DataFrame:
    week_dir = processed_week_dir(season, week)
    offense = read_optional_csv(week_dir / "offense_summary.csv")
    defense = read_optional_csv(week_dir / "defense_summary.csv")
    special = read_optional_csv(week_dir / "special_summary.csv")

    keys: dict[tuple[int, str], dict[str, Any]] = {}
    merge_unit(keys, offense, unit="offense")
    merge_unit(keys, defense, unit="defense")
    merge_unit(keys, special, unit="special")
    rows = list(keys.values())
    if not rows:
        return pd.DataFrame()
    for row in rows:
        if isinstance(row.get("source_datasets"), set):
            row["source_datasets"] = "|".join(sorted(row["source_datasets"]))
    out = pd.DataFrame(rows)
    for column in [
        "offensive_snaps",
        "defensive_snaps",
        "special_teams_snaps",
        "team_offensive_snaps",
        "team_defensive_snaps",
    ]:
        if column not in out.columns:
            out[column] = 0
        out[column] = pd.to_numeric(out[column], errors="coerce").fillna(0).astype(int)
    out["offensive_snap_pct"] = safe_divide(out["offensive_snaps"], out["team_offensive_snaps"])
    out["defensive_snap_pct"] = safe_divide(out["defensive_snaps"], out["team_defensive_snaps"])
    out["special_teams_snap_pct"] = pd.NA
    for column in ["season", "week", "game_id", "player_id"]:
        out[column] = pd.to_numeric(out[column], errors="coerce").astype("Int64")
    return out[ordered_columns(out)].sort_values(["team", "player_name", "week"]).reset_index(drop=True)


def write_week_snap_participation(season: int, week: int) -> Path:
    out = build_week_snap_participation(season, week)
    path = processed_week_dir(season, week) / "snap_participation.csv"
    out.to_csv(path, index=False)
    return path


def read_optional_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def merge_unit(keys: dict[tuple[int, str], dict[str, Any]], df: pd.DataFrame, *, unit: str) -> None:
    if df.empty:
        return
    frame = df.copy()
    frame["team"] = frame["team"].map(normalize_team)
    if unit == "offense":
        frame["unit_snaps"] = pd.to_numeric(frame.get("snap_counts_total", 0), errors="coerce").fillna(0)
        frame["team_unit_snaps"] = frame.groupby(["game_id", "team"])["unit_snaps"].transform("max")
    elif unit == "defense":
        frame["unit_snaps"] = pd.to_numeric(frame.get("snap_counts_defense", 0), errors="coerce").fillna(0)
        frame["team_unit_snaps"] = frame.groupby(["game_id", "team"])["unit_snaps"].transform("max")
    else:
        present = [column for column in ST_SNAP_COLUMNS if column in frame.columns]
        frame["unit_snaps"] = frame[present].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1) if present else 0
        frame["team_unit_snaps"] = pd.NA
    for row in frame.to_dict("records"):
        player_id = int(row["player_id"])
        key = (player_id, str(row.get("game_id")))
        item = keys.setdefault(
            key,
            {
                "season": int(row["season"]),
                "week": int(row["week"]),
                "game_id": row.get("game_id"),
                "player_id": player_id,
                "player_name": row.get("player_name"),
                "team": row.get("team"),
                "opponent": normalize_team(row.get("opponent")),
                "pff_position": row.get("position"),
                "offensive_snaps": 0,
                "defensive_snaps": 0,
                "special_teams_snaps": 0,
                "team_offensive_snaps": 0,
                "team_defensive_snaps": 0,
                "source_datasets": set(),
            },
        )
        item["source_datasets"].add(f"{unit}_summary")
        if unit == "offense":
            item["offensive_snaps"] = max(item["offensive_snaps"], int(row.get("unit_snaps") or 0))
            item["team_offensive_snaps"] = max(item["team_offensive_snaps"], int(row.get("team_unit_snaps") or 0))
        elif unit == "defense":
            item["defensive_snaps"] = max(item["defensive_snaps"], int(row.get("unit_snaps") or 0))
            item["team_defensive_snaps"] = max(item["team_defensive_snaps"], int(row.get("team_unit_snaps") or 0))
        else:
            item["special_teams_snaps"] = max(item["special_teams_snaps"], int(row.get("unit_snaps") or 0))


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    num = pd.to_numeric(numerator, errors="coerce")
    den = pd.to_numeric(denominator, errors="coerce")
    return num.where(den > 0) / den.where(den > 0)


def normalize_team(value: Any) -> Any:
    aliases = {"BLT": "BAL", "HST": "HOU", "LA": "LAR", "WSH": "WAS"}
    if value is None or pd.isna(value):
        return value
    text = str(value).strip().upper()
    return aliases.get(text, text)


def ordered_columns(df: pd.DataFrame) -> list[str]:
    preferred = [
        "season",
        "week",
        "game_id",
        "player_id",
        "player_name",
        "team",
        "opponent",
        "pff_position",
        "offensive_snaps",
        "offensive_snap_pct",
        "defensive_snaps",
        "defensive_snap_pct",
        "special_teams_snaps",
        "special_teams_snap_pct",
        "team_offensive_snaps",
        "team_defensive_snaps",
        "source_datasets",
    ]
    return [column for column in preferred if column in df.columns] + [column for column in df.columns if column not in preferred]
