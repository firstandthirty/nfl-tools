from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt


BASE_DIR = Path(r"C:\Users\brady\OneDrive\Desktop\nfl-tools\player props")
MASTER_PATH = BASE_DIR / "data" / "processed" / "pff" / "pff_player_weekly_master.csv"

OUT_DIR = BASE_DIR / "data" / "processed" / "eda_plots"
OUT_DIR.mkdir(parents=True, exist_ok=True)


PLOTS = [
    {
        "label": "QB_pass_attempts_gte_20_passing_yards",
        "stat": "passing_yards",
        "filter": lambda df: (df["position"] == "QB") & (df["pass_attempts"] >= 20),
        "title": "QB Passing Yards | Pass Attempts >= 20",
        "bins": 40,
    },
    {
        "label": "WR_TE_routes_gte_15_receiving_yards",
        "stat": "receiving_yards",
        "filter": lambda df: df["position"].isin(["WR", "TE"]) & (df["routes"] >= 15),
        "title": "WR/TE Receiving Yards | Routes >= 15",
        "bins": 50,
    },
    {
        "label": "WR_TE_targets_gte_7_receiving_yards",
        "stat": "receiving_yards",
        "filter": lambda df: df["position"].isin(["WR", "TE"]) & (df["routes"] >= 15) & (df["targets"] >= 7),
        "title": "WR/TE Receiving Yards | Routes >= 15 and Targets >= 7",
        "bins": 50,
    },
    {
        "label": "RB_rush_attempts_gte_8_rushing_yards",
        "stat": "rushing_yards",
        "filter": lambda df: df["position"].isin(["HB", "RB"]) & (df["rush_attempts"] >= 8),
        "title": "RB Rushing Yards | Rush Attempts >= 8",
        "bins": 50,
    },
    {
        "label": "QB_rush_attempts_gte_5_rushing_yards",
        "stat": "rushing_yards",
        "filter": lambda df: (df["position"] == "QB") & (df["rush_attempts"] >= 5),
        "title": "QB Rushing Yards | Rush Attempts >= 5",
        "bins": 40,
    },
]


def add_summary_lines(ax, s):
    mean = s.mean()
    median = s.median()
    p25 = s.quantile(0.25)
    p75 = s.quantile(0.75)
    p90 = s.quantile(0.90)

    ax.axvline(mean, linestyle="--", linewidth=1.5, label=f"Mean: {mean:.1f}")
    ax.axvline(median, linestyle="-", linewidth=1.5, label=f"Median: {median:.1f}")
    ax.axvline(p25, linestyle=":", linewidth=1.2, label=f"P25: {p25:.1f}")
    ax.axvline(p75, linestyle=":", linewidth=1.2, label=f"P75: {p75:.1f}")
    ax.axvline(p90, linestyle="-.", linewidth=1.2, label=f"P90: {p90:.1f}")


def plot_histogram(df, cfg):
    stat = cfg["stat"]
    filtered = df[cfg["filter"](df)].copy()

    s = pd.to_numeric(filtered[stat], errors="coerce").dropna()

    if s.empty:
        print(f"[skip] {cfg['label']} no data")
        return

    fig, ax = plt.subplots(figsize=(10, 6))

    ax.hist(s, bins=cfg["bins"], edgecolor="black", alpha=0.75)
    add_summary_lines(ax, s)

    ax.set_title(cfg["title"])
    ax.set_xlabel(stat)
    ax.set_ylabel("Player-games")
    ax.legend()

    summary_text = (
        f"n={len(s):,}\n"
        f"mean={s.mean():.1f}\n"
        f"median={s.median():.1f}\n"
        f"std={s.std():.1f}\n"
        f"cv={(s.std() / s.mean()):.2f}\n"
        f"skew={s.skew():.2f}"
    )

    ax.text(
        0.98,
        0.95,
        summary_text,
        transform=ax.transAxes,
        verticalalignment="top",
        horizontalalignment="right",
        bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.8},
    )

    out_path = OUT_DIR / f"{cfg['label']}.png"
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)

    print(f"[saved] {out_path}")


def plot_boxplot_comparison(df):
    groups = {
        "QB Pass Yds\nAtt >= 20": (
            (df["position"] == "QB") & (df["pass_attempts"] >= 20),
            "passing_yards",
        ),
        "WR/TE Rec Yds\nRoutes >= 15": (
            df["position"].isin(["WR", "TE"]) & (df["routes"] >= 15),
            "receiving_yards",
        ),
        "WR/TE Rec Yds\nTargets >= 7": (
            df["position"].isin(["WR", "TE"]) & (df["routes"] >= 15) & (df["targets"] >= 7),
            "receiving_yards",
        ),
        "RB Rush Yds\nCarries >= 8": (
            df["position"].isin(["HB", "RB"]) & (df["rush_attempts"] >= 8),
            "rushing_yards",
        ),
        "QB Rush Yds\nCarries >= 5": (
            (df["position"] == "QB") & (df["rush_attempts"] >= 5),
            "rushing_yards",
        ),
    }

    labels = []
    data = []

    for label, (mask, stat) in groups.items():
        s = pd.to_numeric(df.loc[mask, stat], errors="coerce").dropna()
        if not s.empty:
            labels.append(label)
            data.append(s)

    fig, ax = plt.subplots(figsize=(12, 7))
    ax.boxplot(data, labels=labels, showfliers=False)

    ax.set_title("Distribution Comparison | Outliers Hidden")
    ax.set_ylabel("Yards")
    ax.tick_params(axis="x", labelrotation=20)

    out_path = OUT_DIR / "boxplot_distribution_comparison.png"
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)

    print(f"[saved] {out_path}")


def main():
    print(f"[load] {MASTER_PATH}")
    df = pd.read_csv(MASTER_PATH)

    numeric_cols = [
        "passing_yards",
        "pass_attempts",
        "receiving_yards",
        "routes",
        "targets",
        "rushing_yards",
        "rush_attempts",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for cfg in PLOTS:
        plot_histogram(df, cfg)

    plot_boxplot_comparison(df)

    print("[done]")


if __name__ == "__main__":
    main()