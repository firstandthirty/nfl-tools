from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from odds_adapters.common import append_unique_rows, build_output_paths, discover_snapshot_files, parse_snapshot_metadata
from odds_adapters.odds_api import build_validation_report, load_json_payload, transform_odds_api_snapshot
from odds_registry.registry import build_odds_registry


def ingest_snapshot_file(raw_file: Path | str, *, source: str, season: int | str, week: int | str, output_root: Path | str, captured_at: str | None = None, sportsbook: str | None = None, market: str | None = None, skip_registry_update: bool = False, overwrite: bool = False) -> dict:
    raw_path = Path(raw_file)
    metadata = parse_snapshot_metadata(raw_path, source=source, season=season, week=week, captured_at=captured_at)
    paths = build_output_paths(output_root, source=source, season=season, week=week, raw_file=raw_path)
    if paths["long_path"].exists() and not overwrite:
        weekly = pd.read_csv(paths["weekly_path"]) if paths["weekly_path"].exists() and paths["weekly_path"].stat().st_size > 0 else pd.DataFrame()
        return {"skipped": True, "rows_written": 0, "rejected_rows": 0, "main_line_rows": 0, "alternate_line_rows": 0, "sportsbooks": [], "markets": [], "output_paths": {key: str(value) for key, value in paths.items()}, "weekly_rows": len(weekly)}

    payload = load_json_payload(raw_path)
    rows, rejected, conflicts = transform_odds_api_snapshot(payload, metadata=metadata, sportsbook_filter=sportsbook, market_filter=market, project_root=PROJECT_ROOT)
    long_df = pd.DataFrame(rows)
    for column in [] if long_df.empty else []:
        long_df[column] = pd.NA
    validation_df = build_validation_report(payload, rows, rejected, conflicts)

    paths["output_dir"].mkdir(parents=True, exist_ok=True)
    long_df.to_csv(paths["long_path"], index=False)
    pd.DataFrame(rejected).to_csv(paths["rejected_path"], index=False)
    validation_df.to_csv(paths["validation_path"], index=False)
    pd.DataFrame(conflicts, columns=["reason", "identity", "existing_price", "new_price"]).to_csv(paths["conflicts_path"], index=False)
    weekly_df, weekly_conflicts = append_unique_rows(paths["weekly_path"], rows, conflict_path=paths["output_dir"] / "odds_long_conflicts.csv")
    weekly_df.to_csv(paths["weekly_path"], index=False)

    registry_result = {}
    if not skip_registry_update:
        try:
            registry_result = build_odds_registry(project_root=PROJECT_ROOT, output_root=output_root, source=source, season=season, week=week)
        except Exception as exc:
            registry_result = {"registry_error": str(exc)}

    sportsbooks = sorted(long_df["sportsbook"].dropna().astype(str).unique().tolist()) if not long_df.empty else []
    markets = sorted(long_df["market"].dropna().astype(str).unique().tolist()) if not long_df.empty else []
    return {
        "skipped": False,
        "rows_written": len(rows),
        "rejected_rows": len(rejected),
        "main_line_rows": int((long_df["is_alternate"] == False).sum()) if not long_df.empty else 0,
        "alternate_line_rows": int((long_df["is_alternate"] == True).sum()) if not long_df.empty else 0,
        "sportsbooks": sportsbooks,
        "markets": markets,
        "weekly_conflicts": len(weekly_conflicts),
        "registry_result": registry_result,
        "output_paths": {key: str(value) for key, value in paths.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest saved sportsbook odds snapshots without live API requests")
    parser.add_argument("--source", required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--captured-at")
    parser.add_argument("--skip-registry-update", action="store_true")
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--sportsbook")
    parser.add_argument("--market")
    args = parser.parse_args()

    raw_files = [args.input] if args.input else discover_snapshot_files(PROJECT_ROOT, source=args.source, season=args.season, week=args.week)
    print("[discovered]", [str(path) for path in raw_files])
    ingested: list[str] = []
    skipped: list[str] = []
    rows_written = 0
    rejected_rows = 0
    main_rows = 0
    alternate_rows = 0
    sportsbooks: set[str] = set()
    markets: set[str] = set()
    output_paths: list[dict] = []
    warnings: list[str] = []

    for raw_file in raw_files:
        result = ingest_snapshot_file(raw_file, source=args.source, season=args.season, week=args.week, output_root=args.output_root, captured_at=args.captured_at, sportsbook=args.sportsbook, market=args.market, skip_registry_update=args.skip_registry_update, overwrite=args.overwrite)
        if result["skipped"]:
            skipped.append(str(raw_file))
        else:
            ingested.append(str(raw_file))
        rows_written += result.get("rows_written", 0)
        rejected_rows += result.get("rejected_rows", 0)
        main_rows += result.get("main_line_rows", 0)
        alternate_rows += result.get("alternate_line_rows", 0)
        sportsbooks.update(result.get("sportsbooks", []))
        markets.update(result.get("markets", []))
        output_paths.append(result.get("output_paths", {}))
        registry_result = result.get("registry_result", {})
        if registry_result.get("registry_error"):
            warnings.append(registry_result["registry_error"])

    print("[ingested]", ingested)
    print("[skipped]", skipped)
    print("[canonical_rows]", rows_written)
    print("[rejection_rows]", rejected_rows)
    print("[main_line_rows]", main_rows)
    print("[alternate_line_rows]", alternate_rows)
    print("[sportsbooks]", sorted(sportsbooks))
    print("[markets]", sorted(markets))
    print("[output_paths]", output_paths)
    print("[warnings]", warnings)
    if warnings:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

