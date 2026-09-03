from __future__ import annotations

import re
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from pandas.errors import EmptyDataError

from projection_adapters.common import SnapshotMetadata, build_output_paths, parse_snapshot_metadata
from projection_adapters.fantasypros import ADAPTER_VERSION as FANTASYPROS_ADAPTER_VERSION
from projection_adapters.fantasypros import identify_source_file_type, _api_projection_items
from utils.name_utils import TEAM_ALIASES

from .hashing import hash_file, hash_files

DEFAULT_MARKETS = [
    "player_pass_yds",
    "player_rush_yds",
    "player_reception_yds",
    "player_receptions",
]

MARKET_THRESHOLDS = {
    "player_pass_yds": 500.0,
    "player_rush_yds": 250.0,
    "player_reception_yds": 250.0,
    "player_receptions": 20.0,
}

RECOGNIZED_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DST"}
RECOGNIZED_TEAMS = set(TEAM_ALIASES.values())


def _to_repo_relative(path: Path | str, *, project_root: Path) -> str:
    path = Path(path)
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _sanitize_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _list_field(values: list[str] | set[str] | None) -> str:
    if not values:
        return ""
    return "|".join(sorted({str(value) for value in values if str(value).strip()}))


def _timestamp_stem(path: Path) -> str:
    parts = path.stem.split("_")
    if len(parts) < 4:
        raise ValueError(f"FantasyPros filename does not start with MM_DD_YY_HHMM timestamp: {path}")
    return "_".join(parts[:4])


def _get_column(frame: pd.DataFrame, *names: str) -> pd.Series:
    for name in names:
        if name in frame.columns:
            return frame[name]
    return pd.Series(["" for _ in range(len(frame))], index=frame.index)


def _nonempty_nunique(series: pd.Series) -> int:
    cleaned = series.dropna().astype(str).str.strip()
    return int(cleaned[cleaned.ne("")].nunique())


def _warning_count_from_validation(validation_df: pd.DataFrame | None) -> tuple[int, str]:
    if validation_df is None or validation_df.empty:
        return 0, ""
    warning_row = validation_df.loc[validation_df["metric"] == "warnings"]
    if warning_row.empty:
        return 0, ""
    value = warning_row.iloc[0].get("value", "")
    if value is None or pd.isna(value):
        value = ""
    elif isinstance(value, str) and value.strip().lower() in {"", "nan", "none", "null"}:
        value = ""
    value = str(value)
    parts = [part for part in re.split(r"\s*\|\s*", value) if part.strip()]
    return len(parts), " | ".join(parts)


def _quality_checks(long_df: pd.DataFrame, rejected_df: pd.DataFrame | None, validation_df: pd.DataFrame | None) -> tuple[list[str], int, str]:
    warnings: list[str] = []
    if validation_df is not None and not validation_df.empty:
        validation_warnings, validation_warning_text = _warning_count_from_validation(validation_df)
        if validation_warning_text:
            warnings.append(validation_warning_text)
    if long_df.empty:
        warnings.append("empty_long_format")
        return warnings, len(warnings), " | ".join(warnings)

    player_series = _get_column(long_df, "player", "player_normalized")
    player_normalized_series = _get_column(long_df, "player_normalized", "player")
    team_series = _get_column(long_df, "team")
    position_series = _get_column(long_df, "position")
    market_series = _get_column(long_df, "market")
    projection_series = _get_column(long_df, "projection")

    duplicate_canonical = int(long_df.duplicated(subset=["player_normalized", "market"]).sum()) if {"player_normalized", "market"}.issubset(long_df.columns) else 0
    if duplicate_canonical:
        warnings.append(f"duplicate_canonical_keys={duplicate_canonical}")

    missing_player = int(player_series.isna().sum() + player_series.astype(str).str.strip().eq("").sum())
    if missing_player:
        warnings.append(f"missing_player_names={missing_player}")

    missing_player_normalized = int(player_normalized_series.isna().sum() + player_normalized_series.astype(str).str.strip().eq("").sum())
    if missing_player_normalized:
        warnings.append(f"missing_normalized_player_names={missing_player_normalized}")

    missing_teams = int(team_series.isna().sum() + team_series.astype(str).str.strip().eq("").sum())
    if missing_teams:
        warnings.append(f"missing_teams={missing_teams}")

    missing_positions = int(position_series.isna().sum() + position_series.astype(str).str.strip().eq("").sum())
    if missing_positions:
        warnings.append(f"missing_positions={missing_positions}")

    missing_markets = int(market_series.isna().sum() + market_series.astype(str).str.strip().eq("").sum())
    if missing_markets:
        warnings.append(f"missing_markets={missing_markets}")

    missing_projections = int(projection_series.isna().sum())
    if missing_projections:
        warnings.append(f"missing_projections={missing_projections}")

    try:
        numeric_projection = pd.to_numeric(projection_series, errors="coerce")
        nonfinite = int(numeric_projection.isna().sum())
    except Exception:
        nonfinite = 0
    if nonfinite:
        warnings.append(f"nonfinite_projections={nonfinite}")

    negative = int(pd.to_numeric(projection_series, errors="coerce").lt(0).sum())
    if negative:
        warnings.append(f"negative_projections={negative}")

    implausible_rows: list[tuple[str, Any]] = []
    for market in DEFAULT_MARKETS:
        threshold = MARKET_THRESHOLDS.get(market)
        if threshold is None:
            continue
        market_values = pd.to_numeric(projection_series[market_series.astype(str) == market], errors="coerce")
        if market_values.empty:
            continue
        implausible = market_values[market_values.gt(threshold)]
        if not implausible.empty:
            implausible_rows.append((market, int(len(implausible))))
    if implausible_rows:
        warnings.extend([f"implausibly_high_{market}={count}" for market, count in implausible_rows])

    unrecognized_teams = int(team_series.astype(str).str.upper().isin(RECOGNIZED_TEAMS).eq(False).sum())
    if unrecognized_teams:
        warnings.append(f"unrecognized_teams={unrecognized_teams}")

    unrecognized_positions = int(position_series.astype(str).str.upper().isin(RECOGNIZED_POSITIONS).eq(False).sum())
    if unrecognized_positions:
        warnings.append(f"unrecognized_positions={unrecognized_positions}")

    if rejected_df is not None and not rejected_df.empty:
        warnings.append(f"rejected_rows={len(rejected_df)}")

    return warnings, len(warnings), " | ".join(warnings)


