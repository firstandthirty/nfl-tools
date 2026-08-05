from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from utils.name_utils import clean_player_name

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TZ = ZoneInfo("America/New_York")

CANONICAL_ODDS_COLUMNS = [
    "sportsbook",
    "source",
    "event_id",
    "commence_time",
    "home_team",
    "away_team",
    "player",
    "player_normalized",
    "market",
    "line",
    "side",
    "price",
    "captured_at",
    "captured_at_source",
    "season",
    "week",
    "is_alternate",
    "market_source_key",
    "outcome_description",
    "raw_file",
    "source_event_index",
    "source_market_index",
    "source_outcome_index",
    "bookmaker_key",
    "bookmaker_title",
    "last_update",
    "market_last_update",
    "point_raw",
    "price_raw",
]

ODDS_IDENTITY_COLUMNS = [
    "source",
    "sportsbook",
    "season",
    "week",
    "captured_at",
    "event_id",
    "player_normalized",
    "market",
    "line",
    "side",
]


@dataclass(frozen=True)
class OddsSnapshotMetadata:
    source: str
    season: int
    week: int
    raw_file: Path
    captured_at: datetime
    captured_at_source: str


def isoformat_with_offset(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=DEFAULT_TZ)
    return value.isoformat()


def parse_timestamp(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            raise ValueError("empty timestamp")
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=DEFAULT_TZ)
    return parsed


def parse_snapshot_metadata(raw_file: Path | str, *, source: str, season: int | str, week: int | str, captured_at: str | datetime | None = None) -> OddsSnapshotMetadata:
    raw_path = Path(raw_file)
    resolved = raw_path.resolve() if raw_path.exists() else raw_path
    if captured_at is not None:
        return OddsSnapshotMetadata(source=source, season=int(season), week=int(week), raw_file=resolved, captured_at=parse_timestamp(captured_at), captured_at_source="explicit")

    stem = raw_path.stem
    patterns = [
        (r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})", "%Y%m%d%H%M%S"),
        (r"(\d{4})-(\d{2})-(\d{2})T(\d{2})(\d{2})(\d{2})", "%Y%m%d%H%M%S"),
        (r"(\d{2})_(\d{2})_(\d{2})_(\d{4})", "%m%d%y%H%M"),
        (r"(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})", "%Y%m%d%H%M"),
    ]
    for pattern, fmt in patterns:
        match = re.search(pattern, stem)
        if not match:
            continue
        try:
            parsed = datetime.strptime("".join(match.groups()), fmt).replace(tzinfo=DEFAULT_TZ)
            return OddsSnapshotMetadata(source=source, season=int(season), week=int(week), raw_file=resolved, captured_at=parsed, captured_at_source="filename")
        except ValueError:
            continue

    fallback = datetime.fromtimestamp(resolved.stat().st_mtime, tz=DEFAULT_TZ)
    return OddsSnapshotMetadata(source=source, season=int(season), week=int(week), raw_file=resolved, captured_at=fallback, captured_at_source="filesystem_mtime")


def discover_snapshot_files(root: Path | str, *, source: str, season: int | str, week: int | str) -> list[Path]:
    base = Path(root)
    week_value = int(week)
    candidates = [f"week_{week_value:02d}", f"week_{week_value}"]
    found: list[Path] = []
    for week_dir in candidates:
        snapshots_dir = base / "data" / "raw" / "odds" / source / str(season) / week_dir / "snapshots"
        if snapshots_dir.exists():
            found.extend(sorted(path for path in snapshots_dir.rglob("*.json") if path.is_file()))
    return sorted(set(found))


def build_output_paths(output_root: Path | str, *, source: str, season: int | str, week: int | str, raw_file: Path) -> dict[str, Path]:
    output_root = Path(output_root)
    output_dir = output_root / "data" / "processed" / "odds" / source / str(season) / f"week_{int(week):02d}"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_file.stem).strip("_") or "snapshot"
    return {
        "output_dir": output_dir,
        "long_path": output_dir / f"{stem}_odds_long.csv",
        "rejected_path": output_dir / f"{stem}_odds_rejected.csv",
        "validation_path": output_dir / f"{stem}_odds_validation.csv",
        "weekly_path": output_dir / "odds_long.csv",
        "conflicts_path": output_dir / f"{stem}_odds_conflicts.csv",
    }


def normalize_player(value: object) -> str:
    return clean_player_name(value) or ""


def normalize_side(value: object) -> str | None:
    text = "" if value is None else str(value).strip().lower()
    if text in {"over", "o"}:
        return "over"
    if text in {"under", "u"}:
        return "under"
    return None


def safe_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value: object) -> int | None:
    if value is None or pd.isna(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number.is_integer():
        return int(number)
    return None


def to_repo_relative(path: Path | str, *, project_root: Path) -> str:
    path = Path(path)
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def append_unique_rows(path: Path | str, new_rows: list[dict], *, conflict_path: Path | str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = pd.read_csv(path) if path.exists() and path.stat().st_size > 0 else pd.DataFrame(columns=CANONICAL_ODDS_COLUMNS)
    combined_records = existing.to_dict(orient="records") if not existing.empty else []
    conflicts: list[dict] = []

    for row in new_rows:
        identity = tuple(row.get(col) for col in ODDS_IDENTITY_COLUMNS)
        matches = [item for item in combined_records if tuple(item.get(col) for col in ODDS_IDENTITY_COLUMNS) == identity]
        if not matches:
            combined_records.append(row)
            continue
        comparable = {col: row.get(col) for col in CANONICAL_ODDS_COLUMNS}
        existing_comparable = {col: matches[0].get(col) for col in CANONICAL_ODDS_COLUMNS}
        if comparable != existing_comparable:
            conflicts.append({"reason": "conflicting_duplicate_identity", "identity": "|".join(map(str, identity)), "existing_price": matches[0].get("price"), "new_price": row.get("price")})

    output = pd.DataFrame(combined_records, columns=CANONICAL_ODDS_COLUMNS)
    conflict_df = pd.DataFrame(conflicts, columns=["reason", "identity", "existing_price", "new_price"])
    if conflict_path is not None:
        conflict_df.to_csv(conflict_path, index=False)
    return output, conflict_df

