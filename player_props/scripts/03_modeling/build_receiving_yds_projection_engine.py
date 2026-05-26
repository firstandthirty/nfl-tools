from pathlib import Path
import argparse
import math
import re
import sys

import numpy as np
import pandas as pd

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT / "00_config") not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT / "00_config"))

from market_config import MARKET_CONFIG


HISTORY_FILE = Path("data/analysis/reception_yds_market_analysis_rows.csv")
OUT_FILE = Path("data/analysis/reception_yds_model_bets.csv")

MARKET = "player_reception_yds"
N_SIMS_DEFAULT = 20_000
RANDOM_SEED_DEFAULT = 42
STD_INFLATION_FACTOR = 1.15


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


PLAYER_COL_CANDIDATES = [
    "player",
    "player_name",
    "player_display_name",
    "name",
]

POSITION_COL_CANDIDATES = [
    "position",
    "pos",
]

PROJECTION_COL_CANDIDATES = [
    "fp_receiving_yds",
    "projected_receiving_yards",
    "projected_reception_yds",
    "projected_reception_yards",
    "projection",
    "weighted_projection",
    "ensemble_projection",
    "fantasy_projection",
    "receiving_yards_projection",
    "receiving_yards",
]

LINE_COL_CANDIDATES = [
    "line",
    "market_line",
    "point",
    "points",
]

OVER_PRICE_COL_CANDIDATES = [
    "over_price",
    "over_odds",
    "price_over",
]

UNDER_PRICE_COL_CANDIDATES = [
    "under_price",
    "under_odds",
    "price_under",
]

def normalize_text(value):
    if pd.isna(value):
        return ""
    text = str(value).lower()
    text = text.replace(".", "")
    text = text.replace("'", "")
    text = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", text)
    text = " ".join(text.split())
    return text.strip()


def find_col(df, candidates, required=True, label="column"):
    lower_map = {c.lower(): c for c in df.columns}

    for c in candidates:
        if c in df.columns:
            return c

    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]

    if required:
        raise RuntimeError(
            f"Could not find {label}. Looked for: {candidates}\n"
            f"Available columns: {list(df.columns)}"
        )
    return None


def detect_odds_format(prices):
    prices = pd.Series(prices).dropna().abs()
    if len(prices) == 0:
        return "decimal"

    median_price = prices.median()
    if 1 <= median_price <= 10:
        return "decimal"
    return "american"


def price_to_decimal(price, odds_format):
    if pd.isna(price):
        return math.nan

    price = float(price)

    if odds_format == "decimal":
        return price

    if price > 0:
        return 1.0 + price / 100.0
    return 1.0 + 100.0 / abs(price)


def prob_to_american(prob):
    if pd.isna(prob):
        return math.nan

    prob = float(prob)
    if prob <= 0:
        return math.inf
    if prob >= 1:
        return -math.inf

    if prob >= 0.5:
        return -100.0 * prob / (1.0 - prob)
    return 100.0 * (1.0 - prob) / prob


def ev_per_1_staked(prob_win, decimal_price):
    if pd.isna(prob_win) or pd.isna(decimal_price):
        return math.nan

    prob_win = float(prob_win)
    decimal_price = float(decimal_price)

    # Profit when win = decimal - 1. Loss when lose = -1.
    return prob_win * (decimal_price - 1.0) - (1.0 - prob_win)


def add_line_bucket(df, line_col="line"):
    # Wider buckets appropriate for receiving yards
    bins = [0, 20, 30, 40, 50, 60, math.inf]
    labels = ["<20", "20-30", "30-40", "40-50", "50-60", "60+"]

    df["line_bucket"] = pd.cut(
        df[line_col],
        bins=bins,
        labels=labels,
        right=False,
    )
    return df