def _validation_status(warnings: list[str]) -> str:
    if not warnings:
        return "passed"
    if any(token.startswith("empty_long_format") or token.startswith("missing_") or token.startswith("negative_") for token in warnings):
        return "failed"
    return "passed_with_warnings"


def _build_registry_row(raw_path: Path, *, project_root: Path, output_root: Path, metadata, long_df: pd.DataFrame, rejected_df: pd.DataFrame | None, validation_df: pd.DataFrame | None, registry_updated_at: datetime, component_raw_files: list[Path] | None = None) -> dict[str, Any]:
    component_raw_files = component_raw_files or [raw_path]
    output_paths = build_output_paths(output_root, source=metadata.source, season=metadata.season, week=metadata.week, raw_file=raw_path)
    long_path = output_paths["long_path"]
    rejected_path = output_paths["rejected_path"]
    validation_path = output_paths["validation_path"]

    warnings, warning_count, warning_text = _quality_checks(long_df, rejected_df, validation_df)
    validation_status = _validation_status(warnings)
    adapter_version = "pff_adapter_v1" if metadata.source == "pff" else FANTASYPROS_ADAPTER_VERSION if metadata.source == "fantasypros" else "adapter_v1"
    component_hashes = [hash_file(path) for path in component_raw_files]
    logical_hash = hash_files(component_raw_files)
    raw_rows = 0
    for component in component_raw_files:
        if not component.exists():
            continue
        if component.suffix.lower() == ".json":
            payload = json.loads(component.read_text(encoding="utf-8"))
            raw_rows += len(_api_projection_items(payload))
        else:
            raw_rows += int(len(pd.read_csv(component)))
    source_format = "api" if raw_path.suffix.lower() == ".json" else "csv"
    sidecar = raw_path.with_suffix(raw_path.suffix + ".metadata.json")
    sidecar_payload: dict[str, Any] = {}
    if sidecar.exists():
        try:
            sidecar_payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            sidecar_payload = {}

    return {
        "source": metadata.source,
        "season": int(metadata.season),
        "week": int(metadata.week),
        "source_format": source_format,
        "captured_at": metadata.captured_at.isoformat(),
        "captured_at_source": metadata.captured_at_source,
        "endpoint_path": sidecar_payload.get("endpoint_path", ""),
        "response_status": sidecar_payload.get("status_code", ""),
        "rate_limit_limit": sidecar_payload.get("rate_limit_headers", {}).get("x-ratelimit-limit", ""),
        "rate_limit_remaining": sidecar_payload.get("rate_limit_headers", {}).get("x-ratelimit-remaining", ""),
        "rate_limit_reset": sidecar_payload.get("rate_limit_headers", {}).get("x-ratelimit-reset", ""),
        "raw_file": _to_repo_relative(raw_path, project_root=project_root),
        "raw_file_name": raw_path.name,
        "raw_file_sha256": logical_hash if len(component_raw_files) > 1 else component_hashes[0],
        "raw_file_size_bytes": int(sum(path.stat().st_size for path in component_raw_files)),
        "component_raw_files": _list_field([_to_repo_relative(path, project_root=project_root) for path in component_raw_files]),
        "component_raw_file_names": _list_field([path.name for path in component_raw_files]),
        "component_raw_file_sha256": _list_field(component_hashes),
        "logical_snapshot_hash": logical_hash,
        "processed_long_file": _to_repo_relative(long_path, project_root=project_root),
        "processed_rejected_file": _to_repo_relative(rejected_path, project_root=project_root) if rejected_path.exists() else "",
        "processed_validation_file": _to_repo_relative(validation_path, project_root=project_root) if validation_path.exists() else "",
        "processed_file_sha256": hash_file(long_path),
        "ingested_at": registry_updated_at.isoformat(),
        "registry_updated_at": registry_updated_at.isoformat(),
        "raw_rows": raw_rows,
        "canonical_rows": int(len(long_df)),
        "unique_players": _nonempty_nunique(long_df["player_normalized"]) if not long_df.empty else 0,
        "unique_teams": _nonempty_nunique(long_df["team"]) if not long_df.empty else 0,
        "positions_covered": _list_field([str(position).upper() for position in long_df["position"].dropna().astype(str).str.strip().tolist()] if not long_df.empty else []),
        "markets_covered": _list_field([str(market) for market in long_df["market"].dropna().astype(str).str.strip().tolist()] if not long_df.empty else []),
        "market_count": int(long_df["market"].dropna().astype(str).str.strip().nunique() if not long_df.empty else 0),
        "rejected_rows": int(len(rejected_df) if rejected_df is not None else 0),
        "rejection_rate": round((len(rejected_df) / max(1, raw_rows) if rejected_df is not None else 0.0), 6),
        "duplicate_canonical_keys": int(long_df.duplicated(subset=["player_normalized", "market"]).sum() if not long_df.empty else 0),
        "validation_status": validation_status,
        "warning_count": warning_count,
        "warnings": warning_text,
        "adapter_version": adapter_version,
        "schema_version": "projection_long_v1",
        "days_before_week_start": "",
        "snapshot_stage": "unknown",
    }


