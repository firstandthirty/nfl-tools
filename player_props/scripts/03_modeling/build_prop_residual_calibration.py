from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from prop_probability import (
    MODELED_MARKETS,
    empirical_probabilities,
    evaluate_probability_rows,
    make_probability_buckets,
    model_probabilities,
    normal_probabilities,
    residual_summary,
    save_calibration_artifact,
    select_chronological_split,
)

LOCAL_TZ = ZoneInfo("America/New_York")
CALIBRATION_VERSION = "residual_distribution_v1"
MIN_CONDITIONAL_BIN_ROWS = 40

MARKET_FILES = {
    "player_pass_yds": {
        "safe": Path("data/analysis/pass_yds_model_bets_backtest_safe.csv"),
        "history": None,
    },
    "player_rush_yds": {
        "safe": Path("data/analysis/rush_yds_model_bets_backtest_safe.csv"),
        "history": Path("data/analysis/rush_yds_market_analysis_rows.csv"),
    },
    "player_reception_yds": {
        "safe": Path("data/analysis/reception_yds_model_bets_backtest_safe.csv"),
        "history": Path("data/analysis/reception_yds_market_analysis_rows.csv"),
    },
}


def _norm_position(value: object) -> str:
    text = "" if pd.isna(value) else str(value).strip().upper()
    if text == "HB":
        return "RB"
    return text or "UNKNOWN"


def load_market_sample(project_root: Path, market: str) -> pd.DataFrame:
    spec = MARKET_FILES[market]
    safe = pd.read_csv(project_root / spec["safe"])
    safe = safe.copy()
    safe["market"] = market
    if "actual" not in safe.columns:
        history = pd.read_csv(project_root / spec["history"])
        history = history.copy()
        history["actual"] = pd.to_numeric(history.get("actual", history.get("actual_value")), errors="coerce")
        history["position_history"] = history.get("position", "UNKNOWN")
        history_keep = history[
            ["season", "week", "event_id", "player_norm", "line", "actual", "position_history"]
        ].drop_duplicates(["season", "week", "event_id", "player_norm", "line"])
        history_keep = history_keep.rename(columns={"event_id": "game_id"})
        safe = safe.merge(history_keep, on=["season", "week", "game_id", "player_norm", "line"], how="left", validate="many_to_one")
    if "position" not in safe.columns:
        safe["position"] = safe.get("position_history", "UNKNOWN")
    safe["position"] = safe["position"].map(_norm_position)
    for col in ["season", "week", "projection", "actual", "line", "over_price", "under_price"]:
        if col in safe.columns:
            safe[col] = pd.to_numeric(safe[col], errors="coerce")
    sample = safe.dropna(subset=["season", "week", "projection", "actual", "line"]).copy()
    sample["season"] = sample["season"].astype(int)
    sample["week"] = sample["week"].astype(int)
    sample["forecast_residual"] = sample["actual"] - sample["projection"]
    sample["actual_minus_line"] = sample["actual"] - sample["line"]
    sample["is_push"] = sample["actual"].eq(sample["line"])
    return sample


def residual_histogram(sample: pd.DataFrame, market: str) -> pd.DataFrame:
    residual = sample["forecast_residual"].dropna()
    counts, edges = np.histogram(residual, bins=20)
    rows = []
    for index, count in enumerate(counts):
        rows.append({
            "market": market,
            "bin_index": index,
            "bin_left": float(edges[index]),
            "bin_right": float(edges[index + 1]),
            "count": int(count),
        })
    return pd.DataFrame(rows)


def qq_diagnostic(sample: pd.DataFrame, market: str) -> pd.DataFrame:
    residual = sample["forecast_residual"].dropna().sort_values().reset_index(drop=True)
    mu = float(residual.mean())
    sigma = float(residual.std(ddof=1))
    rows = []
    for q in np.linspace(0.05, 0.95, 19):
        observed = float(residual.quantile(q))
        # Acklam-style inverse normal approximation would be overkill here; use sampled normal quantiles.
        normal_sample = pd.Series(np.random.default_rng(42).normal(mu, sigma, 200000))
        expected = float(normal_sample.quantile(q))
        rows.append({"market": market, "quantile": float(q), "observed_residual": observed, "normal_expected_residual": expected, "difference": observed - expected})
    return pd.DataFrame(rows)


def heteroskedasticity(sample: pd.DataFrame, market: str) -> pd.DataFrame:
    out = sample.copy()
    out["projection_bucket"] = pd.qcut(out["projection"], q=3, labels=["low", "medium", "high"], duplicates="drop")
    rows = []
    for bucket, group in out.groupby("projection_bucket", observed=True):
        rows.append({
            "market": market,
            "dimension": "projection_bucket",
            "bucket": str(bucket),
            "n": int(len(group)),
            "projection_min": float(group["projection"].min()),
            "projection_max": float(group["projection"].max()),
            "residual_std": float(group["forecast_residual"].std(ddof=1)),
            "mae": float(group["forecast_residual"].abs().mean()),
        })
    for position, group in out.groupby("position", observed=True):
        if len(group) < 30:
            continue
        rows.append({
            "market": market,
            "dimension": "position",
            "bucket": str(position),
            "n": int(len(group)),
            "projection_min": float(group["projection"].min()),
            "projection_max": float(group["projection"].max()),
            "residual_std": float(group["forecast_residual"].std(ddof=1)),
            "mae": float(group["forecast_residual"].abs().mean()),
        })
    return pd.DataFrame(rows)


