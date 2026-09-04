from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from prop_probability import (
    MODELED_MARKETS,
    american_to_decimal,
    break_even_probability,
    expected_value_1u,
    load_calibration_artifact,
    market_parameters,
    model_probabilities,
    profit_per_unit_risked,
)


def _parse_dt(value: object) -> datetime | None:
    if value is None or pd.isna(value):
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _slug(value: str) -> str:
    return value.replace(":", "").replace("-", "").replace("+", "")


def latest_artifact(project_root: Path) -> Path:
    base = project_root / "data" / "processed" / "model_calibration" / "player_props"
    candidates = sorted(base.glob("*/**/calibration_artifact.json"))
    if not candidates:
        raise FileNotFoundError("No calibration_artifact.json found")
    return candidates[-1]


def build_projection_versions(source_rows: pd.DataFrame, consensus_rows: pd.DataFrame, odds_as_of: datetime) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    source = source_rows[source_rows["market"].isin(MODELED_MARKETS)].copy()
    source["projection_type"] = "source"
    source["projection_source"] = source["source"]
    source["projection_source_count"] = 1
    source["projection_value"] = source["projection"].astype(float)
    source["projection_std"] = np.nan
    source["projection_min"] = source["projection_value"]
    source["projection_max"] = source["projection_value"]
    source["projection_snapshot_lineage"] = source["raw_file"].astype(str)
    source["projection_captured_at"] = source["captured_at"].astype(str)
    source["snapshot_age_hours"] = [
        (odds_as_of - _parse_dt(value)).total_seconds() / 3600.0 if _parse_dt(value) else math.nan
        for value in source["captured_at"]
    ]
    frames.append(source)

    aggregate = consensus_rows[
        consensus_rows["market"].isin(MODELED_MARKETS)
        & consensus_rows["projection_count"].astype(int).eq(2)
    ].copy()
    if not aggregate.empty:
        aggregate["projection_type"] = "aggregate"
        aggregate["projection_source"] = "pff|fantasypros"
        aggregate["projection_source_count"] = aggregate["projection_count"].astype(int)
        aggregate["projection_value"] = aggregate["projection_mean"].astype(float)
        aggregate["projection_snapshot_lineage"] = aggregate["sources"].astype(str)
        aggregate["projection_captured_at"] = aggregate["latest_selected_snapshot"].astype(str)
        aggregate["captured_at"] = aggregate["latest_selected_snapshot"].astype(str)
        aggregate["snapshot_age_hours"] = [
            (odds_as_of - _parse_dt(value)).total_seconds() / 3600.0 if _parse_dt(value) else math.nan
            for value in aggregate["latest_selected_snapshot"]
        ]
        frames.append(aggregate)
    versions = pd.concat(frames, ignore_index=True, sort=False)
    versions["production_consensus_eligible"] = False
    return versions


def direction(value: float, line: float) -> str:
    if pd.isna(value) or pd.isna(line):
        return ""
    if float(value) > float(line):
        return "over"
    if float(value) < float(line):
        return "under"
    return "equal"


def source_agreement(source_rows: pd.DataFrame, odds: pd.DataFrame) -> pd.DataFrame:
    modeled_sources = source_rows[source_rows["market"].isin(MODELED_MARKETS)].copy()
    pivot = modeled_sources.pivot_table(
        index=["season", "week", "player_normalized", "market"],
        columns="source",
        values="projection",
        aggfunc="first",
    ).reset_index()
    rows = odds[odds["market"].isin(MODELED_MARKETS)].merge(
        pivot,
        on=["season", "week", "player_normalized", "market"],
        how="left",
    )
    out = []
    for _, row in rows.drop_duplicates(["event_id", "player_normalized", "market", "line"]).iterrows():
        pff = row.get("pff", np.nan)
        fp = row.get("fantasypros", np.nan)
        pff_dir = direction(pff, row["line"])
        fp_dir = direction(fp, row["line"])
        have_both = pd.notna(pff) and pd.notna(fp)
        out.append({
            "season": row["season"],
            "week": row["week"],
            "event_id": row["event_id"],
            "player_normalized": row["player_normalized"],
            "market": row["market"],
            "line": row["line"],
            "pff_projection": pff,
            "fantasypros_projection": fp,
            "pff_direction_vs_line": pff_dir,
            "fantasypros_direction_vs_line": fp_dir,
            "sources_agree_direction": bool(have_both and pff_dir == fp_dir),
            "projection_difference": float(pff - fp) if have_both else math.nan,
            "projection_range": float(abs(pff - fp)) if have_both else math.nan,
        })
    return pd.DataFrame(out)


