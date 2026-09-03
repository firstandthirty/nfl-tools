from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from projection_adapters.common import (
    PROJECT_ROOT as COMMON_PROJECT_ROOT,
    SnapshotMetadata,
    append_weekly_rows,
    build_output_paths,
    discover_snapshot_files,
    isoformat_with_offset,
    parse_snapshot_metadata,
)
from projection_adapters.fantasypros import (
    build_api_validation_report as build_fantasypros_api_validation_report,
    build_sanity_warnings as build_fantasypros_sanity_warnings,
    build_validation_report as build_fantasypros_validation_report,
    identify_source_file_type,
    transform_fantasypros_api_snapshot,
    transform_fantasypros_snapshot,
)
from projection_adapters.pff import build_validation_report, transform_pff_snapshot
from projection_registry.registry import build_projection_registry


def ingest_snapshot_file(raw_file: Path | str, *, source: str, season: int | str, week: int | str, output_root: Path | str, manifest_path: Path | str | None = None, weekly_output_path: Path | str | None = None, skip_registry_update: bool = False) -> dict:
    raw_path = Path(raw_file)
    metadata = parse_snapshot_metadata(raw_path, source=source, season=season, week=week)
    output_paths = build_output_paths(output_root, source=source, season=season, week=week, raw_file=raw_path)

    manifest_path = Path(manifest_path) if manifest_path is not None else output_paths["output_dir"] / "ingested_snapshots.csv"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_df = pd.DataFrame(columns=["source", "season", "week", "raw_file", "captured_at", "captured_at_source"])
    if manifest_path.exists() and manifest_path.stat().st_size > 0:
        manifest_df = pd.read_csv(manifest_path)
    raw_file_key = str(raw_path.resolve())
    if raw_file_key in manifest_df["raw_file"].astype(str).tolist() if not manifest_df.empty else False:
        raw_df = pd.read_csv(raw_path)
        rows, rejected = transform_pff_snapshot(raw_df, metadata=metadata, source=source)
        return {"skipped": True, "rows_written": len(rows), "output_paths": {"long": str(output_paths["long_path"]), "validation": str(output_paths["validation_path"]), "rejected": str(output_paths["rejected_path"])} }

    raw_df = pd.read_csv(raw_path)
    rows, rejected = transform_pff_snapshot(raw_df, metadata=metadata, source=source)
    warnings: list[str] = []
    if metadata.captured_at_source != "filename":
        warnings.append(f"capture_time_fallback={metadata.captured_at_source}")

    long_df = pd.DataFrame(rows)
    if not long_df.empty:
        long_df = long_df[[col for col in long_df.columns if col in [*['player','player_normalized','team','team_raw','position','season','week','source','market','projection','captured_at','captured_at_source','raw_file','source_player_id','source_row_number','source_column']]]]
    validation_df = build_validation_report(raw_df, rows, rejected, metadata, warnings)

    output_paths["long_path"].parent.mkdir(parents=True, exist_ok=True)
    long_df.to_csv(output_paths["long_path"], index=False)
    validation_df.to_csv(output_paths["validation_path"], index=False)
    pd.DataFrame(rejected).to_csv(output_paths["rejected_path"], index=False)

    weekly_output_path = Path(weekly_output_path) if weekly_output_path is not None else output_paths["output_dir"] / "projections_long.csv"
    weekly_output_path.parent.mkdir(parents=True, exist_ok=True)
    appended = append_weekly_rows(
        weekly_output_path,
        rows,
        identity_columns=["source", "season", "week", "captured_at", "player_normalized", "market"],
    )
    appended.to_csv(weekly_output_path, index=False)

    manifest_df = pd.concat([manifest_df, pd.DataFrame([{"source": source, "season": season, "week": week, "raw_file": raw_file_key, "captured_at": isoformat_with_offset(metadata.captured_at), "captured_at_source": metadata.captured_at_source}])], ignore_index=True)
    manifest_df.to_csv(manifest_path, index=False)

    registry_result = {}
    if not skip_registry_update:
        try:
            registry_result = build_projection_registry(project_root=COMMON_PROJECT_ROOT, output_root=COMMON_PROJECT_ROOT, source=source, season=season, week=week)
        except Exception as exc:
            registry_result = {"registry_error": str(exc)}

    return {
        "skipped": False,
        "rows_written": len(rows),
        "output_paths": {
            "long": str(output_paths["long_path"]),
            "validation": str(output_paths["validation_path"]),
            "rejected": str(output_paths["rejected_path"]),
            "weekly": str(weekly_output_path),
        },
        "warnings": warnings,
        "registry_result": registry_result,
    }