def conditional_bins(train: pd.DataFrame) -> list[dict[str, Any]]:
    work = train.copy()
    work["projection_bucket"] = pd.qcut(work["projection"], q=3, labels=False, duplicates="drop")
    bins: list[dict[str, Any]] = []
    for _, group in work.groupby("projection_bucket", observed=True):
        if len(group) < MIN_CONDITIONAL_BIN_ROWS:
            continue
        bins.append({
            "projection_min": float(group["projection"].min()),
            "projection_max": float(group["projection"].max()),
            "n": int(len(group)),
            "residual_std": float(group["forecast_residual"].std(ddof=1)),
            "empirical_residuals": [float(value) for value in group["forecast_residual"].tolist()],
        })
    return bins


def predict_validation(sample: pd.DataFrame, train: pd.DataFrame, method: str, params: dict[str, Any]) -> pd.DataFrame:
    rows = []
    residuals = train["forecast_residual"].astype(float).tolist()
    for _, row in sample.iterrows():
        if method == "normal":
            probs = normal_probabilities(row["projection"], row["line"], params["normal_mu"], params["normal_sigma"])
        elif method == "empirical":
            probs = empirical_probabilities(row["projection"], row["line"], residuals)
        elif method == "conditional_empirical":
            probs = model_probabilities(params, row["projection"], row["line"])
        else:
            raise ValueError(method)
        for side in ["over", "under"]:
            win = row["actual"] > row["line"] if side == "over" else row["actual"] < row["line"]
            rows.append({
                "market": row["market"],
                "method": method,
                "side": side,
                "season": row["season"],
                "week": row["week"],
                "player": row["player"],
                "player_norm": row["player_norm"],
                "projection": row["projection"],
                "line": row["line"],
                "actual": row["actual"],
                "model_win_probability": probs[f"p_{side}"],
                "model_push_probability": probs["p_push"],
                "is_push": bool(row["is_push"]),
                "won": bool(win),
            })
    return pd.DataFrame(rows)


def reliability_table(predictions: pd.DataFrame) -> pd.DataFrame:
    work = predictions[predictions["is_push"] == False].copy()
    work["probability_bucket"] = make_probability_buckets(work["model_win_probability"])
    rows = []
    for (market, method, side, bucket), group in work.groupby(["market", "method", "side", "probability_bucket"], observed=True):
        rows.append({
            "market": market,
            "method": method,
            "side": side,
            "probability_bucket": str(bucket),
            "n": int(len(group)),
            "avg_predicted_probability": float(group["model_win_probability"].mean()),
            "actual_hit_rate": float(group["won"].mean()),
            "calibration_error": float(group["model_win_probability"].mean() - group["won"].mean()),
        })
    return pd.DataFrame(rows)


def compare_methods(market: str, sample: pd.DataFrame, split) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    train = sample[sample["week"].isin(split.train_weeks)].copy()
    validation = sample[sample["week"].isin(split.validation_weeks)].copy()
    base_params = {
        "normal_mu": float(train["forecast_residual"].mean()),
        "normal_sigma": float(train["forecast_residual"].std(ddof=1)),
        "empirical_residuals": [float(value) for value in train["forecast_residual"].tolist()],
    }
    cond_params = {
        **base_params,
        "selected_method": "conditional_empirical",
        "conditional_bins": conditional_bins(train),
    }
    method_params = {
        "normal": base_params,
        "empirical": base_params,
        "conditional_empirical": cond_params,
    }
    frames = [predict_validation(validation, train, method, params) for method, params in method_params.items()]
    predictions = pd.concat(frames, ignore_index=True)
    metrics = []
    for (method, side), group in predictions.groupby(["method", "side"], observed=True):
        metric = evaluate_probability_rows(group, "model_win_probability")
        metrics.append({"market": market, "method": method, "side": side, **metric})
    for method, group in predictions.groupby("method", observed=True):
        metric = evaluate_probability_rows(group, "model_win_probability")
        metrics.append({"market": market, "method": method, "side": "combined", **metric})
    metrics_df = pd.DataFrame(metrics)
    combined = metrics_df[metrics_df["side"].eq("combined")].copy()
    combined = combined.sort_values(["brier_score", "log_loss", "method"], ascending=[True, True, True])
    selected_method = str(combined.iloc[0]["method"])
    params = method_params[selected_method].copy()
    params["selected_method"] = selected_method
    params["validation_brier_score"] = float(combined.iloc[0]["brier_score"])
    params["validation_log_loss"] = float(combined.iloc[0]["log_loss"])
    params["validation_rows"] = int(combined.iloc[0]["n"])
    return params, metrics_df, predictions


