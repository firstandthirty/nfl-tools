from pathlib import Path
import math

import pandas as pd


OUT_DIR = Path("data/analysis")
OUT_FILE = OUT_DIR / "pass_yds_ev_thresholds.csv"

# From clean residual calibration
SIGMA = 68.488252


def normal_cdf(x, mu=0.0, sigma=1.0):
    z = (x - mu) / sigma
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def prob_over_from_delta(delta, sigma=SIGMA):
    return 1.0 - normal_cdf(0.0, mu=delta, sigma=sigma)


def decimal_to_breakeven(decimal_odds):
    return 1.0 / decimal_odds


def ev_per_1_unit(prob, decimal_odds):
    # Profit is decimal_odds - 1 on win, lose 1 on loss
    return prob * (decimal_odds - 1.0) - (1.0 - prob)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    odds_prices = [1.75, 1.80, 1.83, 1.87, 1.90, 1.91, 1.95, 2.00, 2.05, 2.10]
    deltas = list(range(0, 41, 1))

    rows = []

    for odds in odds_prices:
        breakeven = decimal_to_breakeven(odds)

        for delta in deltas:
            p_over = prob_over_from_delta(delta)
            ev = ev_per_1_unit(p_over, odds)

            rows.append(
                {
                    "decimal_odds": odds,
                    "breakeven_prob": breakeven,
                    "projection_minus_line": delta,
                    "p_over": p_over,
                    "edge_prob": p_over - breakeven,
                    "ev_per_1_unit": ev,
                    "ev_percent": ev * 100,
                }
            )

    df = pd.DataFrame(rows)

    threshold_rows = []

    for odds, g in df.groupby("decimal_odds"):
        positive = g[g["ev_per_1_unit"] > 0].copy()

        if len(positive) == 0:
            min_delta = None
            row = None
        else:
            row = positive.sort_values("projection_minus_line").iloc[0]
            min_delta = int(row["projection_minus_line"])

        threshold_rows.append(
            {
                "decimal_odds": odds,
                "breakeven_prob": decimal_to_breakeven(odds),
                "min_delta_for_positive_ev": min_delta,
                "p_over_at_threshold": None if row is None else row["p_over"],
                "ev_percent_at_threshold": None if row is None else row["ev_percent"],
            }
        )

    thresholds = pd.DataFrame(threshold_rows)

    df.to_csv(OUT_FILE, index=False)

    print("\n===== PASS YDS EV THRESHOLDS =====")
    print(thresholds.to_string(index=False))

    print("\n===== SAMPLE EV TABLE: COMMON PRICES =====")
    sample = df[
        (df["decimal_odds"].isin([1.83, 1.87, 1.90, 1.91, 1.95, 2.00]))
        & (df["projection_minus_line"].isin([0, 5, 10, 15, 20, 25, 30]))
    ].copy()

    print(sample.to_string(index=False))

    print("\n===== OUTPUT =====")
    print(f"saved: {OUT_FILE}")


if __name__ == "__main__":
    main()