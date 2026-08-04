from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

DEFAULT_TZ = ZoneInfo("America/New_York")


def _to_repo_relative(path: Path | str, *, project_root: Path) -> str:
    if path is None:
        return ""
    path = Path(path)
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def normalize_datetime(value: Any, *, default_tz: ZoneInfo = DEFAULT_TZ) -> datetime:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        raise ValueError("Datetime value cannot be empty")
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            raise ValueError("Datetime value cannot be empty")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"Invalid timestamp {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz)
    return dt.astimezone(default_tz)


def parse_as_of(value: str | datetime | None, *, default_tz: ZoneInfo = DEFAULT_TZ) -> datetime:
    if value is None:
        return datetime.now(default_tz)
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=default_tz)
        return dt.astimezone(default_tz)
    text = str(value).strip()
    if not text:
        raise ValueError("as_of timestamp cannot be empty")
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid as_of timestamp: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz)
    return dt.astimezone(default_tz)


def load_snapshot_registry(registry_path: Path | str, *, project_root: Path | str | None = None) -> pd.DataFrame:
    registry_path = Path(registry_path)
    if not registry_path.exists():
        return pd.DataFrame(columns=[
            "source", "season", "week", "captured_at", "processed_long_file", "raw_file", "raw_file_sha256", "canonical_rows"
        ])
    registry_df = pd.read_csv(registry_path)
    required_columns = {"source", "season", "week", "captured_at", "processed_long_file", "raw_file", "raw_file_sha256"}
    missing = sorted(required_columns - set(registry_df.columns))
    if missing:
        raise ValueError(f"Registry is missing required columns: {', '.join(missing)}")
    registry_df = registry_df.copy()
    registry_df["season"] = pd.to_numeric(registry_df["season"], errors="coerce").astype("Int64")
    registry_df["week"] = pd.to_numeric(registry_df["week"], errors="coerce").astype("Int64")
    registry_df["captured_at_dt"] = registry_df["captured_at"].apply(normalize_datetime)
    project_root = Path(project_root).resolve() if project_root is not None else None
    if project_root is not None:
        registry_df["processed_long_file_resolved"] = registry_df["processed_long_file"].apply(lambda value: str((project_root / str(value)).resolve()) if isinstance(value, str) and not Path(str(value)).is_absolute() else str(value))
        registry_df["processed_long_file_repo"] = registry_df["processed_long_file"].apply(lambda value: _to_repo_relative(value, project_root=project_root) if value is not None else "")
        registry_df["raw_file_repo"] = registry_df["raw_file"].apply(lambda value: _to_repo_relative(value, project_root=project_root) if value is not None else "")
    else:
        registry_df["processed_long_file_resolved"] = registry_df["processed_long_file"]
        registry_df["processed_long_file_repo"] = registry_df["processed_long_file"]
        registry_df["raw_file_repo"] = registry_df["raw_file"]
    return registry_df


def load_selected_source_rows(registry_row: pd.Series | dict[str, Any], *, project_root: Path | str) -> pd.DataFrame:
    project_root = Path(project_root).resolve()
    long_path = None
    for key in ("processed_long_file_resolved", "selected_processed_file", "processed_long_file", "processed_long_file_repo"):
        if isinstance(registry_row, dict):
            candidate = registry_row.get(key)
        else:
            candidate = registry_row.get(key)
        if candidate is None:
            continue
        candidate = str(candidate).strip()
        if candidate:
            long_path = candidate
            break
    if not long_path:
        raise ValueError("Registry row is missing a processed projection path")
    path_obj = Path(long_path)
    if not path_obj.is_absolute():
        path_obj = project_root / path_obj
    long_path = path_obj.resolve()
    if not long_path.exists():
        raise FileNotFoundError(f"Processed projection file not found: {long_path}")
    frame = pd.read_csv(long_path)
    required_columns = {"player", "player_normalized", "team", "position", "season", "week", "source", "market", "projection", "captured_at", "raw_file"}
    missing = sorted(required_columns - set(frame.columns))
    if missing:
        raise ValueError(f"Processed projection file is missing required columns: {', '.join(missing)}")
    frame = frame.copy()
    frame["season"] = pd.to_numeric(frame["season"], errors="coerce").astype("Int64")
    frame["week"] = pd.to_numeric(frame["week"], errors="coerce").astype("Int64")
    frame["projection"] = pd.to_numeric(frame["projection"], errors="coerce")
    frame["captured_at_dt"] = frame["captured_at"].apply(normalize_datetime)
    frame["raw_file_repo"] = frame["raw_file"].apply(lambda value: _to_repo_relative(value, project_root=project_root) if value is not None else "")
    frame["processed_file_repo"] = str(_to_repo_relative(long_path, project_root=project_root))
    return frame
