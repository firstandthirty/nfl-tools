from pathlib import Path
import math

import pandas as pd


OUT_DIR = Path("data/analysis")
OUT_FILE = OUT_DIR / "pass_yds_projection_error_penalty.csv"

# Clean residual sigma from calibration
OUTCOME_SIGMA = 68.488252


def normal_cdf(x, mu=0.0, sigma=1.0):
    z = (x - mu) / sigma
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def prob_over(delta, total_sigma):
    return 1.0 - normal_cdf(0.0, mu=delta, sigma=total_sigma)


def ev_per_1_unit(prob, decimal_odds):
    return prob * (decimal_odds - 1.0) - (1.0 - prob)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    odds_prices = [1.83, 1.87, 1.90, 1.91, 1.95, 2.00]

    # Guess projection uncertainty.
    # 0 = projection is perfect.
    # 10/15/20/25/30 = projection mean has real error around that many yards.
    projection_error_sigmas = [0, 10, 15, 20, 25, 30, 40]

    deltas = list(range(0, 41, 1))

    rows = []

    for proj_sigma in projection_error_sigmas:
        total_sigma = math.sqrt(OUTCOME_SIGMA ** 2 + proj_sigma ** 2)

        for odds in odds_prices:
            breakeven = 1.0 / odds

            for delta in deltas:
                p = prob_over(delta, total_sigma)
                ev = ev_per_1_unit(p, odds)

                rows.append(
                    {
                        "projection_error_sigma": proj_sigma,
                        "total_sigma": total_sigma,
                        "decimal_odds": odds,
                        "breakeven_prob": breakeven,
                        "projection_minus_line": delta,
                        "p_over": p,
                        "edge_prob": p - breakeven,
                        "ev_per_1_unit": ev,
                        "ev_percent": ev * 100,
                    }
                )

    df = pd.DataFrame(rows)
    df.to_csv(OUT_FILE, index=False)

    threshold_rows = []

    for (proj_sigma, odds), g in df.groupby(["projection_error_sigma", "decimal_odds"]):
        positive = g[g["ev_per_1_unit"] > 0].sort_values("projection_minus_line")

        if positive.empty:
            threshold = None
            p_at = None
            ev_at = None
        else:
            row = positive.iloc[0]
            threshold = int(row["projection_minus_line"])
            p_at = row["p_over"]
            ev_at = row["ev_percent"]

        threshold_rows.append(
            {
                "projection_error_sigma": proj_sigma,
                "decimal_odds": odds,
                "min_delta_for_positive_ev": threshold,
                "p_over_at_threshold": p_at,
                "ev_percent_at_threshold": ev_at,
            }
        )

    thresholds = pd.DataFrame(threshold_rows)

    print("\n===== MIN DELTA FOR POSITIVE EV =====")
    print(
        thresholds.pivot(
            index="projection_error_sigma",
            columns="decimal_odds",
            values="min_delta_for_positive_ev",
        ).to_string()
    )

    print("\n===== COMMON FD PRICE DETAIL: 1.90 =====")
    detail = df[
        (df["decimal_odds"] == 1.90)
        & (df["projection_minus_line"].isin([5, 10, 15, 20, 25, 30]))
    ].copy()

    print(
        detail[
            [
                "projection_error_sigma",
                "projection_minus_line",
                "p_over",
                "edge_prob",
                "ev_percent",
            ]
        ].to_string(index=False)
    )

    print("\n===== OUTPUT =====")
    print(f"saved: {OUT_FILE}")


if __name__ == "__main__":
    main()