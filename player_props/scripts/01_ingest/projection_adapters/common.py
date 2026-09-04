from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd

from utils.name_utils import clean_player_name, clean_team

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_PROJECTIONS_ROOT = PROJECT_ROOT / "data" / "raw" / "projections"
PROCESSED_PROJECTIONS_ROOT = PROJECT_ROOT / "data" / "processed" / "projections"

CANONICAL_MARKETS = {
    "passYds": "player_pass_yds",
    "rushYds": "player_rush_yds",
    "recvYds": "player_reception_yds",
    "recvReceptions": "player_receptions",
}

REQUIRED_PFF_COLUMNS = ["playerName", "teamName", "position", "passYds", "rushYds", "recvYds", "recvReceptions"]
REQUIRED_OUTPUT_COLUMNS = [
    "player",
    "player_normalized",
    "team",
    "position",
    "season",
    "week",
    "source",
    "market",
    "projection",
    "captured_at",
    "captured_at_source",
    "raw_file",
]


@dataclass
class SnapshotMetadata:
    source: str
    season: int
    week: int
    raw_file: Path
    captured_at: datetime
    captured_at_source: str

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "season": self.season,
            "week": self.week,
            "raw_file": str(self.raw_file),
            "captured_at": self.captured_at.isoformat(),
            "captured_at_source": self.captured_at_source,
        }


def discover_snapshot_files(root: Path | str, *, source: str, season: int | str, week: int | str) -> list[Path]:
    base = Path(root)
    week_value = int(week)
    week_candidates = [f"week_{week_value}", f"week_{week_value:02d}"]
    for week_dir in week_candidates:
        snapshots_dir = base / "data" / "raw" / "projections" / source / str(season) / week_dir / "snapshots"
        if snapshots_dir.exists():
            patterns = ["*.csv", "*.json"] if source == "fantasypros" else ["*.csv"]
            candidates = []
            for pattern in patterns:
                candidates.extend(sorted(snapshots_dir.rglob(pattern)))
            return [path for path in candidates if path.is_file()]
    return []


def parse_snapshot_metadata(raw_file: Path | str, *, source: str, season: int | str, week: int | str) -> SnapshotMetadata:
    raw_path = Path(raw_file)
    raw_path = raw_path.resolve() if raw_path.exists() else raw_path
    timestamp_match = re.match(r"^(\d{2})_(\d{2})_(\d{2})_(\d{4})", raw_path.stem)
    tz = ZoneInfo("America/New_York")

    if timestamp_match:
        month, day, year, time_value = timestamp_match.groups()
        try:
            parsed = datetime.strptime(f"{month}_{day}_{year}_{time_value}", "%m_%d_%y_%H%M").replace(tzinfo=tz)
            return SnapshotMetadata(
                source=source,
                season=int(season),
                week=int(week),
                raw_file=raw_path,
                captured_at=parsed,
                captured_at_source="filename",
            )
        except ValueError:
            pass

    fallback = datetime.fromtimestamp(raw_path.stat().st_mtime, tz=tz)
    return SnapshotMetadata(
        source=source,
        season=int(season),
        week=int(week),
        raw_file=raw_path,
        captured_at=fallback,
        captured_at_source="filesystem_mtime",
    )


def isoformat_with_offset(value: datetime) -> str:
    return value.isoformat()


def normalize_player_name(value: object) -> str:
    return clean_player_name(value) or ""


def normalize_team(value: object, *, preserve_raw: bool = True) -> tuple[str, str]:
    raw_value = "" if value is None else str(value).strip()
    normalized = clean_team(raw_value)
    if preserve_raw:
        return normalized, raw_value
    return normalized


def validate_required_columns(frame: pd.DataFrame, required_columns: Iterable[str], provider: str) -> None:
    missing = [col for col in required_columns if col not in frame.columns]
    if missing:
        raise ValueError(f"Missing required {provider} columns: {', '.join(sorted(missing))}")


def build_output_paths(output_root: Path | str, *, source: str, season: int | str, week: int | str, raw_file: Path) -> dict[str, Path]:
    output_root = Path(output_root)
    week_token = f"week_{int(week):02d}" if source == "fantasypros" else f"week_{int(week)}"
    output_dir = output_root / "data" / "processed" / "projections" / source / str(season) / week_token
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = raw_file.stem
    if stem.endswith("_projections"):
        stem = stem
    elif stem.endswith("projections"):
        stem = stem[:-len("projections")] + "_projections"
    long_path = output_dir / f"{stem}_long.csv"
    validation_path = output_dir / f"{stem}_validation.csv"
    rejected_path = output_dir / f"{stem}_rejected.csv"
    return {
        "output_dir": output_dir,
        "long_path": long_path,
        "validation_path": validation_path,
        "rejected_path": rejected_path,
    }


def build_output_row(row: dict, *, metadata: SnapshotMetadata, source: str) -> dict:
    return {
        "player": row["player"],
        "player_normalized": row["player_normalized"],
        "team": row["team"],
        "team_raw": row["team_raw"],
        "position": row["position"],
        "season": metadata.season,
        "week": metadata.week,
        "source": source,
        "market": row["market"],
        "projection": row["projection"],
        "captured_at": isoformat_with_offset(metadata.captured_at),
        "captured_at_source": metadata.captured_at_source,
        "raw_file": str(row.get("raw_file", metadata.raw_file)),
        "source_player_id": row.get("source_player_id"),
        "source_row_number": row.get("source_row_number"),
        "source_column": row.get("source_column"),
    }


def append_weekly_rows(weekly_output_path: Path | str, new_rows: list[dict], *, identity_columns: list[str]) -> pd.DataFrame:
    weekly_output_path = Path(weekly_output_path)
    weekly_output_path.parent.mkdir(parents=True, exist_ok=True)

    extra_columns = []
    for row in new_rows:
        for column in row:
            if column not in REQUIRED_OUTPUT_COLUMNS and column not in extra_columns:
                extra_columns.append(column)
    base_extras = ["team_raw", "source_player_id", "source_row_number", "source_column"]
    columns = [*REQUIRED_OUTPUT_COLUMNS, *base_extras, *[column for column in extra_columns if column not in base_extras]]
    if weekly_output_path.exists() and weekly_output_path.stat().st_size > 0:
        existing_df = pd.read_csv(weekly_output_path)
        existing_records = existing_df.to_dict(orient="records") if not existing_df.empty else []
    else:
        existing_records = []

    new_df = pd.DataFrame(new_rows)
    if new_df.empty:
        return pd.DataFrame(existing_records, columns=columns)

    for column in columns:
        if column not in new_df.columns:
            new_df[column] = pd.NA

    for row in new_df.to_dict(orient="records"):
        identity = tuple(row.get(col) for col in identity_columns)
        matches = [existing_row for existing_row in existing_records if tuple(existing_row.get(col) for col in identity_columns) == identity]
        if matches:
            if any(existing_row != row for existing_row in matches):
                raise ValueError(f"Duplicate canonical key conflict for {identity_columns}: {identity}")
            continue
        existing_records.append(row)

    return pd.DataFrame(existing_records, columns=columns)