def _discover_raw_files(project_root: Path, *, source: str | None = None, season: int | str | None = None, week: int | str | None = None) -> list[Path]:
    raw_root = project_root / "data" / "raw" / "projections"
    if not raw_root.exists():
        return []
    candidates: list[Path] = []
    for source_dir in sorted(raw_root.iterdir()):
        if not source_dir.is_dir():
            continue
        if source is not None and source_dir.name != source:
            continue
        for season_dir in sorted(source_dir.iterdir()):
            if not season_dir.is_dir():
                continue
            if season is not None and str(season_dir.name) != str(season):
                continue
            for week_dir in sorted(season_dir.iterdir()):
                if not week_dir.is_dir():
                    continue
                if week is not None:
                    week_value = int(week)
                    week_candidates = {f"week_{week_value}", f"week_{week_value:02d}"}
                    if week_dir.name not in week_candidates:
                        continue
                snapshots_dir = week_dir / "snapshots"
                if snapshots_dir.exists():
                    candidates.extend(sorted(path for path in snapshots_dir.glob("*.csv") if path.is_file()))
                    if source_dir.name == "fantasypros":
                        candidates.extend(sorted(path for path in snapshots_dir.glob("*.json") if path.is_file() and not path.name.endswith(".metadata.json")))
    return sorted(candidates)


def _discover_logical_snapshots(project_root: Path, *, source: str | None = None, season: int | str | None = None, week: int | str | None = None) -> list[dict[str, Any]]:
    raw_files = _discover_raw_files(project_root, source=source, season=season, week=week)
    if source is not None and source != "fantasypros":
        return [{"raw_path": path, "component_raw_files": [path]} for path in raw_files]

    groups: dict[tuple[str, str, str], dict[str, Path]] = {}
    logical_snapshots: list[dict[str, Any]] = []
    for path in raw_files:
        try:
            source_token = path.resolve().parents[3].name
        except IndexError:
            source_token = ""
        if source_token != "fantasypros":
            logical_snapshots.append({"raw_path": path, "component_raw_files": [path]})
            continue
        if path.suffix.lower() == ".json":
            logical_snapshots.append({"raw_path": path, "component_raw_files": [path]})
            continue
        resolved = path.resolve()
        week_token = resolved.parents[1].name
        season_token = resolved.parents[2].name
        timestamp = _timestamp_stem(path)
        file_type = identify_source_file_type(path)
        key = (season_token, week_token, timestamp)
        if file_type in groups.setdefault(key, {}):
            raise ValueError(f"Duplicate FantasyPros {file_type} component for timestamp {timestamp}")
        groups[key][file_type] = path

    for (_, _, timestamp), components in sorted(groups.items()):
        missing = sorted({"qb", "flex"} - set(components))
        if missing:
            raise ValueError(f"Incomplete FantasyPros logical snapshot {timestamp}; missing components: {', '.join(missing)}")
        qb_path = components["qb"]
        logical_snapshots.append(
            {
                "raw_path": qb_path.with_name(f"{timestamp}_projections.csv"),
                "component_raw_files": [components["qb"], components["flex"]],
            }
        )
    return logical_snapshots


