from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELING_DIR = PROJECT_ROOT / "scripts" / "03_modeling"
if str(MODELING_DIR) not in sys.path:
    sys.path.insert(0, str(MODELING_DIR))

from receiving_crossfit_calibration import (
    BOOTSTRAP_SEED,
    bootstrap_probability_metrics,
    crossfit_signal_predictions,
    load_receiving_history,
    nested_calibrated_predictions,
    position_diagnostics,
    probability_metrics,
    reliability_buckets,
    score_bucket_rows,
    side_diagnostics,
    signal_metrics,
    weekly_stability,
)

OUTPUT_DIR = PROJECT_ROOT / "data" / "analysis" / "model_calibration" / "player_props" / "receiving_crossfit_calibration_v1"


def shrinkage_diagnostics(probability_df: pd.DataFrame) -> pd.DataFrame:
    alpha_by_method = {
        "constant_50": 0.0,
        "logistic_shrunk_alpha_0.25": 0.25,
        "logistic_shrunk_alpha_0.50": 0.50,
        "logistic_shrunk_alpha_0.75": 0.75,
        "logistic": 1.0,
    }
    diagnostics = probability_df[probability_df["calibration_method"].isin(alpha_by_method)].copy()
    diagnostics["shrinkage_alpha"] = diagnostics["calibration_method"].map(alpha_by_method)
    return diagnostics.sort_values(["signal_candidate", "shrinkage_alpha", "calibration_method"]).reset_index(drop=True)


def raw_edge_vs_improved(signal: pd.DataFrame, calibrated: pd.DataFrame) -> pd.DataFrame:
    signal_summary = signal_metrics(signal)
    prob_summary = probability_metrics(calibrated)
    signal_pivot = signal_summary.set_index("candidate").add_prefix("signal_")
    best_probs = prob_summary.sort_values(["signal_candidate", "brier_score", "log_loss"]).groupby("signal_candidate", observed=True).head(1)
    rows = []
    for candidate, prob_row in best_probs.set_index("signal_candidate").iterrows():
        signal_key = "improved_signal" if candidate == "improved_signal" else "raw_projection_edge"
        signal_row = signal_pivot.loc[signal_key]
        rows.append({
            "signal_candidate": candidate,
            "best_calibration_method": prob_row["calibration_method"],
            "signal_directional_accuracy": signal_row["signal_directional_accuracy"],
            "signal_auc": signal_row["signal_auc"],
            "signal_mae_predicted_actual": signal_row["signal_mae_predicted_actual"],
            "probability_brier": prob_row["brier_score"],
            "probability_log_loss": prob_row["log_loss"],
            "probability_auc": prob_row["auc"],
            "probability_actual_win_rate": prob_row["actual_win_rate"],
        })
    return pd.DataFrame(rows)


def run(args: argparse.Namespace) -> dict:
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    history = load_receiving_history(PROJECT_ROOT)
    signal = crossfit_signal_predictions(history)
    calibrated = nested_calibrated_predictions(signal)

    signal_metrics_df = signal_metrics(signal)
    bucket_df = score_bucket_rows(signal)
    side_df = side_diagnostics(signal)
    position_df = position_diagnostics(signal)
    probability_df = probability_metrics(calibrated)
    reliability_df = reliability_buckets(calibrated)
    weekly_df = weekly_stability(calibrated)
    bootstrap_df = bootstrap_probability_metrics(calibrated, iterations=args.bootstrap_iterations, seed=BOOTSTRAP_SEED)
    comparison_df = raw_edge_vs_improved(signal, calibrated)
    shrinkage_df = shrinkage_diagnostics(probability_df)

    signal.to_csv(output_dir / "crossfit_signal_predictions.csv", index=False)
    signal_metrics_df.to_csv(output_dir / "crossfit_signal_metrics.csv", index=False)
    bucket_df.to_csv(output_dir / "crossfit_score_buckets.csv", index=False)
    side_df.to_csv(output_dir / "side_diagnostics.csv", index=False)
    position_df.to_csv(output_dir / "position_diagnostics.csv", index=False)
    calibrated.to_csv(output_dir / "nested_calibrated_predictions.csv", index=False)
    probability_df.to_csv(output_dir / "calibration_method_comparison.csv", index=False)
    reliability_df.to_csv(output_dir / "reliability_buckets.csv", index=False)
    weekly_df.to_csv(output_dir / "weekly_stability.csv", index=False)
    shrinkage_df.to_csv(output_dir / "shrinkage_diagnostics.csv", index=False)
    bootstrap_df.to_csv(output_dir / "bootstrap_metrics.csv", index=False)
    comparison_df.to_csv(output_dir / "raw_edge_vs_improved_signal.csv", index=False)

    summary = {
        "output_dir": str(output_dir),
        "market": "player_reception_yds",
        "historical_rows": int(len(history)),
        "crossfit_signal_rows": int(len(signal)),
        "nested_probability_rows": int(len(calibrated)),
        "predicted_weeks": sorted(int(v) for v in signal["predicted_week"].dropna().unique()),
        "calibrated_weeks": sorted(int(v) for v in calibrated["predicted_week"].dropna().unique()),
        "signal_metrics": signal_metrics_df.to_dict(orient="records"),
        "best_probability_by_brier": probability_df.sort_values(["signal_candidate", "brier_score", "log_loss"]).groupby("signal_candidate", observed=True).head(1).to_dict(orient="records"),
        "raw_edge_vs_improved": comparison_df.to_dict(orient="records"),
        "no_receptions": True,
        "no_2026_outcomes": True,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run receiving-yards cross-fitted signal and nested calibration experiment")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--bootstrap-iterations", type=int, default=5000)
    args = parser.parse_args()
    summary = run(args)
    print("[output_dir]", summary["output_dir"])
    print("[historical_rows]", summary["historical_rows"])
    print("[crossfit_signal_rows]", summary["crossfit_signal_rows"])
    print("[nested_probability_rows]", summary["nested_probability_rows"])
    print("[predicted_weeks]", summary["predicted_weeks"])
    print("[calibrated_weeks]", summary["calibrated_weeks"])
    for row in summary["raw_edge_vs_improved"]:
        print(
            f"[{row['signal_candidate']}] signal_acc={row['signal_directional_accuracy']:.4f} "
            f"signal_auc={row['signal_auc']:.4f} best_cal={row['best_calibration_method']} "
            f"brier={row['probability_brier']:.4f} logloss={row['probability_log_loss']:.4f}"
        )


if __name__ == "__main__":
    main()
