from pathlib import Path
import argparse
import math
import re

import numpy as np
import pandas as pd


HISTORY_FILE = Path("data/processed/fanduel_receptions_history.csv")
OUT_FILE = Path("data/analysis/receptions_model_bets.csv")
BACKTEST_SAFE_OUT_FILE = Path("data/analysis/receptions_model_bets_backtest_safe.csv")

MARKET = "player_receptions"
N_SIMS_DEFAULT = 20_000
RANDOM_SEED_DEFAULT = 42


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
    "projected_receptions",
    "projection",
    "weighted_projection",
    "ensemble_projection",
    "fantasy_projection",
    "receptions_projection",
    "rec_projection",
    "receptions",
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
    bins = [0, 2.5, 3.5, 4.5, 5.5, 6.5, math.inf]
    labels = ["<=2.5", "3.5", "4.5", "5.5", "6.5", "7+"]

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

    # History may not already have actuals. The analysis file generally does.
    actual_col = None
    for c in ["actual", "actual_market_value", "actual_receptions", "receptions"]:
        if c in hist.columns:
            actual_col = c
            break

    if actual_col is None:
        raise RuntimeError(
            "Historical file does not contain actual receptions. "
            "Use data/analysis/receptions_market_analysis_rows.csv if needed, "
            "or rerun analyze_market.py first."
        )

    if "position" not in hist.columns:
        raise RuntimeError(
            "Historical file does not contain position. "
            "Use data/analysis/receptions_market_analysis_rows.csv, which is created by analyze_market.py."
        )

    hist = hist.copy()
    hist["actual"] = pd.to_numeric(hist[actual_col], errors="coerce")
    hist["line"] = pd.to_numeric(hist["line"], errors="coerce")
    hist["position"] = hist["position"].fillna("UNKNOWN").astype(str)

    hist = hist.dropna(subset=["actual", "line"])
    hist = add_line_bucket(hist, "line")

    return hist


def build_variance_table(hist):
    # Estimate variance by position + line bucket.
    # Use actual receptions instead of residuals because the simulation mean comes from projections.
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

    return grouped


def simulate_negative_binomial(mean, variance, n_sims, rng):
    mean = max(float(mean), 0.01)
    variance = max(float(variance), mean + 0.01)

    # Negative binomial parameterization:
    # mean = r * (1-p) / p
    # variance = r * (1-p) / p^2
    # p = mean / variance
    # r = mean^2 / (variance - mean)
    p = mean / variance
    p = min(max(p, 1e-6), 0.999999)
    r = (mean * mean) / max(variance - mean, 1e-6)

    sims = rng.negative_binomial(r, p, size=n_sims)

    # Receptions cannot be negative and extremely high values are basically garbage tails.
    sims = np.clip(sims, 0, 25)

    return sims


def first_existing_col(df, candidates):
    for col in candidates:
        if col in df.columns:
            return col
    return None


def load_projection_file(path, include_stable_keys=False):
    df = pd.read_csv(path)

    player_col = find_col(df, PLAYER_COL_CANDIDATES, label="projection player column")
    proj_col = find_col(df, PROJECTION_COL_CANDIDATES, label="projection receptions column")
    pos_col = find_col(df, POSITION_COL_CANDIDATES, required=False, label="projection position column")

    out = df.copy()
    out["player_norm"] = out[player_col].apply(normalize_text)
    out["projection"] = pd.to_numeric(out[proj_col], errors="coerce")

    if pos_col is not None:
        out["position"] = out[pos_col].astype(str)
    else:
        out["position"] = "UNKNOWN"

    out["player"] = out[player_col]

    keep = ["player", "player_norm", "position", "projection"]
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

    if include_stable_keys:
        for col in ["season", "week"]:
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")
                keep.append(col)

        player_id_col = first_existing_col(out, ["player_id", "fpid", "mflid", "gsis_id", "pfr_id"])
        if player_id_col is not None:
            out["player_id"] = out[player_id_col]
            keep.append("player_id")
        else:
            print(
                "[debug] projections missing player_id: no source column found among "
                "player_id/fpid/mflid/gsis_id/pfr_id."
            )

    return out[keep].dropna(subset=["player_norm", "projection"])


