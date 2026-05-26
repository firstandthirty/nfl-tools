from pathlib import Path
import argparse
import json
import urllib.request

import numpy as np
import pandas as pd

PROPS_PATH = Path("data/historical_props/merged_props_actuals.csv")
OUT_PATH = Path("data/historical_props/game_context.csv")

GITHUB_RELEASE_API = "https://api.github.com/repos/nflverse/nflverse-data/releases/tags/schedules"

TEAM_ALIASES = {
    "ARI": "ARI", "ATL": "ATL", "BAL": "BAL", "BUF": "BUF", "CAR": "CAR",
    "CHI": "CHI", "CIN": "CIN", "CLE": "CLE", "DAL": "DAL", "DEN": "DEN",
    "DET": "DET", "GB": "GB", "HOU": "HOU", "IND": "IND", "JAX": "JAX",
    "KC": "KC", "LA": "LAR", "LAR": "LAR", "LAC": "LAC", "LV": "LV",
    "MIA": "MIA", "MIN": "MIN", "NE": "NE", "NO": "NO", "NYG": "NYG",
    "NYJ": "NYJ", "PHI": "PHI", "PIT": "PIT", "SEA": "SEA", "SF": "SF",
    "TB": "TB", "TEN": "TEN", "WAS": "WAS", "WSH": "WAS",
}


def norm_team(x):
    if pd.isna(x):
        return np.nan
    x = str(x).strip().upper()
    return TEAM_ALIASES.get(x, x)


def parse_args():
    parser = argparse.ArgumentParser(description="Build game-level spread and total context for prepared props.")
    parser.add_argument("--input", type=Path, default=PROPS_PATH)
    parser.add_argument("--output", type=Path, default=OUT_PATH)
    return parser.parse_args()


def get_schedules_asset_url():
    req = urllib.request.Request(
        GITHUB_RELEASE_API,
        headers={"User-Agent": "player-props-context-script"},
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        release = json.loads(resp.read().decode("utf-8"))

    assets = release.get("assets", [])

    print("[github] schedule release assets:")
    for a in assets:
        print(f" - {a.get('name')}")

    preferred_exts = [".csv", ".csv.gz"]

    for ext in preferred_exts:
        for asset in assets:
            name = asset.get("name", "").lower()
            if name.endswith(ext):
                return asset["browser_download_url"]

    raise RuntimeError(
        "Could not find a CSV schedules asset in the nflverse release. "
        "Check printed assets above."
    )


def main():
    args = parse_args()
    if not args.input.exists():
        raise FileNotFoundError(f"Missing props file: {args.input}")

    props = pd.read_csv(args.input)
    props.columns = [c.strip() for c in props.columns]

    seasons = sorted(
        pd.to_numeric(props["season"], errors="coerce")
        .dropna()
        .astype(int)
        .unique()
    )

    print(f"[props] seasons needed: {seasons}")

    games_needed = (
        props[["season", "week", "game_date", "home_team_abbr", "away_team_abbr"]]
        .drop_duplicates()
        .copy()
    )

    games_needed["season"] = pd.to_numeric(games_needed["season"], errors="coerce").astype("Int64")
    games_needed["week"] = pd.to_numeric(games_needed["week"], errors="coerce").astype("Int64")
    games_needed["home_team_abbr"] = games_needed["home_team_abbr"].apply(norm_team)
    games_needed["away_team_abbr"] = games_needed["away_team_abbr"].apply(norm_team)

    print(f"[props] unique games needed: {len(games_needed):,}")

    schedules_url = get_schedules_asset_url()
    print(f"[fetch] {schedules_url}")

    sched = pd.read_csv(schedules_url, low_memory=False)
    sched.columns = [c.strip() for c in sched.columns]

    required = [
        "season",
        "week",
        "home_team",
        "away_team",
        "spread_line",
        "total_line",
    ]

    missing = [c for c in required if c not in sched.columns]
    if missing:
        raise ValueError(
            f"Schedules file missing expected columns: {missing}\n"
            f"Available: {list(sched.columns)}"
        )

    sched = sched[sched["season"].isin(seasons)].copy()

    sched["season"] = pd.to_numeric(sched["season"], errors="coerce").astype("Int64")
    sched["week"] = pd.to_numeric(sched["week"], errors="coerce").astype("Int64")
    sched["home_team_abbr"] = sched["home_team"].apply(norm_team)
    sched["away_team_abbr"] = sched["away_team"].apply(norm_team)

    sched["spread_line"] = pd.to_numeric(sched["spread_line"], errors="coerce")
    sched["game_total"] = pd.to_numeric(sched["total_line"], errors="coerce")

    # nflverse convention:
    # spread_line > 0 means home favored
    # spread_line < 0 means away favored
    #
    # Our convention:
    # negative = favorite
    # positive = underdog
    sched["home_spread"] = -sched["spread_line"]
    sched["away_spread"] = sched["spread_line"]

    ctx = sched[
        [
            "season",
            "week",
            "home_team_abbr",
            "away_team_abbr",
            "home_spread",
            "away_spread",
            "game_total",
            "spread_line",
            "total_line",
            "game_id",
            "gameday",
            "roof",
            "surface",
            "temp",
            "wind",
        ]
    ].drop_duplicates()

    existing_cols = [c for c in ctx.columns if c in sched.columns or c in [
        "season", "week", "home_team_abbr", "away_team_abbr",
        "home_spread", "away_spread", "game_total"
    ]]
    ctx = ctx[existing_cols]

    merged_check = games_needed.merge(
        ctx,
        on=["season", "week", "home_team_abbr", "away_team_abbr"],
        how="left",
        indicator=True,
    )

    matched = merged_check[merged_check["_merge"].eq("both")].copy()
    missing_games = merged_check[merged_check["_merge"].eq("left_only")].copy()

    print(f"[match] matched games: {len(matched):,}")
    print(f"[match] missing games: {len(missing_games):,}")

    if len(missing_games):
        miss_path = args.output.with_name(f"{args.output.stem}_missing_from_nflverse.csv")
        missing_games[
            ["season", "week", "game_date", "away_team_abbr", "home_team_abbr"]
        ].drop_duplicates().to_csv(miss_path, index=False)
        print(f"[warn] missing games saved to: {miss_path}")

    final = matched.drop(columns=["_merge"]).copy()

    base_cols = [
        "season",
        "week",
        "home_team_abbr",
        "away_team_abbr",
        "home_spread",
        "away_spread",
        "game_total",
    ]

    extra_cols = [c for c in final.columns if c not in games_needed.columns and c not in base_cols]
    final = final[base_cols + extra_cols].drop_duplicates()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    final.to_csv(args.output, index=False)

    print(f"[saved] {args.output}")
    print(f"[rows] {len(final):,}")
    print("\n[sample]")
    print(final.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
