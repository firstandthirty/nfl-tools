from pathlib import Path

import pandas as pd


IN_FILE = Path("data/processed/pass_yds_dataset_fp_debiased.csv")
OUT_FILE = Path("data/processed/pass_yds_dataset_sigma.csv")

BUCKET_BINS = [0, 175, 200, 225, 250, 275, 999]
BUCKET_LABELS = [
    "0-175",
    "175-200",
    "200-225",
    "225-250",
    "250-275",
    "275+",
]


def main():
    df = pd.read_csv(IN_FILE)

    df = df[
        (df["market_key"] == "player_pass_yds")
        & df["fp_pass_yds_debiased"].notna()
        & df["actual_value"].notna()
        & df["line"].notna()
    ].copy()

    print(f"[load] usable_rows={len(df):,}")

    df["fp_bucket"] = pd.cut(
        df["fp_pass_yds_debiased"],
        bins=BUCKET_BINS,
        labels=BUCKET_LABELS,
        right=False,
    )

    bucket_summary = (
        df.groupby("fp_bucket", observed=True)
        .agg(
            rows=("actual_value", "size"),
            mean_actual=("actual_value", "mean"),
            median_actual=("actual_value", "median"),
            std_actual=("actual_value", "std"),
            mean_projection=("fp_pass_yds_debiased", "mean"),
            mean_abs_error=("actual_value", lambda s: (s - df.loc[s.index, "fp_pass_yds_debiased"]).abs().mean()),
        )
        .reset_index()
    )

    print("===== PROJECTION BUCKET FALLBACK SIGMA =====")
    print(bucket_summary.to_string(index=False))

    bucket_sigma = bucket_summary.set_index("fp_bucket")["std_actual"].to_dict()
    df["bucket_sigma_fallback"] = df["fp_bucket"].map(bucket_sigma)

    def choose_sigma(row):
        if row["games_played_pre"] >= 5 and pd.notna(row["rolling_std_pass_yds_5g"]):
            return "rolling_5g", row["rolling_std_pass_yds_5g"]
        if row["games_played_pre"] >= 3 and pd.notna(row["rolling_std_pass_yds_3g"]):
            return "rolling_3g", row["rolling_std_pass_yds_3g"]
        return "bucket_fallback", row["bucket_sigma_fallback"]

    sigma_choices = df.apply(choose_sigma, axis=1, result_type="expand")
    sigma_choices.columns = ["sigma_source", "pass_yds_sigma"]
    df = pd.concat([df, sigma_choices], axis=1)

    print("\n===== SIGMA SOURCE DIAGNOSTICS =====")
    source_counts = df["sigma_source"].value_counts(dropna=False)
    print(source_counts.to_string())
    print(f"avg_sigma: {df['pass_yds_sigma'].mean():.4f}")
    print(f"median_sigma: {df['pass_yds_sigma'].median():.4f}")
    print(f"min_sigma: {df['pass_yds_sigma'].min():.4f}")
    print(f"max_sigma: {df['pass_yds_sigma'].max():.4f}")

    SIGMA_FLOOR = 50
    SIGMA_CAP = 115

    df["pass_yds_sigma_raw"] = df["pass_yds_sigma"]
    df["pass_yds_sigma"] = df["pass_yds_sigma"].clip(lower=SIGMA_FLOOR, upper=SIGMA_CAP)

    print("\n===== SIGMA CLIPPING DIAGNOSTICS =====")
    print(f"floor: {SIGMA_FLOOR}")
    print(f"cap: {SIGMA_CAP}")
    print(f"below_floor_raw: {(df['pass_yds_sigma_raw'] < SIGMA_FLOOR).sum()}")
    print(f"above_cap_raw: {(df['pass_yds_sigma_raw'] > SIGMA_CAP).sum()}")

    df["z"] = (
        (df["actual_value"] - df["fp_pass_yds_debiased"])
        / df["pass_yds_sigma"]
    )

    print("\n===== Z-SCORE CALIBRATION =====")
    print(f"mean_z: {df['z'].mean():.4f}")
    print(f"std_z: {df['z'].std():.4f}")
    print(f"pct_within_1_sigma: {(df['z'].abs() <= 1).mean():.2%}")
    print(f"pct_within_2_sigma: {(df['z'].abs() <= 2).mean():.2%}")

    df.to_csv(OUT_FILE, index=False)
    print(f"\n[save] {OUT_FILE}")


if __name__ == "__main__":
    main()
