from pathlib import Path
import sys

import pandas as pd


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT / "00_config") not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT / "00_config"))

from market_config import MARKET_CONFIG


OUT_FILE = Path("data/analysis/backtests/pass_yds_source_lineage_audit.csv")

PLAYER_COLS = ["player", "player_name", "player_display_name", "name"]
PLAYER_NORM_COLS = ["player_norm", "player_clean"]
PLAYER_ID_COLS = ["player_id", "fpid", "mflid", "gsis_id", "pfr_id"]
GAME_ID_COLS = ["game_id", "event_id", "event_id_str"]
SEASON_COLS = ["season", "season_guess", "season_str"]
WEEK_COLS = ["week", "week_guess", "week_guess_numeric", "week_str"]
TEAM_COLS = ["team", "recent_team", "team_name", "home_team_abbr", "away_team_abbr"]
OPPONENT_COLS = ["opponent", "opponent_team"]
LINE_COLS = ["line", "market_line", "point", "points"]
PRICE_PAIRS = [("over_price", "under_price"), ("over_odds", "under_odds")]
PROJECTION_COLS = [
    "weighted_projection",
    "pred_mean",
    "fp_pass_yds",
    "fp_pass_yds_debiased",
    "fantasypros",
    "pff",
    "fantasy_points",
    "etr",
    "your_model",
]


CANDIDATES = [
    (
        "data/analysis/week_pass_yds_ensemble_bets.csv",
        "current-week ensemble output",
        "Has projection/edge/recommendation, but no historical stable game or player ids.",
    ),
    (
        "data/input/week_pass_yds_projections.csv",
        "current-week ensemble input",
        "Has market line/prices and source projections; no season/week/event/player ids.",
    ),
    (
        "data/historical_props/pass_yds_baseline_predictions.csv",
        "reference backtest picks input",
        "Used by simulate_pass_yds; has season/week/line/prices/projection and actuals, but no event_id/player_id.",
    ),
    (
        "data/historical_props/pass_yds_sim_results.csv",
        "reference backtest simulation output",
        "simulate_pass_yds output; has predictions/probabilities/results, but no event_id/player_id.",
    ),
    (
        "data/historical_props/merged_props_with_rolling.csv",
        "baseline model training source",
        "Best historical all-in-one source: odds event_id, season/week, line/prices, actuals, rolling features, model source columns.",
    ),
    (
        "data/processed/merged_props_with_rolling.csv",
        "processed mirror of baseline training source",
        "Same schema as historical_props copy; useful fallback/source comparison.",
    ),
    (
        "data/analysis/pass_yds_market_analysis_rows.csv",
        "analysis history rows",
        "Best market-history source for event_id/game_id plus actuals; season/week are stored as guess/string columns.",
    ),
    (
        "data/processed/fanduel_pass_yds_history.csv",
        "raw processed odds history",
        "Best raw odds source for event_id, line, prices, commence/home/away; no projections/player_id.",
    ),
    (
        "data/processed/fantasypros_qb_weekly_projections.csv",
        "legacy FantasyPros QB projections",
        "Has QB pass projections by season/week/team, but no FantasyPros ids.",
    ),
    (
        "data/processed/fantasypros_weekly_projections_api.csv",
        "FantasyPros API weekly projections",
        "Has fpid/mflid for current receiving/rushing positions; current file has no QB rows, so not usable for pass-yards player_id as-is.",
    ),
    (
        "data/processed/pff/pff_passing_weekly.csv",
        "PFF passing weekly actuals",
        "Best current QB player_id source; matches baseline pass-yards rows on season/week/player.",
    ),
    (
        "data/processed/pff/pff_player_weekly_master.csv",
        "PFF player weekly master",
        "Also carries player_id and passing_yards; broader player stat master.",
    ),
    (
        "data/processed/pass_yds_dataset_fp.csv",
        "historical props joined to FantasyPros QB projections",
        "Has event_id plus FP projections, but joined legacy QB projection file has no fpid.",
    ),
    (
        "data/processed/pass_yds_dataset.csv",
        "historical props joined to FFA projections",
        "Has event_id plus FFA projection features; no player_id.",
    ),
    (
        "data/processed/pass_yds_dataset_fp_debiased.csv",
        "debiased FP pass-yards dataset",
        "Has event_id, season/week, line/prices, fp_pass_yds_debiased; no player_id.",
    ),
    (
        "data/processed/pass_yds_dataset_sigma.csv",
        "sigma-calibrated pass-yards dataset",
        "Best calibrated historical projection source: event_id plus fp_pass_yds_debiased/pass_yds_sigma; no player_id.",
    ),
    (
        "scripts/03_modeling/build_projection_ensemble_engine.py",
        "current-week projection builder",
        "Script reads data/input/week_pass_yds_projections.csv and writes week_pass_yds_ensemble_bets.csv.",
    ),
    (
        "scripts/03_modeling/build_pass_yds_baseline.py",
        "historical baseline prediction builder",
        "Script drops event_id when writing pass_yds_baseline_predictions.csv; upstream input has event_id.",
    ),
    (
        "scripts/03_modeling/simulate_pass_yds.py",
        "reference passing backtest",
        "Reference backtest scores pass_yds_baseline_predictions.csv directly and does not merge on stable keys.",
    ),
    (
        "scripts/00_config/market_config.py",
        "market configuration",
        "player_pass_yds is configured with reference_engine passing_ensemble/simulate_pass_yds, not generalized safe-output flow.",
    ),
]


