from pathlib import Path
import re

import numpy as np
import pandas as pd


BASE_PREDICTIONS = Path("data/historical_props/pass_yds_baseline_predictions.csv")
EVENT_SOURCE = Path("data/historical_props/merged_props_with_rolling.csv")
PLAYER_ID_SOURCE = Path("data/processed/pff/pff_passing_weekly.csv")
OUT_FILE = Path("data/analysis/pass_yds_model_bets_backtest_safe.csv")
VALIDATION_FILE = Path("data/analysis/backtests/pass_yds_safe_sidecar_validation.csv")

MARKET_KEY = "player_pass_yds"

TEAM_ABBR_TO_FULL = {
    "ARI": "Arizona Cardinals",
    "ARZ": "Arizona Cardinals",
    "ATL": "Atlanta Falcons",
    "BAL": "Baltimore Ravens",
    "BLT": "Baltimore Ravens",
    "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers",
    "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals",
    "CLE": "Cleveland Browns",
    "CLV": "Cleveland Browns",
    "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos",
    "DET": "Detroit Lions",
    "GB": "Green Bay Packers",
    "HOU": "Houston Texans",
    "HST": "Houston Texans",
    "IND": "Indianapolis Colts",
    "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs",
    "LAC": "Los Angeles Chargers",
    "LAR": "Los Angeles Rams",
    "LA": "Los Angeles Rams",
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


def normalize_text(value):
    if pd.isna(value):
        return ""
    text = str(value).lower()
    text = text.replace(".", "")
    text = text.replace("'", "")
    text = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", text)
    text = " ".join(text.split())
    return text.strip()


def side_from_projection(edge):
    if pd.isna(edge):
        return pd.NA
    if edge > 0:
        return "over"
    if edge < 0:
        return "under"
    return "pass"


def american_implied_prob(price):
    if pd.isna(price):
        return np.nan
    price = float(price)
    if price < 0:
        return abs(price) / (abs(price) + 100)
    return 100 / (price + 100)


def main():
    base = pd.read_csv(BASE_PREDICTIONS)
    events = pd.read_csv(EVENT_SOURCE)
    pff = pd.read_csv(PLAYER_ID_SOURCE)

    base = base.copy()
    base["player_norm"] = base["player"].apply(normalize_text)
    base["line"] = pd.to_numeric(base["line"], errors="coerce")
    base["projection"] = pd.to_numeric(base["pred_mean"], errors="coerce")
    base["projection_minus_line"] = base["projection"] - base["line"]

    events = events[events["market_key"].eq(MARKET_KEY)].copy()
    events["player_norm"] = events["player"].apply(normalize_text)
    events["line"] = pd.to_numeric(events["line"], errors="coerce")
    event_lookup = (
        events[
            [
                "season",
                "week",
                "player_norm",
                "line",
                "event_id",
                "home_team",
                "away_team",
                "home_team_abbr",
                "away_team_abbr",
            ]
        ]
        .drop_duplicates(["season", "week", "player_norm", "line"])
        .rename(columns={"event_id": "game_id"})
    )

    pff = pff.copy()
    pff["player_norm"] = pff["player"].apply(normalize_text)
    player_id_lookup = (
        pff[["season", "week", "player_norm", "player_id"]]
        .dropna(subset=["season", "week", "player_norm", "player_id"])
        .drop_duplicates(["season", "week", "player_norm"])
    )

    safe = base.merge(
        event_lookup,
        on=["season", "week", "player_norm", "line"],
        how="left",
        validate="one_to_one",
    )
    safe = safe.merge(
        player_id_lookup,
        on=["season", "week", "player_norm"],
        how="left",
        validate="many_to_one",
    )

    safe["team"] = safe["recent_team"]
    team_full = safe["team"].map(TEAM_ABBR_TO_FULL).fillna(safe["team"])
    safe["opponent"] = pd.Series(
        np.where(team_full.eq(safe["home_team"]), safe["away_team"], pd.NA),
        index=safe.index,
    )
    safe["opponent"] = safe["opponent"].combine_first(
        pd.Series(
            np.where(team_full.eq(safe["away_team"]), safe["home_team"], pd.NA),
            index=safe.index,
        )
    )
    safe["market_key"] = MARKET_KEY
    safe["actual"] = safe["actual_value"]
    safe["recommended_side"] = safe["projection_minus_line"].apply(side_from_projection)

    # No probability/EV recommendation was produced by the baseline prediction file.
    safe["recommended_prob"] = pd.NA
    safe["recommended_ev_percent"] = pd.NA

    out_cols = [
        "player",
        "player_norm",
        "player_id",
        "season",
        "week",
        "team",
        "opponent",
        "game_id",
        "market_key",
        "line",
        "over_price",
        "under_price",
        "projection",
        "projection_minus_line",
        "pred_std",
        "actual",
        "recommended_side",
        "recommended_prob",
        "recommended_ev_percent",
    ]
    safe_out = safe[out_cols].copy()

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    safe_out.to_csv(OUT_FILE, index=False)

    projection_equal = safe_out["projection"].equals(pd.to_numeric(base["pred_mean"], errors="coerce"))
    edge_equal = np.allclose(
        safe_out["projection_minus_line"],
        pd.to_numeric(base["pred_mean"], errors="coerce") - pd.to_numeric(base["line"], errors="coerce"),
        equal_nan=True,
    )

    validation = pd.DataFrame(
        [
            {
                "source_baseline_rows": len(base),
                "safe_sidecar_rows": len(safe_out),
                "game_id_non_null": int(safe_out["game_id"].notna().sum()),
                "player_id_non_null": int(safe_out["player_id"].notna().sum()),
                "season_non_null": int(safe_out["season"].notna().sum()),
                "week_non_null": int(safe_out["week"].notna().sum()),
                "team_non_null": int(safe_out["team"].notna().sum()),
                "opponent_non_null": int(safe_out["opponent"].notna().sum()),
                "projection_equals_pred_mean": bool(projection_equal),
                "projection_minus_line_equals_pred_mean_minus_line": bool(edge_equal),
                "output_file": str(OUT_FILE),
            }
        ]
    )
    VALIDATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    validation.to_csv(VALIDATION_FILE, index=False)

    print("===== PASS YDS SAFE SIDECAR VALIDATION =====")
    print(validation.to_string(index=False))
    print("\n===== SAMPLE ROWS =====")
    print(
        safe_out[
            [
                "player",
                "player_norm",
                "player_id",
                "season",
                "week",
                "team",
                "opponent",
                "game_id",
                "line",
                "projection",
                "projection_minus_line",
                "actual",
                "recommended_side",
            ]
        ]
        .head(10)
        .to_string(index=False)
    )
    print(f"\n[output] {OUT_FILE}")
    print(f"[validation] {VALIDATION_FILE}")

    if len(base) != 444 or len(safe_out) != 444:
        raise RuntimeError("Unexpected pass-yards row count; expected 444 baseline and sidecar rows.")
    if safe_out["game_id"].notna().sum() != 444:
        raise RuntimeError("Missing game_id values in pass-yards safe sidecar.")
    if safe_out["player_id"].notna().sum() != 444:
        raise RuntimeError("Missing player_id values in pass-yards safe sidecar.")
    if not projection_equal:
        raise RuntimeError("projection does not exactly equal pred_mean.")
    if not edge_equal:
        raise RuntimeError("projection_minus_line does not equal pred_mean - line.")


if __name__ == "__main__":
    main()
