from pathlib import Path
import argparse
import math

import numpy as np
import pandas as pd


DEFAULT_INPUT = Path("data/analysis/backtests/reception_yds_backtest_rows.csv")
DEFAULT_OUTPUT_DIR = Path("data/analysis/diagnostics")

EDGE_BINS = [0, 2.5, 5, 7.5, 10, 15, 20, math.inf]
EDGE_LABELS = ["0-2.5", "2.5-5", "5-7.5", "7.5-10", "10-15", "15-20", "20+"]
EV_BINS = [-math.inf, 0, 2, 5, 10, 15, 20, math.inf]
EV_LABELS = ["<0", "0-2", "2-5", "5-10", "10-15", "15-20", "20+"]
LINE_SIZE_BINS = [0, 25, 40, 60, math.inf]
LINE_SIZE_LABELS = ["<25", "25-40", "40-60", "60+"]
SUMMARY_COLUMNS = [
    "bets",
    "wins",
    "pushes",
    "hit_rate",
    "profit_units",
    "roi",
    "avg_line",
    "avg_projection",
    "avg_edge_yards",
    "avg_ev_percent",
    "avg_actual",
    "avg_actual_minus_line",
    "avg_projection_minus_actual",
    "avg_market_odds",
    "avg_over_price",
    "avg_under_price",
    "avg_recommended_prob",
    "avg_implied_prob",
    "avg_probability_edge",
    "calibration_gap",
    "projection_bias",
    "overconfidence_flag",
]


def warn(message):
    print(f"[warn] {message}")


def first_available(df, candidates):
    return next((candidate for candidate in candidates if candidate in df.columns), None)


def american_implied_probability(odds):
    if pd.isna(odds):
        return math.nan
    odds = float(odds)
    if odds < 0:
        return abs(odds) / (abs(odds) + 100.0)
    return 100.0 / (odds + 100.0)


def to_bool(series):
    if pd.api.types.is_bool_dtype(series):
        return series
    return series.astype(str).str.lower().isin({"true", "1", "yes"})


def spread_bucket(value):
    if pd.isna(value):
        return "missing"
    value = float(value)
    if value == 0:
        return "pickem"
    if value < -7:
        return "favorite_7_plus"
    if value <= -3:
        return "favorite_3_to_7"
    if value < 0:
        return "favorite_0_to_3"
    if value <= 3:
        return "dog_0_to_3"
    if value <= 7:
        return "dog_3_to_7"
    return "dog_7_plus"


