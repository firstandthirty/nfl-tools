from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSING_DIR = PROJECT_ROOT / "scripts" / "02_processing"
if str(PROCESSING_DIR) not in sys.path:
    sys.path.insert(0, str(PROCESSING_DIR))

from projection_consensus.aggregation import build_consensus_rows
from projection_consensus.loader import load_snapshot_registry


SOURCES = ["pff", "fantasypros", "ftn"]


def _slug(value: str) -> str:
    return value.replace(":", "").replace("-", "").replace("+", "")


def _projection_sets(rows: pd.DataFrame) -> dict[str, set[tuple[str, str]]]:
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
    if rows.empty:
        return pd.DataFrame(columns=["source", "market", "rows", "unique_players"])
    grouped = rows.groupby(["source", "market"], dropna=False)
    return grouped.agg(rows=("player_normalized", "size"), unique_players=("player_normalized", "nunique")).reset_index()


def _overlap(rows: pd.DataFrame) -> pd.DataFrame:
    sets = _projection_sets(rows)
    markets = sorted(rows["market"].dropna().astype(str).unique().tolist()) if not rows.empty else []
    out = []
    for market in ["all", *markets]:
        scoped = rows if market == "all" else rows.loc[rows["market"].astype(str) == market]
        scoped_sets = _projection_sets(scoped)
        pff = scoped_sets["pff"]
        fp = scoped_sets["fantasypros"]
        ftn = scoped_sets["ftn"]
        out.append(
            {
                "market": market,
                "ftn_rows": len(ftn),
                "pff_rows": len(pff),
                "fantasypros_rows": len(fp),
                "ftn_pff_overlap": len(ftn & pff),
                "ftn_fantasypros_overlap": len(ftn & fp),
                "pff_fantasypros_overlap": len(pff & fp),
                "three_source_overlap": len(ftn & pff & fp),
                "ftn_only": len(ftn - pff - fp),
            }
        )
    return pd.DataFrame(out)


def _pairwise_stats(rows: pd.DataFrame) -> pd.DataFrame:
    out = []
    if rows.empty:
        return pd.DataFrame(columns=["market", "source_a", "source_b", "count", "mean_diff_a_minus_b", "median_diff_a_minus_b", "mean_abs_diff", "p50_abs_diff", "p90_abs_diff"])
    for source_a, source_b in [("ftn", "pff"), ("ftn", "fantasypros")]:
        left = rows.loc[rows["source"].astype(str) == source_a, ["player_normalized", "market", "projection"]].copy()
        right = rows.loc[rows["source"].astype(str) == source_b, ["player_normalized", "market", "projection"]].copy()
        merged = left.merge(right, on=["player_normalized", "market"], suffixes=("_a", "_b"))
        for market, group in merged.groupby("market"):
            diff = group["projection_a"].astype(float) - group["projection_b"].astype(float)
            abs_diff = diff.abs()
            out.append(
                {
                    "market": market,
                    "source_a": source_a,
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


def _ftn_only(rows: pd.DataFrame) -> pd.DataFrame:
    sets = _projection_sets(rows)
    ftn_only_keys = sets["ftn"] - sets["pff"] - sets["fantasypros"]
    if not ftn_only_keys:
        return pd.DataFrame(columns=["player", "player_normalized", "team", "position", "market", "projection"])
    ftn_rows = rows.loc[rows["source"].astype(str) == "ftn"].copy()
    mask = ftn_rows[["player_normalized", "market"]].astype(str).apply(tuple, axis=1).isin(ftn_only_keys)
    return ftn_rows.loc[mask, ["player", "player_normalized", "team", "position", "market", "projection"]].sort_values(["market", "player_normalized"])


def run(args: argparse.Namespace) -> dict:
    registry_path = args.registry or PROJECT_ROOT / "data" / "processed" / "projections" / "snapshot_registry.csv"
    registry = load_snapshot_registry(registry_path, project_root=PROJECT_ROOT)
    result = build_consensus_rows(
        registry=registry,
        project_root=PROJECT_ROOT,
        season=args.season,
        week=args.week,
        as_of=args.as_of,
        sources=SOURCES,
        min_sources=1,
    )
    selected = result["selected_snapshots"]
    rows = result["selected_source_projections"]
    consensus = result["consensus_rows"]

    output_dir = args.output_root / "data" / "analysis" / "projection_audits" / "ftn" / str(args.season) / f"week_{args.week:02d}" / f"asof_{_slug(args.as_of)}"
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "selected_snapshots": output_dir / "selected_snapshots.csv",
        "source_projection_coverage": output_dir / "source_projection_coverage.csv",
        "source_overlap": output_dir / "source_overlap.csv",
        "pairwise_differences": output_dir / "pairwise_difference_stats.csv",
        "ftn_only": output_dir / "ftn_only_rows.csv",
        "consensus_by_market_projection_count": output_dir / "consensus_by_market_projection_count.csv",
        "summary": output_dir / "summary.json",
    }
    selected.to_csv(paths["selected_snapshots"], index=False)
    _coverage(rows).to_csv(paths["source_projection_coverage"], index=False)
    _overlap(rows).to_csv(paths["source_overlap"], index=False)
    _pairwise_stats(rows).to_csv(paths["pairwise_differences"], index=False)
    _ftn_only(rows).to_csv(paths["ftn_only"], index=False)
    by_market_count = consensus.groupby(["market", "projection_count"]).size().reset_index(name="rows") if not consensus.empty else pd.DataFrame(columns=["market", "projection_count", "rows"])
    by_market_count.to_csv(paths["consensus_by_market_projection_count"], index=False)

    duplicate_selected_keys = int(rows.duplicated(subset=["player_normalized", "market", "source"]).sum()) if not rows.empty else 0
    summary = {
        "season": int(args.season),
        "week": int(args.week),
        "as_of": args.as_of,
        "selected_snapshots": int((selected["selection_status"] == "selected").sum()) if not selected.empty else 0,
        "selected_projection_rows": int(len(rows)),
        "consensus_rows": int(len(consensus)),
        "max_projection_count": int(consensus["projection_count"].max()) if not consensus.empty else 0,
        "eligible_rows_min_sources_3": int((consensus["projection_count"] >= 3).sum()) if not consensus.empty else 0,
        "duplicate_player_market_source_rows": duplicate_selected_keys,
        "warnings": result["warnings"],
        "outputs": {key: str(path) for key, path in paths.items()},
    }
    paths["summary"].write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit FTN projection integration against PFF/FantasyPros")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    summary = run(args)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
