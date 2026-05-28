from pathlib import Path
import argparse
import difflib
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


def ensure_canonical_time_keys(df):
    df = df.copy()
    if "season" not in df.columns:
        for candidate in ["season_guess", "season_str"]:
            if candidate in df.columns:
                df["season"] = pd.to_numeric(df[candidate], errors="coerce")
                break
    if "week" not in df.columns:
        for candidate in ["week_guess_numeric", "week_guess", "week_str"]:
            if candidate in df.columns:
                df["week"] = pd.to_numeric(df[candidate], errors="coerce")
                break
    if "game_id" not in df.columns:
        for candidate in ["event_id", "event_id_str"]:
            if candidate in df.columns:
                df["game_id"] = df[candidate]
                break
    return df


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


def build_missing_actuals_audit(missing, picks, hist_full, merge_keys, output_path):
    if missing.empty:
        return None

    hist = hist_full.copy()
    if "player_norm" not in hist.columns and "player" in hist.columns:
        hist["player_norm"] = hist["player"].apply(norm_player)
    if "line" in hist.columns:
        hist["line"] = pd.to_numeric(hist["line"], errors="coerce")

    pick_dupes = picks.duplicated(merge_keys, keep=False) if set(merge_keys).issubset(picks.columns) else pd.Series(False, index=picks.index)
    pick_dup_keys = set(
        map(tuple, picks.loc[pick_dupes, merge_keys].itertuples(index=False, name=None))
    ) if pick_dupes.any() else set()

    hist_dup_keys = set()
    if set(merge_keys).issubset(hist.columns):
        hist_dupes = hist.duplicated(merge_keys, keep=False)
        if hist_dupes.any():
            hist_dup_keys = set(map(tuple, hist.loc[hist_dupes, merge_keys].itertuples(index=False, name=None)))

    audit_rows = []
    for _, row in missing.iterrows():
        season = row.get("season")
        week = row.get("week")
        player_norm = row.get("player_norm")
        game_id = row.get("game_id")
        line = row.get("line")

        week_hist = hist[(hist.get("season") == season) & (hist.get("week") == week)].copy()
        same_player_week = week_hist[week_hist.get("player_norm") == player_norm].copy()
        same_game_week = week_hist[week_hist.get("game_id") == game_id].copy() if "game_id" in week_hist.columns else week_hist.iloc[0:0].copy()
        same_game_player = same_game_week[same_game_week.get("player_norm") == player_norm].copy()

        same_player_exists = len(same_player_week) > 0
        same_game_exists = len(same_game_week) > 0
        same_game_player_exists = len(same_game_player) > 0
        same_player_line_exists = bool(same_player_week["line"].eq(line).any()) if "line" in same_player_week.columns else False

        candidate_names = []
        best_name_score = 0.0
        if "player" in same_game_week.columns:
            names = same_game_week["player"].dropna().astype(str).drop_duplicates().tolist()
            candidate_names = difflib.get_close_matches(str(row.get("player", "")), names, n=5, cutoff=0.45)
            if not candidate_names:
                candidate_names = names[:5]
            if candidate_names:
                best_name_score = max(
                    difflib.SequenceMatcher(None, str(row.get("player", "")).lower(), name.lower()).ratio()
                    for name in candidate_names
                )

        exact_key = tuple(row.get(key) for key in merge_keys)
        if exact_key in pick_dup_keys or exact_key in hist_dup_keys:
            reason_guess = "duplicate_or_ambiguous_odds_rows"
        elif same_game_player_exists and same_game_player.get("actual", pd.Series(dtype=float)).isna().all():
            reason_guess = "missing_actual_stats"
        elif same_game_player_exists and not same_player_line_exists:
            reason_guess = "line_mismatch"
        elif same_player_exists and not same_game_player_exists:
            reason_guess = "game_id_mismatch"
        elif same_game_exists and not same_game_player_exists and best_name_score >= 0.85:
            reason_guess = "player_name_normalization_mismatch_or_not_listed"
        elif same_game_exists and not same_player_exists:
            reason_guess = "player_absent_from_actuals_game_inactive_or_zero_stat"
        else:
            reason_guess = "missing_game_or_week_context"

        audit_rows.append({
            "player": row.get("player"),
            "player_norm": player_norm,
            "season": season,
            "week": week,
            "team": row.get("team"),
            "opponent": row.get("opponent"),
            "game_id": game_id,
            "line": line,
            "projection": row.get("projection"),
            "recommended_side": row.get("recommended_side"),
            "market_key": row.get("market_key"),
            "over_price": row.get("over_price"),
            "under_price": row.get("under_price"),
            "recommended_prob": row.get("recommended_prob"),
            "recommended_ev_percent": row.get("recommended_ev_percent"),
            "recommendation": row.get("recommendation"),
            "same_player_norm_exists_in_actuals_week": same_player_exists,
            "same_game_id_exists_in_actuals_week": same_game_exists,
            "same_game_player_exists": same_game_player_exists,
            "same_player_line_exists": same_player_line_exists,
            "closest_actual_player_name_candidates": "; ".join(candidate_names),
            "closest_actual_player_name_score": best_name_score,
            "actual_game_home_team": same_game_week.get("home_team", pd.Series(dtype=str)).dropna().astype(str).head(1).squeeze() if len(same_game_week) else pd.NA,
            "actual_game_away_team": same_game_week.get("away_team", pd.Series(dtype=str)).dropna().astype(str).head(1).squeeze() if len(same_game_week) else pd.NA,
            "matching_player_week_game_ids": "; ".join(
                same_player_week.get("game_id", pd.Series(dtype=str)).dropna().astype(str).drop_duplicates().head(5).tolist()
            ),
            "matching_game_player_lines": "; ".join(
                same_game_player.get("line", pd.Series(dtype=str)).dropna().astype(str).drop_duplicates().head(5).map(str).tolist()
            ),
            "pick_duplicate_key": exact_key in pick_dup_keys,
            "history_duplicate_key": exact_key in hist_dup_keys,
            "reason_guess": reason_guess,
        })

    audit = pd.DataFrame(audit_rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audit.to_csv(output_path, index=False)
    return audit


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
    hist = ensure_canonical_time_keys(hist)
    hist_for_audit = hist.copy()
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
    missing_actuals = df[df["actual"].isna()].copy()
    audit_path = out_dir / f"{output_slug}_missing_actuals_audit.csv"
    if args.market == "player_receptions":
        audit_path = out_dir / "receptions_missing_actuals_audit.csv"
    audit = build_missing_actuals_audit(missing_actuals, merge_picks, hist_for_audit, merge_keys, audit_path)
    if audit is not None:
        print(f"\n[missing actuals audit] saved={audit_path}")
        print(f"[missing actuals audit] total missing={len(audit):,}")
        print("[missing actuals audit] missing by week:")
        print(audit.groupby(["season", "week"]).size().sort_index().to_string())
        print("[missing actuals audit] reason_guess counts:")
        print(audit["reason_guess"].value_counts(dropna=False).to_string())
        sample_cols = [
            "player",
            "player_norm",
            "season",
            "week",
            "team",
            "opponent",
            "game_id",
            "line",
            "projection",
            "recommended_side",
            "same_player_norm_exists_in_actuals_week",
            "same_game_id_exists_in_actuals_week",
            "closest_actual_player_name_candidates",
            "reason_guess",
        ]
        print("[missing actuals audit] sample 20:")
        print(audit[[col for col in sample_cols if col in audit.columns]].head(20).to_string(index=False))
    print(
        f"\n[grading] matched graded bets={df['actual'].notna().sum():,}; "
        f"missing/ungraded bets={len(missing_actuals):,}"
    )
    if len(missing_actuals) > 0:
        print(f"[grading] missing actuals are excluded from graded bets; audit_csv={audit_path}")
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