def has_any(columns, candidates):
    return any(col in columns for col in candidates)


def has_prices(columns):
    return any(over in columns and under in columns for over, under in PRICE_PAIRS)


def read_columns(path):
    suffix = path.suffix.lower()
    if suffix != ".csv" or not path.exists():
        return None, pd.NA
    df = pd.read_csv(path, nrows=0)
    row_count = sum(1 for _ in path.open("r", encoding="utf-8", errors="ignore")) - 1
    return list(df.columns), max(row_count, 0)


def audit_row(file_path, likely_role, notes):
    path = Path(file_path)
    columns, row_count = read_columns(path)
    columns = columns or []

    return {
        "file_path": file_path,
        "exists": path.exists(),
        "row_count": row_count,
        "columns_available": ",".join(columns),
        "has_player": has_any(columns, PLAYER_COLS),
        "has_player_norm": has_any(columns, PLAYER_NORM_COLS),
        "has_player_id": has_any(columns, PLAYER_ID_COLS),
        "has_game_id_or_event_id": has_any(columns, GAME_ID_COLS),
        "has_season_week": has_any(columns, SEASON_COLS) and has_any(columns, WEEK_COLS),
        "has_team": has_any(columns, TEAM_COLS),
        "has_opponent": has_any(columns, OPPONENT_COLS) or ("home_team" in columns and "away_team" in columns),
        "has_line": has_any(columns, LINE_COLS),
        "has_prices": has_prices(columns),
        "has_projection": has_any(columns, PROJECTION_COLS),
        "likely_role": likely_role,
        "notes": notes,
    }


def main():
    rows = [audit_row(*candidate) for candidate in CANDIDATES]
    audit = pd.DataFrame(rows)

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    audit.to_csv(OUT_FILE, index=False)

    config = MARKET_CONFIG["player_pass_yds"]
    print(audit[[
        "file_path",
        "row_count",
        "has_player_id",
        "has_game_id_or_event_id",
        "has_season_week",
        "has_line",
        "has_prices",
        "has_projection",
        "likely_role",
    ]].to_string(index=False))

    print("\n===== PASS YDS LINEAGE RECOMMENDATION =====")
    print("best source for game_id: data/historical_props/merged_props_with_rolling.csv")
    print("  fallback: data/analysis/pass_yds_market_analysis_rows.csv or data/processed/fanduel_pass_yds_history.csv")
    print("best source for player_id: data/processed/pff/pff_passing_weekly.csv via player_id")
    print("  note: data/processed/fantasypros_weekly_projections_api.csv currently has no QB rows, so fpid is not available for pass yards as-is")
    print("best source for projection: current reference backtest uses data/historical_props/pass_yds_baseline_predictions.csv pred_mean/pred_std")
    print("  calibrated FP alternatives exist in data/processed/pass_yds_dataset_fp_debiased.csv and pass_yds_dataset_sigma.csv")
    print("safe sidecar feasible without changing model math: yes")
    print(
        "proposed merge path: start from pass_yds_baseline_predictions.csv, "
        "join event_id from merged_props_with_rolling.csv on season/week/player/line, "
        "join player_id from pff_passing_weekly.csv on season/week/normalized player, "
        "derive opponent from recent_team plus home/away, and map pred_mean to projection."
    )
    print(
        "current config note: "
        f"projection={config['projection_engine']['output_file']}, "
        f"backtest={config['backtest']['picks_file']}, "
        "reference_engine=simulate_pass_yds."
    )
    print(f"\n[output] {OUT_FILE}")


if __name__ == "__main__":
    main()