def _timestamp_stem(path: Path) -> str:
    parts = path.stem.split("_")
    if len(parts) < 4:
        raise ValueError(f"FantasyPros filename does not start with MM_DD_YY_HHMM timestamp: {path}")
    return "_".join(parts[:4])


def _group_fantasypros_files(raw_files: list[Path]) -> list[list[Path]]:
    groups: dict[str, dict[str, Path]] = {}
    for raw_file in raw_files:
        file_type = identify_source_file_type(raw_file)
        timestamp = _timestamp_stem(raw_file)
        if file_type in groups.setdefault(timestamp, {}):
            raise ValueError(f"Duplicate FantasyPros {file_type} component for timestamp {timestamp}")
        groups[timestamp][file_type] = raw_file

    logical_snapshots: list[list[Path]] = []
    for timestamp, components in sorted(groups.items()):
        missing = sorted({"qb", "flex"} - set(components))
        if missing:
            raise ValueError(f"Incomplete FantasyPros logical snapshot {timestamp}; missing components: {', '.join(missing)}")
        logical_snapshots.append([components["qb"], components["flex"]])
    return logical_snapshots


def ingest_fantasypros_snapshot(
    raw_files: list[Path | str],
    *,
    season: int | str,
    week: int | str,
    output_root: Path | str,
    manifest_path: Path | str | None = None,
    weekly_output_path: Path | str | None = None,
    skip_registry_update: bool = False,
) -> dict:
    raw_paths = [Path(path) for path in raw_files]
    if len(raw_paths) != 2:
        raise ValueError("FantasyPros logical snapshots require exactly two files: QB and FLEX")
    components = {identify_source_file_type(path): path for path in raw_paths}
    missing = sorted({"qb", "flex"} - set(components))
    if missing:
        raise ValueError(f"Incomplete FantasyPros logical snapshot; missing components: {', '.join(missing)}")
    if _timestamp_stem(components["qb"]) != _timestamp_stem(components["flex"]):
        raise ValueError("FantasyPros QB and FLEX files must share the same timestamp prefix")

    timestamp = _timestamp_stem(components["qb"])
    synthetic_raw_file = components["qb"].with_name(f"{timestamp}_projections.csv")
    metadata = parse_snapshot_metadata(synthetic_raw_file, source="fantasypros", season=season, week=week)
    metadata = SnapshotMetadata(
        source="fantasypros",
        season=metadata.season,
        week=metadata.week,
        raw_file=synthetic_raw_file,
        captured_at=metadata.captured_at,
        captured_at_source=metadata.captured_at_source,
    )
    output_paths = build_output_paths(output_root, source="fantasypros", season=season, week=week, raw_file=synthetic_raw_file)

    manifest_path = Path(manifest_path) if manifest_path is not None else output_paths["output_dir"] / "ingested_snapshots.csv"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_columns = ["source", "season", "week", "raw_file", "component_raw_files", "captured_at", "captured_at_source"]
    manifest_df = pd.DataFrame(columns=manifest_columns)
    if manifest_path.exists() and manifest_path.stat().st_size > 0:
        manifest_df = pd.read_csv(manifest_path)
    component_key = "|".join(str(components[k].resolve()) for k in ["qb", "flex"])
    if not manifest_df.empty and component_key in manifest_df.get("component_raw_files", pd.Series(dtype=str)).astype(str).tolist():
        raw_frames = {}
        for file_type, path in components.items():
            frame = pd.read_csv(path)
            frame.attrs["raw_file"] = str(path)
            raw_frames[file_type] = frame
        rows, _ = transform_fantasypros_snapshot(raw_frames, metadata=metadata)
        return {"skipped": True, "rows_written": len(rows), "output_paths": {"long": str(output_paths["long_path"]), "validation": str(output_paths["validation_path"]), "rejected": str(output_paths["rejected_path"])}}

    raw_frames = {}
    for file_type, path in components.items():
        frame = pd.read_csv(path)
        frame.attrs["raw_file"] = str(path)
        raw_frames[file_type] = frame
    rows, rejected = transform_fantasypros_snapshot(raw_frames, metadata=metadata)
    warnings = build_fantasypros_sanity_warnings(rows)
    if metadata.captured_at_source != "filename":
        warnings.append(f"capture_time_fallback={metadata.captured_at_source}")

    columns = [
        "player", "player_normalized", "team", "team_raw", "position", "season", "week", "source", "market",
        "projection", "captured_at", "captured_at_source", "raw_file", "source_file_type", "source_player_id",
        "source_row_number", "source_column",
    ]
    long_df = pd.DataFrame(rows)
    for column in columns:
        if column not in long_df.columns:
            long_df[column] = pd.NA
    validation_df = build_fantasypros_validation_report(raw_frames, rows, rejected, metadata, warnings)

    output_paths["long_path"].parent.mkdir(parents=True, exist_ok=True)
    long_df[columns].to_csv(output_paths["long_path"], index=False)
    validation_df.to_csv(output_paths["validation_path"], index=False)
    pd.DataFrame(rejected).to_csv(output_paths["rejected_path"], index=False)

    weekly_output_path = Path(weekly_output_path) if weekly_output_path is not None else output_paths["output_dir"] / "projections_long.csv"
    appended = append_weekly_rows(
        weekly_output_path,
        rows,
        identity_columns=["source", "season", "week", "captured_at", "player_normalized", "market"],
    )
    appended.to_csv(weekly_output_path, index=False)

    manifest_df = pd.concat(
        [
            manifest_df,
            pd.DataFrame(
                [
                    {
                        "source": "fantasypros",
                        "season": season,
                        "week": week,
                        "raw_file": str(synthetic_raw_file),
                        "component_raw_files": component_key,
                        "captured_at": isoformat_with_offset(metadata.captured_at),
                        "captured_at_source": metadata.captured_at_source,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    manifest_df.to_csv(manifest_path, index=False)

    registry_result = {}
    if not skip_registry_update:
        try:
            registry_result = build_projection_registry(project_root=COMMON_PROJECT_ROOT, output_root=COMMON_PROJECT_ROOT, source="fantasypros", season=season, week=week)
        except Exception as exc:
            registry_result = {"registry_error": str(exc)}

    return {
        "skipped": False,
        "rows_written": len(rows),
        "output_paths": {
            "long": str(output_paths["long_path"]),
            "validation": str(output_paths["validation_path"]),
            "rejected": str(output_paths["rejected_path"]),
            "weekly": str(weekly_output_path),
        },
        "warnings": warnings,
        "registry_result": registry_result,
    }


def ingest_fantasypros_api_snapshot(
    raw_file: Path | str,
    *,
    season: int | str,
    week: int | str,
    captured_at,
    output_root: Path | str,
    manifest_path: Path | str | None = None,
    weekly_output_path: Path | str | None = None,
    skip_registry_update: bool = False,
    endpoint_path: str = "",
    response_status: int | str = "",
    metadata_file: Path | str | None = None,
) -> dict:
    raw_path = Path(raw_file)
    metadata = SnapshotMetadata(
        source="fantasypros",
        season=int(season),
        week=int(week),
        raw_file=raw_path,
        captured_at=captured_at,
        captured_at_source="api_request",
    )
    output_paths = build_output_paths(output_root, source="fantasypros", season=season, week=week, raw_file=raw_path)
    manifest_path = Path(manifest_path) if manifest_path is not None else output_paths["output_dir"] / "ingested_snapshots.csv"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_columns = [
        "source", "season", "week", "raw_file", "component_raw_files", "captured_at", "captured_at_source",
        "source_format", "endpoint_path", "response_status", "metadata_file",
    ]
    manifest_df = pd.DataFrame(columns=manifest_columns)
    if manifest_path.exists() and manifest_path.stat().st_size > 0:
        manifest_df = pd.read_csv(manifest_path)
    raw_file_key = str(raw_path.resolve())
    if not manifest_df.empty and raw_file_key in manifest_df.get("raw_file", pd.Series(dtype=str)).astype(str).tolist():
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        rows, _ = transform_fantasypros_api_snapshot(payload, raw_file=raw_path, metadata=metadata)
        return {"skipped": True, "rows_written": len(rows), "output_paths": {"long": str(output_paths["long_path"]), "validation": str(output_paths["validation_path"]), "rejected": str(output_paths["rejected_path"])}}

    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    rows, rejected = transform_fantasypros_api_snapshot(payload, raw_file=raw_path, metadata=metadata)
    warnings = build_fantasypros_sanity_warnings(rows)
    if not rows:
        warnings.append("empty_fantasypros_api_snapshot")

    columns = [
        "player", "player_normalized", "team", "team_raw", "position", "season", "week", "source", "market",
        "projection", "captured_at", "captured_at_source", "raw_file", "source_format", "source_file_type",
        "source_player_id", "fantasypros_player_id", "source_row_number", "source_column", "source_json_path",
        "endpoint_component",
    ]
    long_df = pd.DataFrame(rows)
    for column in columns:
        if column not in long_df.columns:
            long_df[column] = pd.NA
    validation_df = build_fantasypros_api_validation_report(payload, rows, rejected, metadata, warnings)

    output_paths["long_path"].parent.mkdir(parents=True, exist_ok=True)
    long_df[columns].to_csv(output_paths["long_path"], index=False)
    validation_df.to_csv(output_paths["validation_path"], index=False)
    pd.DataFrame(rejected).to_csv(output_paths["rejected_path"], index=False)

    weekly_output_path = Path(weekly_output_path) if weekly_output_path is not None else output_paths["output_dir"] / "projections_long.csv"
    appended = append_weekly_rows(
        weekly_output_path,
        rows,
        identity_columns=["source", "season", "week", "captured_at", "player_normalized", "market"],
    )
    appended.to_csv(weekly_output_path, index=False)

    manifest_df = pd.concat(
        [
            manifest_df,
            pd.DataFrame(
                [
                    {
                        "source": "fantasypros",
                        "season": season,
                        "week": week,
                        "raw_file": raw_file_key,
                        "component_raw_files": raw_file_key,
                        "captured_at": isoformat_with_offset(metadata.captured_at),
                        "captured_at_source": metadata.captured_at_source,
                        "source_format": "api",
                        "endpoint_path": endpoint_path,
                        "response_status": response_status,
                        "metadata_file": str(Path(metadata_file).resolve()) if metadata_file else "",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    manifest_df.to_csv(manifest_path, index=False)

    registry_result = {}
    if not skip_registry_update:
        try:
            registry_result = build_projection_registry(project_root=COMMON_PROJECT_ROOT, output_root=COMMON_PROJECT_ROOT, source="fantasypros", season=season, week=week)
        except Exception as exc:
            registry_result = {"registry_error": str(exc)}

    return {
        "skipped": False,
        "rows_written": len(rows),
        "output_paths": {
            "long": str(output_paths["long_path"]),
            "validation": str(output_paths["validation_path"]),
            "rejected": str(output_paths["rejected_path"]),
            "weekly": str(weekly_output_path),
        },
        "warnings": warnings,
        "registry_result": registry_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest projection snapshots")
    parser.add_argument("--source", required=True)
    parser.add_argument("--season", type=int)
    parser.add_argument("--week", type=int)
    parser.add_argument("--input", type=Path, nargs="*")
    parser.add_argument("--skip-registry-update", action="store_true")
    args = parser.parse_args()

    if args.input:
        raw_files = [Path(path) for path in args.input]
        source = args.source
        season = args.season or 2026
        week = args.week or 1
    else:
        source = args.source
        season = args.season
        week = args.week
        if season is None or week is None:
            raise ValueError("--season and --week are required when --input is not provided")
        raw_files = discover_snapshot_files(COMMON_PROJECT_ROOT, source=source, season=season, week=week)

    print("[discovered]", [str(path) for path in raw_files])

    ingested: list[str] = []
    skipped: list[str] = []
    rows_written = 0
    warnings: list[str] = []
    registry_errors: list[str] = []
    if source == "fantasypros":
        api_files = [path for path in raw_files if path.suffix.lower() == ".json"]
        csv_files = [path for path in raw_files if path.suffix.lower() != ".json"]
        if api_files and csv_files:
            raise ValueError("Ingest API JSON and FantasyPros CSV snapshots separately")
        if api_files:
            raise ValueError("Use download_fantasypros_projections.py for API JSON snapshots so captured_at_source=api_request is preserved")
        logical_snapshots = _group_fantasypros_files(csv_files)
        for logical_files in logical_snapshots:
            result = ingest_fantasypros_snapshot(logical_files, season=season, week=week, output_root=COMMON_PROJECT_ROOT, skip_registry_update=args.skip_registry_update)
            if result.get("skipped"):
                skipped.extend(str(path) for path in logical_files)
            else:
                ingested.extend(str(path) for path in logical_files)
            rows_written += result.get("rows_written", 0)
            warnings.extend(result.get("warnings", []))
            registry_result = result.get("registry_result", {})
            if registry_result.get("registry_error"):
                registry_errors.append(registry_result["registry_error"])
    elif source == "pff":
        for raw_file in raw_files:
            result = ingest_snapshot_file(raw_file, source=source, season=season, week=week, output_root=COMMON_PROJECT_ROOT, skip_registry_update=args.skip_registry_update)
            if result.get("skipped"):
                skipped.append(str(raw_file))
            else:
                ingested.append(str(raw_file))
            rows_written += result.get("rows_written", 0)
            warnings.extend(result.get("warnings", []))
            registry_result = result.get("registry_result", {})
            if registry_result.get("registry_error"):
                registry_errors.append(registry_result["registry_error"])
    else:
        raise ValueError(f"Unsupported projection source: {source}")

    print("[ingested]", ingested)
    print("[skipped]", skipped)
    print("[rows_written]", rows_written)
    print("[warnings]", warnings)
    if registry_errors:
        print("[registry_errors]", registry_errors)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
