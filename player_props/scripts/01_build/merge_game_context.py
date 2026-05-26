from pathlib import Path
import argparse
import pandas as pd
import numpy as np

PROPS_PATH = Path("data/historical_props/merged_props_actuals.csv")

# Put your game-level odds/context file here.
# Required columns are flexible; see normalize_game_context().
CONTEXT_PATHS = [
    Path("data/historical_props/game_context.csv"),
    Path("data/historical_props/game_odds.csv"),
    Path("data/historical_props/spreads_totals.csv"),
]

OUT_PATH = Path("data/historical_props/merged_props_with_context.csv")
TEMPLATE_PATH = Path("data/historical_props/game_context_TEMPLATE.csv")


TEAM_ALIASES = {
    "ARI": "ARI", "ARZ": "ARI", "ATL": "ATL", "BAL": "BAL", "BLT": "BAL", "BUF": "BUF", "CAR": "CAR",
    "CHI": "CHI", "CIN": "CIN", "CLE": "CLE", "CLV": "CLE", "DAL": "DAL", "DEN": "DEN",
    "DET": "DET", "GB": "GB", "HOU": "HOU", "HST": "HOU", "IND": "IND", "JAX": "JAX",
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
    parser = argparse.ArgumentParser(description="Attach game-level context to historical prop actuals.")
    parser.add_argument("--input", type=Path, default=PROPS_PATH)
    parser.add_argument("--context", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=OUT_PATH)
    parser.add_argument("--projections", type=Path, default=None, help="Optional projections file used for join QA only.")
    return parser.parse_args()


def find_context_file(explicit_path=None):
    if explicit_path is not None:
        return explicit_path if explicit_path.exists() else None
    for p in CONTEXT_PATHS:
        if p.exists():
            return p
    return None


def create_template_from_props(props):
    cols = [
        "season",
        "week",
        "game_date",
        "home_team_abbr",
        "away_team_abbr",
        "home_spread",
        "away_spread",
        "game_total",
    ]

    games = (
        props[["season", "week", "game_date", "home_team_abbr", "away_team_abbr"]]
        .drop_duplicates()
        .sort_values(["season", "week", "game_date", "away_team_abbr", "home_team_abbr"])
    )

    games["home_spread"] = ""
    games["away_spread"] = ""
    games["game_total"] = ""

    TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    games[cols].to_csv(TEMPLATE_PATH, index=False)

    raise FileNotFoundError(
        "\nNo game context file found.\n\n"
        f"I created a template here:\n  {TEMPLATE_PATH}\n\n"
        "Fill in home_spread, away_spread, and game_total, then rename/copy it to:\n"
        "  data/historical_props/game_context.csv\n\n"
        "Important convention:\n"
        "  Negative spread = favorite\n"
        "  Positive spread = underdog\n\n"
        "Example:\n"
        "  Bills -7 at Patriots\n"
        "  If Bills are away: away_spread = -7, home_spread = 7\n"
    )


def normalize_game_context(ctx):
    ctx = ctx.copy()
    ctx.columns = [c.strip() for c in ctx.columns]

    rename_map = {
        "home_team": "home_team_abbr",
        "away_team": "away_team_abbr",
        "home_abbr": "home_team_abbr",
        "away_abbr": "away_team_abbr",
        "total": "game_total",
        "closing_total": "game_total",
        "over_under": "game_total",
        "home_closing_spread": "home_spread",
        "away_closing_spread": "away_spread",
        "home_line": "home_spread",
        "away_line": "away_spread",
    }

    ctx = ctx.rename(columns={k: v for k, v in rename_map.items() if k in ctx.columns})

    required = ["season", "week", "home_team_abbr", "away_team_abbr", "game_total"]
    missing = [c for c in required if c not in ctx.columns]
    if missing:
        raise ValueError(
            f"Game context file missing required columns: {missing}\n"
            f"Available columns: {list(ctx.columns)}"
        )

    # Need either both spreads or one spread.
    if "home_spread" not in ctx.columns and "away_spread" not in ctx.columns:
        raise ValueError(
            "Game context file needs home_spread and/or away_spread.\n"
            "Negative spread = favorite, positive = underdog."
        )

    if "home_spread" not in ctx.columns:
        ctx["home_spread"] = -pd.to_numeric(ctx["away_spread"], errors="coerce")

    if "away_spread" not in ctx.columns:
        ctx["away_spread"] = -pd.to_numeric(ctx["home_spread"], errors="coerce")

    for c in ["season", "week"]:
        ctx[c] = pd.to_numeric(ctx[c], errors="coerce").astype("Int64")

    ctx["home_team_abbr"] = ctx["home_team_abbr"].apply(norm_team)
    ctx["away_team_abbr"] = ctx["away_team_abbr"].apply(norm_team)

    ctx["home_spread"] = pd.to_numeric(ctx["home_spread"], errors="coerce")
    ctx["away_spread"] = pd.to_numeric(ctx["away_spread"], errors="coerce")
    ctx["game_total"] = pd.to_numeric(ctx["game_total"], errors="coerce")

    # Sanity check: spreads should be opposites.
    bad_spread = ctx[
        ctx["home_spread"].notna()
        & ctx["away_spread"].notna()
        & ((ctx["home_spread"] + ctx["away_spread"]).abs() > 0.01)
    ]

    if len(bad_spread):
        print("[warn] Some home/away spreads are not exact opposites.")
        print(bad_spread.head(10).to_string(index=False))

    keep = [
        "season",
        "week",
        "home_team_abbr",
        "away_team_abbr",
        "home_spread",
        "away_spread",
        "game_total",
    ]

    return ctx[keep].drop_duplicates()


def add_team_context(df):
    df = df.copy()

    df["is_home"] = df["recent_team"] == df["home_team_abbr"]
    df["is_away"] = df["recent_team"] == df["away_team_abbr"]

    df["team_spread"] = np.where(
        df["is_home"],
        df["home_spread"],
        np.where(df["is_away"], df["away_spread"], np.nan),
    )

    df["opponent_spread"] = -df["team_spread"]

    df["is_favorite"] = df["team_spread"] < 0
    df["is_underdog"] = df["team_spread"] > 0
    df["is_pickem"] = df["team_spread"] == 0

    # Implied team total:
    # favorite -7 in a 44 total gets: 44/2 - (-7/2) = 25.5
    # underdog +7 gets: 44/2 - (7/2) = 18.5
    df["team_total"] = (df["game_total"] / 2) - (df["team_spread"] / 2)

    return df


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


def print_projection_qa(merged, projections_path):
    if projections_path is None:
        print("[projection QA] not requested; provide --projections to check projection coverage.")
        return
    if not projections_path.exists():
        print(f"[projection QA] missing projections file: {projections_path}")
        return

    projections = pd.read_csv(projections_path, low_memory=False)
    player_col = "player" if "player" in projections.columns else "player_clean"
    required = {"season", "week", player_col, "fp_receiving_yds"}
    missing = required.difference(projections.columns)
    if missing:
        print(f"[projection QA] skipped; missing columns: {sorted(missing)}")
        return

    candidate = merged.copy()
    candidate["player_norm"] = normalize_name(candidate["player"])
    projections["player_norm"] = normalize_name(projections[player_col])
    projection_cols = ["season", "week", "player_norm", "fp_receiving_yds"]
    if "team" in projections.columns:
        projections["projection_team"] = projections["team"].apply(norm_team)
        projection_cols.append("projection_team")
    projections = projections[projection_cols].drop_duplicates(
        ["season", "week", "player_norm"]
    )
    checked = candidate.merge(projections, on=["season", "week", "player_norm"], how="left")
    missing_projection = checked["fp_receiving_yds"].isna().sum()
    print(f"[projection QA] rows={len(checked):,} matched={len(checked) - missing_projection:,} missing={missing_projection:,}")
    if "projection_team" in checked.columns and "recent_team" in checked.columns:
        compared = checked.loc[
            checked["fp_receiving_yds"].notna()
            & checked["recent_team"].notna()
            & checked["projection_team"].notna()
        ].copy()
        mismatch = compared["recent_team"].ne(compared["projection_team"])
        print(f"[projection QA] matched rows with team mismatch={mismatch.sum():,} of {len(compared):,} comparable rows")


def main():
    args = parse_args()
    if not args.input.exists():
        raise FileNotFoundError(f"Missing props file: {args.input}")

    props = pd.read_csv(args.input)
    props.columns = [c.strip() for c in props.columns]

    for c in ["season", "week"]:
        props[c] = pd.to_numeric(props[c], errors="coerce").astype("Int64")

    props["home_team_abbr"] = props["home_team_abbr"].apply(norm_team)
    props["away_team_abbr"] = props["away_team_abbr"].apply(norm_team)
    props["recent_team"] = props["recent_team"].apply(norm_team)

    context_path = find_context_file(args.context)

    if context_path is None:
        if args.context is not None:
            raise FileNotFoundError(f"Missing game context file: {args.context}")
        create_template_from_props(props)

    print(f"[load] props: {args.input} rows={len(props):,}")
    print(f"[load] context: {context_path}")

    ctx = pd.read_csv(context_path)
    ctx = normalize_game_context(ctx)

    before = len(props)

    merged = props.merge(
        ctx,
        on=["season", "week", "home_team_abbr", "away_team_abbr"],
        how="left",
        validate="many_to_one",
    )

    merged = add_team_context(merged)

    matched = merged["game_total"].notna().sum()
    missing = before - matched

    print(f"[merge] rows={before:,}")
    print(f"[merge] matched context={matched:,}")
    print(f"[merge] missing context={missing:,}")
    print(f"[team context QA] missing team_spread={merged['team_spread'].isna().sum():,}")
    print("\n===== Rows by Season / Week / Market =====")
    print(merged.groupby(["season", "week", "market_key"]).size().rename("rows").reset_index().to_string(index=False))
    print("\n===== Unique Games by Week =====")
    print(merged.groupby(["season", "week"])["event_id"].nunique().rename("unique_games").reset_index().to_string(index=False))
    duplicate_cols = ["season", "week", "event_id", "market_key", "player", "line"]
    print(f"[duplicate QA] duplicate player/game/market/line rows={merged.duplicated(duplicate_cols, keep=False).sum():,}")
    print_projection_qa(merged, args.projections)

    if missing:
        missing_games = (
            merged[merged["game_total"].isna()]
            [["season", "week", "game_date", "away_team_abbr", "home_team_abbr"]]
            .drop_duplicates()
            .sort_values(["season", "week", "away_team_abbr", "home_team_abbr"])
        )

        miss_path = args.output.with_name(f"{args.output.stem}_missing_game_context.csv")
        missing_games.to_csv(miss_path, index=False)
        print(f"[warn] missing games saved to: {miss_path}")

    bad_team_match = merged[
        merged["recent_team"].notna()
        & ~merged["is_home"]
        & ~merged["is_away"]
    ]

    if len(bad_team_match):
        bad_path = args.output.with_name(f"{args.output.stem}_bad_recent_team_matches.csv")
        (
            bad_team_match[
                [
                    "season",
                    "week",
                    "player",
                    "recent_team",
                    "home_team_abbr",
                    "away_team_abbr",
                ]
            ]
            .drop_duplicates()
            .to_csv(bad_path, index=False)
        )
        print(f"[warn] player team did not match home/away for {len(bad_team_match):,} rows")
        print(f"[warn] saved to: {bad_path}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(args.output, index=False)

    print(f"[saved] {args.output}")

    print("\n[columns added]")
    for c in [
        "home_spread",
        "away_spread",
        "game_total",
        "team_spread",
        "opponent_spread",
        "team_total",
        "is_home",
        "is_favorite",
        "is_underdog",
        "is_pickem",
    ]:
        print(f" - {c}")


if __name__ == "__main__":
    main()
