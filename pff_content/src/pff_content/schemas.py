from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .datasets import DATASETS
from .normalize import normalize_rows


@dataclass(frozen=True)
class ValidationFinding:
    dataset: str
    severity: str
    notes: str


def schema_inventory_row(dataset: str, endpoint: str, raw_field: str, normalized_field: str, series: pd.Series, row_count: int) -> dict[str, Any]:
    non_null = int(series.notna().sum())
    example = ""
    if non_null:
        example = series.dropna().iloc[0]
    return {
        "dataset": dataset,
        "endpoint": endpoint,
        "raw_field": raw_field,
        "normalized_field": normalized_field,
        "dtype": str(series.dtype),
        "example_value": example,
        "non_null_count": non_null,
        "row_count": row_count,
        "notes": "",
    }


def build_schema_inventory(processed: dict[str, pd.DataFrame], column_maps: dict[str, dict[str, str]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    endpoints = {spec.name: spec.endpoint for spec in DATASETS}
    for dataset, df in processed.items():
        reverse = {normalized: raw for raw, normalized in column_maps.get(dataset, {}).items()}
        for column in df.columns:
            rows.append(
                schema_inventory_row(
                    dataset,
                    endpoints.get(dataset, ""),
                    reverse.get(column, column),
                    column,
                    df[column],
                    len(df),
                )
            )
    return pd.DataFrame(rows)


def validation_report(processed: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for dataset, df in processed.items():
        player_key = ["season", "week", "player_id"] if {"season", "week", "player_id"}.issubset(df.columns) else []
        if dataset == "games":
            player_key = ["season", "week", "game_id"] if {"season", "week", "game_id"}.issubset(df.columns) else []
        duplicate_key_rows = int(df.duplicated(player_key).sum()) if player_key else 0
        notes = collect_validation_notes(dataset, df)
        rows.append(
            {
                "dataset": dataset,
                "row_count": len(df),
                "unique_players": int(df["player_id"].nunique(dropna=True)) if "player_id" in df.columns else 0,
                "unique_teams": int(df["team"].nunique(dropna=True)) if "team" in df.columns else _game_team_count(df),
                "missing_player_id": int(df["player_id"].isna().sum()) if "player_id" in df.columns else 0,
                "missing_team": int(df["team"].isna().sum()) if "team" in df.columns else 0,
                "duplicate_key_rows": duplicate_key_rows,
                "notes": "; ".join(notes) if notes else "INFO: checks passed",
            }
        )
    return pd.DataFrame(rows)


def collect_validation_notes(dataset: str, df: pd.DataFrame) -> list[str]:
    notes: list[str] = []
    if df.empty:
        return ["ERROR: empty table"]
    team_count = int(df["team"].nunique(dropna=True)) if "team" in df.columns else _game_team_count(df)
    if team_count and not 20 <= team_count <= 40:
        notes.append(f"WARNING: unusual team count {team_count}")
    for column in [col for col in df.columns if _is_snap_count_column(col)]:
        if pd.to_numeric(df[column], errors="coerce").lt(0).any():
            notes.append(f"ERROR: negative snap count in {column}")
    for column in [col for col in df.columns if "percent" in col or col.endswith("_rate")]:
        values = pd.to_numeric(df[column], errors="coerce").dropna()
        if not values.empty and (values.lt(0).any() or values.gt(100).any() and values.gt(1).all()):
            notes.append(f"WARNING: unusual rate range in {column}")
    if {"receptions", "targets"}.issubset(df.columns):
        bad = pd.to_numeric(df["receptions"], errors="coerce") > pd.to_numeric(df["targets"], errors="coerce")
        if bool(bad.any()):
            notes.append("ERROR: receptions exceed targets")
    if dataset == "pass_rush" and {"pass_rush_wins", "pass_rush_snaps"}.issubset(df.columns):
        bad = pd.to_numeric(df["pass_rush_wins"], errors="coerce") > pd.to_numeric(df["pass_rush_snaps"], errors="coerce")
        if bool(bad.any()):
            notes.append("WARNING: pass-rush wins exceed pass-rush snaps")
    if dataset == "run_defense" and {"stops", "run_defense_snaps"}.issubset(df.columns):
        bad = pd.to_numeric(df["stops"], errors="coerce") > pd.to_numeric(df["run_defense_snaps"], errors="coerce")
        if bool(bad.any()):
            notes.append("WARNING: stops exceed run-defense snaps")
    if dataset == "coverage" and {"targets", "coverage_snaps"}.issubset(df.columns):
        bad = pd.to_numeric(df["targets"], errors="coerce") > pd.to_numeric(df["coverage_snaps"], errors="coerce")
        if bool(bad.any()):
            notes.append("WARNING: coverage targets exceed coverage snaps")
    if dataset == "pass_rush" and {"total_pressures", "sacks", "hits", "hurries"}.issubset(df.columns):
        pressure = pd.to_numeric(df["total_pressures"], errors="coerce")
        parts = pd.to_numeric(df["sacks"], errors="coerce") + pd.to_numeric(df["hits"], errors="coerce") + pd.to_numeric(df["hurries"], errors="coerce")
        if bool((pressure != parts).fillna(False).any()):
            notes.append("INFO: total pressures do not always equal sacks + hits + hurries")
    return notes


def _game_team_count(df: pd.DataFrame) -> int:
    teams: set[Any] = set()
    for column in ["home_team", "away_team"]:
        if column in df.columns:
            teams.update(value for value in df[column].dropna().unique())
    return len(teams)


def _is_snap_count_column(column: str) -> bool:
    return column.endswith("_snaps") or column.startswith("snap_counts_") or column.endswith("_snap_counts_coverage")


def load_cached_raw(path: Path) -> Any:
    import json

    return json.loads(path.read_text(encoding="utf-8"))
