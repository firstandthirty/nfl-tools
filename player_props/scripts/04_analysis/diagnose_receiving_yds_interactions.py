from pathlib import Path
import argparse
import math

import numpy as np
import pandas as pd


DEFAULT_INPUT = Path("data/analysis/backtests/reception_yds_backtest_rows.csv")
DEFAULT_OUTPUT_DIR = Path("data/analysis/diagnostics")

LINE_BUCKET_BINS = [0, 20, 30, 40, 50, 60, math.inf]
LINE_BUCKET_LABELS = ["<20", "20-30", "30-40", "40-50", "50-60", "60+"]
LINE_SIZE_BINS = [0, 25, 40, 60, math.inf]
LINE_SIZE_LABELS = ["<25", "25-40", "40-60", "60+"]
EDGE_BINS = [0, 2.5, 5, 7.5, 10, 15, 20, math.inf]
EDGE_LABELS = ["0-2.5", "2.5-5", "5-7.5", "7.5-10", "10-15", "15-20", "20+"]
EV_BINS = [-math.inf, 0, 2, 5, 10, 15, 20, math.inf]
EV_LABELS = ["<0", "0-2", "2-5", "5-10", "10-15", "15-20", "20+"]

INTERACTIONS = [
    ("side x position x line_bucket", ["side", "position", "line_bucket"]),
    ("side x position x line_size_bucket", ["side", "position", "line_size_bucket"]),
    ("side x edge_bucket", ["side", "edge_bucket"]),
    ("side x ev_bucket", ["side", "ev_bucket"]),
    ("side x favorite_status", ["side", "favorite_status"]),
    ("side x spread_bucket", ["side", "spread_bucket"]),
    ("side x total_bucket", ["side", "total_bucket"]),
    ("side x line_bucket x favorite_status", ["side", "line_bucket", "favorite_status"]),
    ("side x line_bucket x total_bucket", ["side", "line_bucket", "total_bucket"]),
    ("side x position x favorite_status", ["side", "position", "favorite_status"]),
    ("side x position x total_bucket", ["side", "position", "total_bucket"]),
    ("side x position x spread_bucket", ["side", "position", "spread_bucket"]),
    ("side x edge_bucket x line_bucket", ["side", "edge_bucket", "line_bucket"]),
    ("side x edge_bucket x position", ["side", "edge_bucket", "position"]),
    ("side x favorite_status x total_bucket", ["side", "favorite_status", "total_bucket"]),
    (
        "side x position x line_bucket x favorite_status",
        ["side", "position", "line_bucket", "favorite_status"],
    ),
    (
        "side x position x line_bucket x total_bucket",
        ["side", "position", "line_bucket", "total_bucket"],
    ),
]


def warn(message):
    print(f"[warn] {message}")


def first_available(df, candidates):
    return next((candidate for candidate in candidates if candidate in df.columns), None)


def to_bool(series):
    if pd.api.types.is_bool_dtype(series):
        return series
    return series.astype(str).str.lower().isin({"true", "1", "yes"})


def implied_probability(odds):
    if pd.isna(odds):
        return math.nan
    odds = float(odds)
    if odds < 0:
        return abs(odds) / (abs(odds) + 100.0)
    return 100.0 / (odds + 100.0)


def derive_spread_bucket(value):
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


