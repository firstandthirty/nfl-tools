from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from projection_adapters.common import (
    PROJECT_ROOT as COMMON_PROJECT_ROOT,
    append_weekly_rows,
    build_output_paths,
    discover_snapshot_files,
    isoformat_with_offset,
    parse_snapshot_metadata,
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest projection snapshots")
    parser.add_argument("--source", required=True)
    parser.add_argument("--season", type=int)
    parser.add_argument("--week", type=int)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--skip-registry-update", action="store_true")
    args = parser.parse_args()

    if args.input:
        raw_files = [Path(args.input)]
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

    print("[ingested]", ingested)
    print("[skipped]", skipped)
    print("[rows_written]", rows_written)
    print("[warnings]", warnings)
    if registry_errors:
        print("[registry_errors]", registry_errors)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