def load_history(history_file):
    hist = pd.read_csv(history_file)

    required = ["line"]
    for c in required:
        if c not in hist.columns:
            raise RuntimeError(f"Historical file missing required column: {c}")

    # Expect actual receiving yards in the history file under common names
    actual_col = None
    for c in ["actual", "actual_market_value", "receiving_yards", "actual_receiving_yards"]:
        if c in hist.columns:
            actual_col = c
            break

    if actual_col is None:
        raise RuntimeError(
            "Historical file does not contain actual receiving yards. "
            "Use data/analysis/reception_yds_market_analysis_rows.csv if needed, "
            "or rerun analyze_market.py first."
        )

    if "position" not in hist.columns:
        raise RuntimeError(
            "Historical file does not contain position. "
            "Use data/analysis/reception_yds_market_analysis_rows.csv, which is created by analyze_market.py."
        )

    hist = hist.copy()
    hist["actual"] = pd.to_numeric(hist[actual_col], errors="coerce")
    hist["line"] = pd.to_numeric(hist["line"], errors="coerce")
    # Compute residual relative to the market line
    hist["actual_minus_line"] = hist["actual"] - hist["line"]
    hist["position"] = hist["position"].fillna("UNKNOWN").astype(str)

    hist = hist.dropna(subset=["actual", "line"])
    hist = add_line_bucket(hist, "line")

    return hist


def build_variance_table(hist):
    # Estimate variance by position + line bucket.
    # Use actual receiving yards instead of residuals because the simulation mean comes from projections.
    grouped = (
        hist.groupby(["position", "line_bucket"], observed=False)
        .agg(
            rows=("actual", "size"),
            hist_mean_actual=("actual", "mean"),
            hist_std_actual=("actual", "std"),
            hist_var_actual=("actual", "var"),
        )
        .reset_index()
    )

    # Position-level fallback.
    pos_fallback = (
        hist.groupby("position")
        .agg(
            fallback_rows=("actual", "size"),
            fallback_std=("actual", "std"),
            fallback_var=("actual", "var"),
        )
        .reset_index()
    )

    grouped = grouped.merge(pos_fallback, on="position", how="left")

    # Global fallback.
    global_var = float(hist["actual"].var())
    global_std = float(hist["actual"].std())

    grouped["std_for_sim"] = grouped["hist_std_actual"]
    grouped["var_for_sim"] = grouped["hist_var_actual"]

    # If bucket is thin or variance is missing, use position fallback.
    thin_or_missing = (
        grouped["rows"].fillna(0).lt(75)
        | grouped["var_for_sim"].isna()
        | grouped["var_for_sim"].le(0)
    )

    grouped.loc[thin_or_missing, "std_for_sim"] = grouped.loc[thin_or_missing, "fallback_std"]
    grouped.loc[thin_or_missing, "var_for_sim"] = grouped.loc[thin_or_missing, "fallback_var"]

    # If still missing, use global.
    grouped["std_for_sim"] = grouped["std_for_sim"].fillna(global_std)
    grouped["var_for_sim"] = grouped["var_for_sim"].fillna(global_var)

    grouped["std_for_sim"] = grouped["std_for_sim"] * STD_INFLATION_FACTOR
    grouped["var_for_sim"] = grouped["std_for_sim"] ** 2

    print(f"[variance] STD_INFLATION_FACTOR={STD_INFLATION_FACTOR}")

    return grouped

def simulate_normal_yards(mean, std, n_sims, rng, max_clip=350):
    mean = max(float(mean), 0.0)
    std = max(float(std), 1.0)

    sims = rng.normal(
        loc=mean,
        scale=std,
        size=n_sims,
    )

    sims = np.clip(sims, 0, max_clip)

    return sims


