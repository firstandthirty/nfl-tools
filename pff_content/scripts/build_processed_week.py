from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pff_content.client import PFFClient
from pff_content.datasets import DATASETS
from pff_content.normalize import build_team_games, normalize_rows
from pff_content.paths import processed_week_dir
from pff_content.schemas import build_schema_inventory, validation_report
from pff_content.week_status import read_week_status, status_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build processed PFF weekly CSV tables from cached raw data.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--fetch-missing", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    status = read_week_status(args.season, args.week)
    if status is None:
        print("WARNING: PFF week completeness metadata is missing. Processed outputs may be provisional.", file=sys.stderr)
    elif not status.is_complete:
        print("WARNING: PFF has not processed all games for this week.", file=sys.stderr)
        print(f"Processed outputs are provisional ({status_summary(status)}).", file=sys.stderr)

    client = PFFClient() if args.fetch_missing else None
    processed: dict[str, pd.DataFrame] = {}
    column_maps: dict[str, dict[str, str]] = {}
    cache_hits = 0
    api_calls = 0
    games_context: dict[str, dict[str, object]] = {}
    raw_bodies: dict[str, object] = {}
    for spec in DATASETS:
        params = {"league": "nfl", "season": args.season, "week": args.week}
        body = None
        response = None
        if client is not None:
            response = client.get(spec.endpoint, params=params, dataset=spec.name, season=args.season, week=args.week, table=spec.table, use_cache=True)
            body = response.body
            cache_hits += 1 if response.cache_hit else 0
            api_calls += 0 if response.cache_hit else 1
        else:
            from pff_content.cache import RawCache

            body = RawCache().read(season=args.season, week=args.week, dataset=spec.name, path=spec.endpoint, params=params)
            if body is None:
                raise RuntimeError(f"Missing raw cache for {spec.name}; run fetch_week.py or use --fetch-missing")
            cache_hits += 1
        raw_bodies[spec.name] = body
        if spec.name == "games":
            games, column_map = normalize_rows(spec.name, body, table=spec.table, season=args.season, week=args.week)
            processed[spec.name] = games
            column_maps[spec.name] = column_map
            games_context = build_team_games(games)
    for spec in DATASETS:
        if spec.name == "games":
            continue
        df, column_map = normalize_rows(
            spec.name,
            raw_bodies[spec.name],
            table=spec.table,
            season=args.season,
            week=args.week,
            team_games=games_context,
        )
        processed[spec.name] = df
        column_maps[spec.name] = column_map
    out_dir = processed_week_dir(args.season, args.week)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for spec in DATASETS:
        df = processed[spec.name]
        df.to_csv(out_dir / f"{spec.name}.csv", index=False)
        summary.append({"dataset": spec.name, "rows": len(df), "columns": len(df.columns)})
    inventory = build_schema_inventory(processed, column_maps)
    validation = validation_report(processed)
    inventory.to_csv(out_dir / "schema_inventory.csv", index=False)
    validation.to_csv(out_dir / "validation_report.csv", index=False)
    print(json.dumps({"season": args.season, "week": args.week, "api_calls": api_calls, "cache_hits": cache_hits, "week_status": status.to_dict() if status else None, "processed": summary}, indent=2))


if __name__ == "__main__":
    main()
