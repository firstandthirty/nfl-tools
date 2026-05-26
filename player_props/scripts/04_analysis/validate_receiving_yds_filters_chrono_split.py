from pathlib import Path
import argparse

import numpy as np
import pandas as pd


PREFERRED_INPUT = Path("data/analysis/reception_yds_backtest_rows.csv")
VALIDATED_INPUT = Path("data/analysis/backtests/reception_yds_backtest_rows.csv")
DEFAULT_OUTPUT_DIR = Path("data/analysis/diagnostics")
SPLITS = [
    ("weeks_1_9_vs_10_18", 1, 9, 10, 18),
    ("weeks_1_12_vs_13_18", 1, 12, 13, 18),
    ("weeks_1_14_vs_15_18", 1, 14, 15, 18),
]


def warn(message):
    print(f"[warn] {message}")


def first_available(df, candidates):
    return next((column for column in candidates if column in df.columns), None)


def to_bool(series):
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return series.astype(str).str.lower().isin({"true", "1", "yes"})


def american_profit(odds, won):
    odds = float(odds)
    if not won:
        return -1.0
    return odds / 100.0 if odds > 0 else 100.0 / abs(odds)


def resolve_input(requested):
    if requested is not None:
        return requested
    if PREFERRED_INPUT.exists():
        return PREFERRED_INPUT
    if VALIDATED_INPUT.exists():
        warn(f"{PREFERRED_INPUT} is unavailable; using validated output {VALIDATED_INPUT}.")
        return VALIDATED_INPUT
    return PREFERRED_INPUT


