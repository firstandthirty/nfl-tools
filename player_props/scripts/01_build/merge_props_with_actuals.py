import argparse
import pandas as pd
from pathlib import Path


PROPS_PATH = Path("data/historical_props/historical_closing_props.csv")
OUT_PATH = Path("data/historical_props/merged_props_actuals.csv")
PFF_PATH = Path("data/processed/pff/pff_player_weekly_master.csv")

REGULAR_SEASON_START_DATES = {
    2023: "2023-09-07",
    2024: "2024-09-05",
    2025: "2025-09-04",
}

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


def parse_args():
    parser = argparse.ArgumentParser(description="Merge historical prop lines with settled player actuals.")
    parser.add_argument("--season", type=int, default=2024)
    parser.add_argument("--market", default=None, help="Optional market_key filter.")
    parser.add_argument("--input", type=Path, default=PROPS_PATH)
    parser.add_argument("--actuals", type=Path, default=PFF_PATH)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def default_output_path(season):
    if season == 2024:
        return OUT_PATH
    return Path(f"data/processed/merged_props_with_actuals_{season}.csv")


def assign_regular_season_week(props, season):
    if season not in REGULAR_SEASON_START_DATES:
        raise ValueError(
            f"No regular-season start date configured for season={season}. "
            f"Available: {sorted(REGULAR_SEASON_START_DATES)}"
        )

    start = pd.Timestamp(REGULAR_SEASON_START_DATES[season])
    local_dates = props["commence_time"].dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    week = ((local_dates - start).dt.days // 7 + 1).astype("Int64")
    props = props.loc[week.between(1, 18)].copy()
    props["season"] = season
    props["week"] = week.loc[props.index]
    props["game_date"] = local_dates.loc[props.index].dt.date
    return props


def odds_format_sanity(props):
    values = pd.concat(
        [
            pd.to_numeric(props["over_price"], errors="coerce"),
            pd.to_numeric(props["under_price"], errors="coerce"),
        ],
        ignore_index=True,
    ).dropna()
    if values.empty:
        return "unknown"
    decimal_count = values.between(1.0, 10.0).sum()
    american_count = (~values.between(1.0, 10.0)).sum()
    return "decimal" if decimal_count > american_count else "american"


def main():
    args = parse_args()
    output_path = args.output or default_output_path(args.season)
    props = pd.read_csv(args.input)

    print(f"[props] rows={len(props):,}")

    props["commence_time"] = pd.to_datetime(props["commence_time"], utc=True)
    props = assign_regular_season_week(props, args.season)
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
    props = props.loc[
        props["market_key"].isin(MARKET_TO_ACTUAL_COL.keys())
    ].copy()

    if args.market:
        props = props.loc[props["market_key"].eq(args.market)].copy()

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

    print("\n===== Raw Rows by Season / Week / Market =====")
    print(props.groupby(["season", "week", "market_key"]).size().rename("rows").reset_index().to_string(index=False))
    print("\n===== Unique Games by Week =====")
    print(props.groupby(["season", "week"])["event_id"].nunique().rename("unique_games").reset_index().to_string(index=False))
    print(f"\n[odds QA] inferred odds format={odds_format_sanity(props)}")

    dup_cols = ["season", "week", "event_id", "market_key", "player", "line"]
    duplicate_rows = props.duplicated(dup_cols, keep=False).sum()
    print(f"[duplicate QA] duplicate player/game/market/line rows={duplicate_rows:,}")

    weekly = pd.read_csv(args.actuals, low_memory=False)
    weekly = weekly.loc[pd.to_numeric(weekly["season"], errors="coerce").eq(args.season)].copy()
    print(f"[actuals] source={args.actuals} season={args.season} rows={len(weekly):,}")

    weekly = weekly[[
        "player",
        "season",
        "week",
        "team_name",
        "position",
        "passing_yards",
        "rushing_yards",
        "receiving_yards",
        "receptions",
    ]].copy()

    weekly = weekly.rename(columns={"player": "player_display_name", "team_name": "recent_team"})
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

    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(output_path, index=False)

    print()
    print(f"[saved] {output_path}")


if __name__ == "__main__":
    main()