def load_projection_file(path):
    df = pd.read_csv(path)

    player_col = find_col(df, PLAYER_COL_CANDIDATES, label="projection player column")
    proj_col = find_col(df, PROJECTION_COL_CANDIDATES, label="projection receiving yards column")
    pos_col = find_col(df, POSITION_COL_CANDIDATES, required=False, label="projection position column")
    season_col = find_col(df, ["season", "year"], required=False, label="projection season column")
    week_col = find_col(df, ["week"], required=False, label="projection week column")

    out = df.copy()
    out["player_norm"] = out[player_col].apply(normalize_text)
    out["projection"] = pd.to_numeric(out[proj_col], errors="coerce")

    if season_col is not None:
        out["season"] = pd.to_numeric(out[season_col], errors="coerce")
    if week_col is not None:
        out["week"] = pd.to_numeric(out[week_col], errors="coerce")

    if pos_col is not None:
        out["position"] = out[pos_col].astype(str)
    else:
        out["position"] = "UNKNOWN"

    out["player"] = out[player_col]

    keep = ["player", "player_norm", "position", "projection"]
    if season_col is not None:
        keep.append("season")
    if week_col is not None:
        keep.append("week")

    extra_keep = [
        "team",
        "team_name",
        "opponent",
        "game_total",
        "team_spread",
        "is_favorite",
        "is_underdog",
    ]
    keep += [c for c in extra_keep if c in out.columns]

    return out[keep].dropna(subset=["player_norm", "projection"])


