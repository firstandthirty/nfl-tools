from pathlib import Path
import argparse
import math

import numpy as np
import pandas as pd


DEFAULT_INPUT = Path("data/analysis/backtests/reception_yds_backtest_rows.csv")
DEFAULT_OUTPUT = Path("data/analysis/diagnostics/receiving_yds_filter_experiments.csv")


def warn(message):
    print(f"[warn] {message}")


def first_available(df, candidates):
    return next((col for col in candidates if col in df.columns), None)


def to_bool(series):
    if pd.api.types.is_bool_dtype(series):
        return series
    return series.astype(str).str.lower().isin({"true", "1", "yes"})


def american_profit(odds, won):
    if not won:
        return -1.0
    odds = float(odds)
    return odds / 100.0 if odds > 0 else 100.0 / abs(odds)


def implied_probability(odds):
    if pd.isna(odds):
        return math.nan
    odds = float(odds)
    return abs(odds) / (abs(odds) + 100.0) if odds < 0 else 100.0 / (odds + 100.0)


def prepare_rows(raw):
    df = raw.copy()
    side_col = first_available(df, ["model_side", "recommended_side"])
    projection_col = first_available(df, ["projection", "fp_receiving_yds"])
    actual_col = first_available(df, ["actual", "actual_receiving_yards", "receiving_yards"])

    required = {
        "side": side_col,
        "projection": projection_col,
        "actual": actual_col,
        "line": "line" if "line" in df.columns else None,
    }
    missing_required = [label for label, col in required.items() if col is None]
    if missing_required:
        raise RuntimeError(f"Input cannot support filter experiments; missing {missing_required}.")

    df["side"] = df[side_col].astype(str).str.lower()
    df["projection_value"] = pd.to_numeric(df[projection_col], errors="coerce")
    df["actual_value_diagnostic"] = pd.to_numeric(df[actual_col], errors="coerce")
    for col in ["line", "team_spread", "game_total", "recommended_ev_percent", "recommended_prob"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            warn(f"missing {col}; experiments requiring it will retain zero rows or remove none.")
            df[col] = np.nan
    if "position" not in df.columns:
        warn("missing position; WR-specific filter will remove none.")
        df["position"] = ""

    if "edge_yards" in df.columns:
        df["edge_yards"] = pd.to_numeric(df["edge_yards"], errors="coerce")
    else:
        warn("missing edge_yards; derived abs(projection - line).")
        df["edge_yards"] = (df["projection_value"] - df["line"]).abs()

    if "bet_pushed" in df.columns:
        df["pushed"] = to_bool(df["bet_pushed"])
    else:
        warn("missing bet_pushed; inferred from actual == line.")
        df["pushed"] = df["actual_value_diagnostic"].eq(df["line"])
    if "bet_won" in df.columns:
        df["won"] = to_bool(df["bet_won"])
    else:
        warn("missing bet_won; inferred from side and settled actual.")
        df["won"] = np.where(
            df["side"].eq("over"),
            df["actual_value_diagnostic"] > df["line"],
            df["actual_value_diagnostic"] < df["line"],
        )
    if "bet_odds" in df.columns:
        df["market_odds"] = pd.to_numeric(df["bet_odds"], errors="coerce")
    elif {"over_price", "under_price"}.issubset(df.columns):
        warn("missing bet_odds; selected market price by recommended side.")
        df["market_odds"] = np.where(df["side"].eq("over"), df["over_price"], df["under_price"])
    else:
        warn("missing market odds; profit and implied-probability metrics may be blank.")
        df["market_odds"] = np.nan

    if "profit_1u" not in df.columns:
        warn("missing profit_1u; inferred using American odds from settled rows.")
        df["profit_1u"] = [
            0.0 if pushed else american_profit(odds, won)
            for odds, won, pushed in zip(df["market_odds"], df["won"], df["pushed"])
        ]
    else:
        df["profit_1u"] = pd.to_numeric(df["profit_1u"], errors="coerce")

    df["implied_prob"] = df["market_odds"].apply(implied_probability)
    df["projection_minus_actual"] = df["projection_value"] - df["actual_value_diagnostic"]
    return df


def summarize(frame):
    decided = frame.loc[~frame["pushed"]]
    return {
        "bets": len(frame),
        "wins": int(frame["won"].sum()),
        "pushes": int(frame["pushed"].sum()),
        "hit_rate": decided["won"].mean(),
        "profit_units": frame["profit_1u"].sum(min_count=1),
        "roi": frame["profit_1u"].mean(),
        "avg_line": frame["line"].mean(),
        "avg_projection": frame["projection_value"].mean(),
        "avg_edge_yards": frame["edge_yards"].mean(),
        "avg_ev_percent": frame["recommended_ev_percent"].mean(),
        "avg_recommended_prob": frame["recommended_prob"].mean(),
        "avg_actual": frame["actual_value_diagnostic"].mean(),
        "avg_projection_minus_actual": frame["projection_minus_actual"].mean(),
        "calibration_gap": frame["recommended_prob"].mean() - decided["won"].mean(),
    }


def build_experiments(df):
    over = df["side"].eq("over")
    under = df["side"].eq("under")
    high_line = df["line"].ge(50) & df["line"].lt(60)
    wr = df["position"].astype(str).str.upper().eq("WR")
    favorite_3_to_7 = df["team_spread"].ge(-7) & df["team_spread"].lt(-3)
    favorite_7_plus = df["team_spread"].lt(-7)
    mid_total = df["game_total"].ge(42) & df["game_total"].lt(47)
    edge_5_to_7_5 = df["edge_yards"].ge(5) & df["edge_yards"].lt(7.5)
    edge_7_5_to_10 = df["edge_yards"].ge(7.5) & df["edge_yards"].lt(10)
    line_20_to_30 = df["line"].ge(20) & df["line"].lt(30)

    return [
        (
            "baseline",
            "Keep all current receiving-yards backtest bets.",
            pd.Series(True, index=df.index),
        ),
        (
            "remove_high_line_over_50_60",
            "Exclude overs where 50 <= line < 60.",
            ~(over & high_line),
        ),
        (
            "remove_wr_high_line_over_50_60",
            "Exclude WR overs where 50 <= line < 60.",
            ~(over & wr & high_line),
        ),
        (
            "remove_favorite_3_to_7_overs",
            "Exclude overs where -7 <= team_spread < -3 (favorite by 3 to 7).",
            ~(over & favorite_3_to_7),
        ),
        (
            "remove_mid_total_overs",
            "Exclude overs where 42 <= game_total < 47.",
            ~(over & mid_total),
        ),
        (
            "remove_edge_5_to_7_5",
            "Exclude all bets where 5 <= edge_yards < 7.5.",
            ~edge_5_to_7_5,
        ),
        (
            "conservative_combined_filter",
            "Exclude WR overs at 50-60, favorite 3-to-7 overs, and overs with edge 5-7.5.",
            ~((over & wr & high_line) | (over & favorite_3_to_7) | (over & edge_5_to_7_5)),
        ),
        (
            "positive_segment_only_diagnostic",
            "Keep line 20-30, edge 7.5-10, unders, or favorite 7+.",
            line_20_to_30 | edge_7_5_to_10 | under | favorite_7_plus,
        ),
    ]


def parse_args():
    parser = argparse.ArgumentParser(description="Offline receiving-yards settled-bet filter experiments.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.input.exists():
        raise FileNotFoundError(f"Missing receiving-yards settled-bet input: {args.input}")

    raw = pd.read_csv(args.input)
    print(f"[input] {args.input}")
    print(f"[baseline rows] {len(raw):,}")
    print("[available columns]")
    print(", ".join(raw.columns))
    df = prepare_rows(raw)

    rows = []
    for name, definition, mask in build_experiments(df):
        kept = df.loc[mask.fillna(False)].copy()
        result = {
            "experiment": name,
            "filter_definition": definition,
            "bets_removed": len(df) - len(kept),
            **summarize(kept),
        }
        rows.append(result)
        print(f"\n[experiment] {name}")
        print(f"[definition] {definition}")
        print(f"[bets] kept={len(kept):,} removed={len(df) - len(kept):,}")

    results = pd.DataFrame(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(args.output, index=False)

    print("\n===== RANKED BY ROI =====")
    print(results.sort_values(["roi", "profit_units", "bets"], ascending=[False, False, False]).to_string(index=False))
    print("\n===== RANKED BY PROFIT UNITS =====")
    print(results.sort_values(["profit_units", "roi", "bets"], ascending=[False, False, False]).to_string(index=False))
    print("\n===== RANKED BY BET COUNT =====")
    print(results.sort_values(["bets", "roi", "profit_units"], ascending=[False, False, False]).to_string(index=False))
    print("\n[warning] These are in-sample, offline filter checks. Small samples and selected segments should not be overtrusted.")
    print(f"[saved] {args.output}")


if __name__ == "__main__":
    main()
