from pathlib import Path
import argparse
import sys

import numpy as np
import pandas as pd


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT / "00_config") not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT / "00_config"))

from market_config import get_market_config
import simulate_pass_yds as passing_backtest


DEFAULT_MARKET = "player_reception_yds"
SUPPORTED_MARKETS = {DEFAULT_MARKET, "player_rush_yds", "player_receptions", "player_pass_yds"}


def norm_player(value):
    return (
        str(value).lower()
        .replace(".", "")
        .replace("'", "")
        .replace(" jr", "")
        .replace(" sr", "")
        .strip()
    )


def find_col(df, candidates, label):
    lower_map = {col.lower(): col for col in df.columns}
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]
    raise RuntimeError(f"No {label} found. Looked for {candidates}. Columns={df.columns.tolist()}")


def detect_odds_format(picks, backtest_config):
    configured = backtest_config.get("odds_format")
    if configured is not None:
        return configured
    prices = pd.concat([picks["over_price"], picks["under_price"]]).dropna().astype(float)
    return "decimal" if (prices > 0).all() and (prices < 20).all() else "american"


def profit_1u(odds, win, odds_format):
    odds = float(odds)
    if not win:
        return -1.0
    if odds_format == "decimal":
        return odds - 1.0
    if odds_format == "american":
        if odds > 0:
            return odds / 100.0
        return 100.0 / abs(odds)
    raise RuntimeError(f"Unknown odds_format={odds_format!r}; expected 'decimal' or 'american'.")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", default=DEFAULT_MARKET)
    parser.add_argument("--picks", type=Path)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def run_passing_reference_backtest(args, backtest_config):
    passing_backtest.INPUT = Path(args.picks or backtest_config["picks_file"])
    output_dir = Path(args.output_dir or backtest_config["output_dir"])
    passing_backtest.OUT_PATH = output_dir / Path(backtest_config["output_file"]).name
    passing_backtest.N_SIMS = backtest_config["n_sims"]
    passing_backtest.RANDOM_SEED = backtest_config["random_seed"]
    passing_backtest.main()


