from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSING_DIR = PROJECT_ROOT / "scripts" / "02_processing"
if str(PROCESSING_DIR) not in sys.path:
    sys.path.insert(0, str(PROCESSING_DIR))

from projection_consensus.aggregation import build_consensus_rows
from projection_consensus.loader import load_snapshot_registry

SOURCES = ["pff", "fantasypros", "ftn", "4for4"]


def _slug(value: str) -> str:
    return value.replace(":", "").replace("-", "").replace("+", "")


def _sets(rows: pd.DataFrame) -> dict[str, set[tuple[str, str]]]:
    return {
        source: set(
            rows.loc[rows["source"].astype(str) == source, ["player_normalized", "market"]]
            .astype(str)
            .apply(tuple, axis=1)
            .tolist()
        )
        for source in SOURCES
    }


def _coverage(rows: pd.DataFrame) -> pd.DataFrame:
    return rows.groupby(["source", "market"]).agg(rows=("player_normalized", "size"), unique_players=("player_normalized", "nunique")).reset_index()


def _overlap(rows: pd.DataFrame) -> pd.DataFrame:
    out = []
    markets = ["all", *sorted(rows["market"].dropna().astype(str).unique())]
    for market in markets:
        scoped = rows if market == "all" else rows.loc[rows["market"].astype(str) == market]
        source_sets = _sets(scoped)
        fourforfour = source_sets["4for4"]
        out.append(
            {
                "market": market,
                "fourforfour_rows": len(fourforfour),
                "ftn_rows": len(source_sets["ftn"]),
                "pff_rows": len(source_sets["pff"]),
                "fantasypros_rows": len(source_sets["fantasypros"]),
                "fourforfour_pff_overlap": len(fourforfour & source_sets["pff"]),
                "fourforfour_fantasypros_overlap": len(fourforfour & source_sets["fantasypros"]),
                "fourforfour_ftn_overlap": len(fourforfour & source_sets["ftn"]),
                "all_four_overlap": len(set.intersection(*source_sets.values())),
                "fourforfour_only": len(fourforfour - source_sets["pff"] - source_sets["fantasypros"] - source_sets["ftn"]),
            }
        )
    return pd.DataFrame(out)


def _pairwise(rows: pd.DataFrame) -> pd.DataFrame:
    out = []
    for source_b in ["pff", "fantasypros", "ftn"]:
        left = rows.loc[rows["source"].astype(str) == "4for4", ["player_normalized", "market", "projection"]]
        right = rows.loc[rows["source"].astype(str) == source_b, ["player_normalized", "market", "projection"]]
        merged = left.merge(right, on=["player_normalized", "market"], suffixes=("_a", "_b"))
        for market, group in merged.groupby("market"):
            diff = group["projection_a"].astype(float) - group["projection_b"].astype(float)
            abs_diff = diff.abs()
            out.append(
                {
                    "market": market,
                    "source_a": "4for4",
                    "source_b": source_b,
                    "count": int(len(group)),
                    "mean_diff_a_minus_b": float(diff.mean()),
                    "median_diff_a_minus_b": float(diff.median()),
                    "mean_abs_diff": float(abs_diff.mean()),
                    "p50_abs_diff": float(abs_diff.quantile(0.5)),
                    "p90_abs_diff": float(abs_diff.quantile(0.9)),
                }
            )
    return pd.DataFrame(out)


def _all_four_dispersion(consensus: pd.DataFrame) -> pd.DataFrame:
    rows = consensus.loc[consensus["projection_count"].astype(int) == 4].copy()
    out = []
    for market, group in rows.groupby("market"):
        out.append(
            {
                "market": market,
                "all_four_rows": int(len(group)),
                "projection_mean_mean": float(group["projection_mean"].mean()),
                "projection_median_mean": float(group["projection_median"].mean()),
                "projection_range_p25": float(group["projection_range"].quantile(0.25)),
                "projection_range_p50": float(group["projection_range"].quantile(0.50)),
                "projection_range_p75": float(group["projection_range"].quantile(0.75)),
                "projection_range_p90": float(group["projection_range"].quantile(0.90)),
                "projection_range_p95": float(group["projection_range"].quantile(0.95)),
                "projection_stddev_p25": float(group["projection_std"].quantile(0.25)),
                "projection_stddev_p50": float(group["projection_std"].quantile(0.50)),
                "projection_stddev_p75": float(group["projection_std"].quantile(0.75)),
                "projection_stddev_p90": float(group["projection_std"].quantile(0.90)),
                "projection_stddev_p95": float(group["projection_std"].quantile(0.95)),
            }
        )
    return pd.DataFrame(out)


