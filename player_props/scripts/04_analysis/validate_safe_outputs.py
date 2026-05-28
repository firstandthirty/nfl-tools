from pathlib import Path
import argparse
import sys

import pandas as pd


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT / "00_config") not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT / "00_config"))

from market_config import MARKET_CONFIG


MARKETS = [
    "player_receptions",
    "player_reception_yds",
    "player_rush_yds",
]
OUT_FILE = Path("data/analysis/backtests/safe_output_validation_summary.csv")
PASS_INSPECTION_OUT_FILE = Path("data/analysis/backtests/safe_output_validation_summary_with_pass_inspection.csv")


def norm_player(value):
    return (
        str(value).lower()
        .replace(".", "")
        .replace("'", "")
        .replace(" jr", "")
        .replace(" sr", "")
        .strip()
    )


def first_col(df, candidates):
    lower_map = {col.lower(): col for col in df.columns}
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]
    return None


def canonical_history_keys(df):
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
    if "player" in df.columns:
        df["player_norm"] = df["player"].apply(norm_player)
    return df


def count_non_null(df, column):
    if column not in df.columns:
        return 0
    return int(df[column].notna().sum())


def audit_path_for(output_slug):
    return Path("data/analysis/backtests") / f"{output_slug}_missing_actuals_audit.csv"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--include-passing-inspection",
        action="store_true",
        help="Append player_pass_yds as inspection-only; passing is not forced into the safe-output framework.",
    )
    return parser.parse_args()


def inspect_reference_passing_market():
    config = MARKET_CONFIG["player_pass_yds"]
    engine_config = config["projection_engine"]
    backtest_config = config["backtest"]

    legacy_path = Path(engine_config["output_file"])
    backtest_input = Path(backtest_config["picks_file"])
    sim_results = Path(backtest_config["output_dir"]) / Path(backtest_config["output_file"]).name

    output_df = pd.read_csv(legacy_path) if legacy_path.exists() else pd.DataFrame()
    picks = pd.read_csv(backtest_input) if backtest_input.exists() else pd.DataFrame()
    results = pd.read_csv(sim_results) if sim_results.exists() else pd.DataFrame()

    filtered_picks = 0
    matched_graded_bets = 0
    missing_ungraded_bets = 0
    if len(results) > 0:
        over_candidates = int(results.get("bet_over_55", pd.Series(False, index=results.index)).fillna(False).sum())
        under_candidates = int(results.get("bet_under_55", pd.Series(False, index=results.index)).fillna(False).sum())
        filtered_picks = over_candidates + under_candidates
        matched_graded_bets = filtered_picks
    if len(picks) > 0:
        required = ["line", "actual_value", "over_price", "under_price", "pred_mean", "pred_std"]
        missing_ungraded_bets = int(picks[required].isna().any(axis=1).sum()) if set(required).issubset(picks.columns) else 0

    return {
        "market": "player_pass_yds",
        "legacy_output_path": str(legacy_path),
        "legacy_exists": legacy_path.exists(),
        "safe_output_path": "",
        "safe_exists": False,
        "safe_output_row_count": len(output_df),
        "player_id_non_null": count_non_null(output_df, "player_id"),
        "game_id_non_null": count_non_null(output_df, "game_id"),
        "season_non_null": count_non_null(output_df, "season"),
        "week_non_null": count_non_null(output_df, "week"),
        "team_non_null": count_non_null(output_df, "team") or count_non_null(output_df, "recent_team"),
        "opponent_non_null": count_non_null(output_df, "opponent"),
        "configured_backtest_input_path": str(backtest_input),
        "config_points_to_safe_output": False,
        "configured_merge_keys": "reference_engine=simulate_pass_yds",
        "merge_keys_include_game_id": False,
        "filtered_picks": filtered_picks,
        "matched_graded_bets": matched_graded_bets,
        "missing_ungraded_bets": missing_ungraded_bets,
        "missing_audit_path": "",
        "missing_reason_counts": "",
        "inspection_note": (
            "Passing uses reference ensemble/simulate_pass_yds flow, not generalized "
            "safe-output backtesting."
        ),
    }


