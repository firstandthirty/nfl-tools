from pathlib import Path


MARKET_CONFIG = {
    "player_pass_yds": {
        "label": "Passing Yards",
        "bookmaker": "fanduel",
        "actual_col": "passing_yards",
        "primary_actuals_file": Path("data/processed/pff/pff_passing_weekly.csv"),
        "fallback_actuals_file": Path("data/processed/pff/pff_player_weekly_master.csv"),
        "output_slug": "pass_yds",
        "default_clean_filter": {
            "min_attempt_col": "pass_attempts",
            "min_attempts": 10,
            "min_actual": 25,
            "residual_min": -200,
            "residual_max": 200,
        },
        "known_sigma": 68.488252,
    },

    "player_receptions": {
        "label": "Receptions",
        "bookmaker": "fanduel",
        "actual_col": "receptions",
        "primary_actuals_file": Path("data/processed/pff/pff_player_weekly_master.csv"),
        "fallback_actuals_file": None,
        "output_slug": "receptions",
        "default_clean_filter": {
            "min_actual": 0,
            "residual_min": -10,
            "residual_max": 10,
        },
        "known_sigma": None,
    },

    "player_reception_yds": {
        "label": "Receiving Yards",
        "bookmaker": "fanduel",
        "actual_col": "receiving_yards",
        "primary_actuals_file": Path("data/processed/pff/pff_player_weekly_master.csv"),
        "fallback_actuals_file": None,
        "output_slug": "rec_yds",
        "default_clean_filter": {
            "min_actual": 0,
            "residual_min": -150,
            "residual_max": 150,
        },
        "known_sigma": None,
    },

    "player_rush_yds": {
        "label": "Rushing Yards",
        "bookmaker": "fanduel",
        "actual_col": "rushing_yards",
        "primary_actuals_file": Path("data/processed/pff/pff_player_weekly_master.csv"),
        "fallback_actuals_file": None,
        "output_slug": "rush_yds",
        "default_clean_filter": {
            "min_actual": 0,
            "residual_min": -150,
            "residual_max": 150,
        },
        "known_sigma": None,
    },
}


def get_market_config(market_key: str) -> dict:
    if market_key not in MARKET_CONFIG:
        valid = ", ".join(sorted(MARKET_CONFIG))
        raise KeyError(f"Unknown market_key={market_key}. Valid options: {valid}")

    return MARKET_CONFIG[market_key]