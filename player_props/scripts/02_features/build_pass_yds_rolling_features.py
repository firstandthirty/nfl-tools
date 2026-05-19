from pathlib import Path
import numpy as np
import pandas as pd

INPUT = Path("data/historical_props/merged_props_with_context.csv")
OUT_PATH = Path("data/historical_props/merged_props_with_rolling.csv")

MARKET = "player_pass_yds"


def main():
    if not INPUT.exists():
        raise FileNotFoundError(f"Missing input file: {INPUT}")

    df = pd.read_csv(INPUT)
    df.columns = [c.strip() for c in df.columns]

    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce")
    df["actual_value"] = pd.to_numeric(df["actual_value"], errors="coerce")
    df["line"] = pd.to_numeric(df["line"], errors="coerce")

    # Player prop rows can contain duplicate player/game rows from multiple snapshots/books.
    # For rolling features, collapse to one player-game-market row first.
    pass_df = df[df["market_key"].eq(MARKET)].copy()

    key_cols = [
        "season",
        "week",
        "game_date",
        "player_norm",
        "player",
        "recent_team",
        "home_team_abbr",
        "away_team_abbr",
    ]

    game_level = (
        pass_df
        .sort_values(["player_norm", "season", "week", "game_date"])
        .groupby(key_cols, dropna=False)
        .agg(
            pass_yds=("actual_value", "mean"),
            avg_line=("line", "mean"),
            went_over=("went_over", "max"),
            push=("push", "max"),
        )
        .reset_index()
    )

    game_level["actual_minus_line"] = game_level["pass_yds"] - game_level["avg_line"]

    game_level = game_level.sort_values(
        ["player_norm", "season", "week", "game_date"]
    ).copy()

    grouped = game_level.groupby("player_norm", group_keys=False)

    # Prior-game rolling production
    for window in [3, 5]:
        game_level[f"rolling_pass_yds_{window}g"] = grouped["pass_yds"].transform(
            lambda s: s.shift(1).rolling(window, min_periods=1).mean()
        )

        game_level[f"rolling_actual_minus_line_{window}g"] = grouped["actual_minus_line"].transform(
            lambda s: s.shift(1).rolling(window, min_periods=1).mean()
        )

        game_level[f"rolling_std_pass_yds_{window}g"] = grouped["pass_yds"].transform(
            lambda s: s.shift(1).rolling(window, min_periods=2).std()
        )

        game_level[f"rolling_over_rate_{window}g"] = grouped["went_over"].transform(
            lambda s: s.shift(1).rolling(window, min_periods=1).mean()
        )

    # Prior season-to-date averages
    game_level["season_avg_pass_yds_pre"] = grouped["pass_yds"].transform(
        lambda s: s.shift(1).expanding(min_periods=1).mean()
    )

    game_level["season_avg_actual_minus_line_pre"] = grouped["actual_minus_line"].transform(
        lambda s: s.shift(1).expanding(min_periods=1).mean()
    )

    game_level["games_played_pre"] = grouped["pass_yds"].cumcount()

    feature_cols = [
        "season",
        "week",
        "game_date",
        "player_norm",
        "recent_team",
        "rolling_pass_yds_3g",
        "rolling_pass_yds_5g",
        "rolling_actual_minus_line_3g",
        "rolling_actual_minus_line_5g",
        "rolling_std_pass_yds_3g",
        "rolling_std_pass_yds_5g",
        "rolling_over_rate_3g",
        "rolling_over_rate_5g",
        "season_avg_pass_yds_pre",
        "season_avg_actual_minus_line_pre",
        "games_played_pre",
    ]

    features = game_level[feature_cols].copy()

    out = df.merge(
        features,
        on=["season", "week", "game_date", "player_norm", "recent_team"],
        how="left",
        validate="many_to_one",
    )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_PATH, index=False)

    print(f"[load] input rows={len(df):,}")
    print(f"[features] player-game rows={len(game_level):,}")
    print(f"[saved] {OUT_PATH}")

    pass_rows = out[out["market_key"].eq(MARKET)].copy()
    print("\n[coverage on pass yards rows]")
    for c in feature_cols[5:]:
        coverage = pass_rows[c].notna().mean()
        print(f"{c}: {coverage:.1%}")

    print("\n[sample]")
    sample_cols = [
        "season",
        "week",
        "player",
        "recent_team",
        "line",
        "actual_value",
        "rolling_pass_yds_3g",
        "rolling_actual_minus_line_3g",
        "rolling_std_pass_yds_3g",
        "games_played_pre",
    ]
    print(
        pass_rows[sample_cols]
        .sort_values(["player", "season", "week"])
        .head(25)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()