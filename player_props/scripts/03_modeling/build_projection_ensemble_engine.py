from pathlib import Path
import math
import pandas as pd


INPUT_FILE = Path("data/input/week_pass_yds_projections.csv")
OUT_DIR = Path("data/analysis")
OUT_FILE = OUT_DIR / "week_pass_yds_ensemble_bets.csv"

OUTCOME_SIGMA = 68.488252

SOURCE_SIGMA = {
    "fantasypros": 18,
    "pff": 14,
    "fantasy_points": 14,
    "etr": 12,
    "your_model": 16,
}


def normal_cdf(x, mu=0.0, sigma=1.0):
    z = (x - mu) / sigma
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def prob_over(line, mean_projection, total_sigma):
    return 1.0 - normal_cdf(line, mean_projection, total_sigma)


def expected_value(prob, decimal_odds):
    return prob * (decimal_odds - 1.0) - (1.0 - prob)


def weighted_projection(row):
    vals = []
    weights = []

    for source, sigma in SOURCE_SIGMA.items():
        if source in row and pd.notna(row[source]):
            vals.append(float(row[source]))
            weights.append(1 / (sigma ** 2))

    if not vals:
        return math.nan

    return sum(v * w for v, w in zip(vals, weights)) / sum(weights)


def projection_disagreement(row):
    vals = [
        float(row[source])
        for source in SOURCE_SIGMA
        if source in row and pd.notna(row[source])
    ]

    if len(vals) < 2:
        return math.nan

    return pd.Series(vals).std()


def consensus_strength(row):
    vals = [
        float(row[source])
        for source in SOURCE_SIGMA
        if source in row and pd.notna(row[source])
    ]

    if len(vals) < 2:
        return "weak"

    spread = max(vals) - min(vals)

    if spread <= 5:
        return "elite"
    if spread <= 10:
        return "strong"
    if spread <= 15:
        return "moderate"

    return "weak"


def recommendation(edge_yards, consensus):
    abs_edge = abs(edge_yards)

    if consensus == "elite" and abs_edge >= 15:
        return "STRONG BET"

    if consensus in ["elite", "strong"] and abs_edge >= 10:
        return "BET"

    if consensus != "weak" and abs_edge >= 5:
        return "LEAN"

    return "PASS"


def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Missing input file: {INPUT_FILE}\n\n"
            "Create it with columns:\n"
            "player,market_line,over_odds,under_odds,"
            "fantasypros,pff,fantasy_points,etr,your_model"
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(INPUT_FILE)

    required = ["player", "market_line", "over_odds", "under_odds"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(f"Missing required columns: {missing}")

    for col in ["market_line", "over_odds", "under_odds", *SOURCE_SIGMA.keys()]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    rows = []

    for _, row in df.iterrows():
        ensemble_proj = weighted_projection(row)
        disagreement = projection_disagreement(row)
        consensus = consensus_strength(row)

        if pd.isna(ensemble_proj):
            continue

        market_line = float(row["market_line"])
        over_odds = float(row["over_odds"])
        under_odds = float(row["under_odds"])

        total_sigma = math.sqrt(
            OUTCOME_SIGMA ** 2
            + (0 if pd.isna(disagreement) else disagreement ** 2)
        )

        p_over = prob_over(market_line, ensemble_proj, total_sigma)
        p_under = 1.0 - p_over

        over_ev = expected_value(p_over, over_odds)
        under_ev = expected_value(p_under, under_odds)

        edge_yards = ensemble_proj - market_line

        if edge_yards > 0:
            side = "OVER"
            rec_prob = p_over
            rec_ev = over_ev
            rec_odds = over_odds
        elif edge_yards < 0:
            side = "UNDER"
            rec_prob = p_under
            rec_ev = under_ev
            rec_odds = under_odds
        else:
            side = "NONE"
            rec_prob = 0.5
            rec_ev = 0.0
            rec_odds = math.nan

        rec = recommendation(edge_yards, consensus)
        final_rec = "PASS" if rec == "PASS" else f"{rec} {side}"

        out = row.to_dict()
        out.update(
            {
                "weighted_projection": ensemble_proj,
                "projection_minus_line": edge_yards,
                "projection_disagreement": disagreement,
                "consensus": consensus,
                "total_sigma": total_sigma,
                "p_over": p_over,
                "p_under": p_under,
                "over_ev_percent": over_ev * 100,
                "under_ev_percent": under_ev * 100,
                "recommended_side": side,
                "recommended_prob": rec_prob,
                "recommended_odds": rec_odds,
                "recommended_ev_percent": rec_ev * 100,
                "recommendation": final_rec,
            }
        )

        rows.append(out)

    out_df = pd.DataFrame(rows)

    def recommendation_rank(rec):
        if str(rec).startswith("STRONG BET"):
            return 1
        if str(rec).startswith("BET"):
            return 2
        if str(rec).startswith("LEAN"):
            return 3
        return 4


    out_df["recommendation_rank"] = out_df["recommendation"].apply(recommendation_rank)

    out_df = out_df.sort_values(
        ["recommendation_rank", "recommended_ev_percent"],
        ascending=[True, False],
    ).drop(columns=["recommendation_rank"])

    out_df.to_csv(OUT_FILE, index=False)

    print("\n===== WEEK PASS YDS ENSEMBLE BETS =====")
    display_cols = [
        "player",
        "market_line",
        "weighted_projection",
        "projection_minus_line",
        "consensus",
        "p_over",
        "p_under",
        "recommended_side",
        "recommended_prob",
        "recommended_ev_percent",
        "recommendation",
    ]
    print(out_df[display_cols].to_string(index=False))

    print("\n===== OUTPUT =====")
    print(f"saved: {OUT_FILE}")


if __name__ == "__main__":
    main()