def _resolve_snapshot_metadata(raw_path: Path, *, source: str | None, season: int | str | None, week: int | str | None) -> Any:
    raw_path = raw_path.resolve()
    inferred_source = source
    inferred_season = season
    inferred_week = week
    try:
        relative_parts = raw_path.relative_to(raw_path.parents[4]).parts
    except ValueError:
        relative_parts = raw_path.parts
    if inferred_source is None and len(relative_parts) >= 1:
        inferred_source = relative_parts[0]
    if inferred_season is None and len(relative_parts) >= 2:
        inferred_season = relative_parts[1]
    if inferred_week is None and len(relative_parts) >= 3:
        week_token = str(relative_parts[2])
        if week_token.startswith("week_"):
            inferred_week = week_token.split("_", 1)[1]
        else:
            inferred_week = week_token
    if inferred_source is None:
        inferred_source = "pff"
    if inferred_season is None:
        inferred_season = 2026
    if inferred_week is None:
        inferred_week = 1
    if Path(raw_path).suffix.lower() == ".json":
        sidecar = raw_path.with_suffix(raw_path.suffix + ".metadata.json")
        if sidecar.exists():
            try:
                payload = json.loads(sidecar.read_text(encoding="utf-8"))
                captured_at = datetime.fromisoformat(str(payload["captured_at"]))
                return SnapshotMetadata(
                    source=str(payload.get("source") or inferred_source or "fantasypros"),
                    season=int(payload.get("season") or inferred_season),
                    week=int(payload.get("week") or inferred_week),
                    raw_file=raw_path,
                    captured_at=captured_at,
                    captured_at_source=str(payload.get("captured_at_source") or "api_request"),
                )
            except (KeyError, ValueError, json.JSONDecodeError):
                pass
    return parse_snapshot_metadata(raw_path, source=inferred_source, season=inferred_season, week=inferred_week)


