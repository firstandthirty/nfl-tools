from pathlib import Path
import math

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


INPUT_FILE = Path("data/analysis/pass_yds_market_analysis_rows.csv")
OUT_DIR = Path("data/analysis")
PLOT_DIR = OUT_DIR / "plots"

FIT_SUMMARY_FILE = OUT_DIR / "pass_yds_distribution_fit_summary.csv"
CALIBRATION_FILE = OUT_DIR / "pass_yds_distribution_calibration.csv"
BINS_FILE = OUT_DIR / "pass_yds_distribution_probability_bins.csv"

RANDOM_SEED = 42
N_BOOTSTRAP = 20000


def normal_cdf(x, mu=0.0, sigma=1.0):
    if sigma <= 0:
        return math.nan
    z = (x - mu) / sigma
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def normal_prob_over(threshold, mean, sigma):
    return 1.0 - normal_cdf(threshold, mean, sigma)


def brier_score(y, p):
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    return np.mean((p - y) ** 2)


def log_loss(y, p, eps=1e-12):
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    p = np.clip(p, eps, 1 - eps)
    return -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))


def make_prob_bins(df, prob_col, label):
    bins = np.arange(0.0, 1.0001, 0.05)
    out = df.copy()
    out["prob_bin"] = pd.cut(out[prob_col], bins=bins, include_lowest=True)

    grouped = (
        out.groupby("prob_bin", observed=False)
        .agg(
            model=("model", lambda x: label),
            rows=("hit_over", "size"),
            avg_prob=(prob_col, "mean"),
            actual_over_rate=("hit_over", "mean"),
        )
        .reset_index()
    )
    grouped["calibration_gap"] = grouped["actual_over_rate"] - grouped["avg_prob"]
    return grouped[grouped["rows"] > 0]


def empirical_prob_over_from_residuals(threshold_delta, residuals):
    """
    If market line is treated as median baseline, residual = actual - line.
    For a target threshold above/below that baseline, P(over threshold)
    is P(residual > threshold_delta).
    """
    return float(np.mean(residuals > threshold_delta))


