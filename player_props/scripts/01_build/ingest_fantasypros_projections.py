from pathlib import Path
import sys
import os
import time
import json

import pandas as pd
import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.name_utils import clean_player_name, clean_team


load_dotenv()

API_KEY = os.getenv("FANTASYPROS_API_KEY")

BASE_URL = "https://api.fantasypros.com/public/v2/json/nfl/{season}/projections"

RAW_OUT_DIR = Path("data/raw/fantasypros/projections")
PROCESSED_OUT = Path("data/processed/fantasypros_qb_weekly_projections.csv")

SEASONS = [2021, 2022, 2023, 2024, 2025]
WEEKS = list(range(1, 19))

POSITION = "QB"
REQUEST_SLEEP_SECONDS = 1.15


def fetch_projection_json(season: int, week: int, force: bool = False):
    RAW_OUT_DIR.mkdir(parents=True, exist_ok=True)

    raw_file = RAW_OUT_DIR / f"fantasypros_nfl_{season}_week_{week}_{POSITION}.json"

    if raw_file.exists() and not force:
        print(f"[cache] {raw_file}")
        with open(raw_file, "r", encoding="utf-8") as f:
            return json.load(f)

    if not API_KEY:
        raise RuntimeError("FANTASYPROS_API_KEY not found. Check your .env file.")

    url = BASE_URL.format(season=season)

    params = {
        "week": week,
        "position": POSITION,
    }

    headers = {
        "x-api-key": API_KEY,
    }

    print(f"[request] season={season} week={week} position={POSITION}")

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=30,
    )

    print(f"[status] {response.status_code}")

    if response.status_code != 200:
        print(response.text[:1000])
        response.raise_for_status()

    data = response.json()

    with open(raw_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    time.sleep(REQUEST_SLEEP_SECONDS)

    return data


def flatten_projection_response(data: dict, season: int, week: int):
    """
    FantasyPros response shape may vary slightly.
    This tries common containers and keeps all fields so we can inspect them.
    """

    candidates = []

    if isinstance(data, dict):
        for key in ["players", "projections", "data", "results"]:
            value = data.get(key)
            if isinstance(value, list):
                candidates = value
                break

        if not candidates:
            for value in data.values():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    candidates = value
                    break

    elif isinstance(data, list):
        candidates = data

    rows = []

    for item in candidates:
        if not isinstance(item, dict):
            continue

        row = dict(item)
        row["season"] = season
        row["week"] = week
        row["source"] = "fantasypros"
        row["position_requested"] = POSITION
        rows.append(row)

    return rows


def main(test_mode: bool = True, force: bool = False):
    """
    test_mode=True only requests 2025 week 1.
    Once API works, change test_mode=False.
    """

    runs = [(2025, 1)] if test_mode else [
        (season, week)
        for season in SEASONS
        for week in WEEKS
    ]

    all_rows = []

    for season, week in runs:
        data = fetch_projection_json(season, week, force=force)
        rows = flatten_projection_response(data, season, week)

        print(f"[flatten] season={season} week={week} rows={len(rows):,}")

        all_rows.extend(rows)

    if not all_rows:
        print("[warn] no rows flattened")
        return

    df = pd.DataFrame(all_rows)

    # Best-effort standardized columns
    possible_player_cols = [
        "player",
        "player_name",
        "name",
        "full_name",
    ]

    player_col = next((c for c in possible_player_cols if c in df.columns), None)

    if player_col:
        df["player_clean"] = df[player_col].apply(clean_player_name)

    possible_team_cols = [
        "team",
        "team_abbr",
        "team_code",
    ]

    team_col = next((c for c in possible_team_cols if c in df.columns), None)

    if team_col:
        df["team_clean"] = df[team_col].apply(clean_team)

    PROCESSED_OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(PROCESSED_OUT, index=False)

    print("\n===== FANTASYPROS INGEST COMPLETE =====")
    print(f"rows: {len(df):,}")
    print(f"cols: {len(df.columns):,}")
    print(f"output: {PROCESSED_OUT}")

    print("\nColumns:")
    print(df.columns.tolist())

    print("\nSample:")
    print(df.head(10).to_string(index=False))


if __name__ == "__main__":
    main(test_mode=True, force=False)