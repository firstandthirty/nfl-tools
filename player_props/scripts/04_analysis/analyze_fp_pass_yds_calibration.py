from pathlib import Path
import pandas as pd


IN_FILE = Path("data/processed/pass_yds_dataset_fp.csv")
OUT_DIR = Path("data/analysis")
OUT_FILE = OUT_DIR / "fp_pass_yds_calibration_summary.csv"


PROJECTION_BINS = [
    0, 175, 200, 225, 250, 275, 300, 999
]

PROJECTION_LABELS = [
    "<175",
    "175-200",
    "200-225",
    "225-250",
    "250-275",
    "275-300",
    "300+",
]


def main():
    df = pd.read_csv(IN_FILE)

    total_rows = len(df)
    matched_projection_rows = df["fp_pass_yds"].notna().sum()
    missing_projection_rows = total_rows - matched_projection_rows

    print(f"[load] total_rows={total_rows:,}")
    print(f"[diagnostic] matched_projection_rows={matched_projection_rows:,}")
    print(f"[diagnostic] missing_projection_rows={missing_projection_rows:,}")
    print(f"[diagnostic] mean_market_line={df['line'].mean():.2f}")
    print(f"[diagnostic] mean_fp_projection={df['fp_pass_yds'].mean():.2f}")
    print(f"[diagnostic] line_fp_correlation={df['line'].corr(df['fp_pass_yds']):.4f}")

    # Safety filter
    df = df[
        (df["market_key"] == "player_pass_yds")
        & df["fp_pass_yds"].notna()
        & df["actual_value"].notna()
        & df["line"].notna()
    ].copy()

    print(f"[filter] usable rows={len(df):,}")

    # Core residuals
    df["actual_minus_fp"] = df["actual_value"] - df["fp_pass_yds"]
    df["line_minus_fp"] = df["line"] - df["fp_pass_yds"]
    df["actual_minus_line"] = df["actual_value"] - df["line"]

    df["fp_above_line"] = df["fp_pass_yds"] > df["line"]
    df["actual_over_line"] = df["actual_value"] > df["line"]

    # Projection buckets
    df["fp_proj_bucket"] = pd.cut(
        df["fp_pass_yds"],
        bins=PROJECTION_BINS,
        labels=PROJECTION_LABELS,
        right=False,
    )

    overall = pd.DataFrame([{
        "bucket": "OVERALL",
        "rows": len(df),
        "avg_fp_projection": df["fp_pass_yds"].mean(),
        "avg_market_line": df["line"].mean(),
        "avg_actual": df["actual_value"].mean(),
        "median_actual": df["actual_value"].median(),
        "mean_actual_minus_fp": df["actual_minus_fp"].mean(),
        "median_actual_minus_fp": df["actual_minus_fp"].median(),
        "std_actual_minus_fp": df["actual_minus_fp"].std(),
        "mean_line_minus_fp": df["line_minus_fp"].mean(),
        "mean_actual_minus_line": df["actual_minus_line"].mean(),
        "actual_over_rate": df["actual_over_line"].mean(),
        "fp_above_line_rate": df["fp_above_line"].mean(),
        "mae_vs_fp": df["actual_minus_fp"].abs().mean(),
        "rmse_vs_fp": (df["actual_minus_fp"] ** 2).mean() ** 0.5,
    }])

    by_bucket = (
        df.groupby("fp_proj_bucket", observed=True)
        .agg(
            rows=("actual_value", "size"),
            avg_fp_projection=("fp_pass_yds", "mean"),
            avg_market_line=("line", "mean"),
            avg_actual=("actual_value", "mean"),
            median_actual=("actual_value", "median"),
            mean_actual_minus_fp=("actual_minus_fp", "mean"),
            median_actual_minus_fp=("actual_minus_fp", "median"),
            std_actual_minus_fp=("actual_minus_fp", "std"),
            mean_line_minus_fp=("line_minus_fp", "mean"),
            mean_actual_minus_line=("actual_minus_line", "mean"),
            actual_over_rate=("actual_over_line", "mean"),
            fp_above_line_rate=("fp_above_line", "mean"),
            mae_vs_fp=("actual_minus_fp", lambda s: s.abs().mean()),
            rmse_vs_fp=("actual_minus_fp", lambda s: (s.pow(2).mean()) ** 0.5),
        )
        .reset_index()
        .rename(columns={"fp_proj_bucket": "bucket"})
    )

    summary = pd.concat([overall, by_bucket], ignore_index=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary.to_csv(OUT_FILE, index=False)

    print("\n===== FP PASS YDS CALIBRATION =====")
    print(summary.to_string(index=False))

    print(f"\n[save] {OUT_FILE}")

    print("\n===== QUICK READ =====")
    print(f"Rows: {len(df):,}")
    print(f"Avg FP projection: {df['fp_pass_yds'].mean():.2f}")
    print(f"Avg market line: {df['line'].mean():.2f}")
    print(f"Avg actual: {df['actual_value'].mean():.2f}")
    print(f"Mean actual - FP: {df['actual_minus_fp'].mean():.2f}")
    print(f"Median actual - FP: {df['actual_minus_fp'].median():.2f}")
    print(f"Residual SD vs FP: {df['actual_minus_fp'].std():.2f}")
    print(f"Mean line - FP: {df['line_minus_fp'].mean():.2f}")
    print(f"Actual over rate: {df['actual_over_line'].mean():.2%}")
    print(f"FP above line rate: {df['fp_above_line'].mean():.2%}")

    print("\n===== PROJECTION EDGE ANALYSIS =====")
    edge_bins = [-999, -25, -15, -10, -5, 0, 5, 10, 15, 25, 999]
    edge_labels = [
        "<-25", "-25:-15", "-15:-10", "-10:-5",
        "-5:0", "0:5", "5:10", "10:15",
        "15:25", "25+"
    ]

    df["projection_edge"] = df["fp_pass_yds"] - df["line"]

    df["edge_bucket"] = pd.cut(
        df["projection_edge"],
        bins=edge_bins,
        labels=edge_labels,
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

    print("\n===== QUICK SANITY CHECK =====")
    top_disagreements = (
        df.assign(projection_line_diff=(df["line"] - df["fp_pass_yds"]).abs())
        .sort_values("projection_line_diff", ascending=False)
        .head(15)
        [["season", "week", "player", "line", "fp_pass_yds", "actual_value"]]
    )
    print(top_disagreements.to_string(index=False))


if __name__ == "__main__":
    main()