def load_market_file(path):
    df = pd.read_csv(path)

    player_col = find_col(df, PLAYER_COL_CANDIDATES, label="market player column")
    line_col = find_col(df, LINE_COL_CANDIDATES, label="market line column")
    over_col = find_col(df, OVER_PRICE_COL_CANDIDATES, label="market over price column")
    under_col = find_col(df, UNDER_PRICE_COL_CANDIDATES, label="market under price column")
    pos_col = find_col(df, POSITION_COL_CANDIDATES, required=False, label="market position column")
    season_col = find_col(df, ["season", "year"], required=False, label="market season column")
    week_col = find_col(df, ["week"], required=False, label="market week column")

    out = df.copy()
    out["player_norm"] = out[player_col].apply(normalize_text)
    out["player"] = out[player_col]
    out["line"] = pd.to_numeric(out[line_col], errors="coerce")
    out["over_price"] = pd.to_numeric(out[over_col], errors="coerce")
    out["under_price"] = pd.to_numeric(out[under_col], errors="coerce")

    if season_col is not None:
        out["season"] = pd.to_numeric(out[season_col], errors="coerce")
    if week_col is not None:
        out["week"] = pd.to_numeric(out[week_col], errors="coerce")

    if pos_col is not None:
        out["position_market"] = out[pos_col].astype(str)
    else:
        out["position_market"] = pd.NA

    keep = [
        "player",
        "player_norm",
        "position_market",
        "line",
        "over_price",
        "under_price",
    ]

    if "market_key" in out.columns:
        keep.insert(0, "market_key")
        if season_col is not None:
            keep.append("season")
        if week_col is not None:
            keep.append("week")

    extra_keep = [
        "team",
        "team_name",
        "opponent",
        "game_total",
        "team_spread",
        "is_favorite",
        "is_underdog",
        "spread_bucket",
        "total_bucket",
        "sportsbook",
    ]
    keep += [c for c in extra_keep if c in out.columns]

    return out[keep].dropna(subset=["player_norm", "line", "over_price", "under_price"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--projections",
        required=True,
        help="CSV containing fantasy/ensemble receiving yards projections.",
    )
    parser.add_argument(
        "--markets",
        required=True,
        help="CSV containing current FanDuel player_reception_yds lines.",
    )
    parser.add_argument(
        "--history",
        default=str(HISTORY_FILE),
        help="Historical analysis rows with actual receiving yards and position.",
    )
    parser.add_argument(
        "--output",
        default=str(OUT_FILE),
        help="Output CSV path.",
    )
    parser.add_argument("--n-sims", type=int, default=N_SIMS_DEFAULT)
    parser.add_argument("--seed", type=int, default=RANDOM_SEED_DEFAULT)
    parser.add_argument("--min-ev", type=float, default=0.02, help="Minimum EV as decimal, e.g. 0.02 = 2 percent.")
    parser.add_argument("--min-prob", type=float, default=0.525)
    parser.add_argument("--min-line", type=float, default=10.0, help="Minimum receiving yards market line to keep.")
    args = parser.parse_args()

    print("===== RECEIVING YARDS PROJECTION ENGINE =====")

    projections = load_projection_file(Path(args.projections))
    markets = load_market_file(Path(args.markets))
    history = load_history(Path(args.history))

    print(f"[load] projections rows={len(projections):,}")
    print(f"[load] market rows={len(markets):,}")
    print(f"[load] history rows={len(history):,}")

    if "market_key" not in markets.columns:
        raise RuntimeError(
            "Market file must contain a market_key column for strict player_reception_yds filtering."
        )

    markets = markets[markets["market_key"] == MARKET].copy()
    print(f"[filter] filtered markets to {MARKET}: rows={len(markets):,}")
    print(markets["market_key"].value_counts())
    print(markets.groupby("position_market")["line"].describe())

    config = MARKET_CONFIG.get(MARKET, {})
    min_line = config.get("min_line", 0)
    before_filter_rows = len(markets)
    markets = markets[markets["line"] >= min_line].copy()
    print(f"[market filter] min_line >= {min_line}: {before_filter_rows:,} -> {len(markets):,}")

    bad_rb = markets[(markets["position_market"] == "RB") & (markets["line"] > 50)]
    if len(bad_rb):
        raise RuntimeError(
            "RB receiving yards lines over 50 detected. Likely rush yards contamination."
        )

    print(f"[debug] unique market players={markets['player_norm'].nunique():,}")
    print(f"[debug] unique projection players={projections['player_norm'].nunique():,}")

    if len(markets) > 0 and markets["line"].median() < 10:
        raise RuntimeError(
            "Receiving yards market appears incorrect. Median line too small."
        )

    if not {"season", "week"}.issubset(markets.columns):
        print("[warn] market file missing season/week columns; merge may be ambiguous.")
    if not {"season", "week"}.issubset(projections.columns):
        print("[warn] projection file missing season/week columns; merge may be ambiguous.")

    variance_table = build_variance_table(history)
    print("\n===== VARIANCE TABLE =====")
    print(
        variance_table[
            [
                "position",
                "line_bucket",
                "rows",
                "hist_mean_actual",
                "hist_std_actual",
                "hist_var_actual",
                "std_for_sim",
                "var_for_sim",
            ]
        ].to_string(index=False)
    )

    # Merge projections and market.
    merge_keys = ["season", "week", "player_norm"]
    if not set(merge_keys).issubset(markets.columns) or not set(merge_keys).issubset(projections.columns):
        raise RuntimeError(
            "Cannot merge projections and markets: missing season/week/player_norm keys. "
            "Ensure both files contain season, week, and normalized player fields."
        )

    assert markets["market_key"].eq(MARKET).all(), (
        "Filtered market dataframe contains rows outside player_reception_yds. "
        "Check market filtering and market_key values."
    )

    df = markets.merge(
        projections.drop(columns=["player"], errors="ignore"),
        on=merge_keys,
        how="inner",
        suffixes=("", "_proj"),
    )

    market_merge = markets.merge(
        projections.drop(columns=["player"], errors="ignore"),
        on=merge_keys,
        how="left",
        indicator=True,
    )
    projection_merge = projections.merge(
        markets.drop(columns=["player"], errors="ignore"),
        on=merge_keys,
        how="left",
        indicator=True,
    )

    merged_rows = len(df)
    unmatched_market_rows = int((market_merge["_merge"] == "left_only").sum())
    unmatched_projection_rows = int((projection_merge["_merge"] == "left_only").sum())
    merge_rate = merged_rows / max(1, len(markets))

    print(f"[merge] market rows={len(markets):,}")
    print(f"[merge] projection rows={len(projections):,}")
    print(f"[merge] merged rows={merged_rows:,}")
    print(f"[merge] merge rate={merge_rate:.4f}")
    print(f"[merge] unmatched market rows={unmatched_market_rows:,}")
    print(f"[merge] unmatched projection rows={unmatched_projection_rows:,}")
    print(f"[merge] unique players={df['player_norm'].nunique():,}")
    print("[merge] season/week distribution:")
    if {"season", "week"}.issubset(df.columns):
        print(df.groupby(["season", "week"]).size().sort_index().to_string())
    else:
        print("  no season/week columns available")

    # Use market position first if present, otherwise projection position.
    if "position_market" in df.columns:
        df["position"] = df["position_market"].fillna(df.get("position", "UNKNOWN"))
    df["position"] = df["position"].fillna("UNKNOWN").astype(str)

    df = add_line_bucket(df, "line")

    # Attach variance parameters.
    df = df.merge(
        variance_table[
            [
                "position",
                "line_bucket",
                "rows",
                "hist_mean_actual",
                "std_for_sim",
                "var_for_sim",
            ]
        ],
        on=["position", "line_bucket"],
        how="left",
    )

    # Fallback if missing because of unknown positions.
    global_var = float(history["actual"].var())
    global_std = float(history["actual"].std())
    df["var_for_sim"] = df["var_for_sim"].fillna(global_var)
    df["std_for_sim"] = df["std_for_sim"].fillna(global_std)

    odds_format = detect_odds_format(pd.concat([df["over_price"], df["under_price"]]))
    print(f"\n[odds] detected odds format={odds_format}")

    print(df["market_key"].value_counts())
    print(df[["player", "line", "market_key"]].query("player == 'Jonathan Taylor'").to_string(index=False))

    rows_to_simulate = len(df)
    print(f"[simulate] rows={rows_to_simulate:,} n_sims={args.n_sims}")
    if rows_to_simulate > 5000 and args.n_sims >= 10000:
        print(f"[warn] high workload: {rows_to_simulate:,} rows with n_sims={args.n_sims}")

    rng = np.random.default_rng(args.seed)
    results = []

    for i, (_, row) in enumerate(df.iterrows(), start=1):
        if i % 100 == 0:
            print(
                f"[simulate] {i}/{rows_to_simulate} {row.get('player', 'NA')} "
                f"line={row.get('line', 'NA')} projection={row.get('projection', 'NA')}"
            )
        projection = float(row["projection"])
        line = float(row["line"])

        # Receiving yards are modeled as continuous-ish yardage outcomes.
        # Use normal simulation around the projection mean with historical std.

        sims = simulate_normal_yards(
            mean=projection,
            std=row["std_for_sim"],
            n_sims=args.n_sims,
            rng=rng,
            max_clip=350,
        )

        p_over = float(np.mean(sims > line))
        p_under = float(np.mean(sims < line))
        p_push = float(np.mean(sims == line))

        over_dec = price_to_decimal(row["over_price"], odds_format)
        under_dec = price_to_decimal(row["under_price"], odds_format)

        ev_over = ev_per_1_staked(p_over, over_dec)
        ev_under = ev_per_1_staked(p_under, under_dec)

        fair_over_price = prob_to_american(p_over)
        fair_under_price = prob_to_american(p_under)

        projection_minus_line = projection - line

        if ev_over >= ev_under:
            recommended_side = "over"
            recommended_ev = ev_over
            recommended_prob = p_over
        else:
            recommended_side = "under"
            recommended_ev = ev_under
            recommended_prob = p_under

        if pd.isna(recommended_ev) or recommended_ev < args.min_ev or recommended_prob < args.min_prob:
            recommendation = "pass"
        else:
            recommendation = recommended_side

        out = row.to_dict()
        out.update(
            {
                "projection": projection,
                "projection_minus_line": projection_minus_line,
                "p_over": p_over,
                "p_under": p_under,
                "p_push": p_push,
                "fair_over_price": fair_over_price,
                "fair_under_price": fair_under_price,
                "over_price_decimal": over_dec,
                "under_price_decimal": under_dec,
                "ev_over": ev_over,
                "ev_under": ev_under,
                "ev_over_percent": ev_over * 100.0 if not pd.isna(ev_over) else math.nan,
                "ev_under_percent": ev_under * 100.0 if not pd.isna(ev_under) else math.nan,
                "recommended_side": recommended_side,
                "recommended_prob": recommended_prob,
                "recommended_ev": recommended_ev,
                "recommended_ev_percent": recommended_ev * 100.0 if not pd.isna(recommended_ev) else math.nan,
                "recommendation": recommendation,
                "n_sims": args.n_sims,
            }
        )
        results.append(out)

    bets = pd.DataFrame(results)

    if bets.empty:
        print("[warning] no projection/market rows matched.")
    else:
        bets = bets.sort_values("recommended_ev", ascending=False)

    if "market_key" in bets.columns:
        assert bets["market_key"].eq(MARKET).all(), (
            "Output contains rows outside player_reception_yds after simulation. "
            "Check filtered markets and merge logic."
        )

    # Configured production exclusion; simulation and EV calculations above are unchanged.
    recommendation_filters = config.get("recommendation_filters", {})
    if (
        not bets.empty
        and recommendation_filters.get("exclude_high_line_favorite_wr_overs", False)
    ):
        favorite_wr_over_min_line = recommendation_filters["favorite_wr_over_min_line"]
        favorite = bets["is_favorite"].fillna(False)
        if not pd.api.types.is_bool_dtype(favorite):
            favorite = favorite.astype(str).str.lower().isin({"true", "1", "yes"})
        suppression_mask = (
            bets["market_key"].eq(MARKET)
            & bets["recommended_side"].eq("over")
            & bets["position"].astype(str).str.upper().eq("WR")
            & favorite
            & bets["line"].ge(favorite_wr_over_min_line)
        )
        suppressed_rows = int(suppression_mask.sum())
        bets = bets.loc[~suppression_mask].copy()
        print(
            f"[production exclusion] suppressed {MARKET} favorite WR overs "
            f"with line >= {favorite_wr_over_min_line}: rows={suppressed_rows:,}"
        )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bets.to_csv(output_path, index=False)

    print(f"\n[output] {output_path}")
    print(f"[rows] {len(bets):,}")

    # Summary statistics from historical rows
    try:
        print("\n===== HISTORY SUMMARY =====")
        print(f"history rows: {len(history):,}")
        print(f"history players: {history['player'].nunique() if 'player' in history.columns else history['player_norm'].nunique()}" )
        print(f"history positions: {history['position'].nunique()}")
        print(f"history avg line: {history['line'].mean():.2f}")
        print(f"history avg actual yards: {history['actual'].mean():.2f}")
        over_rate = (history['actual'] > history['line']).mean()
        print(f"history over rate: {over_rate:.3f}")
        if 'actual_minus_line' in history.columns:
            res = history['actual_minus_line']
            print(f"history residual mean: {res.mean():.2f}")
            print(f"history residual median: {res.median():.2f}")
            print(f"history residual std: {res.std():.2f}")
            print(f"history residual skew: {res.skew():.2f}")
    except Exception:
        pass

    if not bets.empty:
        print("\n===== TOP OVERS =====")
        over_cols = [
            "player",
            "position",
            "line",
            "projection",
            "projection_minus_line",
            "over_price",
            "p_over",
            "fair_over_price",
            "ev_over_percent",
            "recommendation",
        ]
        print(
            bets.sort_values("ev_over", ascending=False)
            .head(15)[[c for c in over_cols if c in bets.columns]]
            .to_string(index=False)
        )

        print("\n===== TOP UNDERS =====")
        under_cols = [
            "player",
            "position",
            "line",
            "projection",
            "projection_minus_line",
            "under_price",
            "p_under",
            "fair_under_price",
            "ev_under_percent",
            "recommendation",
        ]
        print(
            bets.sort_values("ev_under", ascending=False)
            .head(15)[[c for c in under_cols if c in bets.columns]]
            .to_string(index=False)
        )

        DISPLAY_TOP_N = 10

        print("\n===== TOP RECOMMENDATIONS =====")
        print(
            bets
            .sort_values("recommended_ev_percent", ascending=False)
            .head(DISPLAY_TOP_N)
            .to_string(index=False)
        )

        print(f"\n[showing top {DISPLAY_TOP_N} of {len(bets):,} recommendations]")
if __name__ == "__main__":
    main()
