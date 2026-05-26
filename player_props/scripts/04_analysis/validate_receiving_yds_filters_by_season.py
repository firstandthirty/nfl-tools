from pathlib import Path
import argparse
import math

import numpy as np
import pandas as pd


DEFAULT_INPUT = Path("data/analysis/backtests/reception_yds_backtest_rows.csv")
DEFAULT_OUTPUT_DIR = Path("data/analysis/diagnostics")


def warn(message):
    print(f"[warn] {message}")


def first_available(df, candidates):
    return next((column for column in candidates if column in df.columns), None)


def to_bool(series):
    if pd.api.types.is_bool_dtype(series):
        return series
    return series.astype(str).str.lower().isin({"true", "1", "yes"})


def american_profit(odds, won):
    if not won:
        return -1.0
    odds = float(odds)
    return odds / 100.0 if odds > 0 else 100.0 / abs(odds)


def prepare_rows(raw):
    df = raw.copy()
    side_col = first_available(df, ["model_side", "recommended_side", "side"])
    line_col = first_available(df, ["line", "market_line"])
    projection_col = first_available(df, ["projection", "fp_receiving_yds"])
    actual_col = first_available(df, ["actual", "actual_receiving_yards", "receiving_yards"])
    profit_col = first_available(df, ["profit_1u", "profit_units", "profit"])
    missing = [
        label
        for label, column in {
            "side": side_col,
            "line": line_col,
            "projection": projection_col,
            "actual": actual_col,
        }.items()
        if column is None
    ]
    if missing:
        raise RuntimeError(f"Settled receiving-yards input is missing required fields: {missing}.")

    df["side"] = df[side_col].astype(str).str.lower()
    df["line_value"] = pd.to_numeric(df[line_col], errors="coerce")
    df["projection_value"] = pd.to_numeric(df[projection_col], errors="coerce")
    df["actual_value_diagnostic"] = pd.to_numeric(df[actual_col], errors="coerce")
    for column in ["game_total", "team_spread", "recommended_ev_percent", "recommended_prob"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        else:
            warn(f"missing {column}; policies or metrics requiring it may be unavailable.")
            df[column] = np.nan
    if "position" not in df.columns:
        warn("missing position; WR-specific exclusion policies will remove no rows.")
        df["position"] = ""

    if "season" in df.columns:
        df["season_value"] = pd.to_numeric(df["season"], errors="coerce")
    else:
        game_date_col = first_available(df, ["game_date", "game_date_str", "commence_time"])
        if game_date_col is None:
            raise RuntimeError("Missing season and no game-date column is available for season inference.")
        warn(f"missing season; inferred season year from {game_date_col}.")
        df["season_value"] = pd.to_datetime(df[game_date_col], errors="coerce", utc=True).dt.year
    if df["season_value"].isna().any():
        warn(f"dropping {int(df['season_value'].isna().sum()):,} rows without an identifiable season.")
        df = df.loc[df["season_value"].notna()].copy()
    df["season_value"] = df["season_value"].astype(int)

    if "is_favorite" in df.columns:
        df["favorite"] = to_bool(df["is_favorite"])
    elif "team_spread" in df.columns:
        warn("missing is_favorite; inferred favorite as team_spread < 0.")
        df["favorite"] = df["team_spread"] < 0
    else:
        warn("missing favorite status and team_spread; favorite exclusion policies will remove no rows.")
        df["favorite"] = False

    if "edge_yards" in df.columns:
        df["edge_yards_value"] = pd.to_numeric(df["edge_yards"], errors="coerce")
    else:
        warn("missing edge_yards; derived abs(projection - line).")
        df["edge_yards_value"] = (df["projection_value"] - df["line_value"]).abs()

    if "bet_pushed" in df.columns:
        df["pushed"] = to_bool(df["bet_pushed"])
    else:
        warn("missing bet_pushed; inferred pushes from actual == line.")
        df["pushed"] = df["actual_value_diagnostic"].eq(df["line_value"])
    if "bet_won" in df.columns:
        df["won"] = to_bool(df["bet_won"])
    else:
        warn("missing bet_won; inferred wins from side, actual, and line.")
        df["won"] = np.where(
            df["side"].eq("over"),
            df["actual_value_diagnostic"] > df["line_value"],
            df["actual_value_diagnostic"] < df["line_value"],
        )

    if profit_col is not None:
        df["profit_value"] = pd.to_numeric(df[profit_col], errors="coerce")
    else:
        odds_col = first_available(df, ["bet_odds"])
        if odds_col is None and {"over_price", "under_price"}.issubset(df.columns):
            df["bet_odds_inferred"] = np.where(
                df["side"].eq("over"), df["over_price"], df["under_price"]
            )
            odds_col = "bet_odds_inferred"
        if odds_col is None:
            raise RuntimeError("Missing per-row profit and no side-specific odds are available to infer it.")
        warn(f"missing per-row profit; inferred American-odds profit from {odds_col}.")
        df["profit_value"] = [
            0.0 if push else american_profit(odds, won)
            for odds, won, push in zip(df[odds_col], df["won"], df["pushed"])
        ]

    df["projection_minus_actual"] = df["projection_value"] - df["actual_value_diagnostic"]
    df["actual_minus_line"] = df["actual_value_diagnostic"] - df["line_value"]
    return df


def policy_masks(df):
    over = df["side"].eq("over")
    wr = df["position"].astype(str).str.upper().eq("WR")
    mid_total_over = over & df["game_total"].ge(42) & df["game_total"].lt(47)
    high_line_favorite_wr_over = over & wr & df["favorite"] & df["line_value"].ge(50)
    high_line_favorite_over = over & df["favorite"] & df["line_value"].ge(50)
    high_line_wr_over = over & wr & df["line_value"].ge(50)
    all_rows = pd.Series(True, index=df.index)
    return [
        ("1_baseline", "Keep all current receiving-yards settled bets.", all_rows),
        (
            "2_exclude_mid_total_overs",
            "Exclude overs where 42 <= game_total < 47.",
            ~mid_total_over,
        ),
        (
            "3_exclude_high_line_favorite_wr_overs",
            "Exclude overs where position == WR, team is favorite, and line >= 50.",
            ~high_line_favorite_wr_over,
        ),
        (
            "4_exclude_favorite_high_line_overs_all_positions",
            "Exclude overs where team is favorite and line >= 50.",
            ~high_line_favorite_over,
        ),
        (
            "5_exclude_high_line_wr_overs",
            "Exclude overs where position == WR and line >= 50.",
            ~high_line_wr_over,
        ),
        (
            "6a_high_line_favorite_wr_only",
            "Exclude overs where position == WR, team is favorite, and line >= 50.",
            ~high_line_favorite_wr_over,
        ),
        (
            "6b_high_line_favorite_wr_plus_mid_total_overs",
            "Exclude high-line favorite WR overs and overs where 42 <= game_total < 47.",
            ~(high_line_favorite_wr_over | mid_total_over),
        ),
    ]


def summarize(frame, season, policy_name, definition, baseline_count):
    decided = frame.loc[~frame["pushed"]]
    hit_rate = decided["won"].mean()
    avg_prob = frame["recommended_prob"].mean()
    return {
        "season": season,
        "policy_name": policy_name,
        "filter_definition": definition,
        "bets": len(frame),
        "removed_bets": baseline_count - len(frame),
        "wins": int(frame["won"].sum()),
        "pushes": int(frame["pushed"].sum()),
        "hit_rate": hit_rate,
        "profit_units": frame["profit_value"].sum(min_count=1),
        "roi": frame["profit_value"].mean(),
        "avg_line": frame["line_value"].mean(),
        "avg_projection": frame["projection_value"].mean(),
        "avg_actual": frame["actual_value_diagnostic"].mean(),
        "avg_projection_minus_actual": frame["projection_minus_actual"].mean(),
        "avg_actual_minus_line": frame["actual_minus_line"].mean(),
        "avg_edge_yards": frame["edge_yards_value"].mean(),
        "avg_ev_percent": frame["recommended_ev_percent"].mean(),
        "avg_recommended_prob": avg_prob,
        "calibration_gap": avg_prob - hit_rate,
    }


def validation_rows(df):
    rows = []
    for policy_name, definition, mask in policy_masks(df):
        rows.append(summarize(df.loc[mask], "overall", policy_name, definition, len(df)))
        for season, season_frame in df.groupby("season_value", sort=True):
            season_mask = mask.loc[season_frame.index]
            rows.append(
                summarize(
                    season_frame.loc[season_mask],
                    str(season),
                    policy_name,
                    definition,
                    len(season_frame),
                )
            )
    return pd.DataFrame(rows)


def stability_summary(validation):
    overall = validation.loc[validation["season"].eq("overall")].set_index("policy_name")
    seasonal = validation.loc[~validation["season"].eq("overall")].copy()
    baseline_roi = overall.loc["1_baseline", "roi"]
    rows = []
    for policy_name, frame in seasonal.groupby("policy_name", sort=False):
        policy_overall = overall.loc[policy_name]
        losing_seasons = int((frame["profit_units"] < 0).sum())
        rows.append(
            {
                "policy_name": policy_name,
                "filter_definition": policy_overall["filter_definition"],
                "profitable_seasons": int((frame["profit_units"] > 0).sum()),
                "losing_seasons": losing_seasons,
                "flat_seasons": int((frame["profit_units"] == 0).sum()),
                "worst_season_roi": frame["roi"].min(),
                "best_season_roi": frame["roi"].max(),
                "average_season_roi": frame["roi"].mean(),
                "median_season_roi": frame["roi"].median(),
                "total_profit_units": policy_overall["profit_units"],
                "total_bets": int(policy_overall["bets"]),
                "overall_roi": policy_overall["roi"],
                "aggregate_roi_improvement_vs_baseline": policy_overall["roi"] - baseline_roi,
                "aggregate_improves_but_multiple_losing_seasons": bool(
                    policy_overall["roi"] > baseline_roi and losing_seasons >= 2
                ),
            }
        )
    return pd.DataFrame(rows)


def print_table(title, frame):
    print(f"\n===== {title} =====")
    print(frame.to_string(index=False) if not frame.empty else "No rows available.")


def parse_args():
    parser = argparse.ArgumentParser(description="Validate receiving-yards filters by season offline.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.input.exists():
        raise FileNotFoundError(f"Missing receiving-yards settled-bet input: {args.input}")

    raw = pd.read_csv(args.input)
    print(f"[input] {args.input}")
    print(f"[rows] {len(raw):,}")
    print("[available columns]")
    print(", ".join(raw.columns))
    df = prepare_rows(raw)
    seasons = sorted(df["season_value"].unique().tolist())
    print(f"[seasons] {seasons}")
    if len(seasons) < 2:
        warn("only one season is present; this run cannot establish cross-season stability.")

    validation = validation_rows(df)
    stability = stability_summary(validation)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    validation.to_csv(args.output_dir / "receiving_yds_filter_validation_by_season.csv", index=False)
    stability.to_csv(args.output_dir / "receiving_yds_filter_validation_summary.csv", index=False)

    print_table("OVERALL POLICY COMPARISON", validation.loc[validation["season"].eq("overall")])
    print_table("BY-SEASON POLICY COMPARISON", validation.loc[~validation["season"].eq("overall")])
    ranked = stability.sort_values(
        ["profitable_seasons", "total_profit_units", "median_season_roi", "worst_season_roi"],
        ascending=[False, False, False, False],
    )
    print_table("STABILITY SUMMARY", ranked)
    flagged = stability.loc[stability["aggregate_improves_but_multiple_losing_seasons"]]
    print_table("AGGREGATE ROI IMPROVES BUT FAILS IN MULTIPLE SEASONS", flagged)
    print(f"\n[saved] {args.output_dir}")
    print("[warning] Validation remains offline; production logic is unchanged.")


if __name__ == "__main__":
    main()