def prepare_rows(raw):
    df = raw.copy()
    projection_col = first_available(df, ["projection", "fp_receiving_yds"])
    actual_col = first_available(df, ["actual", "actual_receiving_yards", "receiving_yards"])
    side_col = first_available(df, ["model_side", "recommended_side"])
    required = {
        "side": side_col,
        "position": "position" if "position" in df.columns else None,
        "line": "line" if "line" in df.columns else None,
        "projection": projection_col,
        "actual": actual_col,
        "profit_1u": "profit_1u" if "profit_1u" in df.columns else None,
        "recommended_prob": "recommended_prob" if "recommended_prob" in df.columns else None,
    }
    missing = [label for label, col in required.items() if col is None]
    if missing:
        raise RuntimeError(f"Settled receiving-yards rows are missing required fields: {missing}.")

    df["side"] = df[side_col].astype(str).str.lower()
    df["position"] = df["position"].astype(str)
    df["line"] = pd.to_numeric(df["line"], errors="coerce")
    df["projection_value"] = pd.to_numeric(df[projection_col], errors="coerce")
    df["actual_value_diagnostic"] = pd.to_numeric(df[actual_col], errors="coerce")
    df["profit_1u"] = pd.to_numeric(df["profit_1u"], errors="coerce")
    df["recommended_prob"] = pd.to_numeric(df["recommended_prob"], errors="coerce")
    for col in ["recommended_ev_percent", "team_spread", "game_total"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            warn(f"missing {col}; slices requiring it will be skipped.")

    if "bet_won" in df.columns:
        df["won"] = to_bool(df["bet_won"])
    else:
        warn("missing bet_won; inferring wins from recommended side, actual, and line.")
        df["won"] = np.where(
            df["side"].eq("over"),
            df["actual_value_diagnostic"] > df["line"],
            df["actual_value_diagnostic"] < df["line"],
        )
    if "bet_pushed" in df.columns:
        df["pushed"] = to_bool(df["bet_pushed"])
    else:
        warn("missing bet_pushed; inferring pushes from actual == line.")
        df["pushed"] = df["actual_value_diagnostic"].eq(df["line"])

    if "bet_odds" in df.columns:
        df["market_odds"] = pd.to_numeric(df["bet_odds"], errors="coerce")
        df["implied_prob"] = df["market_odds"].apply(implied_probability)
    else:
        warn("missing bet_odds; avg_implied_prob will be blank.")
        df["implied_prob"] = np.nan

    df["projection_minus_actual"] = df["projection_value"] - df["actual_value_diagnostic"]
    df["actual_minus_line"] = df["actual_value_diagnostic"] - df["line"]
    if "edge_yards" not in df.columns:
        warn("missing edge_yards; deriving abs(projection - line).")
        df["edge_yards"] = (df["projection_value"] - df["line"]).abs()
    else:
        df["edge_yards"] = pd.to_numeric(df["edge_yards"], errors="coerce")

    if "line_bucket" not in df.columns:
        warn("missing line_bucket; deriving with receiving-yards engine buckets.")
        df["line_bucket"] = pd.cut(
            df["line"], bins=LINE_BUCKET_BINS, labels=LINE_BUCKET_LABELS, right=False
        )
    if "edge_bucket" not in df.columns:
        warn("missing edge_bucket; deriving with validated backtest buckets.")
        df["edge_bucket"] = pd.cut(
            df["edge_yards"], bins=EDGE_BINS, labels=EDGE_LABELS, right=False
        )
    if "ev_bucket" not in df.columns:
        if "recommended_ev_percent" in df.columns:
            warn("missing ev_bucket; deriving with validated backtest buckets.")
            df["ev_bucket"] = pd.cut(
                df["recommended_ev_percent"], bins=EV_BINS, labels=EV_LABELS, right=False
            )
        else:
            warn("missing ev_bucket and recommended_ev_percent; EV slices will be skipped.")
    df["line_size_bucket"] = pd.cut(
        df["line"], bins=LINE_SIZE_BINS, labels=LINE_SIZE_LABELS, right=False
    )

    if "is_favorite" in df.columns or "is_underdog" in df.columns:
        is_favorite = (
            to_bool(df["is_favorite"]) if "is_favorite" in df.columns else pd.Series(False, index=df.index)
        )
        is_underdog = (
            to_bool(df["is_underdog"]) if "is_underdog" in df.columns else pd.Series(False, index=df.index)
        )
        df["favorite_status"] = np.select(
            [is_favorite, is_underdog], ["favorite", "underdog"], default="pickem_or_unknown"
        )
    else:
        warn("missing is_favorite/is_underdog; favorite-status slices will be skipped.")
    if "spread_bucket" not in df.columns:
        if "team_spread" in df.columns:
            df["spread_bucket"] = df["team_spread"].apply(derive_spread_bucket)
        else:
            warn("missing spread_bucket and team_spread; spread slices will be skipped.")
    if "total_bucket" not in df.columns:
        if "game_total" in df.columns:
            df["total_bucket"] = pd.cut(
                df["game_total"],
                bins=[-math.inf, 42, 47, math.inf],
                labels=["low_total_<42", "mid_total_42_47", "high_total_47_plus"],
                right=False,
            )
        else:
            warn("missing total_bucket and game_total; total slices will be skipped.")
    return df


def summarize(frame):
    decided = frame.loc[~frame["pushed"]]
    hit_rate = decided["won"].mean()
    avg_recommended_prob = frame["recommended_prob"].mean()
    calibration_gap = avg_recommended_prob - hit_rate
    return {
        "bets": len(frame),
        "wins": int(frame["won"].sum()),
        "pushes": int(frame["pushed"].sum()),
        "hit_rate": hit_rate,
        "profit_units": frame["profit_1u"].sum(min_count=1),
        "roi": frame["profit_1u"].mean(),
        "avg_line": frame["line"].mean(),
        "avg_projection": frame["projection_value"].mean(),
        "avg_actual": frame["actual_value_diagnostic"].mean(),
        "avg_projection_minus_actual": frame["projection_minus_actual"].mean(),
        "avg_actual_minus_line": frame["actual_minus_line"].mean(),
        "avg_edge_yards": frame["edge_yards"].mean(),
        "avg_ev_percent": frame["recommended_ev_percent"].mean()
        if "recommended_ev_percent" in frame.columns
        else math.nan,
        "avg_recommended_prob": avg_recommended_prob,
        "avg_implied_prob": frame["implied_prob"].mean(),
        "calibration_gap": calibration_gap,
        "overconfidence_flag": bool(pd.notna(calibration_gap) and calibration_gap >= 0.05),
        "underconfidence_flag": bool(pd.notna(calibration_gap) and calibration_gap <= -0.05),
    }


def grouped_interaction(df, slice_name, columns):
    missing = [column for column in columns if column not in df.columns]
    if missing:
        warn(f"skipping {slice_name}: missing fields {missing}.")
        return pd.DataFrame()
    grouped = df.copy()
    for column in columns:
        grouped[column] = grouped[column].astype(object).where(grouped[column].notna(), "missing")
    rows = []
    for values, frame in grouped.groupby(columns, dropna=False, observed=True):
        values = values if isinstance(values, tuple) else (values,)
        label = " | ".join(f"{key}={value}" for key, value in zip(columns, values))
        rows.append({"slice_name": slice_name, "bucket_value": label, **summarize(frame)})
    return pd.DataFrame(rows)


def print_table(title, frame, limit=None):
    print(f"\n===== {title} =====")
    if frame.empty:
        print("No qualifying buckets.")
        return
    display = frame.head(limit) if limit is not None else frame
    print(display.to_string(index=False))


def parse_args():
    parser = argparse.ArgumentParser(description="Diagnose receiving-yards interaction buckets offline.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.input.exists():
        raise FileNotFoundError(f"Missing settled receiving-yards backtest input: {args.input}")

    raw = pd.read_csv(args.input)
    print(f"[input] {args.input}")
    print(f"[rows] {len(raw):,}")
    print("[available columns]")
    print(", ".join(raw.columns))
    df = prepare_rows(raw)

    all_tables = [grouped_interaction(df, name, columns) for name, columns in INTERACTIONS]
    interactions = pd.concat([table for table in all_tables if not table.empty], ignore_index=True)
    interactions = interactions.loc[interactions["bets"] >= 10].copy()
    min30 = interactions.loc[interactions["bets"] >= 30].copy()
    min50 = interactions.loc[interactions["bets"] >= 50].copy()

    worst_min30 = min30.sort_values(["profit_units", "roi", "bets"], ascending=[True, True, False])
    best_min30 = min30.sort_values(["profit_units", "roi", "bets"], ascending=[False, False, False])
    high_confidence = min50.sort_values(["profit_units", "roi"], ascending=[True, True])

    args.output_dir.mkdir(parents=True, exist_ok=True)
    interactions.to_csv(args.output_dir / "receiving_yds_interaction_diagnostics.csv", index=False)
    worst_min30.to_csv(args.output_dir / "receiving_yds_worst_interactions_min30.csv", index=False)
    best_min30.to_csv(args.output_dir / "receiving_yds_best_interactions_min30.csv", index=False)
    high_confidence.to_csv(
        args.output_dir / "receiving_yds_high_confidence_interactions_min50.csv", index=False
    )

    baseline = pd.DataFrame([{"slice_name": "overall", "bucket_value": "all bets", **summarize(df)}])
    print_table("OVERALL BASELINE SUMMARY", baseline)
    print_table("WORST 20 INTERACTIONS BY PROFIT UNITS (MIN 30)", worst_min30, 20)
    print_table(
        "WORST 20 INTERACTIONS BY ROI (MIN 30)",
        min30.sort_values(["roi", "profit_units", "bets"], ascending=[True, True, False]),
        20,
    )
    print_table("BEST 20 INTERACTIONS BY PROFIT UNITS (MIN 30)", best_min30, 20)
    print_table("HIGH-CONFIDENCE STRUCTURAL BUCKETS (MIN 50)", high_confidence)
    print_table(
        "LARGEST POSITIVE CALIBRATION GAPS (MIN 30)",
        min30.sort_values(["calibration_gap", "bets"], ascending=[False, False]),
        20,
    )
    print_table(
        "LARGEST PROJECTION OVERSTATEMENT (MIN 30)",
        min30.sort_values(["avg_projection_minus_actual", "bets"], ascending=[False, False]),
        20,
    )
    print(f"\n[saved] {args.output_dir}")
    print("[warning] Interaction results are in-sample diagnostics; overlapping buckets and small samples require out-of-sample validation.")


if __name__ == "__main__":
    main()
