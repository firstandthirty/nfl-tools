from pathlib import Path
import sys
import argparse
import math
import re

import pandas as pd
import matplotlib.pyplot as plt


INPUT_FILE = Path("data/processed/fanduel_pass_yds_history.csv")
OUT_DIR = Path("data/analysis")
PLOT_DIR = OUT_DIR / "plots"

SUMMARY_FILE = OUT_DIR / "pass_yds_market_summary.csv"
LINE_BUCKET_FILE = OUT_DIR / "pass_yds_line_buckets.csv"
JUICE_BUCKET_FILE = OUT_DIR / "pass_yds_juice_buckets.csv"
RESIDUAL_FILE = OUT_DIR / "pass_yds_residuals.csv"
CLEAN_FILE = OUT_DIR / "pass_yds_market_analysis_rows.csv"
PRIMARY_PFF_FILE = Path("data/processed/pff/pff_passing_weekly.csv")
FALLBACK_PFF_FILE = Path("data/processed/pff/pff_player_weekly_master.csv")
FINAL_FALLBACK_FILE = Path("data/processed/merged_props_with_rolling.csv")

# Standard internal name for the joined actual value column used throughout the analysis
ACTUAL_STD_COL = "actual_market_value"

# Minimal market config built into the script for market-aware behavior
MARKET_CONFIG = {
    "player_pass_yds": {
        "display_name": "PASS YARDS",
        "actual_col_candidates": ["actual_passing_yards", "actual_pass_yds", "passing_yards"],
        "stat_col_candidates": ["passing_yards"],
        "input_file": "data/processed/fanduel_pass_yds_history.csv",
        "line_bins": [-math.inf, 180, 220, 260, 300, math.inf],
        "line_labels": ["<180", "180-220", "220-260", "260-300", "300+"],
        "max_actual": 600,
        "clean_filter": {"min_attempt_col": "pass_attempts", "min_attempts": 10, "residual_min": -200, "residual_max": 200},
    },
    "player_receptions": {
        "display_name": "RECEPTIONS",
        "actual_col_candidates": ["actual_receptions", "receptions"],
        "stat_col_candidates": ["receptions"],
        "input_file": "data/processed/fanduel_receptions_history.csv",
        "line_bins": [0, 2.5, 3.5, 4.5, 5.5, 6.5, 100],
        "line_labels": ["<=2.5", "3.5", "4.5", "5.5", "6.5", "7+"],
        "max_actual": 50,
        "clean_filter": {},
    },
}

NFL_TEAM_ABBR_TO_FULL = {
    "ARZ": "Arizona Cardinals",
    "ATL": "Atlanta Falcons",
    "BLT": "Baltimore Ravens",
    "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers",
    "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals",
    "CLV": "Cleveland Browns",
    "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos",
    "DET": "Detroit Lions",
    "GB": "Green Bay Packers",
    "HST": "Houston Texans",
    "HOU": "Houston Texans",
    "IND": "Indianapolis Colts",
    "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs",
    "LA": "Los Angeles Rams",
    "LAR": "Los Angeles Rams",
    "LAC": "Los Angeles Chargers",
    "LV": "Las Vegas Raiders",
    "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings",
    "NE": "New England Patriots",
    "NO": "New Orleans Saints",
    "NYG": "New York Giants",
    "NYJ": "New York Jets",
    "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks",
    "SF": "San Francisco 49ers",
    "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans",
    "WAS": "Washington Commanders",
    "WSH": "Washington Commanders",
}


def spread_bucket(v):
    if pd.isna(v):
        return None
    if v == 0:
        return "pickem"
    if v < -7:
        return "favorite_7_plus"
    if -7 <= v < -3:
        return "favorite_3_to_7"
    if -3 <= v < 0:
        return "favorite_0_to_3"
    if 0 < v <= 3:
        return "dog_0_to_3"
    if 3 < v <= 7:
        return "dog_3_to_7"
    return "dog_7_plus"


def derive_team_context_from_pff(df):
    team_col = None
    for c in ["team_name", "team_name_pff", "pff_team_name", "team_pff", "team"]:
        if c in df.columns and df[c].notna().any():
            team_col = c
            break

    needed = {"home_team", "away_team", "home_spread", "away_spread"}
    missing = needed - set(df.columns)

    if team_col is None:
        print("[team_context] skipped: no usable PFF team column found")
        print("[team_context] candidate team columns:", [c for c in df.columns if "team" in c.lower()])
        return df

    if missing:
        print(f"[team_context] skipped missing columns: {sorted(missing)}")
        return df

    print(f"[team_context] using team column: {team_col}")

    raw_team = df[team_col].astype(str).str.strip()
    team_full = raw_team.map(NFL_TEAM_ABBR_TO_FULL)
    df["team"] = team_full.fillna(raw_team)

    df["is_home"] = df["team"].eq(df["home_team"])
    is_away = df["team"].eq(df["away_team"])

    unknown_team = (~df["is_home"]) & (~is_away)
    df["is_home"] = df["is_home"].astype("object")
    df.loc[unknown_team, "is_home"] = None

    df["opponent"] = pd.NA
    df.loc[df["is_home"] == True, "opponent"] = df.loc[df["is_home"] == True, "away_team"]
    df.loc[is_away, "opponent"] = df.loc[is_away, "home_team"]

    df["team_spread"] = pd.NA
    df.loc[df["is_home"] == True, "team_spread"] = df.loc[df["is_home"] == True, "home_spread"]
    df.loc[is_away, "team_spread"] = df.loc[is_away, "away_spread"]

    df["opponent_spread"] = pd.NA
    df.loc[df["is_home"] == True, "opponent_spread"] = df.loc[df["is_home"] == True, "away_spread"]
    df.loc[is_away, "opponent_spread"] = df.loc[is_away, "home_spread"]

    df["team_spread"] = pd.to_numeric(df["team_spread"], errors="coerce")
    df["opponent_spread"] = pd.to_numeric(df["opponent_spread"], errors="coerce")

    df["is_favorite"] = df["team_spread"] < 0
    df["is_underdog"] = df["team_spread"] > 0
    df["spread_abs"] = df["team_spread"].abs()
    df["spread_bucket"] = df["team_spread"].apply(spread_bucket)

    if "game_total" in df.columns:
        df["game_total"] = pd.to_numeric(df["game_total"], errors="coerce")

    print("[team_context]")
    for c in ["team", "opponent", "team_spread", "is_favorite", "spread_bucket"]:
        print(f"{c} non_null_rate={df[c].notna().mean():.1%}")

    return df