def main():
    args = parse_args()
    rows = []
    for market_key in MARKETS:
        config = MARKET_CONFIG[market_key]
        engine_config = config["projection_engine"]
        backtest_config = config["backtest"]

        legacy_path = Path(engine_config["output_file"])
        safe_path = Path(backtest_config["picks_file"])
        history_path = Path(backtest_config["history_file"])
        merge_keys = backtest_config.get("merge_keys", ["season", "week", "player_norm", "line"])

        safe_exists = safe_path.exists()
        legacy_exists = legacy_path.exists()
        safe = pd.read_csv(safe_path) if safe_exists else pd.DataFrame()
        filtered_picks = pd.DataFrame()
        matched = 0
        missing = 0

        if safe_exists and history_path.exists():
            filtered_picks = safe.copy()
            filter_mask = filtered_picks["recommended_ev_percent"].between(
                backtest_config["min_ev_percent"],
                backtest_config["max_ev_percent"],
                inclusive="both",
            )
            side_filter = backtest_config.get("side_filter")
            if side_filter is not None:
                filter_mask &= filtered_picks["recommendation"].eq(side_filter)
            filtered_picks = filtered_picks[filter_mask].copy()
            if "player" in filtered_picks.columns:
                filtered_picks["player_norm"] = filtered_picks["player"].apply(norm_player)

            hist = pd.read_csv(history_path)
            hist = canonical_history_keys(hist)
            actual_col = first_col(
                hist,
                ["actual", "actual_market_value", *config["actual_col_candidates"]],
            )
            if actual_col is not None and set(merge_keys).issubset(hist.columns):
                hist = hist.rename(columns={config["line_col"]: "line", actual_col: "actual"})
                merged = filtered_picks.merge(
                    hist[[*merge_keys, "actual"]],
                    on=merge_keys,
                    how="left",
                    validate="many_to_one",
                )
                matched = int(merged["actual"].notna().sum())
                missing = int(merged["actual"].isna().sum())

        audit_path = audit_path_for(config["output_slug"])
        reason_counts = ""
        if audit_path.exists():
            audit = pd.read_csv(audit_path)
            if "reason_guess" in audit.columns and len(audit) > 0:
                reason_counts = "; ".join(
                    f"{reason}={count}"
                    for reason, count in audit["reason_guess"].value_counts(dropna=False).items()
                )

        rows.append(
            {
                "market": market_key,
                "legacy_output_path": str(legacy_path),
                "legacy_exists": legacy_exists,
                "safe_output_path": str(safe_path),
                "safe_exists": safe_exists,
                "safe_output_row_count": len(safe),
                "player_id_non_null": count_non_null(safe, "player_id"),
                "game_id_non_null": count_non_null(safe, "game_id"),
                "season_non_null": count_non_null(safe, "season"),
                "week_non_null": count_non_null(safe, "week"),
                "team_non_null": count_non_null(safe, "team"),
                "opponent_non_null": count_non_null(safe, "opponent"),
                "configured_backtest_input_path": str(safe_path),
                "config_points_to_safe_output": safe_path != legacy_path and "backtest_safe" in safe_path.name,
                "configured_merge_keys": "/".join(merge_keys),
                "merge_keys_include_game_id": "game_id" in merge_keys,
                "filtered_picks": len(filtered_picks),
                "matched_graded_bets": matched,
                "missing_ungraded_bets": missing,
                "missing_audit_path": str(audit_path) if audit_path.exists() else "",
                "missing_reason_counts": reason_counts,
                "inspection_note": "",
            }
        )

    if args.include_passing_inspection:
        rows.append(inspect_reference_passing_market())

    summary = pd.DataFrame(rows)
    out_file = PASS_INSPECTION_OUT_FILE if args.include_passing_inspection else OUT_FILE
    out_file.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(out_file, index=False)
    print(summary.to_string(index=False))
    print(f"\n[output] {out_file}")


if __name__ == "__main__":
    main()
