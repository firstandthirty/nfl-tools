from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

DEFAULT_TZ = ZoneInfo("America/New_York")


def parse_as_of(value: str | datetime | None) -> datetime:
    if value is None:
        parsed = datetime.now(DEFAULT_TZ)
    elif isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=DEFAULT_TZ)
    return parsed


def normalize_datetime(value: str | datetime) -> datetime:
    parsed = parse_as_of(value)
    return parsed


def load_odds_registry(path: Path | str, *, project_root: Path | str) -> pd.DataFrame:
    registry = pd.read_csv(path) if Path(path).exists() and Path(path).stat().st_size > 0 else pd.DataFrame()
    if registry.empty:
        return registry
    registry = registry.fillna("")
    registry["captured_at_dt"] = registry["captured_at"].apply(normalize_datetime)
    project_root = Path(project_root).resolve()
    for column in ["raw_file", "processed_long_file", "processed_rejected_file", "processed_validation_file"]:
        if column in registry.columns:
            registry[f"{column}_repo"] = registry[column].astype(str)
            registry[column] = registry[column].apply(lambda value: project_root / str(value) if str(value).strip() else Path(""))
    return registry


def load_selected_odds(row: dict, *, project_root: Path | str, sportsbook: str | None = None, market: str | None = None) -> pd.DataFrame:
    path = Path(row.get("processed_long_file", ""))
    if not path.exists():
        path = Path(project_root) / str(row.get("selected_processed_file", ""))
    frame = pd.read_csv(path) if path.exists() and path.stat().st_size > 0 else pd.DataFrame()
    if sportsbook and not frame.empty:
        frame = frame.loc[frame["sportsbook"].astype(str) == sportsbook].copy()
    if market and not frame.empty:
        frame = frame.loc[frame["market"].astype(str) == market].copy()
    return frame