def main():
    args = parse_args()
    if args.market not in SUPPORTED_MARKETS:
        raise RuntimeError(
            f"Market {args.market!r} is not migrated to the generalized backtest yet. "
            f"Currently supported: {', '.join(sorted(SUPPORTED_MARKETS))}"
        )

    config = get_market_config(args.market)
    backtest_config = config["backtest"]
    if backtest_config.get("reference_engine") == "simulate_pass_yds":
        run_passing_reference_backtest(args, backtest_config)
        return
    if config["distribution"] not in {"normal", "negative_binomial"}:
        raise RuntimeError(
            f"{config['label']} uses unsupported backtest distribution={config['distribution']!r}."
        )
    picks_file = args.picks or Path(backtest_config["picks_file"])
    history_file = args.history or Path(backtest_config["history_file"])
    out_dir = args.output_dir or Path(backtest_config["output_dir"])
    output_slug = config["output_slug"]
    projection_col = config["projection_col"]
    line_col = config["line_col"]

    picks = pd.read_csv(picks_file)
    hist = pd.read_csv(history_file)
    odds_format = detect_odds_format(picks, backtest_config)
    print(f"[odds] format={odds_format}")

    side_filter = backtest_config["side_filter"]
    filter_mask = picks["recommended_ev_percent"].between(
        backtest_config["min_ev_percent"],
        backtest_config["max_ev_percent"],
        inclusive="both",
    )
    if side_filter is not None:
        filter_mask &= picks["recommendation"].eq(side_filter)
    picks = picks[filter_mask].copy()
    print(f"[filter] {backtest_config['filter_message']} picks={len(picks):,}")

    picks["player_norm"] = picks["player"].apply(norm_player)
    hist["player_norm"] = hist["player"].apply(norm_player)
    actual_col = find_col(
        hist,
        ["actual", "actual_market_value", *config["actual_col_candidates"]],
        f"actual {config['label'].lower()} column",
    )

    picks_line_col = line_col if line_col in picks.columns else "line"
    merge_picks = picks.copy()
    if picks_line_col != "line":
        merge_picks = merge_picks.rename(columns={picks_line_col: "line"})
    hist = hist.rename(columns={line_col: "line", actual_col: "actual"})
    merge_keys = backtest_config.get("merge_keys", ["season", "week", "player_norm", "line"])
    required_pick_keys = backtest_config.get("required_pick_keys", merge_keys)
    missing_pick_keys = [key for key in required_pick_keys if key not in merge_picks.columns]
    if missing_pick_keys:
        reason = backtest_config.get("blocked_reason", "")
        detail = f" {reason}" if reason else ""
        raise RuntimeError(
            f"Cannot safely backtest {config['label']}: picks are missing stable join keys "
            f"{missing_pick_keys}.{detail}"
        )
    missing_history_keys = [key for key in merge_keys if key not in hist.columns]
    if missing_history_keys:
        raise RuntimeError(
            f"Cannot safely backtest {config['label']}: history is missing join keys "
            f"{missing_history_keys}."
        )
    hist = hist[[*merge_keys, "actual"]].copy()
    df = merge_picks.merge(hist, on=merge_keys, how="left", validate="many_to_one")

    print(f"[load] picks={len(picks):,}")
    print(f"[merge] rows={len(df):,}")
    print(f"[merge] actual matched={df['actual'].notna().sum():,}")
    print(f"[merge] actual missing={df['actual'].isna().sum():,}")
    df = df.dropna(subset=["actual"]).copy()

    model_projection_col = projection_col if projection_col in df.columns else "projection"
    edge_col = backtest_config.get("edge_col", "edge_yards")
    summary_edge_col = backtest_config.get("summary_edge_col", "avg_edge_yards")
    df[edge_col] = (df[model_projection_col] - df["line"]).abs()
    df["model_side"] = df["recommended_side"]
    if backtest_config.get("print_side_recommendations"):
        print(f"\n===== {side_filter.upper()} RECOMMENDATIONS =====")
        print(
            df.loc[
                df["model_side"] == side_filter,
                [
                    "player",
                    "season",
                    "week",
                    "line",
                    model_projection_col,
                    "recommended_ev_percent",
                    "actual",
                ],
            ]
            .rename(columns={model_projection_col: "projection"})
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
        0.0 if pushed else profit_1u(odds, won, odds_format)
        for odds, won, pushed in zip(df["bet_odds"], df["bet_won"], df["bet_pushed"])
    ]

    df["edge_bucket"] = pd.cut(
        df[edge_col],
        bins=backtest_config["edge_bins"],
        labels=backtest_config["edge_labels"],
        right=False,
    )
    df["ev_bucket"] = pd.cut(
        df["recommended_ev_percent"],
        bins=backtest_config["ev_bins"],
        labels=backtest_config["ev_labels"],
        right=False,
    )

    summary = pd.DataFrame([{
        "bets": len(df),
        "wins": int(df["bet_won"].sum()),
        "pushes": int(df["bet_pushed"].sum()),
        "hit_rate": df.loc[~df["bet_pushed"], "bet_won"].mean(),
        "profit_units": df["profit_1u"].sum(),
        "roi": df["profit_1u"].sum() / len(df),
        summary_edge_col: df[edge_col].mean(),
        "avg_ev_percent": df["recommended_ev_percent"].mean(),
    }])
    by_edge = df.groupby("edge_bucket", dropna=False).agg(
        bets=("profit_1u", "size"),
        hit_rate=("bet_won", "mean"),
        profit_units=("profit_1u", "sum"),
        avg_profit=("profit_1u", "mean"),
        avg_ev_percent=("recommended_ev_percent", "mean"),
        **{summary_edge_col: (edge_col, "mean")},
    ).reset_index()
    by_ev = df.groupby("ev_bucket", dropna=False).agg(
        bets=("profit_1u", "size"),
        hit_rate=("bet_won", "mean"),
        profit_units=("profit_1u", "sum"),
        avg_profit=("profit_1u", "mean"),
        avg_ev_percent=("recommended_ev_percent", "mean"),
        **{summary_edge_col: (edge_col, "mean")},
    ).reset_index()
    by_side = df.groupby("model_side", dropna=False).agg(
        bets=("profit_1u", "size"),
        hit_rate=("bet_won", "mean"),
        profit_units=("profit_1u", "sum"),
        avg_profit=("profit_1u", "mean"),
    ).reset_index()

    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / f"{output_slug}_backtest_rows.csv", index=False)
    summary.to_csv(out_dir / f"{output_slug}_backtest_summary.csv", index=False)
    by_edge.to_csv(out_dir / f"{output_slug}_backtest_by_edge_bucket.csv", index=False)
    by_ev.to_csv(out_dir / f"{output_slug}_backtest_by_ev_bucket.csv", index=False)
    by_side.to_csv(out_dir / f"{output_slug}_backtest_by_side.csv", index=False)

    print(f"\n===== {backtest_config.get('summary_heading', 'SUMMARY')} =====")
    print(summary.to_string(index=False))
    print("\n===== BY EDGE BUCKET =====")
    print(by_edge.to_string(index=False))
    print("\n===== BY EV BUCKET =====")
    print(by_ev.to_string(index=False))
    print("\n===== BY SIDE =====")
    print(by_side.to_string(index=False))
    print(f"\n[saved] {out_dir}")


if __name__ == "__main__":
    main()