def load_market_config_safe(market_name: str):
    # Attempt to import by file path to handle package names that start with digits
    try:
        ROOT = Path(__file__).resolve().parents[2]
        cfg_path = ROOT / "scripts" / "00_config" / "market_config.py"
        if cfg_path.exists():
            import importlib.util

            spec = importlib.util.spec_from_file_location("market_config", str(cfg_path))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "get_market_config"):
                return module.get_market_config(market_name)
    except Exception:
        return None
    return None

ACTUAL_COL_CANDIDATES = [
    "actual_passing_yards",
    "actual_pass_yds",
    "actual_value",
    "actual",
    "passing_yards",
    "pass_yds",
    "yards",
]
PLAYER_COL_CANDIDATES = ["player", "player_name", "description", "player_display_name"]
PFF_PLAYER_COL_CANDIDATES = ["player", "player_name", "name"]
PFF_SEASON_COL_CANDIDATES = ["season", "season_guess"]
PFF_WEEK_COL_CANDIDATES = ["week", "week_guess"]
PFF_YARDS_COL_CANDIDATES = ["passing_yards", "pass_yds", "yards"]
EVENT_ID_COL_CANDIDATES = ["event_id"]
MARKET_COL_CANDIDATES = ["market_key"]
SPORT_COL_CANDIDATES = ["sport_key"]

def normalize_text(value):
    if pd.isna(value):
        return ""
    text = str(value)
    text = text.lower()
    text = text.replace(".", "")
    text = text.replace("'", "")
    text = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", text)
    text = " ".join(text.split())
    return text.strip()


def find_best_col(df, candidates):
    for col in candidates:
        if col in df.columns:
            return col
    lower_map = {c.lower(): c for c in df.columns}
    for col in candidates:
        if col.lower() in lower_map:
            return lower_map[col.lower()]
    return None


def american_to_prob(odds):
    if pd.isna(odds):
        return math.nan

    odds = float(odds)

    if odds < 0:
        return abs(odds) / (abs(odds) + 100)

    return 100 / (odds + 100)


def odds_to_prob(price, odds_format):
    if pd.isna(price):
        return math.nan

    if odds_format == "decimal":
        price = float(price)
        if price <= 0:
            return math.nan
        return 1.0 / price

    return american_to_prob(price)


def detect_odds_format(prices: pd.Series):
    prices = prices.dropna().abs()
    if len(prices) == 0:
        return "american"

    median_price = prices.median()
    if median_price > 20:
        return "american"
    if 1 <= median_price <= 10:
        return "decimal"
    return "american"


def price_to_decimal(price, odds_format):
    if pd.isna(price):
        return math.nan
    try:
        price = float(price)
    except Exception:
        return math.nan
    if odds_format == "decimal":
        return price
    # american to decimal
    if price > 0:
        return (price / 100.0) + 1.0
    return (100.0 / abs(price)) + 1.0


def find_actual_col(df, candidates=None):
    if candidates is None:
        candidates = ACTUAL_COL_CANDIDATES
    for col in candidates:
        if col in df.columns:
            return col

    lower_map = {c.lower(): c for c in df.columns}
    for col in candidates:
        if col.lower() in lower_map:
            return lower_map[col.lower()]

    return None


