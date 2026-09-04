from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELING_DIR = PROJECT_ROOT / "scripts" / "03_modeling"
if str(MODELING_DIR) not in sys.path:
    sys.path.insert(0, str(MODELING_DIR))

from build_prop_residual_calibration import compare_methods, load_market_sample
from prop_probability import (
    MODELED_MARKETS,
    brier_score,
    clipped_probability,
    load_calibration_artifact,
    log_loss,
    make_probability_buckets,
    market_parameters,
    model_probabilities,
    select_chronological_split,
)

DEFAULT_ARTIFACT = PROJECT_ROOT / "data" / "processed" / "model_calibration" / "player_props" / "residual_distribution_v1" / "20260903T154042-0400" / "calibration_artifact.json"
DEFAULT_WEEK1_EVAL = PROJECT_ROOT / "data" / "analysis" / "prop_evaluations" / "2026" / "week_01" / "prop_evaluation_rows.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "analysis" / "model_calibration" / "player_props" / "calibration_sanity_audit_v1"
BOOTSTRAP_ITERATIONS = 5000
BOOTSTRAP_SEED = 20260904


def shrink_probability(probability: float, alpha: float) -> float:
    return 0.5 + float(alpha) * (float(probability) - 0.5)


def projection_direction(edge: float) -> str:
    if float(edge) > 0:
        return "over"
    if float(edge) < 0:
        return "under"
    return "equal"