def _build_coverage_rows(long_df: pd.DataFrame, rejected_df: pd.DataFrame | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for market in DEFAULT_MARKETS:
        market_rows = long_df.loc[long_df["market"] == market] if not long_df.empty else pd.DataFrame()
        metrics = {
            "report_section": "market_coverage",
            "entity": market,
            "market": market,
            "rows": int(len(market_rows)),
            "unique_players": _nonempty_nunique(market_rows["player_normalized"]) if not market_rows.empty else 0,
            "unique_teams": _nonempty_nunique(market_rows["team"]) if not market_rows.empty else 0,
            "positions_represented": _list_field([str(position).upper() for position in market_rows["position"].dropna().astype(str).str.strip().tolist()] if not market_rows.empty else []),
            "null_projection_count": int(market_rows["projection"].isna().sum() if not market_rows.empty else 0),
            "zero_projection_count": int(market_rows["projection"].eq(0).sum() if not market_rows.empty else 0),
            "minimum_projection": float(market_rows["projection"].min()) if not market_rows.empty and market_rows["projection"].notna().any() else None,
            "p25_projection": float(market_rows["projection"].quantile(0.25)) if not market_rows.empty and market_rows["projection"].notna().any() else None,
            "median_projection": float(market_rows["projection"].median()) if not market_rows.empty and market_rows["projection"].notna().any() else None,
            "mean_projection": float(market_rows["projection"].mean()) if not market_rows.empty and market_rows["projection"].notna().any() else None,
            "p75_projection": float(market_rows["projection"].quantile(0.75)) if not market_rows.empty and market_rows["projection"].notna().any() else None,
            "maximum_projection": float(market_rows["projection"].max()) if not market_rows.empty and market_rows["projection"].notna().any() else None,
            "std_projection": float(market_rows["projection"].std()) if not market_rows.empty and market_rows["projection"].notna().any() else None,
        }
        rows.append(metrics)

    if not long_df.empty:
        for position in sorted({str(value).upper() for value in long_df["position"].dropna().astype(str).str.strip().tolist()}):
            position_rows = long_df.loc[long_df["position"].astype(str).str.upper() == position]
            rows.append({
                "report_section": "position_coverage",
                "entity": position,
                "position": position,
                "unique_players": _nonempty_nunique(position_rows["player_normalized"]),
                "canonical_rows": int(len(position_rows)),
                "markets_represented": _list_field([str(market) for market in position_rows["market"].dropna().astype(str).str.strip().tolist()]),
                "teams_represented": _list_field([str(team) for team in position_rows["team"].dropna().astype(str).str.strip().tolist()]),
            })

        for team in sorted({str(value).upper() for value in long_df["team"].dropna().astype(str).str.strip().tolist()}):
            team_rows = long_df.loc[long_df["team"].astype(str).str.upper() == team]
            rows.append({
                "report_section": "team_coverage",
                "entity": team,
                "team": team,
                "unique_players": _nonempty_nunique(team_rows["player_normalized"]),
                "canonical_rows": int(len(team_rows)),
                "positions_represented": _list_field([str(position).upper() for position in team_rows["position"].dropna().astype(str).str.strip().tolist()]),
                "markets_represented": _list_field([str(market) for market in team_rows["market"].dropna().astype(str).str.strip().tolist()]),
            })

    if rejected_df is not None and not rejected_df.empty:
        group_columns = [column for column in ["reason", "source_column", "position"] if column in rejected_df.columns]
        if not group_columns:
            group_columns = ["reason"]
        for grouped_key, grouped in rejected_df.groupby(group_columns):
            if isinstance(grouped_key, tuple):
                reason, source_column, position = (grouped_key + ("", ""))[0:3]
            else:
                reason = grouped_key
                source_column = ""
                position = ""
            rows.append({
                "report_section": "rejections",
                "entity": reason,
                "reason": reason,
                "source_column": source_column,
                "position": position,
                "count": int(len(grouped)),
            })

    quality_warnings, _, _ = _quality_checks(long_df, rejected_df, None)
    for warning in quality_warnings:
        rows.append({
            "report_section": "data_quality",
            "entity": warning,
            "metric": warning.split("=", 1)[0],
            "value": warning.split("=", 1)[1] if "=" in warning else "",
        })
    return rows


def _write_snapshot_coverage_report(snapshot_rows: list[dict[str, Any]], *, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not snapshot_rows:
        pd.DataFrame(columns=["report_section", "entity"]).to_csv(output_path, index=False)
        return
    pd.DataFrame(snapshot_rows).to_csv(output_path, index=False)


def build_weekly_coverage(long_dfs: list[pd.DataFrame] | pd.DataFrame, *, source: str, season: int | str, week: int | str, captured_at: str, snapshot_hash: str, rejected_df: pd.DataFrame | None = None) -> pd.DataFrame:
    if not isinstance(long_dfs, list):
        long_dfs = [long_dfs]
    rows: list[dict[str, Any]] = []
    for long_df in long_dfs:
        if long_df is None or long_df.empty:
            continue
        for market in sorted({str(value) for value in long_df["market"].dropna().astype(str).str.strip().tolist()}):
            market_rows = long_df.loc[long_df["market"].astype(str) == market]
            rows.append({
                "source": source,
                "season": int(season),
                "week": int(week),
                "captured_at": captured_at,
                "market": market,
                "rows": int(len(market_rows)),
                "unique_players": _nonempty_nunique(market_rows["player_normalized"]),
                "unique_teams": _nonempty_nunique(market_rows["team"]),
                "positions_covered": _list_field([str(position).upper() for position in market_rows["position"].dropna().astype(str).str.strip().tolist()]),
                "projection_mean": float(market_rows["projection"].mean()) if market_rows["projection"].notna().any() else None,
                "projection_median": float(market_rows["projection"].median()) if market_rows["projection"].notna().any() else None,
                "projection_std": float(market_rows["projection"].std()) if market_rows["projection"].notna().any() else None,
                "projection_min": float(market_rows["projection"].min()) if market_rows["projection"].notna().any() else None,
                "projection_max": float(market_rows["projection"].max()) if market_rows["projection"].notna().any() else None,
                "rejected_rows_for_snapshot": int(len(rejected_df)) if rejected_df is not None else 0,
                "snapshot_hash": snapshot_hash,
            })
    if not rows:
        return pd.DataFrame(columns=["source", "season", "week", "captured_at", "market", "rows", "unique_players", "unique_teams", "positions_covered", "projection_mean", "projection_median", "projection_std", "projection_min", "projection_max", "rejected_rows_for_snapshot", "snapshot_hash"])
    weekly_df = pd.DataFrame(rows)
    weekly_df = weekly_df.drop_duplicates(subset=["source", "season", "week", "captured_at", "market"]).sort_values(["source", "season", "week", "captured_at", "market"]).reset_index(drop=True)
    return weekly_df


def build_snapshot_change_report(prior_long_dfs: list[pd.DataFrame] | pd.DataFrame | None, current_long_dfs: list[pd.DataFrame] | pd.DataFrame | None = None, *, source: str, season: int | str, week: int | str) -> pd.DataFrame:
    if not isinstance(prior_long_dfs, list):
        prior_long_dfs = [prior_long_dfs] if prior_long_dfs is not None else []
    if not isinstance(current_long_dfs, list):
        current_long_dfs = [current_long_dfs] if current_long_dfs is not None else []
    if not prior_long_dfs and not current_long_dfs:
        return pd.DataFrame(columns=["source", "season", "week", "prior_captured_at", "current_captured_at", "shared_players", "added_players", "removed_players", "changed_players", "unchanged_players", "mean_absolute_change", "median_absolute_change", "maximum_absolute_change", "largest_increase_player", "largest_increase_value", "largest_decrease_player", "largest_decrease_value"])
    prior_frames = [frame for frame in prior_long_dfs if frame is not None and not frame.empty]
    current_frames = [frame for frame in current_long_dfs if frame is not None and not frame.empty]
    prior_df = pd.concat(prior_frames, ignore_index=True) if prior_frames else pd.DataFrame()
    current_df = pd.concat(current_frames, ignore_index=True) if current_frames else pd.DataFrame()
    if prior_df.empty or current_df.empty:
        return pd.DataFrame(columns=["source", "season", "week", "prior_captured_at", "current_captured_at", "shared_players", "added_players", "removed_players", "changed_players", "unchanged_players", "mean_absolute_change", "median_absolute_change", "maximum_absolute_change", "largest_increase_player", "largest_increase_value", "largest_decrease_player", "largest_decrease_value"])
    prior_keys = set(prior_df[["player_normalized", "market"]].apply(tuple, axis=1))
    current_keys = set(current_df[["player_normalized", "market"]].apply(tuple, axis=1))
    shared = prior_keys & current_keys
    added = current_keys - prior_keys
    removed = prior_keys - current_keys
    changed = set()
    for key in shared:
        prior_value = prior_df[(prior_df["player_normalized"] == key[0]) & (prior_df["market"] == key[1])]["projection"].iloc[0] if not prior_df.empty else None
        current_value = current_df[(current_df["player_normalized"] == key[0]) & (current_df["market"] == key[1])]["projection"].iloc[0] if not current_df.empty else None
        if prior_value is not None and current_value is not None and prior_value != current_value:
            changed.add(key)
    rows = [{
        "source": source,
        "season": int(season),
        "week": int(week),
        "prior_captured_at": "",
        "current_captured_at": "",
        "shared_players": len(shared),
        "added_players": len(added),
        "removed_players": len(removed),
        "changed_players": len(changed),
        "unchanged_players": len(shared) - len(changed),
        "mean_absolute_change": None,
        "median_absolute_change": None,
        "maximum_absolute_change": None,
        "largest_increase_player": "",
        "largest_increase_value": None,
        "largest_decrease_player": "",
        "largest_decrease_value": None,
    }]
    return pd.DataFrame(rows)


def build_projection_registry(project_root: Path | str, output_root: Path | str | None = None, *, source: str | None = None, season: int | str | None = None, week: int | str | None = None, rebuild: bool = False) -> dict[str, Any]:
    project_root = Path(project_root).resolve()
    output_root = Path(output_root).resolve() if output_root is not None else project_root
    processed_root = output_root / "data" / "processed" / "projections"
    coverage_root = processed_root / "coverage_reports"
    registry_path = processed_root / "snapshot_registry.csv"
    conflicts_path = processed_root / "registry_conflicts.csv"

    processed_root.mkdir(parents=True, exist_ok=True)
    coverage_root.mkdir(parents=True, exist_ok=True)

    registry_df = pd.DataFrame(columns=[
        "source", "season", "week", "source_format", "captured_at", "captured_at_source", "endpoint_path", "response_status",
        "rate_limit_limit", "rate_limit_remaining", "rate_limit_reset", "raw_file", "raw_file_name", "raw_file_sha256",
        "raw_file_size_bytes", "component_raw_files", "component_raw_file_names", "component_raw_file_sha256", "logical_snapshot_hash",
        "processed_long_file", "processed_rejected_file", "processed_validation_file", "processed_file_sha256",
        "ingested_at", "registry_updated_at", "raw_rows", "canonical_rows", "unique_players", "unique_teams", "positions_covered",
        "markets_covered", "market_count", "rejected_rows", "rejection_rate", "duplicate_canonical_keys", "validation_status",
        "warning_count", "warnings", "adapter_version", "schema_version", "days_before_week_start", "snapshot_stage"
    ])
    if registry_path.exists() and registry_path.stat().st_size > 0 and not rebuild:
        registry_df = pd.read_csv(registry_path)
    registry_df = registry_df.fillna("")

    conflicts: list[dict[str, Any]] = []
    added_rows = 0
    unchanged_rows = 0
    discovered_snapshots: list[Path] = []
    weekly_rows: list[dict[str, Any]] = []
    change_rows: list[dict[str, Any]] = []
    discovery_warnings: list[str] = []

    for snapshot in _discover_logical_snapshots(project_root, source=source, season=season, week=week):
        raw_path = snapshot["raw_path"]
        component_raw_files = snapshot["component_raw_files"]
        metadata = _resolve_snapshot_metadata(raw_path, source=source, season=season, week=week)
        if metadata.source == "fantasypros":
            metadata = SnapshotMetadata(
                source=metadata.source,
                season=metadata.season,
                week=metadata.week,
                raw_file=raw_path,
                captured_at=metadata.captured_at,
                captured_at_source=metadata.captured_at_source,
            )
        discovered_snapshots.append(raw_path)
        output_paths = build_output_paths(output_root, source=metadata.source, season=metadata.season, week=metadata.week, raw_file=raw_path)
        long_path = output_paths["long_path"]
        if not long_path.exists():
            if source is None and metadata.source == "fantasypros":
                discovery_warnings.append(f"unprocessed_fantasypros_snapshot_skipped={_to_repo_relative(raw_path, project_root=project_root)}")
                continue
            raise ValueError(f"Missing required long-format file for snapshot: {raw_path}")

        long_df = pd.read_csv(long_path)
        rejected_path = output_paths["rejected_path"]
        validation_path = output_paths["validation_path"]
        try:
            rejected_df = pd.read_csv(rejected_path) if rejected_path.exists() and rejected_path.stat().st_size > 0 else pd.DataFrame()
        except EmptyDataError:
            rejected_df = pd.DataFrame()
        try:
            validation_df = pd.read_csv(validation_path) if validation_path.exists() and validation_path.stat().st_size > 0 else pd.DataFrame()
        except EmptyDataError:
            validation_df = pd.DataFrame()

        row = _build_registry_row(raw_path, project_root=project_root, output_root=output_root, metadata=metadata, long_df=long_df, rejected_df=rejected_df, validation_df=validation_df, registry_updated_at=datetime.now(timezone.utc), component_raw_files=component_raw_files)
        row_hash = row["raw_file_sha256"]

        existing_match = registry_df.loc[registry_df["raw_file_sha256"] == row_hash] if not registry_df.empty else pd.DataFrame()
        if not existing_match.empty:
            existing = existing_match.iloc[0].to_dict()
            if existing.get("source") == row["source"] and existing.get("season") == row["season"] and existing.get("week") == row["week"] and existing.get("captured_at") == row["captured_at"] and existing.get("captured_at_source") == row["captured_at_source"] and existing.get("processed_long_file") == row["processed_long_file"]:
                unchanged_rows += 1
                continue
            conflicts.append({
                "source": metadata.source,
                "season": int(metadata.season),
                "week": int(metadata.week),
                "raw_file_sha256": row_hash,
                "reason": "conflicting_metadata_for_existing_hash",
                "existing_row": str(existing.get("raw_file")),
                "new_row": row["raw_file"],
            })
            continue

        processed_match = registry_df.loc[registry_df["processed_long_file"] == row["processed_long_file"]] if not registry_df.empty else pd.DataFrame()
        if not processed_match.empty and str(processed_match.iloc[0].get("processed_file_sha256", "")) != row["processed_file_sha256"]:
            conflicts.append({
                "source": metadata.source,
                "season": int(metadata.season),
                "week": int(metadata.week),
                "raw_file_sha256": row_hash,
                "reason": "processed_file_hash_conflict",
                "existing_row": str(processed_match.iloc[0].get("processed_long_file")),
                "new_row": row["processed_long_file"],
            })
            continue

        registry_df = pd.concat([registry_df, pd.DataFrame([row])], ignore_index=True)
        added_rows += 1
        weekly_rows.append({
            "long_df": long_df,
            "rejected_df": rejected_df,
            "source": metadata.source,
            "season": int(metadata.season),
            "week": int(metadata.week),
            "captured_at": row["captured_at"],
            "snapshot_hash": row_hash,
        })

    if not rebuild and registry_df.empty:
        registry_df = pd.DataFrame(columns=[
            "source", "season", "week", "source_format", "captured_at", "captured_at_source", "endpoint_path", "response_status",
            "rate_limit_limit", "rate_limit_remaining", "rate_limit_reset", "raw_file", "raw_file_name", "raw_file_sha256",
            "raw_file_size_bytes", "component_raw_files", "component_raw_file_names", "component_raw_file_sha256", "logical_snapshot_hash",
            "processed_long_file", "processed_rejected_file", "processed_validation_file", "processed_file_sha256",
            "ingested_at", "registry_updated_at", "raw_rows", "canonical_rows", "unique_players", "unique_teams", "positions_covered",
            "markets_covered", "market_count", "rejected_rows", "rejection_rate", "duplicate_canonical_keys", "validation_status",
            "warning_count", "warnings", "adapter_version", "schema_version", "days_before_week_start", "snapshot_stage"
        ])

    if not registry_df.empty:
        registry_df.to_csv(registry_path, index=False)
    if conflicts:
        pd.DataFrame(conflicts).to_csv(conflicts_path, index=False)
    else:
        pd.DataFrame(columns=["source", "season", "week", "raw_file_sha256", "reason", "existing_row", "new_row"]).to_csv(conflicts_path, index=False)

    weekly_df = pd.DataFrame(columns=["source", "season", "week", "captured_at", "market", "rows", "unique_players", "unique_teams", "positions_covered", "projection_mean", "projection_median", "projection_std", "projection_min", "projection_max", "rejected_rows_for_snapshot", "snapshot_hash"])
    for snapshot in weekly_rows:
        weekly_df = pd.concat([weekly_df, build_weekly_coverage(snapshot["long_df"], source=snapshot["source"], season=snapshot["season"], week=snapshot["week"], captured_at=snapshot["captured_at"], snapshot_hash=snapshot["snapshot_hash"], rejected_df=snapshot["rejected_df"])], ignore_index=True)
    if not weekly_df.empty:
        weekly_df = weekly_df.drop_duplicates(subset=["source", "season", "week", "captured_at", "market"]).sort_values(["source", "season", "week", "captured_at", "market"]).reset_index(drop=True)
    weekly_df.to_csv(coverage_root / "weekly_coverage.csv", index=False)

    change_df = pd.DataFrame(columns=["source", "season", "week", "prior_captured_at", "current_captured_at", "shared_players", "added_players", "removed_players", "changed_players", "unchanged_players", "mean_absolute_change", "median_absolute_change", "maximum_absolute_change", "largest_increase_player", "largest_increase_value", "largest_decrease_player", "largest_decrease_value"])
    if weekly_rows:
        grouped: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
        for snapshot in weekly_rows:
            key = (snapshot["source"], int(snapshot["season"]), int(snapshot["week"]))
            grouped.setdefault(key, []).append(snapshot)
        for key, snapshots in grouped.items():
            snapshots_sorted = sorted(snapshots, key=lambda item: item["captured_at"])
            for index in range(1, len(snapshots_sorted)):
                prior = snapshots_sorted[index - 1]
                current = snapshots_sorted[index]
                change_df = pd.concat([change_df, build_snapshot_change_report(prior["long_df"], current["long_df"], source=key[0], season=key[1], week=key[2])], ignore_index=True)
    change_df.to_csv(coverage_root / "snapshot_changes.csv", index=False)

    for snapshot in weekly_rows:
        week_value = int(snapshot["week"])
        week_token = f"week_{week_value:02d}"
        captured_token = _sanitize_name(snapshot["captured_at"].replace(":", "").replace("-", ""))
        snapshot_name = f"{snapshot['source']}_{snapshot['season']}_{week_token}_{captured_token}_coverage.csv"
        coverage_path = coverage_root / snapshot_name
        coverage_rows = _build_coverage_rows(snapshot["long_df"], snapshot["rejected_df"])
        _write_snapshot_coverage_report(coverage_rows, output_path=coverage_path)

    return {
        "project_root": str(project_root),
        "processed_root": str(processed_root),
        "registry_path": str(registry_path),
        "conflicts_path": str(conflicts_path),
        "registry_rows": registry_df.to_dict(orient="records"),
        "added_rows": added_rows,
        "unchanged_rows": unchanged_rows,
        "conflicts": conflicts,
        "coverage_reports_written": len(weekly_rows),
        "weekly_coverage_rows_written": int(len(weekly_df)),
        "snapshot_comparison_rows_written": int(len(change_df)),
        "output_paths": {
            "registry": str(registry_path),
            "conflicts": str(conflicts_path),
            "weekly_coverage": str(coverage_root / "weekly_coverage.csv"),
            "snapshot_changes": str(coverage_root / "snapshot_changes.csv"),
        },
        "warnings": [*discovery_warnings, *[row["warnings"] for row in registry_df.to_dict(orient="records") if row.get("warnings")]],
    }