def prepare_rows(raw):
    df = raw.copy()
    side_col = first_available(df, ["recommended_side", "model_side", "side"])
    week_col = first_available(df, ["week", "game_week"])
    line_col = first_available(df, ["line", "market_line"])
    projection_col = first_available(df, ["projection", "fp_receiving_yds"])
    actual_col = first_available(df, ["actual", "actual_receiving_yards", "receiving_yards"])
    profit_col = first_available(df, ["profit_1u", "profit_units", "profit"])
    missing = [
        label
        for label, column in {
            "side": side_col,
            "week": week_col,
            "line": line_col,
            "projection": projection_col,
            "actual": actual_col,
        }.items()
        if column is None
    ]
    if missing:
        raise RuntimeError(f"Settled receiving-yards input is missing required fields: {missing}.")

    df["side_value"] = df[side_col].astype(str).str.lower()
    df["week_value"] = pd.to_numeric(df[week_col], errors="coerce")
    df["line_value"] = pd.to_numeric(df[line_col], errors="coerce")
    df["projection_value"] = pd.to_numeric(df[projection_col], errors="coerce")
    df["actual_value"] = pd.to_numeric(df[actual_col], errors="coerce")
    for column in ["game_total", "team_spread", "recommended_ev_percent", "recommended_prob"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        else:
            warn(f"missing {column}; policies or metrics requiring it may be unavailable.")
            df[column] = np.nan

    if "position" not in df.columns:
        warn("missing position; WR-specific policies cannot exclude rows.")
        df["position"] = ""

    if "is_favorite" in df.columns:
        df["favorite_value"] = to_bool(df["is_favorite"])
    elif "team_spread" in df.columns:
        warn("missing is_favorite; inferred favorite as team_spread < 0.")
        df["favorite_value"] = df["team_spread"] < 0
    else:
        warn("missing favorite status and team_spread; favorite-based policies cannot exclude rows.")
        df["favorite_value"] = False

    if "edge_yards" in df.columns:
        df["edge_yards_value"] = pd.to_numeric(df["edge_yards"], errors="coerce")
    else:
        warn("missing edge_yards; derived abs(projection - line).")
        df["edge_yards_value"] = (df["projection_value"] - df["line_value"]).abs()

    if "bet_pushed" in df.columns:
        df["pushed_value"] = to_bool(df["bet_pushed"])
    else:
        warn("missing bet_pushed; inferred pushes from actual == line.")
        df["pushed_value"] = df["actual_value"].eq(df["line_value"])
    if "bet_won" in df.columns:
        df["won_value"] = to_bool(df["bet_won"])
    else:
        warn("missing bet_won; inferred wins from side, actual, and line.")
        df["won_value"] = np.where(
            df["side_value"].eq("over"),
            df["actual_value"] > df["line_value"],
            df["actual_value"] < df["line_value"],
        )

    if profit_col is not None:
        df["profit_value"] = pd.to_numeric(df[profit_col], errors="coerce")
    else:
        odds_col = first_available(df, ["bet_odds"])
        if odds_col is None and {"over_price", "under_price"}.issubset(df.columns):
            df["bet_odds_inferred"] = np.where(
                df["side_value"].eq("over"), df["over_price"], df["under_price"]
            )
            odds_col = "bet_odds_inferred"
        if odds_col is None:
            raise RuntimeError("Missing per-row profit and no odds are available to infer it.")
        warn(f"missing per-row profit; inferred American-odds profit from {odds_col}.")
        df["profit_value"] = [
            0.0 if push else american_profit(odds, won)
            for odds, won, push in zip(df[odds_col], df["won_value"], df["pushed_value"])
        ]

    dropped = int(df["week_value"].isna().sum())
    if dropped:
        warn(f"dropping {dropped:,} rows without an identifiable week.")
        df = df.loc[df["week_value"].notna()].copy()
    df["week_value"] = df["week_value"].astype(int)
    df["projection_minus_actual"] = df["projection_value"] - df["actual_value"]
    df["actual_minus_line"] = df["actual_value"] - df["line_value"]
    return df


def policies(df):
    over = df["side_value"].eq("over")
    wr = df["position"].astype(str).str.upper().eq("WR")
    high_line_favorite_wr_over = (
        over & wr & df["favorite_value"] & df["line_value"].ge(50)
    )
    mid_total_over = over & df["game_total"].ge(42) & df["game_total"].lt(47)
    keep_all = pd.Series(True, index=df.index)
    return [
        ("1_baseline", "Keep all current receiving-yards settled bets.", keep_all),
        (
            "2_exclude_high_line_favorite_wr_overs",
            "Exclude overs where position == WR, team is favorite, and line >= 50.",
            ~high_line_favorite_wr_over,
        ),
        (
            "3_exclude_mid_total_overs",
            "Exclude overs where 42 <= game_total < 47.",
            ~mid_total_over,
        ),
        (
            "4_combined",
            "Exclude high-line favorite WR overs and overs where 42 <= game_total < 47.",
            ~(high_line_favorite_wr_over | mid_total_over),
        ),
    ]


def summarize(frame, base_frame, split_name, sample_type, policy_name, definition):
    decided = frame.loc[~frame["pushed_value"]]
    hit_rate = decided["won_value"].mean()
    avg_probability = frame["recommended_prob"].mean()
    return {
        "split_name": split_name,
        "sample_type": sample_type,
        "policy_name": policy_name,
        "filter_definition": definition,
        "bets": len(frame),
        "removed_bets": len(base_frame) - len(frame),
        "wins": int(frame["won_value"].sum()),
        "pushes": int(frame["pushed_value"].sum()),
        "hit_rate": hit_rate,
        "profit_units": frame["profit_value"].sum(min_count=1),
        "roi": frame["profit_value"].mean(),
        "avg_line": frame["line_value"].mean(),
        "avg_projection": frame["projection_value"].mean(),
        "avg_actual": frame["actual_value"].mean(),
        "avg_projection_minus_actual": frame["projection_minus_actual"].mean(),
        "avg_actual_minus_line": frame["actual_minus_line"].mean(),
        "avg_edge_yards": frame["edge_yards_value"].mean(),
        "avg_ev_percent": frame["recommended_ev_percent"].mean(),
        "avg_recommended_prob": avg_probability,
        "calibration_gap": avg_probability - hit_rate,
    }


def produce_results(df):
    rows = []
    policy_set = policies(df)
    full_frame = df.copy()
    for policy_name, definition, mask in policy_set:
        rows.append(
            summarize(
                full_frame.loc[mask.loc[full_frame.index]],
                full_frame,
                "full_season",
                "full",
                policy_name,
                definition,
            )
        )

    for split_name, train_min, train_max, test_min, test_max in SPLITS:
        samples = [
            ("train", df.loc[df["week_value"].between(train_min, train_max)]),
            ("test", df.loc[df["week_value"].between(test_min, test_max)]),
        ]
        for sample_type, sample in samples:
            for policy_name, definition, mask in policy_set:
                rows.append(
                    summarize(
                        sample.loc[mask.loc[sample.index]],
                        sample,
                        split_name,
                        sample_type,
                        policy_name,
                        definition,
                    )
                )
    return pd.DataFrame(rows)


def make_summary(results):
    baseline = results.loc[results["policy_name"].eq("1_baseline"), [
        "split_name", "sample_type", "roi", "profit_units"
    ]].rename(columns={"roi": "baseline_roi", "profit_units": "baseline_profit_units"})
    compared = results.merge(baseline, on=["split_name", "sample_type"], how="left")
    compared["roi_improvement_vs_baseline"] = compared["roi"] - compared["baseline_roi"]
    compared["profit_improvement_vs_baseline"] = (
        compared["profit_units"] - compared["baseline_profit_units"]
    )

    rows = []
    non_baseline = compared.loc[
        compared["policy_name"].ne("1_baseline")
        & compared["split_name"].ne("full_season")
    ]
    for policy_name, frame in non_baseline.groupby("policy_name", sort=False):
        train = frame.loc[frame["sample_type"].eq("train")]
        test = frame.loc[frame["sample_type"].eq("test")]
        test_improvement = test["roi_improvement_vs_baseline"]
        rows.append(
            {
                "policy_name": policy_name,
                "filter_definition": frame["filter_definition"].iloc[0],
                "train_splits_improved_vs_baseline": int(
                    (train["roi_improvement_vs_baseline"] > 0).sum()
                ),
                "test_splits_improved_vs_baseline": int((test_improvement > 0).sum()),
                "test_splits_worse_vs_baseline": int((test_improvement < 0).sum()),
                "avg_test_roi_improvement_vs_baseline": test_improvement.mean(),
                "min_test_roi_improvement_vs_baseline": test_improvement.min(),
                "train_improves_but_test_fails_any_split": bool(
                    (
                        train[["split_name", "roi_improvement_vs_baseline"]]
                        .merge(
                            test[["split_name", "roi_improvement_vs_baseline"]],
                            on="split_name",
                            suffixes=("_train", "_test"),
                        )
                        .eval(
                            "roi_improvement_vs_baseline_train > 0 "
                            "and roi_improvement_vs_baseline_test < 0"
                        )
                    ).any()
                ),
                "test_roi_improves_across_multiple_splits": bool(
                    (test_improvement > 0).sum() >= 2
                ),
            }
        )
    return compared, pd.DataFrame(rows)


def print_table(title, frame, columns=None):
    print(f"\n===== {title} =====")
    shown = frame.loc[:, columns] if columns is not None and not frame.empty else frame
    print(shown.to_string(index=False) if not shown.empty else "No rows available.")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Validate receiving-yards filters on chronological week holdouts offline."
    )
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main():
    args = parse_args()
    input_path = resolve_input(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Missing receiving-yards settled-bet input: {input_path}")

    raw = pd.read_csv(input_path)
    print(f"[input] {input_path}")
    print(f"[rows] {len(raw):,}")
    print("[available columns]")
    print(", ".join(raw.columns))
    df = prepare_rows(raw)
    available_weeks = sorted(df["week_value"].unique().tolist())
    print(f"[weeks] {available_weeks}")
    missing_requested_weeks = [week for week in range(1, 19) if week not in available_weeks]
    if missing_requested_weeks:
        warn(
            "requested weeks without settled rows: "
            + ", ".join(map(str, missing_requested_weeks))
            + "; results use available rows only."
        )

    results = produce_results(df)
    compared, summary = make_summary(results)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results.to_csv(args.output_dir / "receiving_yds_filter_chrono_split.csv", index=False)
    summary.to_csv(args.output_dir / "receiving_yds_filter_chrono_summary.csv", index=False)

    display_columns = [
        "split_name", "sample_type", "policy_name", "bets", "removed_bets",
        "wins", "profit_units", "roi", "hit_rate", "calibration_gap",
    ]
    print_table(
        "FULL-SEASON COMPARISON",
        results.loc[results["sample_type"].eq("full")],
        display_columns,
    )
    print_table(
        "TRAIN/TEST COMPARISON BY SPLIT",
        results.loc[results["sample_type"].isin(["train", "test"])],
        display_columns,
    )
    print_table(
        "POLICIES WHERE TRAIN IMPROVES BUT TEST FAILS",
        summary.loc[summary["train_improves_but_test_fails_any_split"]],
    )
    print_table(
        "POLICIES IMPROVING TEST ROI VS BASELINE IN MULTIPLE SPLITS",
        summary.loc[summary["test_roi_improves_across_multiple_splits"]],
    )
    print(f"\n[saved] {args.output_dir / 'receiving_yds_filter_chrono_split.csv'}")
    print(f"[saved] {args.output_dir / 'receiving_yds_filter_chrono_summary.csv'}")
    print("[warning] This is offline chronological validation only; production logic is unchanged.")


if __name__ == "__main__":
    main()