def evaluate_rows(projections: pd.DataFrame, odds: pd.DataFrame, artifact: dict[str, Any], artifact_path: Path, as_of: str) -> pd.DataFrame:
    joined = projections.merge(
        odds[odds["market"].isin(MODELED_MARKETS)].copy(),
        on=["season", "week", "player_normalized", "market"],
        how="inner",
        suffixes=("_projection", "_odds"),
    )
    rows = []
    for _, row in joined.iterrows():
        params = market_parameters(artifact, row["market"])
        probs = model_probabilities(params, row["projection_value"], row["line"])
        side = str(row["side"]).lower()
        win_prob = probs[f"p_{side}"]
        push_prob = probs["p_push"]
        loss_prob = max(0.0, 1.0 - win_prob - push_prob)
        price = int(row["price"])
        breakeven = break_even_probability(price)
        ev = expected_value_1u(win_prob, push_prob, price)
        projection_age = row.get("snapshot_age_hours", np.nan)
        suspicious = []
        if win_prob < 0.01 or win_prob > 0.99:
            suspicious.append("extreme_model_probability")
        if abs(ev) > 1.0:
            suspicious.append("extreme_ev")
        if pd.notna(projection_age) and float(projection_age) > 168:
            suspicious.append("stale_projection")
        residual_needed = float(row["line"]) - float(row["projection_value"])
        q = params.get("empirical_quantiles", {})
        if q and (residual_needed < float(q["0.05"]) or residual_needed > float(q["0.95"])):
            suspicious.append("line_projection_gap_outside_5_95_residual_support")
        rows.append({
            "season": row["season"],
            "week": row["week"],
            "as_of": as_of,
            "event_id": row["event_id"],
            "commence_time": row["commence_time"],
            "sportsbook": row["sportsbook"],
            "player": row.get("player_projection", row.get("player_odds", "")),
            "player_normalized": row["player_normalized"],
            "team": row.get("team_projection", ""),
            "position": row.get("position_projection", ""),
            "market": row["market"],
            "line": row["line"],
            "side": side,
            "american_price": price,
            "decimal_price": american_to_decimal(price),
            "is_alternate": row["is_alternate"],
            "projection": row["projection_value"],
            "projection_type": row["projection_type"],
            "projection_source": row["projection_source"],
            "projection_source_count": row["projection_source_count"],
            "projection_std": row.get("projection_std", np.nan),
            "projection_min": row.get("projection_min", np.nan),
            "projection_max": row.get("projection_max", np.nan),
            "break_even_probability": breakeven,
            "profit_if_win_for_1u": profit_per_unit_risked(price),
            "model_win_probability": win_prob,
            "model_push_probability": push_prob,
            "model_loss_probability": loss_prob,
            "probability_edge": win_prob - breakeven,
            "expected_value_1u": ev,
            "expected_value_pct": ev * 100.0,
            "calibration_method": params["selected_method"],
            "calibration_sample_size": params["sample_size"],
            "production_consensus_eligible": bool(row["production_consensus_eligible"]),
            "projection_captured_at": row.get("projection_captured_at", row.get("captured_at_projection", "")),
            "projection_age_hours": projection_age,
            "projection_snapshot_lineage": row.get("projection_snapshot_lineage", ""),
            "odds_snapshot": row.get("raw_file", ""),
            "odds_captured_at": row.get("captured_at_odds", row.get("captured_at", "")),
            "calibration_artifact": str(artifact_path),
            "suspicious_flags": "|".join(suspicious),
        })
    return pd.DataFrame(rows)


