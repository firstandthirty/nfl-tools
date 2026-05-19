from pathlib import Path

import numpy as np
import pandas as pd

INPUT = Path("data/historical_props/pass_yds_baseline_predictions.csv")
OUT_PATH = Path("data/historical_props/pass_yds_sim_results.csv")

N_SIMS = 10000
RANDOM_SEED = 42


def american_implied_prob(price):
    price = float(price)
    if price < 0:
        return abs(price) / (abs(price) + 100)
    return 100 / (price + 100)


def american_profit(price):
    price = float(price)
    if price > 0:
        return price / 100
    return 100 / abs(price)


def main():
    if not INPUT.exists():
        raise FileNotFoundError(f"Missing input file: {INPUT}")

    rng = np.random.default_rng(RANDOM_SEED)

    df = pd.read_csv(INPUT)
    df.columns = [c.strip() for c in df.columns]

    required = [
        "line",
        "actual_value",
        "over_price",
        "under_price",
        "pred_mean",
        "pred_std",
    ]

    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    for c in required:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=required).copy()

    p_overs = []
    p_unders = []
    sim_means = []
    sim_medians = []
    sim_p10s = []
    sim_p90s = []

    for _, row in df.iterrows():
        mean = row["pred_mean"]
        std = max(row["pred_std"], 1.0)
        line = row["line"]

        sims = rng.normal(mean, std, N_SIMS)
        sims = np.maximum(sims, 0)

        p_overs.append(float(np.mean(sims > line)))
        p_unders.append(float(np.mean(sims < line)))
        sim_means.append(float(np.mean(sims)))
        sim_medians.append(float(np.median(sims)))
        sim_p10s.append(float(np.percentile(sims, 10)))
        sim_p90s.append(float(np.percentile(sims, 90)))

    df["sim_p_over"] = p_overs
    df["sim_p_under"] = p_unders
    df["sim_mean"] = sim_means
    df["sim_median"] = sim_medians
    df["sim_p10"] = sim_p10s
    df["sim_p90"] = sim_p90s

    df["market_p_over_raw"] = df["over_price"].apply(american_implied_prob)
    df["market_p_under_raw"] = df["under_price"].apply(american_implied_prob)

    # Remove vig by normalizing both sides.
    raw_sum = df["market_p_over_raw"] + df["market_p_under_raw"]
    df["market_p_over_novig"] = df["market_p_over_raw"] / raw_sum
    df["market_p_under_novig"] = df["market_p_under_raw"] / raw_sum

    df["edge_over_prob"] = df["sim_p_over"] - df["market_p_over_novig"]
    df["edge_under_prob"] = df["sim_p_under"] - df["market_p_under_novig"]

    df["actual_over"] = df["actual_value"] > df["line"]
    df["actual_under"] = df["actual_value"] < df["line"]
    df["actual_push"] = df["actual_value"] == df["line"]

    df["over_profit"] = np.where(
        df["actual_push"],
        0,
        np.where(df["actual_over"], df["over_price"].apply(american_profit), -1),
    )

    df["under_profit"] = np.where(
        df["actual_push"],
        0,
        np.where(df["actual_under"], df["under_price"].apply(american_profit), -1),
    )

    # Simple candidate flags.
    df["bet_over_55"] = df["sim_p_over"] >= 0.55
    df["bet_under_55"] = df["sim_p_under"] >= 0.55

    over_candidates = df[df["bet_over_55"]].copy()
    under_candidates = df[df["bet_under_55"]].copy()

    print("\n===== SIM SUMMARY =====")
    print(f"rows: {len(df):,}")
    print(f"avg sim_p_over: {df['sim_p_over'].mean():.3f}")
    print(f"avg market_p_over_novig: {df['market_p_over_novig'].mean():.3f}")

    print("\n===== CANDIDATE BACKTEST: OVER >= 55% =====")
    if len(over_candidates):
        print(f"bets: {len(over_candidates):,}")
        print(f"hit rate: {over_candidates['actual_over'].mean():.3f}")
        print(f"ROI: {over_candidates['over_profit'].mean():.3f}")
    else:
        print("No over candidates.")

    print("\n===== CANDIDATE BACKTEST: UNDER >= 55% =====")
    if len(under_candidates):
        print(f"bets: {len(under_candidates):,}")
        print(f"hit rate: {under_candidates['actual_under'].mean():.3f}")
        print(f"ROI: {under_candidates['under_profit'].mean():.3f}")
    else:
        print("No under candidates.")

    print("\n===== BIGGEST OVER EDGES =====")
    cols = [
        "week",
        "player",
        "recent_team",
        "line",
        "actual_value",
        "pred_mean",
        "pred_std",
        "sim_p_over",
        "market_p_over_novig",
        "edge_over_prob",
        "over_profit",
    ]
    cols = [c for c in cols if c in df.columns]

    print(
        df.sort_values("edge_over_prob", ascending=False)
        [cols]
        .head(20)
        .to_string(index=False)
    )

    print("\n===== BIGGEST UNDER EDGES =====")
    cols = [
        "week",
        "player",
        "recent_team",
        "line",
        "actual_value",
        "pred_mean",
        "pred_std",
        "sim_p_under",
        "market_p_under_novig",
        "edge_under_prob",
        "under_profit",
    ]
    cols = [c for c in cols if c in df.columns]

    print(
        df.sort_values("edge_under_prob", ascending=False)
        [cols]
        .head(20)
        .to_string(index=False)
    )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)

    print(f"\n[saved] {OUT_PATH}")


if __name__ == "__main__":
    main()