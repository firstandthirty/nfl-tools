import pandas as pd
import nfl_data_py as nfl
from pathlib import Path


PROPS_PATH = Path("data/historical_props/historical_closing_props.csv")
OUT_PATH = Path("data/historical_props/merged_props_actuals.csv")

TEAM_NAME_TO_ABBR = {
    "Arizona Cardinals": "ARI",
    "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR",
    "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN",
    "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN",
    "Detroit Lions": "DET",
    "Green Bay Packers": "GB",
    "Houston Texans": "HOU",
    "Indianapolis Colts": "IND",
    "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV",
    "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LA",
    "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN",
    "New England Patriots": "NE",
    "New Orleans Saints": "NO",
    "New York Giants": "NYG",
    "New York Jets": "NYJ",
    "Philadelphia Eagles": "PHI",
    "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA",
    "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN",
    "Washington Commanders": "WAS",
}

MARKET_TO_ACTUAL_COL = {
    "player_pass_yds": "passing_yards",
    "player_rush_yds": "rushing_yards",
    "player_reception_yds": "receiving_yards",
    "player_receptions": "receptions",
}


def normalize_name(series):
    return (
        series.astype(str)
        .str.lower()
        .str.strip()
        .str.replace(".", "", regex=False)
        .str.replace("'", "", regex=False)
        .str.replace("-", " ", regex=False)
        .str.replace(r"\b(jr|sr|ii|iii|iv|v)\b", "", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )

def main():
    props = pd.read_csv(PROPS_PATH)

    print(f"[props] rows={len(props):,}")

    props["commence_time"] = pd.to_datetime(props["commence_time"], utc=True)
    props["game_date"] = (
        props["commence_time"]
        .dt.tz_convert("America/New_York")
        .dt.date
    )
    props["home_team_abbr"] = props["home_team"].map(TEAM_NAME_TO_ABBR)
    props["away_team_abbr"] = props["away_team"].map(TEAM_NAME_TO_ABBR)

    missing_home = props.loc[props["home_team_abbr"].isna(), ["home_team"]].drop_duplicates()
    missing_away = props.loc[props["away_team_abbr"].isna(), ["away_team"]].drop_duplicates()

    if len(missing_home):
        print("[team map] missing home team mappings:")
        print(missing_home.to_string(index=False))

    if len(missing_away):
        print("[team map] missing away team mappings:")
        print(missing_away.to_string(index=False))
    props = props.loc[props["commence_time"].dt.year == 2024].copy()

    props = props.loc[
        props["market_key"].isin(MARKET_TO_ACTUAL_COL.keys())
    ].copy()

    print("[props before dedupe] rows:", len(props))

    dedupe_cols = [
        "event_id",
        "market_key",
        "player",
        "line",
        "over_price",
        "under_price",
    ]

    props = props.drop_duplicates(
        subset=dedupe_cols,
        keep="last",
    ).copy()

    print("[props after dedupe] rows:", len(props))

    print(f"[props] supported market rows={len(props):,}")
    print(props["market_key"].value_counts().to_string())

    seasons = sorted(props["commence_time"].dt.year.unique().tolist())

    print(f"[nflverse] loading seasons={seasons}")

    available_actual_seasons = [s for s in seasons if s <= 2024]

    if not available_actual_seasons:
        raise RuntimeError(
            f"No actual nflverse weekly data available for seasons={seasons}. "
            "This is expected if your historical props are from future 2025 games. "
            "Use 2024 historical props for testing, or wait until 2025 actuals are published."
        )

    weekly = nfl.import_weekly_data(available_actual_seasons)
    schedule = nfl.import_schedules(seasons)

    print(f"[weekly] rows={len(weekly):,}")
    print(f"[schedule] rows={len(schedule):,}")

    weekly = weekly[[
        "player_display_name",
        "season",
        "week",
        "recent_team",
        "position",
        "passing_yards",
        "rushing_yards",
        "receiving_yards",
        "receptions",
    ]].copy()

    weekly["player_norm"] = normalize_name(weekly["player_display_name"])

    weekly = weekly.sort_values(
        ["season", "week", "player_display_name"]
    )

    weekly = weekly.drop_duplicates(
        subset=["player_norm", "season", "week"],
        keep="first",
    )

    print("[weekly deduped] rows=", len(weekly))

    props["player_norm"] = normalize_name(props["player"])

    schedule["gameday"] = pd.to_datetime(schedule["gameday"])
    schedule["game_date"] = schedule["gameday"].dt.date

    schedule_home = schedule[[
        "season",
        "week",
        "game_date",
        "home_team",
        "away_team",
    ]].copy()

    schedule_home = schedule_home.rename(columns={
        "home_team": "home_team_abbr",
        "away_team": "away_team_abbr",
    })

    props = props.merge(
        schedule_home,
        on=["home_team_abbr", "away_team_abbr", "game_date"],
        how="left",
    )

    print(
        "[schedule merge] missing season/week:",
        props["season"].isna().sum(),
    )
    
    missing_schedule = props.loc[
        props["season"].isna(),
        [
            "player",
            "home_team",
            "away_team",
            "home_team_abbr",
            "away_team_abbr",
            "game_date",
            "commence_time",
        ]
    ]

    if len(missing_schedule):
        print()
        print("===== Missing Schedule Matches =====")
        print(missing_schedule.drop_duplicates(
            ["home_team", "away_team", "game_date"]
        ).to_string(index=False))

        print()
        print("===== Schedule Debug Table =====")
        min_date = props["game_date"].min()
        max_date = props["game_date"].max()
        debug_sched = schedule.loc[
            (schedule["gameday"].dt.date >= min_date) & (schedule["gameday"].dt.date <= max_date),
            ["season", "week", "gameday", "away_team", "home_team"]
        ]
        print(debug_sched.to_string(index=False))

    merged = props.merge(
        weekly,
        on=["player_norm", "season", "week"],
        how="left",
    )

    merged["actual_value"] = merged.apply(
        lambda row: row[MARKET_TO_ACTUAL_COL[row["market_key"]]],
        axis=1,
    )

    NON_PASSING_MARKETS = {
        "player_rush_yds",
        "player_reception_yds",
        "player_receptions",
    }

    fill_mask = (
        merged["actual_value"].isna() &
        merged["market_key"].isin(NON_PASSING_MARKETS)
    )

    print()
    print("[fill zeros] rows filled:", fill_mask.sum())

    merged.loc[fill_mask, "actual_value"] = 0

    merged["went_over"] = (
        merged["actual_value"] > merged["line"]
    ).astype("Int64")

    merged["push"] = (
        merged["actual_value"] == merged["line"]
    ).astype("Int64")

    missing_actuals = merged.loc[merged["actual_value"].isna()].copy()

    if len(missing_actuals):
        print()
        print("===== Missing Actuals Debug: Available NFLVerse Players Same Week/Teams =====")

        for _, row in missing_actuals.head(25).iterrows():
            same_week = weekly.loc[
                (weekly["season"] == row["season"]) &
                (weekly["week"] == row["week"])
            ]

            print()
            print(
                f'{row["player"]} | {row["market_key"]} | '
                f'{row["away_team"]} @ {row["home_team"]} | line={row["line"]}'
            )

            candidates = same_week.loc[
                same_week["player_display_name"]
                .str.contains(row["player"].split()[0], case=False, na=False),
                ["player_display_name", "recent_team", "position"]
            ].drop_duplicates()

            if len(candidates):
                print(candidates.head(15).to_string(index=False))
            else:
                print("No same-week name candidates found.")

    print()
    print("===== QA =====")
    print("rows:", len(merged))
    print("missing actual_value:", merged["actual_value"].isna().sum())
    print("over rate:", round(merged["went_over"].mean(), 4))

    print()
    print("===== QA by Market =====")
    qa_by_market = merged.groupby("market_key").agg(
        rows=("market_key", "size"),
        over_rate=("went_over", "mean"),
        avg_line=("line", "mean"),
        missing_actuals=("actual_value", lambda x: x.isna().sum()),
    ).reset_index()

    print(qa_by_market.to_string(index=False))

    missing = merged.loc[
        merged["actual_value"].isna(),
        ["player", "home_team", "away_team", "commence_time", "line"]
    ]

    if len(missing):
        print()
        print("===== Missing Actuals Sample =====")
        print(missing.head(25).to_string(index=False))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(OUT_PATH, index=False)

    print()
    print(f"[saved] {OUT_PATH}")


if __name__ == "__main__":
    main()