def build_calibration(project_root: Path, output_root: Path) -> dict[str, Any]:
    build_ts = datetime.now(LOCAL_TZ)
    diagnostics_dir = output_root / "data" / "analysis" / "model_calibration" / "player_props" / CALIBRATION_VERSION / build_ts.strftime("%Y%m%dT%H%M%S%z")
    artifact_path = output_root / "data" / "processed" / "model_calibration" / "player_props" / CALIBRATION_VERSION / build_ts.strftime("%Y%m%dT%H%M%S%z") / "calibration_artifact.json"
    market_artifacts: dict[str, Any] = {}
    diagnostics = []
    coverage_rows = []
    histogram_rows = []
    qq_rows = []
    hetero_rows = []
    metrics_rows = []
    reliability_rows = []
    validation_rows = []
    for market in sorted(MODELED_MARKETS):
        sample = load_market_sample(project_root, market)
        split = select_chronological_split(sample, min_validation_rows=50)
        train = sample[sample["week"].isin(split.train_weeks)].copy()
        validation = sample[sample["week"].isin(split.validation_weeks)].copy()
        params, metrics_df, predictions = compare_methods(market, sample, split)
        summary = residual_summary(sample)
        diagnostics.append({"market": market, **summary})
        coverage_rows.extend(
            {"market": market, "season": int(season), "week": int(week), "rows": int(len(group))}
            for (season, week), group in sample.groupby(["season", "week"], observed=True)
        )
        histogram_rows.append(residual_histogram(sample, market))
        qq_rows.append(qq_diagnostic(sample, market))
        hetero_rows.append(heteroskedasticity(sample, market))
        metrics_rows.append(metrics_df)
        reliability_rows.append(reliability_table(predictions))
        validation_rows.append(predictions)
        market_artifacts[market] = {
            "market": market,
            "selected_method": params["selected_method"],
            "selection_rationale": "lowest combined validation Brier score, then log loss; simple methods preferred only through metric tie ordering",
            "train_seasons": sorted(int(value) for value in train["season"].dropna().unique()),
            "train_weeks": split.train_weeks,
            "validation_weeks": split.validation_weeks,
            "split_method": split.method,
            "sample_size": int(len(sample)),
            "training_sample_size": int(len(train)),
            "validation_sample_size": int(len(validation)),
            "normal_mu": float(train["forecast_residual"].mean()),
            "normal_sigma": float(train["forecast_residual"].std(ddof=1)),
            "empirical_residuals": [float(value) for value in train["forecast_residual"].tolist()],
            "empirical_quantiles": {str(q): float(train["forecast_residual"].quantile(q)) for q in [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]},
            "conditional_bins": conditional_bins(train),
            "validation_brier_score": params["validation_brier_score"],
            "validation_log_loss": params["validation_log_loss"],
            "validation_scored_sides": params["validation_rows"],
            "residual_sign_convention": "actual - projection; positive residual means actual exceeded projection",
        }
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(diagnostics).to_csv(diagnostics_dir / "residual_diagnostics.csv", index=False)
    pd.DataFrame(coverage_rows).to_csv(diagnostics_dir / "sample_coverage.csv", index=False)
    pd.concat(histogram_rows, ignore_index=True).to_csv(diagnostics_dir / "residual_histogram.csv", index=False)
    pd.concat(qq_rows, ignore_index=True).to_csv(diagnostics_dir / "qq_normality_diagnostic.csv", index=False)
    pd.concat(hetero_rows, ignore_index=True).to_csv(diagnostics_dir / "heteroskedasticity.csv", index=False)
    pd.concat(metrics_rows, ignore_index=True).to_csv(diagnostics_dir / "candidate_method_metrics.csv", index=False)
    pd.concat(reliability_rows, ignore_index=True).to_csv(diagnostics_dir / "candidate_reliability_buckets.csv", index=False)
    pd.concat(validation_rows, ignore_index=True).to_csv(diagnostics_dir / "validation_predictions.csv", index=False)
    artifact = {
        "version": CALIBRATION_VERSION,
        "built_at": build_ts.isoformat(),
        "project_root": str(project_root),
        "diagnostics_dir": str(diagnostics_dir),
        "markets": market_artifacts,
        "excluded_markets": {"player_receptions": "excluded from production probability evaluation in this task"},
        "probability_clip": "1e-6 to 1 - 1e-6 for numerical log-loss stability",
    }
    save_calibration_artifact(artifact_path, artifact)
    artifact["artifact_path"] = str(artifact_path)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description="Build player-prop residual distribution calibration artifacts")
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    artifact = build_calibration(PROJECT_ROOT, args.output_root)
    print("[artifact]", artifact["artifact_path"])
    print("[diagnostics_dir]", artifact["diagnostics_dir"])
    for market, params in artifact["markets"].items():
        print(
            f"[{market}] sample={params['sample_size']} train={params['training_sample_size']} "
            f"validation_lines={params['validation_sample_size']} "
            f"validation_scored_sides={params['validation_scored_sides']} method={params['selected_method']} "
            f"brier={params['validation_brier_score']:.4f} logloss={params['validation_log_loss']:.4f}"
        )


if __name__ == "__main__":
    main()