def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Missing input file: {INPUT_FILE}\n"
            "Run scripts/04_analysis/analyze_pass_yds_market.py first."
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PLOT_DIR.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(INPUT_FILE)

    required = [
        "line",
        "actual_passing_yards",
        "actual_minus_line",
        "hit_over",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(
            "Missing required columns:\n"
            + "\n".join(f"- {c}" for c in missing)
            + "\n\nAvailable columns:\n"
            + "\n".join(df.columns.astype(str))
        )

    df["line"] = pd.to_numeric(df["line"], errors="coerce")
    df["actual_passing_yards"] = pd.to_numeric(df["actual_passing_yards"], errors="coerce")
    df["actual_minus_line"] = pd.to_numeric(df["actual_minus_line"], errors="coerce")
    df["hit_over"] = df["actual_passing_yards"] > df["line"]

    df = df.dropna(subset=["line", "actual_passing_yards", "actual_minus_line"]).copy()

    # Full residuals
    full_resid = df["actual_minus_line"].to_numpy(dtype=float)

    # Clean residuals: keep meaningful starts and remove extreme tails
    clean = df.copy()

    if "pass_attempts" in clean.columns:
        clean["pass_attempts"] = pd.to_numeric(clean["pass_attempts"], errors="coerce")
        clean = clean[clean["pass_attempts"].isna() | (clean["pass_attempts"] >= 10)].copy()
    else:
        clean = clean[clean["actual_passing_yards"] >= 25].copy()

    clean = clean[clean["actual_minus_line"].between(-200, 200)].copy()
    clean_resid = clean["actual_minus_line"].to_numpy(dtype=float)

    print(f"[load] rows={len(df):,}")
    print(f"[clean] rows={len(clean):,}")
    print(f"[clean] removed={len(df) - len(clean):,}")

    # Distribution parameter estimates
    full_mu = float(np.mean(full_resid))
    full_sigma = float(np.std(full_resid, ddof=1))

    clean_mu = float(np.mean(clean_resid))
    clean_sigma = float(np.std(clean_resid, ddof=1))

    # Robust sigma using IQR. For normal dist, sigma ~= IQR / 1.349
    q25, q75 = np.quantile(clean_resid, [0.25, 0.75])
    robust_sigma = float((q75 - q25) / 1.349)

    # Because market line behaves like median, a market-only model should be ~50%.
    # For distribution fitting, we test probabilities for the actual listed line.
    # Normal centered on line + residual mean.
    df["p_over_normal_full"] = [
        normal_prob_over(line, line + full_mu, full_sigma)
        for line in df["line"]
    ]

    df["p_over_normal_clean"] = [
        normal_prob_over(line, line + clean_mu, clean_sigma)
        for line in df["line"]
    ]

    df["p_over_normal_robust"] = [
        normal_prob_over(line, line + clean_mu, robust_sigma)
        for line in df["line"]
    ]

    # Empirical residual distribution. Since listed line is the threshold,
    # threshold_delta = 0.
    emp_prob_full = empirical_prob_over_from_residuals(0.0, full_resid)
    emp_prob_clean = empirical_prob_over_from_residuals(0.0, clean_resid)

    df["p_over_empirical_full"] = emp_prob_full
    df["p_over_empirical_clean"] = emp_prob_clean

    model_cols = [
        "p_over_normal_full",
        "p_over_normal_clean",
        "p_over_normal_robust",
        "p_over_empirical_full",
        "p_over_empirical_clean",
    ]

    fit_rows = []
    for col in model_cols:
        fit_rows.append(
            {
                "model": col,
                "rows": len(df),
                "avg_pred_prob": df[col].mean(),
                "actual_over_rate": df["hit_over"].mean(),
                "calibration_gap": df["hit_over"].mean() - df[col].mean(),
                "brier_score": brier_score(df["hit_over"], df[col]),
                "log_loss": log_loss(df["hit_over"], df[col]),
            }
        )

    fit_summary = pd.DataFrame(fit_rows)

    param_summary = pd.DataFrame(
        [
            {
                "sample": "full",
                "rows": len(full_resid),
                "mean": full_mu,
                "std": full_sigma,
                "p5": np.quantile(full_resid, 0.05),
                "p10": np.quantile(full_resid, 0.10),
                "p25": np.quantile(full_resid, 0.25),
                "p50": np.quantile(full_resid, 0.50),
                "p75": np.quantile(full_resid, 0.75),
                "p90": np.quantile(full_resid, 0.90),
                "p95": np.quantile(full_resid, 0.95),
            },
            {
                "sample": "clean",
                "rows": len(clean_resid),
                "mean": clean_mu,
                "std": clean_sigma,
                "robust_sigma_iqr": robust_sigma,
                "p5": np.quantile(clean_resid, 0.05),
                "p10": np.quantile(clean_resid, 0.10),
                "p25": np.quantile(clean_resid, 0.25),
                "p50": np.quantile(clean_resid, 0.50),
                "p75": np.quantile(clean_resid, 0.75),
                "p90": np.quantile(clean_resid, 0.90),
                "p95": np.quantile(clean_resid, 0.95),
            },
        ]
    )

    fit_summary.to_csv(FIT_SUMMARY_FILE, index=False)

    all_bins = []
    for col in model_cols:
        all_bins.append(make_prob_bins(df.assign(model=col), col, col))

    calibration = pd.concat(all_bins, ignore_index=True)
    calibration.to_csv(CALIBRATION_FILE, index=False)

    # Useful “what delta do we need?” table.
    # Interpret delta as projection_mean - market_line.
    # Assuming a normal distribution centered at projection mean, estimate P(over market line).
    deltas = list(range(-40, 45, 5))
    delta_rows = []
    for delta in deltas:
        p_clean = normal_prob_over(0.0, delta, clean_sigma)
        p_robust = normal_prob_over(0.0, delta, robust_sigma)
        p_full = normal_prob_over(0.0, delta, full_sigma)

        delta_rows.append(
            {
                "projection_minus_line": delta,
                "p_over_normal_full_sigma": p_full,
                "p_over_normal_clean_sigma": p_clean,
                "p_over_normal_robust_sigma": p_robust,
                "fair_decimal_clean_sigma": 1 / p_clean if p_clean > 0 else math.nan,
                "fair_decimal_robust_sigma": 1 / p_robust if p_robust > 0 else math.nan,
            }
        )

    delta_table = pd.DataFrame(delta_rows)
    delta_table.to_csv(BINS_FILE, index=False)

    # Plots
    hist_path = PLOT_DIR / "pass_yds_residual_distribution_fit.png"
    qq_path = PLOT_DIR / "pass_yds_residual_qq_normal.png"
    delta_path = PLOT_DIR / "pass_yds_projection_delta_to_p_over.png"

    plt.figure()
    plt.hist(clean_resid, bins=40, density=True, alpha=0.55)
    xs = np.linspace(clean_resid.min(), clean_resid.max(), 500)
    ys = [
        (1 / (clean_sigma * math.sqrt(2 * math.pi)))
        * math.exp(-0.5 * ((x - clean_mu) / clean_sigma) ** 2)
        for x in xs
    ]
    plt.plot(xs, ys)
    plt.title("Passing Yards Residuals vs Normal Fit")
    plt.xlabel("Actual - Market Line")
    plt.ylabel("Density")
    plt.tight_layout()
    plt.savefig(hist_path)
    plt.close()

    sorted_resid = np.sort(clean_resid)
    n = len(sorted_resid)

    # Approximate normal theoretical quantiles via numpy percentile on simulated normal samples
    rng = np.random.default_rng(RANDOM_SEED)
    sim_normal = rng.normal(clean_mu, clean_sigma, size=200000)
    probs = (np.arange(1, n + 1) - 0.5) / n
    theoretical = np.quantile(sim_normal, probs)

    plt.figure()
    plt.scatter(theoretical, sorted_resid, alpha=0.35)
    lo = min(theoretical.min(), sorted_resid.min())
    hi = max(theoretical.max(), sorted_resid.max())
    plt.plot([lo, hi], [lo, hi])
    plt.title("Q-Q Plot: Clean Residuals vs Normal")
    plt.xlabel("Normal Theoretical Quantiles")
    plt.ylabel("Observed Residual Quantiles")
    plt.tight_layout()
    plt.savefig(qq_path)
    plt.close()

    plt.figure()
    plt.plot(
        delta_table["projection_minus_line"],
        delta_table["p_over_normal_clean_sigma"],
        marker="o",
    )
    plt.axhline(0.5, linestyle="--")
    plt.title("Projection Edge to Estimated P(Over)")
    plt.xlabel("Projection Mean - Market Line")
    plt.ylabel("Estimated P(Over)")
    plt.tight_layout()
    plt.savefig(delta_path)
    plt.close()

    print("\n===== DISTRIBUTION PARAMS =====")
    print(param_summary.to_string(index=False))

    print("\n===== FIT SUMMARY =====")
    print(fit_summary.to_string(index=False))

    print("\n===== PROJECTION DELTA TABLE =====")
    print(delta_table.to_string(index=False))

    print("\n===== OUTPUTS =====")
    print(f"fit summary: {FIT_SUMMARY_FILE}")
    print(f"calibration: {CALIBRATION_FILE}")
    print(f"delta table: {BINS_FILE}")
    print(f"hist: {hist_path}")
    print(f"qq: {qq_path}")
    print(f"delta plot: {delta_path}")


if __name__ == "__main__":
    main()