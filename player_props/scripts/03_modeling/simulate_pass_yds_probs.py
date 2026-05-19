from pathlib import Path

import numpy as np
import pandas as pd


IN_FILE = Path("data/processed/pass_yds_dataset_sigma.csv")
OUT_FILE = Path("data/processed/pass_yds_sim_probs.csv")

N_SIMS = 20000
SEED = 42

EDGE_BUCKETS = [0, 0.40, 0.45, 0.475, 0.50, 0.525, 0.55, 0.60, 1.0]


def prob_to_american_odds(p):
    if p <= 0 or p >= 1:
        return None
    if p >= 0.5:
        return -100 * p / (1 - p)
    return 100 * (1 - p) / p


def main():
    df = pd.read_csv(IN_FILE)

    df = df[
        (df["market_key"] == "player_pass_yds")
        & df["fp_pass_yds_debiased"].notna()
        & df["pass_yds_sigma"].notna()
        & df["line"].notna()
        & df["actual_value"].notna()
    ].copy()

    print(f"[load] usable_rows={len(df):,}")

    rng = np.random.default_rng(SEED)

    sim_probs = []
    sim_means = []
    sim_meds = []
    sim_stds = []

    for i, row in df.iterrows():
        mu = float(row["fp_pass_yds_debiased"])
        sigma = float(row["pass_yds_sigma"])
        line = float(row["line"])

        if sigma <= 0:
            sims = np.full(N_SIMS, mu)
        else:
            sims = rng.normal(loc=mu, scale=sigma, size=N_SIMS)

        prob_over = (sims > line).mean()
        prob_under = (sims < line).mean()

        sim_probs.append((prob_over, prob_under))
        sim_means.append(sims.mean())
        sim_meds.append(np.median(sims))
        sim_stds.append(sims.std(ddof=0))

    sim_probs = np.array(sim_probs)
    df["sim_prob_over"] = sim_probs[:, 0]
    df["sim_prob_under"] = sim_probs[:, 1]
    df["sim_mean"] = sim_means
    df["sim_median"] = sim_meds
    df["sim_std"] = sim_stds

    df["fair_over_odds"] = df["sim_prob_over"].apply(prob_to_american_odds)
    df["fair_under_odds"] = df["sim_prob_under"].apply(prob_to_american_odds)

    df["model_edge_over"] = df["sim_prob_over"] - 0.5
    df["model_edge_under"] = df["sim_prob_under"] - 0.5

    # Probability shrinkage toward 0.5 to reduce overconfident edges
    df["sim_prob_over_shrunk"] = 0.5 + 0.65 * (df["sim_prob_over"] - 0.5)
    df["sim_prob_under_shrunk"] = 0.5 + 0.65 * (df["sim_prob_under"] - 0.5)

    # v1 betting policy: only consider bets in these original-probability ranges
    # Over: 0.55 <= P(over) < 0.60
    # Under: 0.40 < P(over) <= 0.45  (i.e., P(under) in [0.55,0.60) roughly)
    def pick_with_shrink(row):
        po = row["sim_prob_over"]
        pu = row["sim_prob_under"]
        po_s = row["sim_prob_over_shrunk"]
        pu_s = row["sim_prob_under_shrunk"]

        # Over-range
        if (po >= 0.55) and (po < 0.60):
            return "over" if po_s >= 0.525 else "pass"

        # Under-range (expressed via sim_prob_over bounds)
        if (po > 0.40) and (po <= 0.45):
            return "under" if pu_s >= 0.525 else "pass"

        return "pass"

    df["model_pick"] = df.apply(pick_with_shrink, axis=1)

    # Historical performance by pick
    df["went_over"] = df["actual_value"] > df["line"]
    df["went_under"] = df["actual_value"] < df["line"]
    df["push"] = df["actual_value"] == df["line"]

    grp = df.groupby("model_pick", observed=True)

    print("\n===== PERFORMANCE BY MODEL PICK =====")
    for name, g in grp:
        rows = len(g)
        if name == "pass":
            hit_rate = float("nan")
        else:
            if name == "over":
                hits = ((g["went_over"]) & (~g["push"]))
            else:
                hits = ((g["went_under"]) & (~g["push"]))
            denom = (~g["push"]).sum()
            hit_rate = hits.sum() / denom if denom > 0 else float("nan")

        print(f"pick={name}: rows={rows}, hit_rate={hit_rate if pd.notna(hit_rate) else 'NA'}, avg_prob_over={g['sim_prob_over'].mean():.3f}, avg_prob_under={g['sim_prob_under'].mean():.3f}, avg_actual_minus_line={(g['actual_value'] - g['line']).mean():.3f}")

    # Edge buckets
    df["prob_bucket"] = pd.cut(df["sim_prob_over"], bins=EDGE_BUCKETS, right=False)

    grp = df.groupby("prob_bucket", observed=True)
    edge_rows = grp.size()
    edge_avg_prob = grp["sim_prob_over"].mean()
    edge_over_rate = grp["went_over"].mean()
    edge_avg_actual_minus_line = grp.apply(lambda g: (g["actual_value"] - g["line"]).mean())

    edge_summary = (
        pd.DataFrame(
            {
                "prob_bucket": edge_rows.index.astype(str),
                "rows": edge_rows.values,
                "avg_prob_over": edge_avg_prob.values,
                "over_rate": edge_over_rate.values,
                "avg_actual_minus_line": edge_avg_actual_minus_line.values,
            }
        )
    )

    print("\n===== EDGE BUCKETS =====")
    print(edge_summary.to_string(index=False))

    # historical top opportunities
    # Limit top opportunities to actionable zone and sort by edge within that zone
    top = df[
        ((df["sim_prob_over"] >= 0.55) & (df["sim_prob_over"] < 0.60))
        | ((df["sim_prob_over"] > 0.40) & (df["sim_prob_over"] <= 0.45))
    ].copy()
    top["edge_from_50"] = (top["sim_prob_over"] - 0.5).abs()
    top = top.sort_values("edge_from_50", ascending=False).head(20)

    top_cols = [
        "season",
        "week",
        "player",
        "line",
        "fp_pass_yds_debiased",
        "pass_yds_sigma",
        "sim_prob_over",
        "sim_prob_under",
        "fair_over_odds",
        "fair_under_odds",
        "actual_value",
    ]

    top = top.assign(went_over=(top["actual_value"] > top["line"]))
    print("\n===== TOP 20 OPPORTUNITIES (ACTIONABLE ZONE) =====")
    print(top[top_cols + ["went_over", "edge_from_50"]].to_string(index=False))

    df.to_csv(OUT_FILE, index=False)
    print(f"\n[save] {OUT_FILE}")


if __name__ == "__main__":
    main()
