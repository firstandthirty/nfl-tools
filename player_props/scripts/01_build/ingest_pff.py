from pathlib import Path
import pandas as pd


BASE_DIR = Path(r"C:\Users\brady\OneDrive\Desktop\nfl-tools\player props")
RAW_PFF_DIR = BASE_DIR / "data" / "raw" / "pff"
PROCESSED_DIR = BASE_DIR / "data" / "processed" / "pff"

SEASONS = range(2021, 2026)
WEEKS = range(1, 23)

FILES = {
    "passing": "passing_summary.csv",
    "receiving": "receiving_summary.csv",
    "rushing": "rushing_summary.csv",
}


RENAME_MAPS = {
    "passing": {
        "attempts": "pass_attempts",
        "yards": "passing_yards",
        "touchdowns": "passing_tds",
        "interceptions": "passing_ints",
        "first_downs": "passing_first_downs",
        "longest": "passing_longest",
        "grades_offense": "passing_grade_offense",
        "grades_pass": "passing_grade_pass",
        "grades_run": "passing_grade_run",
        "ypa": "passing_ypa",
        "scrambles": "passing_scrambles",
        "fumbles": "passing_fumbles",
        "avg_depth_of_target": "passing_adot",
    },

    "receiving": {
        "yards": "receiving_yards",
        "touchdowns": "receiving_tds",
        "first_downs": "receiving_first_downs",
        "longest": "receiving_longest",
        "grades_offense": "receiving_grade_offense",
        "grades_pass_route": "receiving_grade_route",
        "grades_pass_block": "receiving_grade_pass_block",
        "avg_depth_of_target": "receiving_adot",
        "fumbles": "receiving_fumbles",
    },

    "rushing": {
        "attempts": "rush_attempts",
        "yards": "rushing_yards",
        "touchdowns": "rushing_tds",
        "first_downs": "rushing_first_downs",
        "longest": "rushing_longest",
        "grades_offense": "rushing_grade_offense",
        "grades_run": "rushing_grade_run",
        "grades_pass": "rushing_grade_pass",
        "grades_pass_block": "rushing_grade_pass_block",
        "grades_pass_route": "rushing_grade_pass_route",
        "ypa": "rushing_ypa",
        "fumbles": "rushing_fumbles",
        "scrambles": "rushing_scrambles",
    },
}


def clean_col(col: str) -> str:
    return (
        col.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("%", "percent")
    )


def read_pff_file(stat_type: str, season: int, week: int) -> pd.DataFrame | None:
    path = RAW_PFF_DIR / str(season) / f"week_{week:02d}" / FILES[stat_type]

    if not path.exists():
        print(f"[missing] {stat_type}: {season} week_{week:02d} | {path}")
        return None

    try:
        df = pd.read_csv(path)
    except Exception as e:
        print(f"[error] could not read {path}: {e}")
        return None

    if df.empty:
        print(f"[empty] {stat_type}: {season} week_{week:02d}")
        return None

    df.columns = [clean_col(c) for c in df.columns]

    df["season"] = season
    df["week"] = week
    df["is_playoffs"] = week >= 19
    df["stat_type"] = stat_type
    df["source"] = "pff"

    df = df.rename(columns=RENAME_MAPS.get(stat_type, {}))

    # Keep IDs as strings to avoid weird numeric issues later.
    if "player_id" in df.columns:
        df["player_id"] = df["player_id"].astype(str)

    if "player" in df.columns:
        df["player"] = df["player"].astype(str).str.strip()

    if "team_name" in df.columns:
        df["team_name"] = df["team_name"].astype(str).str.strip()

    if "position" in df.columns:
        df["position"] = df["position"].astype(str).str.strip()

    return df


def ingest_stat_type(stat_type: str) -> pd.DataFrame:
    frames = []

    for season in SEASONS:
        for week in WEEKS:
            df = read_pff_file(stat_type, season, week)
            if df is not None:
                frames.append(df)

    if not frames:
        raise RuntimeError(f"No files loaded for stat_type={stat_type}")

    combined = pd.concat(frames, ignore_index=True)

    # Put metadata columns first if present.
    front_cols = [
        "season",
        "week",
        "is_playoffs",
        "stat_type",
        "source",
        "player",
        "player_id",
        "position",
        "team_name",
        "franchise_id",
        "player_game_count",
    ]

    front_cols = [c for c in front_cols if c in combined.columns]
    other_cols = [c for c in combined.columns if c not in front_cols]
    combined = combined[front_cols + other_cols]

    return combined


def build_master(passing: pd.DataFrame, receiving: pd.DataFrame, rushing: pd.DataFrame) -> pd.DataFrame:
    key_cols = ["season", "week", "is_playoffs", "player", "player_id", "position", "team_name"]

    passing_cols = [c for c in passing.columns if c not in ["stat_type", "source"]]
    receiving_cols = [c for c in receiving.columns if c not in ["stat_type", "source"]]
    rushing_cols = [c for c in rushing.columns if c not in ["stat_type", "source"]]

    passing_small = passing[passing_cols].copy()
    receiving_small = receiving[receiving_cols].copy()
    rushing_small = rushing[rushing_cols].copy()

    master = passing_small.merge(
        receiving_small,
        on=key_cols,
        how="outer",
        suffixes=("", "_receiving_dup"),
    )

    master = master.merge(
        rushing_small,
        on=key_cols,
        how="outer",
        suffixes=("", "_rushing_dup"),
    )

    # Drop duplicate merge artifacts where possible.
    dup_cols = [c for c in master.columns if c.endswith("_receiving_dup") or c.endswith("_rushing_dup")]
    if dup_cols:
        master = master.drop(columns=dup_cols)

    master = master.sort_values(["season", "week", "team_name", "player"]).reset_index(drop=True)

    return master


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[start] reading raw PFF files from: {RAW_PFF_DIR}")

    passing = ingest_stat_type("passing")
    receiving = ingest_stat_type("receiving")
    rushing = ingest_stat_type("rushing")

    passing_out = PROCESSED_DIR / "pff_passing_weekly.csv"
    receiving_out = PROCESSED_DIR / "pff_receiving_weekly.csv"
    rushing_out = PROCESSED_DIR / "pff_rushing_weekly.csv"
    master_out = PROCESSED_DIR / "pff_player_weekly_master.csv"

    passing.to_csv(passing_out, index=False)
    receiving.to_csv(receiving_out, index=False)
    rushing.to_csv(rushing_out, index=False)

    print(f"[saved] {passing_out} rows={len(passing):,}")
    print(f"[saved] {receiving_out} rows={len(receiving):,}")
    print(f"[saved] {rushing_out} rows={len(rushing):,}")

    master = build_master(passing, receiving, rushing)
    master.to_csv(master_out, index=False)

    print(f"[saved] {master_out} rows={len(master):,}")
    print("[done]")


if __name__ == "__main__":
    main()