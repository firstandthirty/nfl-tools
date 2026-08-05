from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from odds_adapters.common import build_output_paths, parse_snapshot_metadata, to_repo_relative

from .hashing import hash_file

REGISTRY_COLUMNS = [
    "source", "season", "week", "captured_at", "captured_at_source", "raw_file", "raw_file_name", "raw_file_sha256",
    "raw_file_size_bytes", "processed_long_file", "processed_rejected_file", "processed_validation_file", "processed_file_sha256",
    "ingested_at", "registry_updated_at", "raw_events", "sportsbooks", "canonical_rows", "unique_events", "unique_players",
    "markets_covered", "raw_market_keys", "main_line_rows", "alternate_line_rows", "rejected_rows", "validation_status",
    "warning_count", "warnings", "schema_version"
]


def _discover_raw_files(project_root: Path, *, source: str | None = None, season: int | str | None = None, week: int | str | None = None) -> list[Path]:
    raw_root = project_root / "data" / "raw" / "odds"
    if not raw_root.exists():
        return []
    files: list[Path] = []
    for source_dir in sorted(path for path in raw_root.iterdir() if path.is_dir()):
        if source and source_dir.name != source:
            continue
        for season_dir in sorted(path for path in source_dir.iterdir() if path.is_dir()):
            if season is not None and season_dir.name != str(season):
                continue
            for week_dir in sorted(path for path in season_dir.iterdir() if path.is_dir()):
                if week is not None and week_dir.name not in {f"week_{int(week):02d}", f"week_{int(week)}"}:
                    continue
                snapshot_dir = week_dir / "snapshots"
                if snapshot_dir.exists():
                    files.extend(sorted(path for path in snapshot_dir.rglob("*.json") if path.is_file()))
    return files


def _metric(validation_df: pd.DataFrame, name: str) -> Any:
    if validation_df.empty or "metric" not in validation_df.columns:
        return ""
    rows = validation_df.loc[validation_df["metric"] == name]
    if rows.empty:
        return ""
    return rows.iloc[0].get("value", "")


def _list_field(values: list[str]) -> str:
    return "|".join(sorted({str(value) for value in values if str(value).strip()}))


