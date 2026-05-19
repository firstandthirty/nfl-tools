from pathlib import Path
import sys
import re

import pandas as pd


# ------------------------------------------------------------
# Make project-root imports work when running:
# python scripts\01_build\ingest_ffa_projections.py
# ------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.name_utils import clean_player_name, clean_team


RAW_FFA_DIR = Path("data/raw/ffa")
OUT_DIR = Path("data/processed")
OUT_FILE = OUT_DIR / "ffa_weekly_projections.csv"

REQUIRED_COLS = [
    "player", "position", "team", "points", "sd_pts", "floor", "ceiling",
    "rank", "position_rank", "tier", "age", "adp", "aav",
    "uncertainty", "experience"
]


def parse_season_week(path: Path):
    """
    Expected filename examples:
      projections_2025_wk1.csv
      projections_2024_wk17.csv
    """
    m = re.search(r"projections_(\d{4})_wk(\d+)", path.stem.lower())
    if not m:
        return None, None

    return int(m.group(1)), int(m.group(2))


def ingest_ffa():
    print(f"[root] {PROJECT_ROOT}")
    print(f"[input] {RAW_FFA_DIR}")

    csv_files = sorted(RAW_FFA_DIR.glob("**/*.csv"))

    if not csv_files:
        raise FileNotFoundError(f"No CSV files found under {RAW_FFA_DIR}")

    frames = []

    for path in csv_files:
        season, week = parse_season_week(path)

        if season is None or week is None:
            print(f"[skip] could not parse season/week from {path}")
            continue

        df = pd.read_csv(path)
        df.columns = [c.strip() for c in df.columns]

        missing = [c for c in REQUIRED_COLS if c not in df.columns]
        if missing:
            print(f"[warn] {path} missing columns: {missing}")

        df["season"] = season
        df["week"] = week
        df["source"] = "ffa"
        df["file_name"] = path.name

        df["player_clean"] = df["player"].apply(clean_player_name)
        df["position"] = df["position"].astype(str).str.upper().str.strip()
        df["team"] = df["team"].apply(clean_team)

        frames.append(df)

        print(f"[load] {path} rows={len(df):,}")

    if not frames:
        raise RuntimeError("No valid FFA projection files ingested.")

    out = pd.concat(frames, ignore_index=True)

    front_cols = [
        "season", "week", "source", "player", "player_clean",
        "position", "team"
    ]

    remaining_cols = [c for c in out.columns if c not in front_cols]
    out = out[front_cols + remaining_cols]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_FILE, index=False)

    print("\n===== FFA INGEST COMPLETE =====")
    print(f"files loaded: {len(frames):,}")
    print(f"rows: {len(out):,}")
    print(f"output: {OUT_FILE}")

    print("\nRows by season:")
    print(out.groupby("season").size())

    print("\nRows by position:")
    print(out.groupby("position").size().sort_values(ascending=False))

    print("\nTeams:")
    print(sorted(out["team"].dropna().unique()))


if __name__ == "__main__":
    ingest_ffa()