def prepare_join_keys(df: pd.DataFrame, player_candidates=None, season_candidates=None, week_candidates=None):
    if player_candidates is None:
        player_candidates = PLAYER_COL_CANDIDATES
    if season_candidates is None:
        season_candidates = ["season_guess"]
    if week_candidates is None:
        week_candidates = ["week_guess"]

    if "event_id" in df.columns:
        df["event_id_str"] = df["event_id"].astype(str).str.strip()

    player_col = find_best_col(df, player_candidates)
    if player_col is not None:
        df["player_norm"] = df[player_col].apply(normalize_text)

    season_col = find_best_col(df, season_candidates)
    if season_col is not None:
        df["season_str"] = df[season_col].astype(str).str.strip()

    week_col = find_best_col(df, week_candidates)
    if week_col is not None:
        df["week_str"] = df[week_col].astype(str).str.strip()

    if "game_date" in df.columns:
        df["game_date_str"] = pd.to_datetime(df["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if "commence_time" in df.columns and "game_date_str" not in df.columns:
        df["game_date_str"] = pd.to_datetime(df["commence_time"], errors="coerce").dt.strftime("%Y-%m-%d")
    return df


def dedup_actuals(df: pd.DataFrame, key_cols, actual_col):
    df = df.copy()
    df["actual_nonnull"] = df[actual_col].notna().astype(int)
    sort_cols = [c for c in [*key_cols, "actual_nonnull"] if c in df.columns]
    ascending = [True] * (len(sort_cols) - 1) + [False]
    df = df.sort_values(sort_cols, ascending=ascending)
    return df.drop_duplicates(subset=key_cols, keep="first")


def join_on_keys(odds_df: pd.DataFrame, source_df: pd.DataFrame, key_cols, actual_col):
    source_cols = [*key_cols, actual_col]

    extra_cols = ["position", "team_name"]
    for col in extra_cols:
        if col in source_df.columns and col not in source_cols:
            source_cols.append(col)

    print("\n[join_on_keys debug]")
    print("key_cols:", key_cols)
    print("actual_col:", actual_col)
    print("source_cols:", source_cols)
    print("source has team_name:", "team_name" in source_df.columns)
    print("odds has team_name:", "team_name" in odds_df.columns)
    print("source team_name sample:", source_df["team_name"].dropna().astype(str).unique()[:10] if "team_name" in source_df.columns else "MISSING")

    merged = odds_df.merge(
        source_df[source_cols],
        on=key_cols,
        how="left",
        suffixes=("", "_src"),
    )

    print("merged team columns:", [c for c in merged.columns if "team" in c.lower()])

    matched = merged[actual_col].notna().sum()
    return merged, matched


def print_source_diagnostics(path: Path, df: pd.DataFrame, label: str):
    print(f"[{label}] path={path}")
    print(f"[{label}] rows={len(df):,}")
    print(f"[{label}] columns={list(df.columns)}")
    if "season_str" in df.columns:
        print(f"[{label}] distinct seasons={df['season_str'].nunique():,}")
    if "week_str" in df.columns:
        print(f"[{label}] distinct weeks={df['week_str'].nunique():,}")


def require_columns(df, required):
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(
            "\nMissing required columns:\n"
            + "\n".join(f"- {c}" for c in missing)
            + "\n\nAvailable columns:\n"
            + "\n".join(df.columns.astype(str))
        )


def summarize_bool(series):
    if len(series) == 0:
        return math.nan
    return float(series.mean())


def residual_distribution_stats(series):
    series = series.dropna()
    return {
        "rows": len(series),
        "mean": series.mean(),
        "median": series.median(),
        "std": series.std(),
        "skew": series.skew(),
        "kurtosis": series.kurt(),
        "p5": series.quantile(0.05),
        "p10": series.quantile(0.10),
        "p25": series.quantile(0.25),
        "p50": series.quantile(0.50),
        "p75": series.quantile(0.75),
        "p90": series.quantile(0.90),
        "p95": series.quantile(0.95),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", default="player_pass_yds")
    args = parser.parse_args()

    cfg = load_market_config_safe(args.market) or {}

    # Built-in market definitions
    market_local_cfg = MARKET_CONFIG.get(args.market)
    if market_local_cfg is None:
        raise RuntimeError(f"Unknown market: {args.market}. Available: {list(MARKET_CONFIG.keys())}")

    # Combined config: built-in market defaults overridden by external config if provided
    combined_cfg = {**market_local_cfg, **cfg}

    market_label = combined_cfg.get("display_name", args.market)
    print(f"[market] {args.market}")
    output_slug = combined_cfg.get("output_slug") or args.market.replace("player_", "")

    input_file = Path(combined_cfg.get("input_file") or f"data/processed/fanduel_{output_slug}_history.csv")
    out_dir = Path("data/analysis")
    plot_dir = out_dir / "plots"

    summary_file = out_dir / f"{output_slug}_market_summary.csv"
    line_bucket_file = out_dir / f"{output_slug}_line_buckets.csv"
    juice_bucket_file = out_dir / f"{output_slug}_juice_buckets.csv"
    residual_file = out_dir / f"{output_slug}_residuals.csv"
    residual_clean_file = out_dir / f"{output_slug}_residuals_clean.csv"
    clean_file = out_dir / f"{output_slug}_market_analysis_rows.csv"

    primary_actuals_file = Path(combined_cfg.get("primary_actuals_file")) if combined_cfg.get("primary_actuals_file") else PRIMARY_PFF_FILE
    fallback_actuals_file = Path(combined_cfg.get("fallback_actuals_file")) if combined_cfg.get("fallback_actuals_file") else FALLBACK_PFF_FILE
    final_fallback_file = Path(combined_cfg.get("final_fallback_file")) if combined_cfg.get("final_fallback_file") else FINAL_FALLBACK_FILE
    configured_actual_col = combined_cfg.get("actual_col")
    # market candidate lists
    actual_col_candidates = combined_cfg.get("actual_col_candidates") or market_local_cfg.get("actual_col_candidates")
    stat_col_candidates = combined_cfg.get("stat_col_candidates") or market_local_cfg.get("stat_col_candidates")

    # support both legacy 'default_clean_filter' and new 'clean_filter' keys
    default_clean = combined_cfg.get("clean_filter") or combined_cfg.get("default_clean_filter") or {}
    min_attempt_col = default_clean.get("min_attempt_col")
    min_attempts = default_clean.get("min_attempts")
    residual_min = default_clean.get("residual_min", -200)
    residual_max = default_clean.get("residual_max", 200)

    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    out_dir.mkdir(parents=True, exist_ok=True)
    plot_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(input_file)

    required = [
        "season_guess",
        "week_guess",
        "player",
        "line",
        "over_price",
        "under_price",
        "event_id",
        "commence_time",
    ]
    require_columns(df, required)

    # Try to find an actuals column in the odds file itself first. Prefer configured names.
    actual_col = None
    actual_original_col = None
    if configured_actual_col and configured_actual_col in df.columns:
        actual_col = configured_actual_col
        actual_original_col = configured_actual_col
    else:
        candidates = actual_col_candidates or ACTUAL_COL_CANDIDATES
        actual_found = find_actual_col(df, candidates)
        if actual_found:
            actual_col = actual_found
            actual_original_col = actual_found
        else:
            actual_col = None
    if actual_col is None:
        odds_df = prepare_join_keys(df.copy())
        pff_join_keys = ["season_str", "week_str", "player_norm"]
        final_actual_col = "actual_passing_yards"

        def load_pff_source(path: Path, label: str):
            if not path.exists():
                return None, None

            source_df = pd.read_csv(path)
            source_df = prepare_join_keys(
                source_df,
                player_candidates=PFF_PLAYER_COL_CANDIDATES,
                season_candidates=PFF_SEASON_COL_CANDIDATES,
                week_candidates=PFF_WEEK_COL_CANDIDATES,
            )
            print_source_diagnostics(path, source_df, label)

            # Determine which stat column to use from this PFF source (market-specific)
            if configured_actual_col and configured_actual_col in source_df.columns:
                src_actual_col = configured_actual_col
            else:
                candidates = stat_col_candidates or PFF_YARDS_COL_CANDIDATES
                src_actual_col = find_actual_col(source_df, candidates)
            if src_actual_col is None:
                raise RuntimeError(
                    f"Could not find passing yards actual column in {path}.\n"
                    "Looked for:\n"
                    + "\n".join(f"- {c}" for c in (candidates or PFF_YARDS_COL_CANDIDATES))
                    + "\n\nAvailable columns:\n"
                    + "\n".join(source_df.columns.astype(str))
                )

            if not set(pff_join_keys).issubset(source_df.columns):
                raise RuntimeError(
                    f"Primary PFF source is missing join keys in {path}. "
                    f"Required: {pff_join_keys}. Available: {list(source_df.columns)}"
                )

            source_df = dedup_actuals(source_df, pff_join_keys, src_actual_col)
            return source_df, src_actual_col

        primary_src, primary_actual_col = load_pff_source(primary_actuals_file, "primary_pff")
        fallback_src, fallback_actual_col = load_pff_source(fallback_actuals_file, "fallback_pff")

        merged = odds_df.copy()
        matched = 0
        source_rows_after = 0
        final_actual_col = None

        if primary_src is not None:
            # Merge primary PFF using its actual column, normalize to a temp column name
            merged, matched = join_on_keys(odds_df, primary_src, pff_join_keys, primary_actual_col)
            merged = merged.rename(columns={primary_actual_col: "actual_from_source"})
            final_actual_col = "actual_from_source"
            actual_original_col = primary_actual_col
            source_rows_after = len(primary_src)
            print(f"[join] primary PFF matched rows={matched:,}")

            if matched / len(odds_df) < 0.9 and fallback_src is not None:
                fallback_cols = [*pff_join_keys, fallback_actual_col]
                if "position" in fallback_src.columns and "position" not in merged.columns:
                    fallback_cols.append("position")
                merged = merged.merge(
                    fallback_src[fallback_cols],
                    on=pff_join_keys,
                    how="left",
                    suffixes=("", "_fallback"),
                )
                merged[final_actual_col] = merged[final_actual_col].fillna(
                    merged[f"{fallback_actual_col}_fallback"]
                )
                merged = merged.drop(columns=[f"{fallback_actual_col}_fallback"])
                matched = merged[final_actual_col].notna().sum()
                print(f"[join] fallback PFF matched rows={matched:,}")
                source_rows_after += len(fallback_src)

        elif fallback_src is not None:
            merged, matched = join_on_keys(odds_df, fallback_src, pff_join_keys, fallback_actual_col)
            merged = merged.rename(columns={fallback_actual_col: "actual_from_source"})
            final_actual_col = "actual_from_source"
            actual_original_col = fallback_actual_col
            source_rows_after = len(fallback_src)
            print(f"[join] fallback PFF matched rows={matched:,}")

        if matched / len(odds_df) < 0.9 and final_fallback_file.exists():
            final_src = pd.read_csv(final_fallback_file)
            final_src = prepare_join_keys(final_src)
            print_source_diagnostics(final_fallback_file, final_src, "final_fallback")

            final_actual_col = find_actual_col(final_src)
            if final_actual_col is None:
                raise RuntimeError(
                    f"Could not find actual passing yards column in {FINAL_FALLBACK_FILE}.\n"
                    "Looked for:\n"
                    + "\n".join(f"- {c}" for c in ACTUAL_COL_CANDIDATES)
                    + "\n\nAvailable columns:\n"
                    + "\n".join(final_src.columns.astype(str))
                )

            if not set(["event_id_str", "player_norm"]).issubset(final_src.columns):
                raise RuntimeError(
                    f"Final fallback source is missing join keys in {FINAL_FALLBACK_FILE}. "
                    "Required: ['event_id_str', 'player_norm']."
                )

            final_src = dedup_actuals(final_src, ["event_id_str", "player_norm"], final_actual_col)
            final_cols = ["event_id_str", "player_norm", final_actual_col]
            if "position" in final_src.columns and "position" not in merged.columns:
                final_cols.append("position")
            merged = merged.merge(
                final_src[final_cols],
                on=["event_id_str", "player_norm"],
                how="left",
                suffixes=("", "_final"),
            )
            merged[final_actual_col] = merged[final_actual_col].fillna(
                merged[f"{final_actual_col}_final"]
            )
            merged = merged.drop(columns=[f"{final_actual_col}_final"])
            matched = merged[final_actual_col].notna().sum()
            print(f"[join] final fallback matched rows={matched:,}")

        if final_actual_col is None or final_actual_col not in merged.columns:
            raise RuntimeError(
                "Unable to locate actual value after joining available sources. "
                "Check PFF and fallback source coverage."
            )

        unmatched = len(merged) - matched
        match_rate = matched / len(merged) if len(merged) else 0.0

        print(f"[join] odds rows={len(odds_df):,}")
        print(f"[join] source rows after filters={source_rows_after:,}")
        print(f"[join] matched rows={matched:,}")
        print(f"[join] unmatched rows={unmatched:,}")
        print(f"[join] match rate={match_rate:.1%}")


        if match_rate < 0.9:
            print(
                "[WARNING] match rate below 90%. Check season/week/player normalization or source coverage."
            )

        if unmatched > 0:
            print("[join] unmatched sample:")
            print(
                merged[merged[final_actual_col].isna()]
                .loc[:, ["event_id", "player", "season_guess", "week_guess", "player_norm"]]
                .drop_duplicates()
                .head(10)
                .to_string(index=False)
            )

        df = merged
        actual_col = final_actual_col

        df = derive_team_context_from_pff(df)

        # remember original column name for user-facing debug when joining sources
        if actual_original_col is None:
            actual_original_col = actual_col
        pos_exists = "position" in df.columns
        pos_unique = df["position"].dropna().unique()[:10].tolist() if pos_exists else []
        print(f"[position] exists={pos_exists}")
        print(f"[position] unique={pos_unique}")

    print(f"[load] rows={len(df):,}")
    # print user-friendly actual column name when possible
    debug_actual_name = actual_original_col if actual_original_col is not None else actual_col
    print(f"[actual] using column: {debug_actual_name}")

    # Coerce core numeric fields
    numeric_cols = ["line", "over_price", "under_price", actual_col]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Basic cleanup
    before = len(df)
    df = df.dropna(subset=["line", "over_price", "under_price", actual_col]).copy()
    after = len(df)

    if after < before:
        print(f"[clean] dropped rows with null line/odds/actual: {before - after:,}")

    # Normalize the actual column to a standard internal name used throughout the script
    df = df.rename(columns={actual_col: ACTUAL_STD_COL})
    # ensure a simple 'actual' alias exists for readability in outputs
    df["actual"] = df[ACTUAL_STD_COL]

    df["actual_minus_line"] = df[ACTUAL_STD_COL] - df["line"]
    df["hit_over"] = df[ACTUAL_STD_COL] > df["line"]
    df["hit_under"] = df[ACTUAL_STD_COL] < df["line"]
    df["push"] = df[ACTUAL_STD_COL] == df["line"]

    odds_series = pd.concat([df["over_price"], df["under_price"]], ignore_index=True)
    odds_format = detect_odds_format(odds_series)
    print(f"[odds] detected odds format={odds_format}")

    df["over_implied_prob"] = df["over_price"].apply(lambda price: odds_to_prob(price, odds_format))
    df["under_implied_prob"] = df["under_price"].apply(lambda price: odds_to_prob(price, odds_format))
    df["market_hold"] = df["over_implied_prob"] + df["under_implied_prob"] - 1

    # Sanity checks
    max_actual_warn = combined_cfg.get("max_actual", market_local_cfg.get("max_actual", 600))
    if df[ACTUAL_STD_COL].isna().mean() > 0.05:
        print(f"[WARNING] More than 5% of actual {market_label} values are null.")

    if (df["line"] <= 0).any():
        print("[WARNING] Found line <= 0 rows.")

    if (df[ACTUAL_STD_COL] > max_actual_warn).any():
        print(f"[WARNING] Found actual {market_label} > {max_actual_warn} rows.")

    # Core summary
    residual = df["actual_minus_line"]

    summary = pd.DataFrame(
        [
            {
                "rows": len(df),
                "seasons": df["season_guess"].nunique(),
                "players": df["player"].nunique(),
                "games": df["event_id"].nunique(),
                "avg_line": df["line"].mean(),
                "median_line": df["line"].median(),
                "std_line": df["line"].std(),
                "avg_actual": df[ACTUAL_STD_COL].mean(),
                "avg_actual_minus_line": residual.mean(),
                "median_actual_minus_line": residual.median(),
                "std_actual_minus_line": residual.std(),
                "skew_actual_minus_line": residual.skew(),
                "kurt_actual_minus_line": residual.kurt(),
                "over_hit_rate": summarize_bool(df["hit_over"]),
                "under_hit_rate": summarize_bool(df["hit_under"]),
                "push_rate": summarize_bool(df["push"]),
                "avg_market_hold": df["market_hold"].mean(),
                "median_market_hold": df["market_hold"].median(),
            }
        ]
    )

    summary.to_csv(summary_file, index=False)

    # Line buckets
    # Use market-specific line buckets when available
    line_bins = combined_cfg.get("line_bins") or market_local_cfg.get("line_bins")
    line_labels = combined_cfg.get("line_labels") or market_local_cfg.get("line_labels")
    df["line_bucket"] = pd.cut(
        df["line"],
        bins=line_bins,
        labels=line_labels,
        right=False,
    )

    line_buckets = (
        df.groupby("line_bucket", observed=False)
        .agg(
            rows=("line", "size"),
            avg_line=("line", "mean"),
            over_hit_rate=("hit_over", "mean"),
            avg_actual_minus_line=("actual_minus_line", "mean"),
            std_actual_minus_line=("actual_minus_line", "std"),
        )
        .reset_index()
    )
    line_buckets.to_csv(line_bucket_file, index=False)

    # Juice buckets based on detected odds format and over_price
    def juice_bucket(price):
        if pd.isna(price):
            return "missing"
        if odds_format == "decimal":
            if price <= 1.70:
                return "favorite_over"
            if 1.71 <= price <= 1.84:
                return "moderate_favorite"
            if 1.85 <= price <= 1.95:
                return "coin_flip"
            if price > 2.00:
                return "plus_money"
            return "other"

        if price <= -140:
            return "favorite_over"
        if -139 <= price <= -120:
            return "moderate_favorite"
        if -119 <= price <= -101:
            return "coin_flip"
        if price >= 100:
            return "plus_money"
        return "other"

    df["juice_bucket"] = df["over_price"].apply(juice_bucket)

    juice_buckets = (
        df.groupby("juice_bucket")
        .agg(
            rows=("over_price", "size"),
            avg_price=("over_price", "mean"),
            over_hit_rate=("hit_over", "mean"),
    
        # --- Game-level spread/total inspection and derived buckets for receptions ---
            implied_probability=("over_implied_prob", "mean"),
        )
        .reset_index()
    )
    juice_buckets["calibration_gap"] = (
        juice_buckets["over_hit_rate"] - juice_buckets["implied_probability"]
    )
    juice_buckets.to_csv(juice_bucket_file, index=False)

    # Default flags for reception-specific buckets
    have_spread = False
    have_total = False
    # Track which receptions ROI CSVs were actually created
    created_pos_fav = False
    created_pos_spread = False
    created_pos_total = False
    created_pos_line_fav = False
    created_pos_fav_total = False
    created_pos_line_fav_total = False

    # Detect spread/total columns and create buckets for player_receptions
    if args.market == "player_receptions":
        spread_cols = [
            "spread",
            "point_spread",
            "team_spread",
            "spread_line",
            "home_spread",
            "away_spread",
        ]

        total_cols = [
            "total",
            "game_total",
            "over_under",
            "total_points",
        ]

        spread_col = find_best_col(df, spread_cols)
        total_col = find_best_col(df, total_cols)

        have_spread = spread_col is not None
        have_total = total_col is not None

        print("[spread]")
        print(f"exists={have_spread}")
        print(f"column={spread_col}")
        print("[total]")
        print(f"exists={have_total}")
        print(f"column={total_col}")

        if not have_spread:
            print("[receptions][warn] no spread column found")
        else:
            # coerce numeric
            df[spread_col] = pd.to_numeric(df[spread_col], errors="coerce")

            def spread_bucket_fn(v):
                if pd.isna(v):
                    return "missing"
                if v == 0:
                    return "pickem"
                if v > 7:
                    return "favorite_7_plus"
                if 3 < v <= 7:
                    return "favorite_3_to_7"
                if 0 < v <= 3:
                    return "favorite_0_to_3"
                av = abs(v)
                if av <= 3:
                    return "dog_0_to_3"
                if 3 < av <= 7:
                    return "dog_3_to_7"
                return "dog_7_plus"

            df["is_favorite"] = df[spread_col].apply(lambda v: False if pd.isna(v) else (v > 0))
            df["is_underdog"] = df[spread_col].apply(lambda v: False if pd.isna(v) else (v < 0))
            df["spread_bucket"] = df[spread_col].apply(spread_bucket_fn)

        if not have_total:
            print("[receptions][warn] no total column found")
        else:
            df[total_col] = pd.to_numeric(df[total_col], errors="coerce")
            df["total_bucket"] = pd.cut(
                df[total_col], bins=[-math.inf, 42, 47, math.inf], labels=["low_total_<42", "mid_total_42_47", "high_total_47_plus"], right=False
            )

    # --- ROI calculations (blind betting) ---
    # Convert prices to decimal multipliers
    df["over_price_dec"] = df["over_price"].apply(lambda p: price_to_decimal(p, odds_format))
    df["under_price_dec"] = df["under_price"].apply(lambda p: price_to_decimal(p, odds_format))

    # Per-row blind ROI assuming stake=1, push returns stake (profit=0)
    def row_over_roi(r):
        if pd.isna(r["over_price_dec"]):
            return math.nan
        if r.get("push", False):
            return 0.0
        return (r["over_price_dec"] - 1.0) if r.get("hit_over", False) else -1.0

    def row_under_roi(r):
        if pd.isna(r["under_price_dec"]):
            return math.nan
        if r.get("push", False):
            return 0.0
        return (r["under_price_dec"] - 1.0) if r.get("hit_under", False) else -1.0

    df["over_roi_row"] = df.apply(row_over_roi, axis=1)
    df["under_roi_row"] = df.apply(row_under_roi, axis=1)

    # Helper aggregator
    def roi_agg(gdf):
        return pd.Series(
            {
                "rows": len(gdf),
                "over_hit_rate": summarize_bool(gdf["hit_over"]),
                "under_hit_rate": summarize_bool(gdf["hit_under"]),
                "push_rate": summarize_bool(gdf["push"]),
                "avg_over_price": gdf["over_price"].mean(),
                "avg_under_price": gdf["under_price"].mean(),
                "blind_over_roi": gdf["over_roi_row"].mean(),
                "blind_under_roi": gdf["under_roi_row"].mean(),
            }
        )

    # ROI by line bucket
    roi_line = df.groupby("line_bucket", dropna=False).apply(roi_agg).reset_index()
    roi_line_file = out_dir / f"{output_slug}_roi_by_line_bucket.csv"
    roi_line.to_csv(roi_line_file, index=False)
    print(f"[output] roi by line file: {roi_line_file}")

    # ROI by juice bucket
    roi_juice = df.groupby("juice_bucket", dropna=False).apply(roi_agg).reset_index()
    roi_juice_file = out_dir / f"{output_slug}_roi_by_juice_bucket.csv"
    roi_juice.to_csv(roi_juice_file, index=False)
    print(f"[output] roi by juice file: {roi_juice_file}")

    # ROI by position (if available)
    roi_position = None
    roi_position_file = out_dir / f"{output_slug}_roi_by_position.csv"
    roi_position_line_file = out_dir / f"{output_slug}_roi_by_position_line_bucket.csv"
    if "position" in df.columns:
        df["position"] = df["position"].fillna("UNKNOWN")
        roi_position = df.groupby("position").apply(roi_agg).reset_index()
        roi_position.to_csv(roi_position_file, index=False)
        print(f"[output] roi by position file: {roi_position_file}")

        # position + line bucket
        roi_pos_line = df.groupby(["position", "line_bucket"], dropna=False).apply(roi_agg).reset_index()
        roi_pos_line.to_csv(roi_position_line_file, index=False)
        print(f"[output] roi by position+line file: {roi_position_line_file}")
    else:
        print(f"[warning] 'position' column not found; skipping position-based ROI files")

    # Print ROI tables to console
    print("\n===== ROI BY LINE BUCKET =====")
    print(roi_line.to_string(index=False))

    print("\n===== ROI BY JUICE BUCKET =====")
    print(roi_juice.to_string(index=False))

    if roi_position is not None:
        print("\n===== ROI BY POSITION =====")
        print(roi_position.to_string(index=False))
        print("\n===== ROI BY POSITION + LINE BUCKET =====")
        print(roi_pos_line.to_string(index=False))

        # Additional receptions ROI splits by game/script buckets
        if args.market == "player_receptions":
            print("[receptions] computing additional ROI splits for receptions (if data available)")
            # Ensure position is filled
            df["position"] = df["position"].fillna("UNKNOWN")

            # ROI by position + favorite status
            try:
                if have_spread:
                    roi_pos_fav = df.groupby(["position", "is_favorite"], dropna=False).apply(roi_agg).reset_index()
                    roi_pos_fav.to_csv(out_dir / "receptions_roi_by_position_favorite_status.csv", index=False)
                    created_pos_fav = True
                    print(f"[output] receptions roi by position+favorite: {out_dir / 'receptions_roi_by_position_favorite_status.csv'}")
                else:
                    print("[receptions][warning] cannot compute position+favorite ROI (spread data missing)")
            except Exception as e:
                print(f"[receptions][error] position+favorite ROI failed: {e}")

            # ROI by position + spread bucket
            try:
                if have_spread:
                    roi_pos_spread = df.groupby(["position", "spread_bucket"], dropna=False).apply(roi_agg).reset_index()
                    roi_pos_spread.to_csv(out_dir / "receptions_roi_by_position_spread_bucket.csv", index=False)
                    created_pos_spread = True
                    print(f"[output] receptions roi by position+spread: {out_dir / 'receptions_roi_by_position_spread_bucket.csv'}")
                else:
                    print("[receptions][warning] cannot compute position+spread ROI (spread data missing)")
            except Exception as e:
                print(f"[receptions][error] position+spread ROI failed: {e}")

            # ROI by position + total bucket
            try:
                if have_total:
                    roi_pos_total = df.groupby(["position", "total_bucket"], dropna=False).apply(roi_agg).reset_index()
                    roi_pos_total.to_csv(out_dir / "receptions_roi_by_position_total_bucket.csv", index=False)
                    created_pos_total = True
                    print(f"[output] receptions roi by position+total: {out_dir / 'receptions_roi_by_position_total_bucket.csv'}")
                else:
                    print("[receptions][warning] cannot compute position+total ROI (total data missing)")
            except Exception as e:
                print(f"[receptions][error] position+total ROI failed: {e}")

            # ROI by position + favorite status + total bucket
            try:
                if have_spread and have_total:
                    roi_pos_fav_total = (
                        df.groupby(["position", "is_favorite", "total_bucket"], dropna=False)
                        .apply(roi_agg)
                        .reset_index()
                    )

                    roi_pos_fav_total_file = out_dir / "receptions_roi_by_position_favorite_total_bucket.csv"
                    roi_pos_fav_total.to_csv(roi_pos_fav_total_file, index=False)

                    created_pos_fav_total = True

                    print(f"[output] receptions roi by position+favorite+total: {roi_pos_fav_total_file}")

                    print("\n===== ROI BY POSITION + FAVORITE + TOTAL BUCKET =====")
                    print(roi_pos_fav_total.to_string(index=False))
                else:
                    print("[receptions][warning] cannot compute position+favorite+total ROI (spread or total data missing)")
            except Exception as e:
                print(f"[receptions][error] position+favorite+total ROI failed: {e}")

            # ROI by position + line + favorite + total bucket
            try:
                if have_spread and have_total:
                    roi_pos_line_fav_total = (
                        df.groupby(
                            ["position", "line_bucket", "is_favorite", "total_bucket"],
                            dropna=False,
                        )
                        .apply(roi_agg)
                        .reset_index()
                    )

                    roi_pos_line_fav_total_file = (
                        out_dir / "receptions_roi_by_position_line_bucket_favorite_total_bucket.csv"
                    )

                    roi_pos_line_fav_total.to_csv(
                        roi_pos_line_fav_total_file,
                        index=False,
                    )

                    created_pos_line_fav_total = True

                    print(
                        "[output] receptions roi by "
                        f"position+line+favorite+total: "
                        f"{roi_pos_line_fav_total_file}"
                    )

                    print(
                        "\n===== ROI BY POSITION + LINE + FAVORITE + TOTAL BUCKET ====="
                    )
                    print(roi_pos_line_fav_total.to_string(index=False))

                else:
                    print(
                        "[receptions][warning] cannot compute "
                        "position+line+favorite+total ROI "
                        "(spread or total data missing)"
                    )

            except Exception as e:
                print(
                    f"[receptions][error] "
                    f"position+line+favorite+total ROI failed: {e}"
                )

            # WR underdog high-total line buckets by juice
            try:
                if have_spread and have_total:

                    wr_shootout_dogs = df[
                        (df["position"] == "WR")
                        & (df["is_favorite"] == False)
                        & (df["total_bucket"] == "high_total_47_plus")
                    ].copy()

                    roi_wr_dog_high_total_juice = (
                        wr_shootout_dogs.groupby(
                            ["line_bucket", "juice_bucket"],
                            dropna=False,
                        )
                        .apply(roi_agg)
                        .reset_index()
                    )

                    wr_dog_high_total_juice_file = (
                        out_dir /
                        "receptions_roi_wr_underdog_high_total_by_juice.csv"
                    )

                    roi_wr_dog_high_total_juice.to_csv(
                        wr_dog_high_total_juice_file,
                        index=False,
                    )

                    print(
                        "[output] wr underdog high-total by juice: "
                        f"{wr_dog_high_total_juice_file}"
                    )

                    print(
                        "\n===== WR UNDERDOG HIGH TOTAL "
                        "(47+) BY LINE + JUICE ====="
                    )
                    print(
                        roi_wr_dog_high_total_juice.to_string(index=False)
                    )

            except Exception as e:
                print(
                    "[receptions][error] wr underdog "
                    f"high-total juice split failed: {e}"
                )

            # ROI by position + line bucket + favorite status
            try:
                if have_spread:
                    roi_pos_line_fav = df.groupby(["position", "line_bucket", "is_favorite"], dropna=False).apply(roi_agg).reset_index()
                    roi_pos_line_fav.to_csv(out_dir / "receptions_roi_by_position_line_bucket_favorite_status.csv", index=False)
                    created_pos_line_fav = True
                    print(f"[output] receptions roi by position+line+favorite: {out_dir / 'receptions_roi_by_position_line_bucket_favorite_status.csv'}")
                else:
                    print("[receptions][warning] cannot compute position+line+favorite ROI (spread data missing)")
            except Exception as e:
                print(f"[receptions][error] position+line+favorite ROI failed: {e}")

    # Residual distribution
    residual_summary = pd.DataFrame([residual_distribution_stats(residual)])
    residual_summary.to_csv(residual_file, index=False)

    clean_mask = pd.Series(True, index=df.index)
    # Only apply attempt-based filtering if configured by the market
    if min_attempt_col and min_attempt_col in df.columns and min_attempts:
        clean_mask &= (df[min_attempt_col] >= min_attempts) | (df[ACTUAL_STD_COL] >= 25)
    # Always require a non-null actual
    clean_mask &= df[ACTUAL_STD_COL].notna()
    # Apply residual bounds if configured
    if residual_min is not None and residual_max is not None:
        clean_mask &= df["actual_minus_line"].between(residual_min, residual_max)

    df_clean = df[clean_mask].copy()
    clean_residual = df_clean["actual_minus_line"]

    residual_summary_clean = pd.DataFrame([residual_distribution_stats(clean_residual)])
    residual_summary_clean.to_csv(residual_clean_file, index=False)

    df.to_csv(clean_file, index=False)

    removed_rows = len(df) - len(df_clean)
    removed_sample = (
        df.loc[~clean_mask]
        .assign(abs_miss=df["actual_minus_line"].abs())
        .sort_values("abs_miss", ascending=False)
        .head(10)
    )

    residual_comparison = pd.DataFrame(
        {
            "full_sample": residual_summary.iloc[0],
            "clean_sample": residual_summary_clean.iloc[0],
        }
    )

    print("\n===== RESIDUAL SUMMARY COMPARISON =====")
    print(residual_comparison.T.to_string(header=True))
    print(f"\n[clean] rows removed={removed_rows:,}")
    if removed_rows > 0:
        print("[clean] largest removed misses:")
        display_cols = [
            "player",
            "season_guess",
            "week_guess",
            "commence_time",
            "line",
            "actual",
            "actual_minus_line",
            "over_price",
            "under_price",
        ]
        print(removed_sample[display_cols].to_string(index=False))

    # Plots
    hist_path = plot_dir / f"{output_slug}_actual_minus_line_hist.png"
    boxplot_path = plot_dir / f"{output_slug}_actual_minus_line_boxplot.png"
    scatter_path = plot_dir / f"{output_slug}_line_vs_actual_scatter.png"

    plt.figure()
    df["actual_minus_line"].hist(bins=40)
    plt.title(f"{market_label}: Actual Minus Line")
    plt.xlabel("Actual - Line")
    plt.ylabel("Rows")
    plt.tight_layout()
    plt.savefig(hist_path)
    plt.close()

    plt.figure()
    plt.boxplot(df["actual_minus_line"].dropna(), vert=False)
    plt.title(f"{market_label}: Actual Minus Line")
    plt.xlabel("Actual - Line")
    plt.tight_layout()
    plt.savefig(boxplot_path)
    plt.close()

    plt.figure()
    plt.scatter(df["line"], df["actual"], alpha=0.35)
    plt.title(f"{market_label}: Line vs Actual")
    plt.xlabel("Line")
    plt.ylabel(f"Actual {market_label}")
    plt.tight_layout()
    plt.savefig(scatter_path)
    plt.close()

    # Console output
    print(f"\n===== {market_label} MARKET SUMMARY =====")
    print(summary.T.to_string(header=False))

    print("\n===== LINE BUCKETS =====")
    print(line_buckets.to_string(index=False))

    print("\n===== JUICE BUCKETS =====")
    print(juice_buckets.to_string(index=False))

    print("\n===== RESIDUAL SUMMARY =====")
    print(residual_summary.T.to_string(header=False))

    print("\n===== TOP 10 LARGEST MISSES =====")
    top_misses_cols = [
        "player",
        "season_guess",
        "week_guess",
        "commence_time",
        "line",
        "actual",
        "actual_minus_line",
        "over_price",
        "under_price",
    ]
    print(
        df.assign(abs_miss=df["actual_minus_line"].abs())
        .sort_values("abs_miss", ascending=False)
        .head(10)[top_misses_cols]
        .to_string(index=False)
    )

    print("\n===== ANALYSIS COMPLETE =====")
    print(f"summary: {summary_file}")
    print(f"line buckets: {line_bucket_file}")
    print(f"juice buckets: {juice_bucket_file}")
    print(f"residuals: {residual_file}")
    print(f"residuals clean: {residual_clean_file}")
    print(f"clean rows: {clean_file}")
    print(f"hist: {hist_path}")
    print(f"boxplot: {boxplot_path}")
    print(f"scatter: {scatter_path}")
    # ROI outputs
    try:
        print(f"roi by line: {roi_line_file}")
        print(f"roi by juice: {roi_juice_file}")
    except Exception:
        pass
    if "position" in df.columns:
        try:
            print(f"roi by position: {roi_position_file}")
            print(f"roi by position+line: {roi_position_line_file}")
        except Exception:
            pass
    else:
        print("[warning] position-based ROI files were not created (position column missing)")

    if created_pos_fav_total:
        print(f"receptions roi by position+favorite+total: {out_dir / 'receptions_roi_by_position_favorite_total_bucket.csv'}")
    else:
        print("receptions roi by position+favorite+total: skipped - spread or total data missing")

    if args.market == "player_receptions":
        if created_pos_fav:
            print(f"receptions roi by position+favorite: {out_dir / 'receptions_roi_by_position_favorite_status.csv'}")
        else:
            print("receptions roi by position+favorite: skipped - spread data missing")

        if created_pos_spread:
            print(f"receptions roi by position+spread: {out_dir / 'receptions_roi_by_position_spread_bucket.csv'}")
        else:
            print("receptions roi by position+spread: skipped - spread data missing")

        if created_pos_total:
            print(f"receptions roi by position+total: {out_dir / 'receptions_roi_by_position_total_bucket.csv'}")
        else:
            print("receptions roi by position+total: skipped - total data missing")

        if created_pos_line_fav:
            print(f"receptions roi by position+line+favorite: {out_dir / 'receptions_roi_by_position_line_bucket_favorite_status.csv'}")
        else:
            print("receptions roi by position+line+favorite: skipped - spread data missing")
        if created_pos_line_fav_total:
            print(
                f"receptions roi by position+line+favorite+total: "
                f"{out_dir / 'receptions_roi_by_position_line_bucket_favorite_total_bucket.csv'}"
            )
        else:
            print(
                "receptions roi by position+line+favorite+total: "
                "skipped - spread or total data missing"
            )

if __name__ == "__main__":
    main()