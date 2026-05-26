from pathlib import Path
import pandas as pd
import numpy as np


PICKS_FILE = Path("data/analysis/rush_yds_model_bets.csv")
HISTORY_FILE = Path("data/analysis/rush_yds_market_analysis_rows.csv")
OUT_DIR = Path("data/analysis/backtests")


def norm_player(s):
    return (
        str(s).lower()
        .replace(".", "")
        .replace("'", "")
        .replace(" jr", "")
        .replace(" sr", "")
        .strip()
    )


def american_profit(odds, win):
    odds = float(odds)
    if not win:
        return -1.0
    if odds > 0:
        return odds / 100.0
    return 100.0 / abs(odds)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    
    picks = pd.read_csv(PICKS_FILE)
    hist = pd.read_csv(HISTORY_FILE)

    # TEMP TEST: rushing yards v1 filter
    # unders only, EV 2-10%
    picks = picks[
        (picks["recommendation"] == "under")
        & (picks["recommended_ev_percent"] >= 0)
        & (picks["recommended_ev_percent"] <= 15)
    ].copy()

    print(f"[filter] unders only, EV 0-15 picks={len(picks):,}")

    picks["player_norm"] = picks["player"].apply(norm_player)
    hist["player_norm"] = hist["player"].apply(norm_player)

    actual_col = None
    for c in ["actual", "actual_market_value", "actual_rushing_yards", "rushing_yards", "actual_rush_yds", "rush_yds"]:
        if c in hist.columns:
            actual_col = c
            break

    if actual_col is None:
        raise RuntimeError(f"No actual rushing yards column found. Columns={hist.columns.tolist()}")

    hist = hist[["season", "week", "player_norm", "line", actual_col]].copy()
    hist = hist.rename(columns={actual_col: "actual"})

    df = picks.merge(
        hist,
        on=["season", "week", "player_norm", "line"],
        how="left",
    )

    print(f"[load] picks={len(picks):,}")
    print(f"[merge] rows={len(df):,}")
    print(f"[merge] actual matched={df['actual'].notna().sum():,}")
    print(f"[merge] actual missing={df['actual'].isna().sum():,}")

    df = df.dropna(subset=["actual"]).copy()

    df["edge_yards"] = (df["projection"] - df["line"]).abs()
    df["model_side"] = df["recommended_side"]

    print("\n===== UNDER RECOMMENDATIONS =====")

    print(
        df.loc[
            df["model_side"] == "under",
            [
                "player",
                "season",
                "week",
                "line",
                "projection",
                "recommended_ev_percent",
                "actual",
            ],
        ]
        .sort_values("recommended_ev_percent", ascending=False)
        .to_string(index=False)
    )

    df["bet_won"] = np.where(
        df["model_side"].eq("over"),
        df["actual"] > df["line"],
        df["actual"] < df["line"],
    )

    df["bet_pushed"] = df["actual"].eq(df["line"])

    df["bet_odds"] = np.where(
        df["model_side"].eq("over"),
        df["over_price"],
        df["under_price"],
    )

    df["profit_1u"] = [
        0.0 if pushed else american_profit(odds, won)
        for odds, won, pushed in zip(df["bet_odds"], df["bet_won"], df["bet_pushed"])
    ]

    df["edge_bucket"] = pd.cut(
        df["edge_yards"],
        bins=[0, 2.5, 5, 7.5, 10, 15, 20, 999],
        labels=["0-2.5", "2.5-5", "5-7.5", "7.5-10", "10-15", "15-20", "20+"],
        right=False,
    )

    df["ev_bucket"] = pd.cut(
        df["recommended_ev_percent"],
        bins=[-999, 0, 2, 5, 10, 15, 20, 999],
        labels=["<0", "0-2", "2-5", "5-10", "10-15", "15-20", "20+"],
        right=False,
    )

    summary = pd.DataFrame([{
        "bets": len(df),
        "wins": int(df["bet_won"].sum()),
        "pushes": int(df["bet_pushed"].sum()),
        "hit_rate": df.loc[~df["bet_pushed"], "bet_won"].mean(),
        "profit_units": df["profit_1u"].sum(),
        "roi": df["profit_1u"].sum() / len(df),
        "avg_edge_yards": df["edge_yards"].mean(),
        "avg_ev_percent": df["recommended_ev_percent"].mean(),
    }])

    by_edge = df.groupby("edge_bucket", dropna=False).agg(
        bets=("profit_1u", "size"),
        hit_rate=("bet_won", "mean"),
        profit_units=("profit_1u", "sum"),
        avg_profit=("profit_1u", "mean"),
        avg_ev_percent=("recommended_ev_percent", "mean"),
        avg_edge_yards=("edge_yards", "mean"),
    ).reset_index()

    by_ev = df.groupby("ev_bucket", dropna=False).agg(
        bets=("profit_1u", "size"),
        hit_rate=("bet_won", "mean"),
        profit_units=("profit_1u", "sum"),
        avg_profit=("profit_1u", "mean"),
        avg_ev_percent=("recommended_ev_percent", "mean"),
        avg_edge_yards=("edge_yards", "mean"),
    ).reset_index()

    by_side = df.groupby("model_side", dropna=False).agg(
        bets=("profit_1u", "size"),
        hit_rate=("bet_won", "mean"),
        profit_units=("profit_1u", "sum"),
        avg_profit=("profit_1u", "mean"),
    ).reset_index()

    df.to_csv(OUT_DIR / "rush_yds_backtest_rows.csv", index=False)
    summary.to_csv(OUT_DIR / "rush_yds_backtest_summary.csv", index=False)
    by_edge.to_csv(OUT_DIR / "rush_yds_backtest_by_edge_bucket.csv", index=False)
    by_ev.to_csv(OUT_DIR / "rush_yds_backtest_by_ev_bucket.csv", index=False)
    by_side.to_csv(OUT_DIR / "rush_yds_backtest_by_side.csv", index=False)

    print("\n===== RUSH YARDS SUMMARY =====")
    print(summary.to_string(index=False))

    print("\n===== BY EDGE BUCKET =====")
    print(by_edge.to_string(index=False))

    print("\n===== BY EV BUCKET =====")
    print(by_ev.to_string(index=False))

    print("\n===== BY SIDE =====")
    print(by_side.to_string(index=False))

    print(f"\n[saved] {OUT_DIR}")

if __name__ == "__main__":
    main()