def prepare_rows(df):
    df = df.copy()
    projection_col = first_available(df, ["projection", "fp_receiving_yds"])
    actual_col = first_available(df, ["actual", "actual_receiving_yards", "receiving_yards"])
    side_col = first_available(df, ["model_side", "recommended_side", "recommendation"])

    for label, col in [
        ("projection", projection_col),
        ("actual", actual_col),
        ("side", side_col),
        ("line", "line" if "line" in df.columns else None),
    ]:
        if col is None:
            warn(f"missing required {label} column; diagnostics using it will be empty.")

    if projection_col is not None:
        df["projection_value"] = pd.to_numeric(df[projection_col], errors="coerce")
    else:
        df["projection_value"] = np.nan
    if actual_col is not None:
        df["actual_value_diagnostic"] = pd.to_numeric(df[actual_col], errors="coerce")
    else:
        df["actual_value_diagnostic"] = np.nan
    if "line" in df.columns:
        df["line"] = pd.to_numeric(df["line"], errors="coerce")
    else:
        df["line"] = np.nan
    df["side"] = df[side_col].astype(str).str.lower() if side_col is not None else "missing"

    for col in ["recommended_ev_percent", "recommended_prob", "over_price", "under_price", "profit_1u"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            warn(f"missing optional column {col}; related output metrics will be blank.")
            df[col] = np.nan

    if "edge_yards" not in df.columns:
        df["edge_yards"] = (df["projection_value"] - df["line"]).abs()
    else:
        df["edge_yards"] = pd.to_numeric(df["edge_yards"], errors="coerce")
    df["actual_minus_line_diagnostic"] = df["actual_value_diagnostic"] - df["line"]
    df["projection_minus_actual"] = df["projection_value"] - df["actual_value_diagnostic"]

    if "bet_pushed" in df.columns:
        df["pushed"] = to_bool(df["bet_pushed"])
    else:
        df["pushed"] = df["actual_value_diagnostic"].eq(df["line"])
        warn("missing bet_pushed; inferred pushes from actual == line.")
    if "bet_won" in df.columns:
        df["won"] = to_bool(df["bet_won"])
    else:
        df["won"] = np.where(
            df["side"].eq("over"),
            df["actual_value_diagnostic"] > df["line"],
            df["actual_value_diagnostic"] < df["line"],
        )
        warn("missing bet_won; inferred wins from side, actual, and line.")

    if "bet_odds" in df.columns:
        df["market_odds"] = pd.to_numeric(df["bet_odds"], errors="coerce")
    else:
        df["market_odds"] = np.where(df["side"].eq("over"), df["over_price"], df["under_price"])
        warn("missing bet_odds; selected market odds from recommended side.")
    df["implied_prob"] = df["market_odds"].apply(american_implied_probability)
    df["probability_edge"] = df["recommended_prob"] - df["implied_prob"]

    df["edge_bucket"] = pd.cut(df["edge_yards"], bins=EDGE_BINS, labels=EDGE_LABELS, right=False)
    df["ev_bucket"] = pd.cut(
        df["recommended_ev_percent"], bins=EV_BINS, labels=EV_LABELS, right=False
    )
    if "line_bucket" not in df.columns:
        warn("missing line_bucket; deriving receiving-yards engine bucket from line.")
        df["line_bucket"] = pd.cut(
            df["line"],
            bins=[0, 20, 30, 40, 50, 60, math.inf],
            labels=["<20", "20-30", "30-40", "40-50", "50-60", "60+"],
            right=False,
        )
    df["line_size_bucket"] = pd.cut(
        df["line"], bins=LINE_SIZE_BINS, labels=LINE_SIZE_LABELS, right=False
    )

    if "is_favorite" in df.columns or "is_underdog" in df.columns:
        favorite = to_bool(df["is_favorite"]) if "is_favorite" in df.columns else pd.Series(False, index=df.index)
        underdog = to_bool(df["is_underdog"]) if "is_underdog" in df.columns else pd.Series(False, index=df.index)
        df["fav_status"] = np.select(
            [favorite, underdog],
            ["favorite", "underdog"],
            default="pickem_or_unknown",
        )
    else:
        warn("missing favorite/underdog flags; favorite-status diagnostics will be empty.")
    if "team_spread" in df.columns:
        df["spread_bucket"] = pd.to_numeric(df["team_spread"], errors="coerce").apply(spread_bucket)
    else:
        warn("missing team_spread; spread diagnostics will be empty.")
    if "game_total" in df.columns:
        df["total_bucket"] = pd.cut(
            pd.to_numeric(df["game_total"], errors="coerce"),
            bins=[-math.inf, 42, 47, math.inf],
            labels=["low_total_<42", "mid_total_42_47", "high_total_47_plus"],
            right=False,
        )
    else:
        warn("missing game_total; total diagnostics will be empty.")
    return df


def summarize_frame(frame):
    non_push = frame.loc[~frame["pushed"]]
    calibration_gap = frame["recommended_prob"].mean() - non_push["won"].mean()
    projection_error = frame["projection_minus_actual"].mean()
    if pd.isna(projection_error):
        bias = "unavailable"
    elif projection_error > 0:
        bias = "projection_high"
    elif projection_error < 0:
        bias = "projection_low"
    else:
        bias = "balanced"
    return {
        "bets": len(frame),
        "wins": int(frame["won"].sum()),
        "pushes": int(frame["pushed"].sum()),
        "hit_rate": non_push["won"].mean(),
        "profit_units": frame["profit_1u"].sum(min_count=1),
        "roi": frame["profit_1u"].mean(),
        "avg_line": frame["line"].mean(),
        "avg_projection": frame["projection_value"].mean(),
        "avg_edge_yards": frame["edge_yards"].mean(),
        "avg_ev_percent": frame["recommended_ev_percent"].mean(),
        "avg_actual": frame["actual_value_diagnostic"].mean(),
        "avg_actual_minus_line": frame["actual_minus_line_diagnostic"].mean(),
        "avg_projection_minus_actual": projection_error,
        "avg_market_odds": frame["market_odds"].mean(),
        "avg_over_price": frame["over_price"].mean(),
        "avg_under_price": frame["under_price"].mean(),
        "avg_recommended_prob": frame["recommended_prob"].mean(),
        "avg_implied_prob": frame["implied_prob"].mean(),
        "avg_probability_edge": frame["probability_edge"].mean(),
        "calibration_gap": calibration_gap,
        "projection_bias": bias,
        "overconfidence_flag": bool(len(frame) >= 30 and pd.notna(calibration_gap) and calibration_gap >= 0.05),
    }


def grouped_summary(df, group_cols, slice_name):
    missing = [col for col in group_cols if col not in df.columns]
    if missing:
        warn(f"skipping {slice_name}: missing columns {missing}.")
        return pd.DataFrame(columns=["slice", *group_cols, *SUMMARY_COLUMNS])
    grouped = df.copy()
    for col in group_cols:
        grouped[col] = grouped[col].astype(object).where(grouped[col].notna(), "missing")
    rows = []
    for keys, frame in grouped.groupby(group_cols, dropna=False, observed=True):
        keys = keys if isinstance(keys, tuple) else (keys,)
        row = {"slice": slice_name}
        row.update(dict(zip(group_cols, keys)))
        row.update(summarize_frame(frame))
        rows.append(row)
    return pd.DataFrame(rows)


def print_table(title, table):
    print(f"\n===== {title} =====")
    if table.empty:
        print("No rows available.")
    else:
        print(table.to_string(index=False))


def parse_args():
    parser = argparse.ArgumentParser(description="Diagnose settled receiving-yards model backtest results.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.input.exists():
        raise FileNotFoundError(
            f"Missing settled receiving-yards backtest rows: {args.input}. "
            "Run the validated receiving-yards backtest before diagnostics."
        )

    raw = pd.read_csv(args.input)
    print(f"[input] {args.input}")
    print(f"[rows] {len(raw):,}")
    print("[available columns]")
    print(", ".join(raw.columns))
    df = prepare_rows(raw)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    summary = pd.DataFrame([{"slice": "overall", **summarize_frame(df)}])
    outputs = {
        "receiving_yds_diagnostic_summary.csv": summary,
        "receiving_yds_by_side.csv": grouped_summary(df, ["side"], "side"),
        "receiving_yds_by_position.csv": grouped_summary(df, ["position"], "position"),
        "receiving_yds_by_line_bucket.csv": grouped_summary(df, ["line_bucket"], "line_bucket"),
        "receiving_yds_by_edge_bucket.csv": grouped_summary(df, ["edge_bucket"], "edge_bucket"),
        "receiving_yds_by_ev_bucket.csv": grouped_summary(df, ["ev_bucket"], "ev_bucket"),
        "receiving_yds_by_fav_status.csv": grouped_summary(df, ["fav_status"], "fav_status"),
        "receiving_yds_by_spread_bucket.csv": grouped_summary(df, ["spread_bucket"], "spread_bucket"),
        "receiving_yds_by_total_bucket.csv": grouped_summary(df, ["total_bucket"], "total_bucket"),
        "receiving_yds_by_line_size_bucket.csv": grouped_summary(
            df, ["line_size_bucket"], "line_size_bucket"
        ),
    }
    interactions = [
        grouped_summary(df, ["position", "line_bucket"], "position + line_bucket"),
        grouped_summary(df, ["side", "position"], "side + position"),
        grouped_summary(df, ["side", "line_bucket"], "side + line_bucket"),
        grouped_summary(df, ["side", "fav_status"], "side + favorite/underdog"),
        grouped_summary(df, ["side", "spread_bucket"], "side + spread_bucket"),
        grouped_summary(df, ["side", "total_bucket"], "side + total_bucket"),
    ]
    outputs["receiving_yds_interactions.csv"] = pd.concat(interactions, ignore_index=True, sort=False)

    for filename, output in outputs.items():
        output.to_csv(args.output_dir / filename, index=False)

    print_table("OVERALL SUMMARY", summary)
    table_titles = [
        ("SIDE", "receiving_yds_by_side.csv"),
        ("POSITION", "receiving_yds_by_position.csv"),
        ("LINE BUCKET", "receiving_yds_by_line_bucket.csv"),
        ("EV BUCKET / CONFIDENCE", "receiving_yds_by_ev_bucket.csv"),
        ("EDGE BUCKET / CONFIDENCE", "receiving_yds_by_edge_bucket.csv"),
        ("FAVORITE / UNDERDOG", "receiving_yds_by_fav_status.csv"),
        ("SPREAD BUCKET", "receiving_yds_by_spread_bucket.csv"),
        ("TOTAL BUCKET", "receiving_yds_by_total_bucket.csv"),
    ]
    for title, filename in table_titles:
        print_table(title, outputs[filename])

    structural = pd.concat(
        [
            outputs["receiving_yds_by_position.csv"],
            outputs["receiving_yds_by_line_bucket.csv"],
            outputs["receiving_yds_by_fav_status.csv"],
            outputs["receiving_yds_by_spread_bucket.csv"],
            outputs["receiving_yds_by_total_bucket.csv"],
            outputs["receiving_yds_by_line_size_bucket.csv"],
            outputs["receiving_yds_interactions.csv"],
        ],
        ignore_index=True,
        sort=False,
    )
    structural = structural.loc[structural["bets"] >= 30].copy()
    print_table("WORST 10 STRUCTURAL BUCKETS (MIN 30 BETS)", structural.nsmallest(10, "roi"))
    print_table("BEST 10 STRUCTURAL BUCKETS (MIN 30 BETS)", structural.nlargest(10, "roi"))
    print(f"\n[saved] {args.output_dir}")


if __name__ == "__main__":
    main()