def _fourforfour_only(rows: pd.DataFrame) -> pd.DataFrame:
    source_sets = _sets(rows)
    only = source_sets["4for4"] - source_sets["pff"] - source_sets["fantasypros"] - source_sets["ftn"]
    four_rows = rows.loc[rows["source"].astype(str) == "4for4"].copy()
    mask = four_rows[["player_normalized", "market"]].astype(str).apply(tuple, axis=1).isin(only)
    return four_rows.loc[mask, ["player", "player_normalized", "team", "position", "market", "projection"]].sort_values(["market", "player_normalized"])


def _source_combination_counts(consensus: pd.DataFrame) -> pd.DataFrame:
    out = []
    for market, group in consensus.groupby("market"):
        for sources, count in group["sources"].value_counts().sort_index().items():
            out.append({"market": market, "sources": sources, "rows": int(count)})
    return pd.DataFrame(out)


def run(args: argparse.Namespace) -> dict:
    registry = load_snapshot_registry(args.registry, project_root=PROJECT_ROOT)
    result = build_consensus_rows(registry=registry, project_root=PROJECT_ROOT, season=args.season, week=args.week, as_of=args.as_of, sources=SOURCES, min_sources=1)
    rows = result["selected_source_projections"]
    consensus = result["consensus_rows"]

    output_dir = args.output_root / "data" / "analysis" / "projection_audits" / "fourforfour" / str(args.season) / f"week_{args.week:02d}" / f"asof_{_slug(args.as_of)}"
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "selected_snapshots": output_dir / "selected_snapshots.csv",
        "coverage": output_dir / "source_projection_coverage.csv",
        "overlap": output_dir / "source_overlap.csv",
        "pairwise_differences": output_dir / "pairwise_difference_stats.csv",
        "all_four_dispersion": output_dir / "all_four_dispersion.csv",
        "fourforfour_only": output_dir / "fourforfour_only_rows.csv",
        "source_combinations": output_dir / "source_combinations.csv",
        "summary": output_dir / "summary.json",
    }
    result["selected_snapshots"].to_csv(outputs["selected_snapshots"], index=False)
    _coverage(rows).to_csv(outputs["coverage"], index=False)
    _overlap(rows).to_csv(outputs["overlap"], index=False)
    _pairwise(rows).to_csv(outputs["pairwise_differences"], index=False)
    _all_four_dispersion(consensus).to_csv(outputs["all_four_dispersion"], index=False)
    _fourforfour_only(rows).to_csv(outputs["fourforfour_only"], index=False)
    _source_combination_counts(consensus).to_csv(outputs["source_combinations"], index=False)

    summary = {
        "season": int(args.season),
        "week": int(args.week),
        "as_of": args.as_of,
        "selected_snapshots": int((result["selected_snapshots"]["selection_status"] == "selected").sum()),
        "selected_projection_rows": int(len(rows)),
        "consensus_rows": int(len(consensus)),
        "max_projection_count": int(consensus["projection_count"].max()) if not consensus.empty else 0,
        "duplicate_player_market_source_rows": int(rows.duplicated(subset=["player_normalized", "market", "source"]).sum()) if not rows.empty else 0,
        "outputs": {key: str(path) for key, path in outputs.items()},
    }
    outputs["summary"].write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit 4for4 projection integration against PFF/FantasyPros/FTN")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--registry", type=Path, default=PROJECT_ROOT / "data" / "processed" / "projections" / "snapshot_registry.csv")
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