def load_market_file(path, include_stable_keys=False):
    df = pd.read_csv(path)

    player_col = find_col(df, PLAYER_COL_CANDIDATES, label="market player column")
    line_col = find_col(df, LINE_COL_CANDIDATES, label="market line column")
    over_col = find_col(df, OVER_PRICE_COL_CANDIDATES, label="market over price column")
    under_col = find_col(df, UNDER_PRICE_COL_CANDIDATES, label="market under price column")
    pos_col = find_col(df, POSITION_COL_CANDIDATES, required=False, label="market position column")

    out = df.copy()
    out["player_norm"] = out[player_col].apply(normalize_text)
    out["player"] = out[player_col]
    out["line"] = pd.to_numeric(out[line_col], errors="coerce")
    out["over_price"] = pd.to_numeric(out[over_col], errors="coerce")
    out["under_price"] = pd.to_numeric(out[under_col], errors="coerce")

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

    if include_stable_keys:
        season_source = first_existing_col(out, ["season", "season_guess", "season_str"])
        week_source = first_existing_col(out, ["week", "week_guess_numeric", "week_guess", "week_str"])
        game_id_source = first_existing_col(out, ["game_id", "event_id", "event_id_str"])

        if season_source is not None:
            out["season"] = pd.to_numeric(out[season_source], errors="coerce")
            keep.append("season")
        else:
            print(
                "[debug] markets missing season: no source column found among "
                "season/season_guess/season_str."
            )

        if week_source is not None:
            out["week"] = pd.to_numeric(out[week_source], errors="coerce")
            keep.append("week")
        else:
            print(
                "[debug] markets missing week: no source column found among "
                "week/week_guess_numeric/week_guess/week_str."
            )

        if game_id_source is not None:
            out["game_id"] = out[game_id_source]
            keep.append("game_id")
        else:
            print(
                "[debug] markets missing game_id: no source column found among "
                "game_id/event_id/event_id_str."
            )

        if "market_key" in out.columns:
            keep.append("market_key")
        else:
            out["market_key"] = MARKET
            keep.append("market_key")

    return out[keep].dropna(subset=["player_norm", "line", "over_price", "under_price"])


def merge_projection_market(markets, projections, merge_keys=None, require_stable_keys=False):
    if merge_keys is None:
        merge_keys = ["player_norm"]

    missing_market_keys = [key for key in merge_keys if key not in markets.columns]
    missing_projection_keys = [key for key in merge_keys if key not in projections.columns]
    if missing_market_keys or missing_projection_keys:
        message = (
            f"Cannot merge projections and markets on {merge_keys}: "
            f"markets missing {missing_market_keys}, projections missing {missing_projection_keys}."
        )
        if require_stable_keys:
            raise RuntimeError(message)
        print(f"[debug] {message} Falling back to player_norm merge.")
        merge_keys = ["player_norm"]

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

    print(f"[merge] keys={merge_keys}")
    print(f"[merge] market rows={len(markets):,}")
    print(f"[merge] projection rows={len(projections):,}")
    print(f"[merge] merged rows={merged_rows:,}")
    print(f"[merge] merge rate={merge_rate:.4f}")
    print(f"[merge] unmatched market rows={unmatched_market_rows:,}")
    print(f"[merge] unmatched projection rows={unmatched_projection_rows:,}")
    if "player_norm" in df.columns:
        print(f"[merge] unique players={df['player_norm'].nunique():,}")
    if {"season", "week"}.issubset(df.columns):
        print("[merge] season/week distribution:")
        print(df.groupby(["season", "week"]).size().sort_index().to_string())

    return df