def roc_auc_score_binary(y_true: pd.Series, probability: pd.Series) -> float:
    y = y_true.astype(int).to_numpy()
    p = probability.astype(float).to_numpy()
    positives = int(y.sum())
    negatives = int(len(y) - positives)
    if positives == 0 or negatives == 0:
        return math.nan
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p), dtype=float)
    sorted_p = p[order]
    start = 0
    while start < len(p):
        end = start + 1
        while end < len(p) and sorted_p[end] == sorted_p[start]:
            end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2.0
        start = end
    positive_rank_sum = float(ranks[y == 1].sum())
    return (positive_rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def rank_correlation(y_true: pd.Series, probability: pd.Series) -> float:
    if len(y_true) < 2:
        return math.nan
    y_rank = pd.Series(y_true).astype(float).rank(method="average")
    p_rank = pd.Series(probability).astype(float).rank(method="average")
    if y_rank.nunique() < 2 or p_rank.nunique() < 2:
        return math.nan
    return float(p_rank.corr(y_rank))


def binary_metrics(df: pd.DataFrame, probability_col: str) -> dict[str, Any]:
    decided = df[df["is_push"] == False].copy()
    if decided.empty:
        return {
            "n": 0,
            "wins": 0,
            "losses": 0,
            "pushes": int(df["is_push"].sum()),
            "brier_score": math.nan,
            "log_loss": math.nan,
            "mean_predicted_probability": math.nan,
            "actual_win_rate": math.nan,
            "calibration_bias": math.nan,
            "auc": math.nan,
            "spearman": math.nan,
        }
    y = decided["won"].astype(float)
    p = decided[probability_col].astype(float).map(clipped_probability)
    return {
        "n": int(len(decided)),
        "wins": int(y.sum()),
        "losses": int(len(y) - y.sum()),
        "pushes": int(df["is_push"].sum()),
        "brier_score": brier_score(y, p),
        "log_loss": log_loss(y, p),
        "mean_predicted_probability": float(p.mean()),
        "actual_win_rate": float(y.mean()),
        "calibration_bias": float(p.mean() - y.mean()),
        "auc": roc_auc_score_binary(y, p),
        "spearman": rank_correlation(y, p),
    }


def make_side_rows(sample: pd.DataFrame, method: str, params: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for _, row in sample.iterrows():
        probs = model_probabilities(params, row["projection"], row["line"])
        for side in ["over", "under"]:
            won = row["actual"] > row["line"] if side == "over" else row["actual"] < row["line"]
            projection_edge = float(row["projection"]) - float(row["line"])
            rows.append({
                "market": row["market"],
                "selected_probability_method": method,
                "season": int(row["season"]),
                "week": int(row["week"]),
                "player": row.get("player", ""),
                "player_norm": row.get("player_norm", ""),
                "projection": float(row["projection"]),
                "actual": float(row["actual"]),
                "sportsbook_line": float(row["line"]),
                "line": float(row["line"]),
                "side": side,
                "model_probability": float(probs[f"p_{side}"]),
                "model_push_probability": float(probs["p_push"]),
                "is_push": bool(row["is_push"]),
                "realized_outcome": "push" if bool(row["is_push"]) else ("win" if won else "loss"),
                "won": bool(won),
                "projection_edge": projection_edge,
                "absolute_projection_edge": abs(projection_edge),
                "projection_indicated_side": projection_direction(projection_edge),
                "projection_indicated_won": (
                    row["actual"] > row["line"] if projection_edge > 0 else row["actual"] < row["line"] if projection_edge < 0 else False
                ),
            })
    return pd.DataFrame(rows)


def training_base_rates(train: pd.DataFrame) -> dict[str, float]:
    side_rows = make_side_rows(train, "training_label_rows", {"selected_method": "normal", "normal_mu": 0.0, "normal_sigma": 1.0})
    decided = side_rows[side_rows["is_push"] == False]
    return {str(side): float(group["won"].mean()) for side, group in decided.groupby("side", observed=True)}


def reconstruct_validation(artifact: dict[str, Any], project_root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    validation_frames = []
    candidate_frames = []
    method_metric_frames = []
    for market in sorted(MODELED_MARKETS):
        params = market_parameters(artifact, market)
        sample = load_market_sample(project_root, market)
        train_weeks = [int(value) for value in params["train_weeks"]]
        validation_weeks = [int(value) for value in params["validation_weeks"]]
        train = sample[sample["week"].isin(train_weeks)].copy()
        validation = sample[sample["week"].isin(validation_weeks)].copy()
        rows = make_side_rows(validation, params["selected_method"], params)
        rates = training_base_rates(train)
        rows["constant_50_probability"] = 0.5
        rows["training_base_rate_probability"] = rows["side"].map(rates).astype(float)
        rows["train_or_validation"] = "validation"
        validation_frames.append(rows)

        split = select_chronological_split(sample, min_validation_rows=50)
        _, metrics_df, predictions = compare_methods(market, sample, split)
        candidate_frames.append(predictions)
        method_metric_frames.append(metrics_df)
    return (
        pd.concat(validation_frames, ignore_index=True),
        pd.concat(candidate_frames, ignore_index=True),
        pd.concat(method_metric_frames, ignore_index=True),
    )


def baseline_comparison(validation: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (market, side), group in validation.groupby(["market", "side"], observed=True):
        for label, col in [
            ("constant_50", "constant_50_probability"),
            ("training_base_rate", "training_base_rate_probability"),
            ("selected_model", "model_probability"),
        ]:
            rows.append({"market": market, "side": side, "model": label, **binary_metrics(group, col)})
    for market, group in validation.groupby("market", observed=True):
        base = binary_metrics(group, "constant_50_probability")
        for label, col in [
            ("constant_50", "constant_50_probability"),
            ("training_base_rate", "training_base_rate_probability"),
            ("selected_model", "model_probability"),
        ]:
            metric = binary_metrics(group, col)
            rows.append({
                "market": market,
                "side": "combined",
                "model": label,
                **metric,
                "brier_diff_vs_50": metric["brier_score"] - base["brier_score"],
                "brier_relative_diff_vs_50": (metric["brier_score"] / base["brier_score"] - 1.0) if base["brier_score"] else math.nan,
                "logloss_diff_vs_50": metric["log_loss"] - base["log_loss"],
                "logloss_relative_diff_vs_50": (metric["log_loss"] / base["log_loss"] - 1.0) if base["log_loss"] else math.nan,
            })
    return pd.DataFrame(rows)


def probability_buckets(validation: pd.DataFrame) -> pd.DataFrame:
    work = validation[validation["is_push"] == False].copy()
    work["probability_bucket"] = make_probability_buckets(work["model_probability"])
    rows = []
    for (market, bucket), group in work.groupby(["market", "probability_bucket"], observed=True):
        metric = binary_metrics(group, "model_probability")
        rows.append({
            "market": market,
            "bucket_type": "probability",
            "bucket": str(bucket),
            **metric,
            "avg_abs_projection_edge": float(group["absolute_projection_edge"].mean()),
        })
    for market, group in work.groupby("market", observed=True):
        ranked = group.sort_values("model_probability", kind="mergesort").copy()
        ranked["half"] = pd.qcut(np.arange(len(ranked)), q=2, labels=["bottom_half", "top_half"])
        ranked["tercile"] = pd.qcut(np.arange(len(ranked)), q=3, labels=["bottom_tercile", "middle_tercile", "top_tercile"])
        for label_col in ["half", "tercile"]:
            for label, bucket_group in ranked.groupby(label_col, observed=True):
                metric = binary_metrics(bucket_group, "model_probability")
                rows.append({
                    "market": market,
                    "bucket_type": label_col,
                    "bucket": str(label),
                    **metric,
                    "avg_abs_projection_edge": float(bucket_group["absolute_projection_edge"].mean()),
                })
    return pd.DataFrame(rows)


def projection_edge_buckets(validation: pd.DataFrame) -> pd.DataFrame:
    line_level = validation.drop_duplicates(["market", "season", "week", "player_norm", "line"]).copy()
    line_level = line_level[line_level["projection_indicated_side"].isin(["over", "under"])].copy()
    rows = []
    for market, group in line_level.groupby("market", observed=True):
        q = min(4, max(2, len(group) // 20))
        group = group.copy()
        group["edge_bucket"] = pd.qcut(group["absolute_projection_edge"], q=q, duplicates="drop")
        for bucket, bucket_group in group.groupby("edge_bucket", observed=True):
            decided = bucket_group[bucket_group["is_push"] == False]
            rows.append({
                "market": market,
                "edge_bucket": str(bucket),
                "n": int(len(bucket_group)),
                "decided_n": int(len(decided)),
                "mean_absolute_projection_edge": float(bucket_group["absolute_projection_edge"].mean()),
                "median_absolute_projection_edge": float(bucket_group["absolute_projection_edge"].median()),
                "projection_indicated_side_win_rate": float(decided["projection_indicated_won"].mean()) if not decided.empty else math.nan,
                "pushes": int(bucket_group["is_push"].sum()),
            })
    return pd.DataFrame(rows)


def side_diagnostics(validation: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (market, side), group in validation.groupby(["market", "side"], observed=True):
        metric = binary_metrics(group, "model_probability")
        indicated = group[group["projection_indicated_side"].eq(side)]
        decided_indicated = indicated[indicated["is_push"] == False]
        rows.append({
            "market": market,
            "side": side,
            **metric,
            "projection_direction_rows": int(len(indicated)),
            "projection_direction_accuracy": float(decided_indicated["won"].mean()) if not decided_indicated.empty else math.nan,
        })
    return pd.DataFrame(rows)


def bootstrap_metrics(validation: pd.DataFrame, iterations: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for market, group in validation.groupby("market", observed=True):
        decided = group[group["is_push"] == False].reset_index(drop=True)
        line_level = group.drop_duplicates(["season", "week", "player_norm", "line"]).reset_index(drop=True)
        line_level = line_level[line_level["is_push"] == False].reset_index(drop=True)
        if decided.empty:
            continue
        observed = {
            "model_brier": binary_metrics(decided, "model_probability")["brier_score"],
            "baseline_brier": binary_metrics(decided, "constant_50_probability")["brier_score"],
            "brier_diff": binary_metrics(decided, "model_probability")["brier_score"] - binary_metrics(decided, "constant_50_probability")["brier_score"],
            "model_log_loss": binary_metrics(decided, "model_probability")["log_loss"],
            "baseline_log_loss": binary_metrics(decided, "constant_50_probability")["log_loss"],
            "logloss_diff": binary_metrics(decided, "model_probability")["log_loss"] - binary_metrics(decided, "constant_50_probability")["log_loss"],
            "auc": binary_metrics(decided, "model_probability")["auc"],
        }
        if not line_level.empty:
            observed["directional_hit_rate"] = float(line_level["projection_indicated_won"].mean())
        values = {key: [] for key in observed}
        for _ in range(iterations):
            sample_idx = rng.integers(0, len(decided), len(decided))
            resample = decided.iloc[sample_idx]
            model = binary_metrics(resample, "model_probability")
            base = binary_metrics(resample, "constant_50_probability")
            values["model_brier"].append(model["brier_score"])
            values["baseline_brier"].append(base["brier_score"])
            values["brier_diff"].append(model["brier_score"] - base["brier_score"])
            values["model_log_loss"].append(model["log_loss"])
            values["baseline_log_loss"].append(base["log_loss"])
            values["logloss_diff"].append(model["log_loss"] - base["log_loss"])
            values["auc"].append(model["auc"])
            if "directional_hit_rate" in values:
                line_idx = rng.integers(0, len(line_level), len(line_level))
                values["directional_hit_rate"].append(float(line_level.iloc[line_idx]["projection_indicated_won"].mean()))
        for metric, samples in values.items():
            arr = np.asarray(samples, dtype=float)
            arr = arr[~np.isnan(arr)]
            rows.append({
                "market": market,
                "metric": metric,
                "observed": float(observed[metric]),
                "ci_low_95": float(np.quantile(arr, 0.025)) if len(arr) else math.nan,
                "ci_high_95": float(np.quantile(arr, 0.975)) if len(arr) else math.nan,
                "iterations": iterations,
                "seed": seed,
            })
    return pd.DataFrame(rows)


def shrinkage_experiment(validation: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for market, group in validation.groupby("market", observed=True):
        for alpha in [0.0, 0.25, 0.5, 0.75, 1.0]:
            work = group.copy()
            work["shrunk_probability"] = work["model_probability"].map(lambda value: shrink_probability(value, alpha))
            rows.append({"market": market, "alpha": alpha, **binary_metrics(work, "shrunk_probability")})
    return pd.DataFrame(rows)


def calibration_slope(validation: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for market, group in validation.groupby("market", observed=True):
        decided = group[group["is_push"] == False].copy()
        if len(decided) < 20 or decided["won"].nunique() < 2:
            rows.append({"market": market, "n": len(decided), "calibration_intercept": math.nan, "calibration_slope": math.nan})
            continue
        p = decided["model_probability"].astype(float).map(clipped_probability)
        logits = np.log(p / (1.0 - p)).to_numpy(dtype=float)
        x = np.column_stack([np.ones(len(logits)), logits])
        y = decided["won"].astype(float).to_numpy(dtype=float)
        beta = np.array([0.0, 1.0], dtype=float)
        for _ in range(50):
            linear = x @ beta
            pred = 1.0 / (1.0 + np.exp(-np.clip(linear, -35.0, 35.0)))
            weights = np.clip(pred * (1.0 - pred), 1e-9, None)
            gradient = x.T @ (y - pred)
            hessian = x.T @ (x * weights[:, None])
            try:
                delta = np.linalg.solve(hessian, gradient)
            except np.linalg.LinAlgError:
                break
            beta += delta
            if float(np.max(np.abs(delta))) < 1e-8:
                break
        rows.append({
            "market": market,
            "n": int(len(decided)),
            "calibration_intercept": float(beta[0]),
            "calibration_slope": float(beta[1]),
        })
    return pd.DataFrame(rows)


def candidate_method_comparison(candidate_predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    work = candidate_predictions.copy()
    work["constant_50_probability"] = 0.5
    for market, group in work.groupby("market", observed=True):
        baseline_group = group.drop_duplicates(["season", "week", "player_norm", "line", "side"]).copy()
        rows.append({"market": market, "method": "constant_50", "side": "combined", **binary_metrics(baseline_group, "constant_50_probability")})
        for method, method_group in group.groupby("method", observed=True):
            rows.append({"market": market, "method": method, "side": "combined", **binary_metrics(method_group, "model_win_probability")})
    for (market, method, side), group in work.groupby(["market", "method", "side"], observed=True):
        rows.append({"market": market, "method": method, "side": side, **binary_metrics(group, "model_win_probability")})
    return pd.DataFrame(rows)


def week1_ev_diagnostics(path_or_rows: Path | pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    evaluations = pd.read_csv(path_or_rows) if isinstance(path_or_rows, Path) else path_or_rows.copy()
    evaluations = evaluations[evaluations["market"].isin(MODELED_MARKETS)].copy()
    evaluations["is_ev_gt_5"] = evaluations["expected_value_pct"] > 5.0
    evaluations["has_suspicious_flag"] = evaluations["suspicious_flags"].fillna("").astype(str).ne("")
    evaluations["is_stale_pff"] = evaluations["projection_source"].eq("pff") & evaluations["suspicious_flags"].fillna("").str.contains("stale_projection")
    evaluations["probability_bucket"] = make_probability_buckets(evaluations["model_win_probability"])
    evaluations["projection_line_gap"] = evaluations["projection"] - evaluations["line"]
    evaluations["abs_projection_line_gap"] = evaluations["projection_line_gap"].abs()
    evaluations["projection_gap_bucket"] = pd.qcut(evaluations["abs_projection_line_gap"], q=5, duplicates="drop")
    evaluations["price_bucket"] = pd.cut(
        evaluations["american_price"],
        bins=[-10000, -200, -150, -120, -100, 0, 100, 120, 150, 200, 10000],
        labels=["<-200", "-200..-151", "-150..-121", "-120..-101", "-100..-1", "0..100", "+101..+120", "+121..+150", "+151..+200", ">+200"],
    )
    groupings = [
        ("market", ["market"]),
        ("projection_source", ["projection_type", "projection_source"]),
        ("main_vs_alternate", ["is_alternate"]),
        ("sportsbook", ["sportsbook"]),
        ("side", ["side"]),
        ("probability_bucket", ["probability_bucket"]),
        ("projection_gap_bucket", ["projection_gap_bucket"]),
        ("price_bucket", ["price_bucket"]),
    ]
    rows = []
    for label, cols in groupings:
        for keys, group in evaluations.groupby(cols, observed=True, dropna=False):
            if not isinstance(keys, tuple):
                keys = (keys,)
            key_text = "|".join(str(value) for value in keys)
            ev5 = group[group["is_ev_gt_5"]]
            rows.append({
                "breakdown": label,
                "bucket": key_text,
                "rows": int(len(group)),
                "ev_gt_0": int((group["expected_value_1u"] > 0).sum()),
                "ev_gt_2pct": int((group["expected_value_pct"] > 2.0).sum()),
                "ev_gt_5pct": int(len(ev5)),
                "ev5_median_model_probability": float(ev5["model_win_probability"].median()) if not ev5.empty else math.nan,
                "ev5_median_break_even_probability": float(ev5["break_even_probability"].median()) if not ev5.empty else math.nan,
                "ev5_median_probability_edge": float(ev5["probability_edge"].median()) if not ev5.empty else math.nan,
                "ev5_median_projection_line_gap": float(ev5["projection_line_gap"].median()) if not ev5.empty else math.nan,
                "ev5_alternate_share": float(ev5["is_alternate"].mean()) if not ev5.empty else math.nan,
                "ev5_over_share": float(ev5["side"].eq("over").mean()) if not ev5.empty else math.nan,
                "ev5_suspicious_share": float(ev5["has_suspicious_flag"].mean()) if not ev5.empty else math.nan,
                "ev5_stale_pff_share": float(ev5["is_stale_pff"].mean()) if not ev5.empty else math.nan,
            })
    return evaluations, pd.DataFrame(rows)


def week1_unique_counts(evaluations: pd.DataFrame) -> pd.DataFrame:
    grains = {
        "full_evaluation_rows": ["projection_type", "projection_source", "sportsbook", "player_normalized", "market", "line", "side"],
        "unique_sportsbook_wagers": ["sportsbook", "player_normalized", "market", "line", "side"],
        "unique_player_market_line_side": ["player_normalized", "market", "line", "side"],
        "unique_player_market_side": ["player_normalized", "market", "side"],
        "unique_player_market": ["player_normalized", "market"],
    }
    rows = []
    for grain, cols in grains.items():
        grouped = evaluations.groupby(cols, observed=True, dropna=False).agg(
            max_ev_pct=("expected_value_pct", "max"),
            rows=("expected_value_pct", "size"),
        ).reset_index()
        rows.append({
            "grain": grain,
            "total": int(len(grouped)),
            "ev_gt_0": int((grouped["max_ev_pct"] > 0).sum()),
            "ev_gt_2pct": int((grouped["max_ev_pct"] > 2.0).sum()),
            "ev_gt_5pct": int((grouped["max_ev_pct"] > 5.0).sum()),
            "median_rows_per_group": float(grouped["rows"].median()),
            "max_rows_per_group": int(grouped["rows"].max()),
        })
    return pd.DataFrame(rows)


def validation_summary(validation: pd.DataFrame, artifact: dict[str, Any], baseline: pd.DataFrame) -> dict[str, Any]:
    summary: dict[str, Any] = {"markets": {}}
    for market, group in validation.groupby("market", observed=True):
        params = market_parameters(artifact, market)
        selected = baseline[(baseline["market"].eq(market)) & baseline["side"].eq("combined") & baseline["model"].eq("selected_model")].iloc[0]
        base = baseline[(baseline["market"].eq(market)) & baseline["side"].eq("combined") & baseline["model"].eq("constant_50")].iloc[0]
        summary["markets"][market] = {
            "selected_method": params["selected_method"],
            "validation_line_rows": int(group.drop_duplicates(["season", "week", "player_norm", "line"]).shape[0]),
            "validation_side_rows": int(len(group)),
            "decided_side_rows": int((group["is_push"] == False).sum()),
            "push_side_rows": int(group["is_push"].sum()),
            "artifact_brier": float(params["validation_brier_score"]),
            "reconstructed_brier": float(selected["brier_score"]),
            "artifact_log_loss": float(params["validation_log_loss"]),
            "reconstructed_log_loss": float(selected["log_loss"]),
            "constant_50_brier": float(base["brier_score"]),
            "constant_50_log_loss": float(base["log_loss"]),
            "brier_diff_vs_50": float(selected["brier_score"] - base["brier_score"]),
            "logloss_diff_vs_50": float(selected["log_loss"] - base["log_loss"]),
        }
    return summary


def run_audit(args: argparse.Namespace) -> dict[str, Any]:
    artifact = load_calibration_artifact(args.calibration_artifact)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    validation, candidate_predictions, original_candidate_metrics = reconstruct_validation(artifact, PROJECT_ROOT)
    baseline = baseline_comparison(validation)
    buckets = probability_buckets(validation)
    edge_buckets = projection_edge_buckets(validation)
    sides = side_diagnostics(validation)
    boot = bootstrap_metrics(validation, args.bootstrap_iterations, BOOTSTRAP_SEED)
    shrink = shrinkage_experiment(validation)
    slope = calibration_slope(validation)
    candidates = candidate_method_comparison(candidate_predictions)
    week1_rows, week1_diag = week1_ev_diagnostics(args.week1_evaluations)
    unique_counts = week1_unique_counts(week1_rows)

    validation.to_csv(output_dir / "validation_observations.csv", index=False)
    baseline.to_csv(output_dir / "baseline_comparison.csv", index=False)
    buckets.to_csv(output_dir / "probability_buckets.csv", index=False)
    edge_buckets.to_csv(output_dir / "projection_edge_buckets.csv", index=False)
    sides.to_csv(output_dir / "side_diagnostics.csv", index=False)
    boot.to_csv(output_dir / "bootstrap_metrics.csv", index=False)
    shrink.to_csv(output_dir / "shrinkage_experiment.csv", index=False)
    candidates.to_csv(output_dir / "candidate_method_comparison.csv", index=False)
    original_candidate_metrics.to_csv(output_dir / "original_candidate_method_metrics.csv", index=False)
    slope.to_csv(output_dir / "calibration_slope.csv", index=False)
    week1_diag.to_csv(output_dir / "week1_ev_diagnostics.csv", index=False)
    unique_counts.to_csv(output_dir / "week1_unique_opportunity_counts.csv", index=False)

    summary = validation_summary(validation, artifact, baseline)
    summary["output_dir"] = str(output_dir)
    summary["calibration_artifact"] = str(args.calibration_artifact)
    summary["week1_evaluations"] = str(args.week1_evaluations)
    summary["week1_rows"] = int(len(week1_rows))
    summary["week1_ev_gt_0"] = int((week1_rows["expected_value_1u"] > 0).sum())
    summary["week1_ev_gt_2pct"] = int((week1_rows["expected_value_pct"] > 2.0).sum())
    summary["week1_ev_gt_5pct"] = int((week1_rows["expected_value_pct"] > 5.0).sum())
    summary["receptions_rows"] = int((week1_rows["market"] == "player_receptions").sum())
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit residual probability calibration before EV bet selection")
    parser.add_argument("--calibration-artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--week1-evaluations", type=Path, default=DEFAULT_WEEK1_EVAL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--bootstrap-iterations", type=int, default=BOOTSTRAP_ITERATIONS)
    args = parser.parse_args()
    summary = run_audit(args)
    print("[output_dir]", summary["output_dir"])
    print("[calibration_artifact]", summary["calibration_artifact"])
    for market, stats in summary["markets"].items():
        print(
            f"[{market}] method={stats['selected_method']} validation_lines={stats['validation_line_rows']} "
            f"decided_sides={stats['decided_side_rows']} pushes={stats['push_side_rows']} "
            f"brier={stats['reconstructed_brier']:.4f} vs50={stats['brier_diff_vs_50']:+.4f} "
            f"logloss={stats['reconstructed_log_loss']:.4f} vs50={stats['logloss_diff_vs_50']:+.4f}"
        )
    print(
        f"[week1] rows={summary['week1_rows']} ev>0={summary['week1_ev_gt_0']} "
        f"ev>2%={summary['week1_ev_gt_2pct']} ev>5%={summary['week1_ev_gt_5pct']} receptions={summary['receptions_rows']}"
    )


if __name__ == "__main__":
    main()