def market_summary(evaluations: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for market, group in evaluations.groupby("market", observed=True):
        rows.append({
            "market": market,
            "evaluated_wager_rows": len(group),
            "unique_player_markets": group[["player_normalized", "market"]].drop_duplicates().shape[0],
            "main_rows": int((group["is_alternate"] == False).sum()),
            "alternate_rows": int((group["is_alternate"] == True).sum()),
            "sportsbooks": int(group["sportsbook"].nunique()),
            "model_probability_min": float(group["model_win_probability"].min()),
            "model_probability_median": float(group["model_win_probability"].median()),
            "model_probability_max": float(group["model_win_probability"].max()),
            "probability_edge_min": float(group["probability_edge"].min()),
            "probability_edge_median": float(group["probability_edge"].median()),
            "probability_edge_max": float(group["probability_edge"].max()),
            "ev_min": float(group["expected_value_pct"].min()),
            "ev_median": float(group["expected_value_pct"].median()),
            "ev_max": float(group["expected_value_pct"].max()),
            "ev_gt_0": int((group["expected_value_1u"] > 0).sum()),
            "ev_gt_2pct": int((group["expected_value_pct"] > 2).sum()),
            "ev_gt_5pct": int((group["expected_value_pct"] > 5).sum()),
            "suspicious_rows": int(group["suspicious_flags"].astype(str).ne("").sum()),
        })
    return pd.DataFrame(rows)


def run_evaluation(args: argparse.Namespace) -> dict[str, Any]:
    artifact_path = args.calibration_artifact or latest_artifact(PROJECT_ROOT)
    artifact = load_calibration_artifact(artifact_path)
    source_rows = pd.read_csv(args.selected_source_projections)
    consensus_rows = pd.read_csv(args.consensus)
    odds = pd.read_csv(args.selected_odds)
    odds_as_of = _parse_dt(args.as_of)
    projections = build_projection_versions(source_rows, consensus_rows, odds_as_of)
    evaluations = evaluate_rows(projections, odds, artifact, artifact_path, args.as_of)
    agreement = source_agreement(source_rows, odds)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = market_summary(evaluations)
    calibration_summary = pd.DataFrame([
        {
            "market": market,
            "selected_method": params["selected_method"],
            "sample_size": params["sample_size"],
            "training_sample_size": params["training_sample_size"],
            "validation_sample_size": params["validation_sample_size"],
            "validation_scored_sides": params["validation_scored_sides"],
            "validation_brier_score": params["validation_brier_score"],
            "validation_log_loss": params["validation_log_loss"],
            "artifact": str(artifact_path),
        }
        for market, params in artifact["markets"].items()
    ])
    evaluations.to_csv(output_dir / "prop_evaluation_rows.csv", index=False)
    agreement.to_csv(output_dir / "source_agreement_diagnostics.csv", index=False)
    summary.to_csv(output_dir / "market_summary.csv", index=False)
    calibration_summary.to_csv(output_dir / "calibration_summary_used.csv", index=False)
    return {
        "output_dir": str(output_dir),
        "evaluation_rows": len(evaluations),
        "rows_by_projection_type": evaluations.groupby(["projection_type", "projection_source"]).size().to_dict() if not evaluations.empty else {},
        "rows_by_market": evaluations.groupby("market").size().to_dict() if not evaluations.empty else {},
        "main_rows": int((evaluations["is_alternate"] == False).sum()) if not evaluations.empty else 0,
        "alternate_rows": int((evaluations["is_alternate"] == True).sum()) if not evaluations.empty else 0,
        "agreement_rows": len(agreement),
        "agreement_rate": float(agreement["sources_agree_direction"].mean()) if not agreement.empty else math.nan,
        "suspicious_rows": int(evaluations["suspicious_flags"].astype(str).ne("").sum()) if not evaluations.empty else 0,
        "calibration_artifact": str(artifact_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate live player-prop odds with residual-calibrated probabilities")
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--week", type=int, default=1)
    parser.add_argument("--as-of", default="2026-09-03T13:34:20.625874-04:00")
    parser.add_argument("--selected-source-projections", type=Path, default=PROJECT_ROOT / "data" / "processed" / "projection_consensus" / "2026" / "week_1" / "asof_20260903T1300000400" / "selected_source_projections.csv")
    parser.add_argument("--consensus", type=Path, default=PROJECT_ROOT / "data" / "processed" / "projection_consensus" / "2026" / "week_1" / "asof_20260903T1300000400" / "consensus_long.csv")
    parser.add_argument("--selected-odds", type=Path, default=PROJECT_ROOT / "data" / "processed" / "odds_asof" / "2026" / "week_01" / "asof_20260903T133420.6258740400" / "selected_odds.csv")
    parser.add_argument("--calibration-artifact", type=Path)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "analysis" / "prop_evaluations" / "2026" / "week_01")
    args = parser.parse_args()
    result = run_evaluation(args)
    for key, value in result.items():
        print(f"[{key}] {value}")


if __name__ == "__main__":
    main()