def simulate_bets(df, history, variance_table, args):
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

    rng = np.random.default_rng(args.seed)
    results = []

    for _, row in df.iterrows():
        projection = float(row["projection"])
        line = float(row["line"])

        # Simulation variance should never be lower than mean + a tiny amount.
        variance = max(float(row["var_for_sim"]), projection + 0.01)

        sims = simulate_negative_binomial(
            mean=projection,
            variance=variance,
            n_sims=args.n_sims,
            rng=rng,
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
                "edge": projection_minus_line,
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
    return bets


def write_backtest_safe_output(args, history, variance_table):
    print("\n===== BACKTEST-SAFE RECEPTIONS OUTPUT =====")
    projections = load_projection_file(Path(args.projections), include_stable_keys=True)
    markets = load_market_file(Path(args.markets), include_stable_keys=True)

    for label, frame in [("projections", projections), ("markets", markets)]:
        print(f"[safe keys] {label} rows={len(frame):,}")
        for key in ["player_id", "season", "week", "game_id"]:
            if key in frame.columns:
                print(f"[safe keys] {label}.{key} non-null={frame[key].notna().sum():,}")
            elif key in {"player_id", "game_id"}:
                print(f"[debug] {label}.{key} unavailable at output stage; source did not provide it.")

    stable_keys = ["season", "week", "player_norm"]
    df = merge_projection_market(markets, projections, stable_keys, require_stable_keys=True)
    bets = simulate_bets(df, history, variance_table, args)

    if "market_key" not in bets.columns:
        bets["market_key"] = MARKET
    if "team" not in bets.columns and "team_name" in bets.columns:
        bets["team"] = bets["team_name"]
    if "opponent" not in bets.columns:
        bets["opponent"] = pd.NA
    if "player_id" not in bets.columns:
        bets["player_id"] = pd.NA
    if "game_id" not in bets.columns:
        bets["game_id"] = pd.NA

    if {"team", "opponent"}.issubset(history.columns):
        context = history.copy()
        if "game_id" not in context.columns:
            game_id_source = first_existing_col(context, ["event_id", "event_id_str"])
            if game_id_source is not None:
                context["game_id"] = context[game_id_source]
        if "player_norm" not in context.columns:
            context["player_norm"] = context["player"].apply(normalize_text)
        context["line"] = pd.to_numeric(context["line"], errors="coerce")

        context_keys = ["game_id", "player_norm", "line"]
        if set(context_keys).issubset(context.columns):
            context = (
                context[context_keys + ["team", "opponent"]]
                .dropna(subset=context_keys)
                .drop_duplicates(context_keys)
            )
            before_team = int(bets["team"].notna().sum())
            bets = bets.merge(
                context,
                on=context_keys,
                how="left",
                suffixes=("", "_history"),
            )
            bets["team"] = bets["team"].combine_first(bets.pop("team_history"))
            bets["opponent"] = bets["opponent"].combine_first(bets.pop("opponent_history"))
            print(
                "[safe keys] team/opponent filled from history="
                f"{int(bets['team'].notna().sum()) - before_team:,}"
            )
        else:
            print(
                "[debug] team/opponent context unavailable: history lacks "
                "game_id/event_id, player_norm/player, or line."
            )
    else:
        print("[debug] team/opponent context unavailable: history lacks team/opponent columns.")

    safe_cols = [
        "player",
        "player_id",
        "team",
        "opponent",
        "season",
        "week",
        "game_id",
        "market_key",
        "line",
        "over_price",
        "under_price",
        "projection",
        "projection_minus_line",
        "edge",
        "recommended_side",
        "recommended_prob",
        "recommended_ev_percent",
        "recommendation",
        "player_norm",
    ]
    safe = bets[[col for col in safe_cols if col in bets.columns]].copy()

    for col in ["season", "week"]:
        if col in safe.columns:
            safe[col] = pd.to_numeric(safe[col], errors="coerce").astype("Int64")

    output_path = Path(args.backtest_safe_output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    safe.to_csv(output_path, index=False)

    print(f"[output] {output_path}")
    print(f"[rows] {len(safe):,}")
    for key in ["player_id", "season", "week", "game_id"]:
        if key in safe.columns:
            print(f"[safe keys] output.{key} non-null={safe[key].notna().sum():,}")

    sample_cols = [
        "player",
        "season",
        "week",
        "team",
        "opponent",
        "player_id",
        "game_id",
        "line",
        "projection",
    ]
    print("\n===== BACKTEST-SAFE SAMPLE =====")
    if safe.empty:
        print("No rows.")
    else:
        print(safe[[col for col in sample_cols if col in safe.columns]].head(10).to_string(index=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--projections",
        required=True,
        help="CSV containing fantasy/ensemble receptions projections.",
    )
    parser.add_argument(
        "--markets",
        required=True,
        help="CSV containing current FanDuel player_receptions lines.",
    )
    parser.add_argument(
        "--history",
        default=str(Path("data/analysis/receptions_market_analysis_rows.csv")),
        help="Historical analysis rows with actual receptions and position.",
    )
    parser.add_argument(
        "--output",
        default=str(OUT_FILE),
        help="Output CSV path.",
    )
    parser.add_argument(
        "--backtest-safe-output",
        default=str(BACKTEST_SAFE_OUT_FILE),
        help="Separate CSV path with stable season/week/player/game keys for receptions backtests.",
    )
    parser.add_argument("--n-sims", type=int, default=N_SIMS_DEFAULT)
    parser.add_argument("--seed", type=int, default=RANDOM_SEED_DEFAULT)
    parser.add_argument("--min-ev", type=float, default=0.02, help="Minimum EV as decimal, e.g. 0.02 = 2%.")
    parser.add_argument("--min-prob", type=float, default=0.525)
    args = parser.parse_args()

    print("===== RECEPTIONS PROJECTION ENGINE =====")

    projections = load_projection_file(Path(args.projections))
    markets = load_market_file(Path(args.markets))
    history = load_history(Path(args.history))

    print(f"[load] projections rows={len(projections):,}")
    print(f"[load] market rows={len(markets):,}")
    print(f"[load] history rows={len(history):,}")

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
    df = markets.merge(
        projections.drop(columns=["player"], errors="ignore"),
        on="player_norm",
        how="inner",
        suffixes=("", "_proj"),
    )

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

    rng = np.random.default_rng(args.seed)
    results = []

    for _, row in df.iterrows():
        projection = float(row["projection"])
        line = float(row["line"])

        # Simulation variance should never be lower than mean + a tiny amount.
        variance = max(float(row["var_for_sim"]), projection + 0.01)

        sims = simulate_negative_binomial(
            mean=projection,
            variance=variance,
            n_sims=args.n_sims,
            rng=rng,
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

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bets.to_csv(output_path, index=False)

    print(f"\n[output] {output_path}")
    print(f"[rows] {len(bets):,}")

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

        print("\n===== RECOMMENDATIONS =====")
        recs = bets[bets["recommendation"] != "pass"]
        if recs.empty:
            print("No bets met thresholds.")
        else:
            rec_cols = [
                "player",
                "position",
                "line",
                "projection",
                "over_price",
                "under_price",
                "p_over",
                "p_under",
                "recommended_side",
                "recommended_prob",
                "recommended_ev_percent",
            ]
            print(recs.head(50)[[c for c in rec_cols if c in recs.columns]].to_string(index=False))
            if len(recs) > 50:
                print(f"... {len(recs) - 50:,} additional recommendations omitted from console output.")

    write_backtest_safe_output(args, history, variance_table)


if __name__ == "__main__":
    main()
