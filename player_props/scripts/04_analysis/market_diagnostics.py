#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from diagnostics.buckets import add_buckets, bucket_metadata_rows
from diagnostics.calibration import calibration_table
from diagnostics.interactions import interaction_table
from diagnostics.loader import read_input, standardize_frame
from diagnostics.metrics import bootstrap_roi_interval, summarize
from diagnostics.plotting import save_charts
from diagnostics.recommendations import candidate_kill_table, generate_candidate_rules
from diagnostics.reporting import write_report
from diagnostics.slicing import slice_table


DEFAULT_DIMENSIONS = ["side", "line_bucket", "season", "week", "team", "opponent"]
OPTIONAL_DIMENSIONS = ["position", "favorite_status", "spread_bucket", "total_bucket", "home_away", "implied_team_total_bucket", "book"]
INTERACTION_DIMENSIONS = ["side", "line_bucket", "projection_minus_line_bucket", "probability_bucket", "ev_bucket", "verified_edge_bucket", "season"]
THRESHOLD_COLUMNS = ["recommended_ev_percent_value", "predicted_probability", "projection_edge", "absolute_projection_edge"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Market-specific diagnostics for settled player-prop backtests.")
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--market", default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--min-slice-bets", type=int, default=15)
    parser.add_argument("--min-interaction-bets", type=int, default=30)
    parser.add_argument("--min-player-bets", type=int, default=8)
    parser.add_argument("--max-categories", type=int, default=40)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-charts", action="store_true")
    return parser.parse_args()


def market_name(df: pd.DataFrame, requested: str | None, input_path: Path) -> str:
    if requested:
        return requested
    if "market" in df and df["market"].dropna().nunique() == 1:
        return str(df["market"].dropna().iloc[0])
    return input_path.stem


def data_quality(raw: pd.DataFrame, df: pd.DataFrame, column_map: dict[str, str], metadata: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = [
        {"check": "input_rows", "value": len(raw)},
        {"check": "input_columns", "value": len(raw.columns)},
        {"check": "graded_rows", "value": int(df["profit_units"].notna().sum())},
        {"check": "ungraded_rows", "value": int(df["profit_units"].isna().sum())},
        {"check": "duplicate_full_rows", "value": int(raw.duplicated().sum())},
    ]
    for canonical in sorted(column_map):
        rows.append({"check": f"column_{canonical}", "value": column_map[canonical]})
    for col in ["side", "line_value", "projection_value", "predicted_probability", "recommended_ev_percent_value", "profit_units", "won", "pushed"]:
        if col in df:
            rows.append({"check": f"missing_{col}", "value": int(df[col].isna().sum())})
    for _, row in metadata.iterrows():
        if pd.notna(row.get("bucket_boundaries")) and str(row.get("bucket_boundaries")):
            rows.append({"check": f"bucket_{row['field']}", "value": f"{row['interpreted_unit']} | {row['bucket_boundaries']}"})
    return pd.DataFrame(rows)


def run(args: argparse.Namespace) -> int:
    raw = read_input(args.input_csv)
    loaded = standardize_frame(raw, market=args.market)
    df = add_buckets(loaded.df)
    metadata = pd.DataFrame(bucket_metadata_rows() + loaded.edge_metadata)
    market = market_name(df, args.market, args.input_csv)
    output_dir = args.output_dir or Path("data") / "analysis" / "market_diagnostics" / market
    output_dir.mkdir(parents=True, exist_ok=True)

    graded = df[df["profit_units"].notna()].copy()
    summary = summarize(graded)
    ci_low, ci_high = bootstrap_roi_interval(graded["profit_units"], args.bootstrap_samples, args.seed)
    overall = pd.DataFrame([{**{"market": market}, **summary, "roi_ci_95_low": ci_low, "roi_ci_95_high": ci_high}])
    quality = data_quality(raw, df, loaded.column_map, metadata)

    overall.to_csv(output_dir / "overall_summary.csv", index=False)
    quality.to_csv(output_dir / "data_quality.csv", index=False)
    metadata.to_csv(output_dir / "bucket_definitions.csv", index=False)

    calibrations = {
        "probability": calibration_table(graded, "predicted_probability", "probability_bucket", "recommended_probability", True, args.min_slice_bets),
        "ev": calibration_table(graded, "recommended_ev_percent_value", "ev_bucket", "recommended_ev_percent", False, args.min_slice_bets),
        "projection_minus_line": calibration_table(graded, "projection_edge", "projection_minus_line_bucket", "projection_minus_line", False, args.min_slice_bets),
        "verified_edge": calibration_table(graded, "absolute_projection_edge", "verified_edge_bucket", "absolute_projection_edge", False, args.min_slice_bets),
    }
    calibrations["probability"].to_csv(output_dir / "calibration_probability.csv", index=False)
    calibrations["ev"].to_csv(output_dir / "calibration_ev.csv", index=False)
    calibrations["projection_minus_line"].to_csv(output_dir / "calibration_projection_minus_line.csv", index=False)
    calibrations["verified_edge"].to_csv(output_dir / "calibration_verified_edge.csv", index=False)

    slices: dict[str, pd.DataFrame] = {}
    for dim in DEFAULT_DIMENSIONS + [d for d in OPTIONAL_DIMENSIONS if d in graded]:
        table = slice_table(graded, dim, args.min_slice_bets, args.max_categories)
        if not table.empty:
            slices[dim] = table
            table.to_csv(output_dir / f"slice_{dim}.csv", index=False)
    if "player" in graded:
        table = slice_table(graded, "player", args.min_player_bets, max(args.max_categories, graded["player"].nunique(dropna=True)))
        if not table.empty:
            slices["player"] = table
            table.to_csv(output_dir / "slice_player.csv", index=False)

    interactions = interaction_table(graded, INTERACTION_DIMENSIONS, args.min_interaction_bets, args.max_categories)
    interactions.to_csv(output_dir / "interactions.csv", index=False)
    rules = generate_candidate_rules(graded, INTERACTION_DIMENSIONS, THRESHOLD_COLUMNS, args.min_interaction_bets, args.max_categories)
    kill_rules = candidate_kill_table(graded, rules, min_remaining=max(args.min_interaction_bets, 50))
    kill_rules.to_csv(output_dir / "candidate_kill_rules.csv", index=False)

    warnings = loaded.warnings.copy()
    if not args.no_charts:
        warnings.extend(save_charts(output_dir, slices, calibrations["probability"]))
    write_report(output_dir, args.input_csv, market, overall, quality, calibrations, slices, interactions, kill_rules, metadata, warnings)

    print(f"Market: {market}")
    print(f"Rows read: {len(raw):,}")
    print(f"Graded bets: {summary['bets']:,}")
    print(f"ROI: {summary['roi']:.2%}")
    print(f"Profit: {summary['profit_units']:.2f} units")
    print(f"Output: {output_dir.resolve()}")
    return 0


def main() -> int:
    try:
        return run(parse_args())
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
