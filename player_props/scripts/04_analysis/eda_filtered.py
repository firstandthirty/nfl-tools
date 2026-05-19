from pathlib import Path
import pandas as pd
import numpy as np


BASE_DIR = Path(r"C:\Users\brady\OneDrive\Desktop\nfl-tools\player props")
MASTER_PATH = BASE_DIR / "data" / "processed" / "pff" / "pff_player_weekly_master.csv"

OUT_DIR = BASE_DIR / "data" / "processed" / "eda_filtered"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def summarize(df: pd.DataFrame, stat: str, label: str) -> dict:
    s = pd.to_numeric(df[stat], errors="coerce").dropna()

    if len(s) == 0:
        return {
            "group": label,
            "stat": stat,
            "status": "empty",
        }

    mean = s.mean()
    median = s.median()
    std = s.std()

    return {
        "group": label,
        "stat": stat,
        "count": len(s),
        "mean": mean,
        "median": median,
        "mean_minus_median": mean - median,
        "mean_to_median_ratio": mean / median if median != 0 else np.nan,
        "std": std,
        "cv": std / mean if mean != 0 else np.nan,
        "skew": s.skew(),
        "kurtosis": s.kurtosis(),
        "min": s.min(),
        "p10": s.quantile(0.10),
        "p25": s.quantile(0.25),
        "p50": s.quantile(0.50),
        "p75": s.quantile(0.75),
        "p90": s.quantile(0.90),
        "p95": s.quantile(0.95),
        "max": s.max(),
    }


def main():
    print(f"[load] {MASTER_PATH}")
    df = pd.read_csv(MASTER_PATH)

    summaries = []

    #
    # QB FILTERS
    #
    qb = df[
        (df["position"] == "QB") &
        (df["pass_attempts"] >= 20)
    ].copy()

    summaries.append(
        summarize(qb, "passing_yards", "QB_pass_attempts_gte_20")
    )

    summaries.append(
        summarize(qb, "passing_tds", "QB_pass_attempts_gte_20")
    )

    summaries.append(
        summarize(qb, "passing_ypa", "QB_pass_attempts_gte_20")
    )

    #
    # WR/TE FILTERS
    #
    wr_te = df[
        (df["position"].isin(["WR", "TE"])) &
        (df["routes"] >= 15)
    ].copy()

    summaries.append(
        summarize(wr_te, "receiving_yards", "WR_TE_routes_gte_15")
    )

    summaries.append(
        summarize(wr_te, "targets", "WR_TE_routes_gte_15")
    )

    summaries.append(
        summarize(wr_te, "receptions", "WR_TE_routes_gte_15")
    )

    summaries.append(
        summarize(wr_te, "yprr", "WR_TE_routes_gte_15")
    )

    #
    # HIGH TARGET WR/TE
    #
    high_target = wr_te[
        wr_te["targets"] >= 7
    ].copy()

    summaries.append(
        summarize(high_target, "receiving_yards", "WR_TE_targets_gte_7")
    )

    summaries.append(
        summarize(high_target, "targets", "WR_TE_targets_gte_7")
    )

    #
    # RB FILTERS
    #
    rb = df[
        (df["position"].isin(["HB", "RB"])) &
        (df["rush_attempts"] >= 8)
    ].copy()

    summaries.append(
        summarize(rb, "rushing_yards", "RB_rush_attempts_gte_8")
    )

    summaries.append(
        summarize(rb, "rush_attempts", "RB_rush_attempts_gte_8")
    )

    summaries.append(
        summarize(rb, "rushing_ypa", "RB_rush_attempts_gte_8")
    )

    #
    # RECEIVING RBs
    #
    receiving_rb = df[
        (df["position"].isin(["HB", "RB"])) &
        (df["targets"] >= 4)
    ].copy()

    summaries.append(
        summarize(receiving_rb, "receiving_yards", "RB_targets_gte_4")
    )

    summaries.append(
        summarize(receiving_rb, "targets", "RB_targets_gte_4")
    )

    #
    # MOBILE QB RUSHING
    #
    mobile_qb = df[
        (df["position"] == "QB") &
        (df["rush_attempts"] >= 5)
    ].copy()

    summaries.append(
        summarize(mobile_qb, "rushing_yards", "QB_rush_attempts_gte_5")
    )

    summaries.append(
        summarize(mobile_qb, "rush_attempts", "QB_rush_attempts_gte_5")
    )

    out = pd.DataFrame(summaries)

    out_path = OUT_DIR / "filtered_stat_summary.csv"
    out.to_csv(out_path, index=False)

    print(f"[saved] {out_path}")
    print("[done]")


if __name__ == "__main__":
    main()