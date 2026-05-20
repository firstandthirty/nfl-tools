from pathlib import Path

import pandas as pd
from sklearn.linear_model import LinearRegression


IN_FILE = Path("data/processed/pass_yds_dataset_fp.csv")
OUT_FILE = Path("data/processed/pass_yds_dataset_fp_debiased.csv")

EDGE_BINS = [-999, -25, -15, -10, -5, 0, 5, 10, 15, 25, 999]
EDGE_LABELS = [
    "<-25",
    "-25:-15",
    "-15:-10",
    "-10:-5",
    "-5:0",
    "0:5",
    "5:10",
    "10:15",
    "15:25",
    "25+",
]


def fit_regression(df: pd.DataFrame):
    model = LinearRegression()
    X = df[["fp_pass_yds"]].values
    y = df["actual_value"].values
    model.fit(X, y)
    intercept = model.intercept_
    slope = model.coef_[0]
    r2 = model.score(X, y)
    return intercept, slope, r2


def residual_stats(series: pd.Series) -> dict:
    return {
        "mae": series.abs().mean(),
        "rmse": (series.pow(2).mean()) ** 0.5,
        "mean_residual": series.mean(),
        "median_residual": series.median(),
    }


def main():
    df = pd.read_csv(IN_FILE)

    df = df[
        (df["market_key"] == "player_pass_yds")
        & df["fp_pass_yds"].notna()
        & df["actual_value"].notna()
        & df["line"].notna()
    ].copy()

    print(f"[load] usable_rows={len(df):,}")

    intercept, slope, r2 = fit_regression(df)
    correlation = df["fp_pass_yds"].corr(df["actual_value"])

    print("===== REGRESSION FIT =====")
    print(f"intercept: {intercept:.4f}")
    print(f"slope: {slope:.6f}")
    print(f"R^2: {r2:.4f}")
    print(f"correlation(fp_pass_yds, actual_value): {correlation:.4f}")

    df["fp_pass_yds_debiased"] = intercept + slope * df["fp_pass_yds"]
    df["actual_minus_fp"] = df["actual_value"] - df["fp_pass_yds"]
    df["actual_minus_fp_debiased"] = df["actual_value"] - df["fp_pass_yds_debiased"]
    df["actual_minus_line"] = df["actual_value"] - df["line"]

    print("\n===== CALIBRATION COMPARISON =====")
    original_stats = residual_stats(df["actual_minus_fp"])
    debiased_stats = residual_stats(df["actual_minus_fp_debiased"])

    print("Original FP projection")
    print(f"MAE: {original_stats['mae']:.4f}")
    print(f"RMSE: {original_stats['rmse']:.4f}")
    print(f"mean residual: {original_stats['mean_residual']:.4f}")
    print(f"median residual: {original_stats['median_residual']:.4f}")

    print("\nDebiased FP projection")
    print(f"MAE: {debiased_stats['mae']:.4f}")
    print(f"RMSE: {debiased_stats['rmse']:.4f}")
    print(f"mean residual: {debiased_stats['mean_residual']:.4f}")
    print(f"median residual: {debiased_stats['median_residual']:.4f}")

    print("\n===== VEGAS LINE COMPARISON =====")
    print(f"mean(fp_pass_yds - line): {(df['fp_pass_yds'] - df['line']).mean():.4f}")
    print(f"mean(fp_pass_yds_debiased - line): {(df['fp_pass_yds_debiased'] - df['line']).mean():.4f}")

    print("\n===== DEBIASED PROJECTION EDGE BUCKETS =====")
    df["projection_edge"] = df["fp_pass_yds_debiased"] - df["line"]
    df["actual_over_line"] = df["actual_value"] > df["line"]
    df["edge_bucket"] = pd.cut(
        df["projection_edge"],
        bins=EDGE_BINS,
        labels=EDGE_LABELS,
    )

    edge_summary = (
        df.groupby("edge_bucket", observed=True)
        .agg(
            rows=("actual_value", "size"),
            avg_edge=("projection_edge", "mean"),
            over_rate=("actual_over_line", "mean"),
            avg_actual_minus_line=("actual_minus_line", "mean"),
        )
        .reset_index()
    )

    print(edge_summary.to_string(index=False))

    df.to_csv(OUT_FILE, index=False)
    print(f"\n[save] {OUT_FILE}")


if __name__ == "__main__":
    main()