def build_odds_registry(project_root: Path | str, output_root: Path | str | None = None, *, source: str | None = None, season: int | str | None = None, week: int | str | None = None, rebuild: bool = False) -> dict[str, Any]:
    project_root = Path(project_root).resolve()
    output_root = Path(output_root).resolve() if output_root is not None else project_root
    processed_root = output_root / "data" / "processed" / "odds"
    registry_path = processed_root / "snapshot_registry.csv"
    conflicts_path = processed_root / "registry_conflicts.csv"
    processed_root.mkdir(parents=True, exist_ok=True)

    registry_df = pd.DataFrame(columns=REGISTRY_COLUMNS)
    if registry_path.exists() and registry_path.stat().st_size > 0 and not rebuild:
        registry_df = pd.read_csv(registry_path).fillna("")

    added = 0
    unchanged = 0
    conflicts: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    for raw_file in _discover_raw_files(project_root, source=source, season=season, week=week):
        parts = raw_file.parts
        if source is not None:
            source_value = source
        elif "odds" in parts:
            source_value = parts[parts.index("odds") + 1]
        else:
            source_value = "odds_api"
        if season is not None:
            season_value = season
        elif str(source_value) in parts:
            season_value = parts[parts.index(str(source_value)) + 1]
        else:
            season_value = 0
        week_token = week
        if week_token is None:
            for part in parts:
                if str(part).startswith("week_"):
                    week_token = str(part).split("_", 1)[1]
                    break
        metadata = parse_snapshot_metadata(raw_file, source=str(source_value), season=int(season_value), week=int(week_token or 0))
        paths = build_output_paths(output_root, source=metadata.source, season=metadata.season, week=metadata.week, raw_file=raw_file)
        if not paths["long_path"].exists():
            raise ValueError(f"Missing required odds long file for snapshot: {raw_file}")
        long_df = pd.read_csv(paths["long_path"]) if paths["long_path"].stat().st_size > 0 else pd.DataFrame()
        rejected_df = pd.read_csv(paths["rejected_path"]) if paths["rejected_path"].exists() and paths["rejected_path"].stat().st_size > 0 else pd.DataFrame()
        validation_df = pd.read_csv(paths["validation_path"]) if paths["validation_path"].exists() and paths["validation_path"].stat().st_size > 0 else pd.DataFrame()
        warnings = str(_metric(validation_df, "warnings") or "")
        raw_hash = hash_file(raw_file)
        row = {
            "source": metadata.source,
            "season": metadata.season,
            "week": metadata.week,
            "captured_at": metadata.captured_at.isoformat(),
            "captured_at_source": metadata.captured_at_source,
            "raw_file": to_repo_relative(raw_file, project_root=project_root),
            "raw_file_name": raw_file.name,
            "raw_file_sha256": raw_hash,
            "raw_file_size_bytes": raw_file.stat().st_size,
            "processed_long_file": to_repo_relative(paths["long_path"], project_root=project_root),
            "processed_rejected_file": to_repo_relative(paths["rejected_path"], project_root=project_root),
            "processed_validation_file": to_repo_relative(paths["validation_path"], project_root=project_root),
            "processed_file_sha256": hash_file(paths["long_path"]),
            "ingested_at": now,
            "registry_updated_at": now,
            "raw_events": int(_metric(validation_df, "raw_events") or 0),
            "sportsbooks": _list_field(long_df["sportsbook"].dropna().astype(str).tolist()) if not long_df.empty else "",
            "canonical_rows": len(long_df),
            "unique_events": int(long_df["event_id"].nunique()) if not long_df.empty else 0,
            "unique_players": int(long_df["player_normalized"].nunique()) if not long_df.empty else 0,
            "markets_covered": _list_field(long_df["market"].dropna().astype(str).tolist()) if not long_df.empty else "",
            "raw_market_keys": _list_field(long_df["market_source_key"].dropna().astype(str).tolist()) if not long_df.empty else "",
            "main_line_rows": int((long_df["is_alternate"] == False).sum()) if not long_df.empty else 0,
            "alternate_line_rows": int((long_df["is_alternate"] == True).sum()) if not long_df.empty else 0,
            "rejected_rows": len(rejected_df),
            "validation_status": "passed" if not warnings else "passed_with_warnings",
            "warning_count": 0 if not warnings else len([item for item in warnings.split("|") if item.strip()]),
            "warnings": warnings,
            "schema_version": "odds_long_v1",
        }
        existing_hash = registry_df.loc[registry_df["raw_file_sha256"].astype(str) == raw_hash] if not registry_df.empty else pd.DataFrame()
        if not existing_hash.empty:
            existing = existing_hash.iloc[0].to_dict()
            if existing.get("source") == row["source"] and int(existing.get("season")) == row["season"] and int(existing.get("week")) == row["week"] and existing.get("captured_at") == row["captured_at"] and existing.get("processed_long_file") == row["processed_long_file"]:
                unchanged += 1
                continue
            conflicts.append({"reason": "conflicting_metadata_for_existing_hash", "raw_file_sha256": raw_hash, "existing_row": existing.get("raw_file"), "new_row": row["raw_file"]})
            continue
        same_timestamp = registry_df.loc[(registry_df["source"].astype(str) == row["source"]) & (registry_df["season"].astype(str) == str(row["season"])) & (registry_df["week"].astype(str) == str(row["week"])) & (registry_df["captured_at"].astype(str) == row["captured_at"])] if not registry_df.empty else pd.DataFrame()
        if not same_timestamp.empty and not (same_timestamp["raw_file_sha256"].astype(str) == raw_hash).any():
            conflicts.append({"reason": "same_timestamp_different_content", "raw_file_sha256": raw_hash, "existing_row": same_timestamp.iloc[0].get("raw_file"), "new_row": row["raw_file"]})
        processed_match = registry_df.loc[registry_df["processed_long_file"].astype(str) == row["processed_long_file"]] if not registry_df.empty else pd.DataFrame()
        if not processed_match.empty and str(processed_match.iloc[0].get("processed_file_sha256", "")) != row["processed_file_sha256"]:
            conflicts.append({"reason": "conflicting_processed_hash", "raw_file_sha256": raw_hash, "existing_row": processed_match.iloc[0].get("processed_long_file"), "new_row": row["processed_long_file"]})
            continue
        registry_df = pd.concat([registry_df, pd.DataFrame([row])], ignore_index=True)
        added += 1

    registry_df.to_csv(registry_path, index=False)
    pd.DataFrame(conflicts, columns=["reason", "raw_file_sha256", "existing_row", "new_row"]).to_csv(conflicts_path, index=False)
    return {"registry_path": str(registry_path), "conflicts_path": str(conflicts_path), "registry_rows": registry_df.to_dict(orient="records"), "added_rows": added, "unchanged_rows": unchanged, "conflicts": conflicts}
