from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv


BASE_URL = "https://api.fantasypros.com/public/v2/json/nfl/{season}/projections"

DEFAULT_SEASONS = [2021, 2022, 2023, 2024, 2025]
DEFAULT_WEEKS = list(range(1, 19))
DEFAULT_POSITIONS = ["QB", "RB", "WR", "TE"]

RAW_DIR = Path("data/raw/fantasypros/api_weekly_projections")
OUT_FILE = Path("data/processed/fantasypros_weekly_projections_api.csv")


def clean_player_name(value: Any) -> str:
    if pd.isna(value):
        return ""

    text = str(value).lower()
    text = text.replace(".", "")
    text = text.replace("'", "")
    text = text.replace("’", "")
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", text)
    text = re.sub(r"[^a-z0-9\s-]", " ", text)
    text = " ".join(text.split())
    return text.strip()


def get_api_key() -> str:
    load_dotenv()
    api_key = os.getenv("FANTASYPROS_API_KEY")

    if not api_key:
        raise RuntimeError(
            "Missing FANTASYPROS_API_KEY. Add it to .env or set it as an environment variable."
        )

    return api_key


def parse_int_list(value: str | None, default: list[int]) -> list[int]:
    if not value:
        return default

    out: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue

        if "-" in part:
            start, end = part.split("-", 1)
            out.extend(range(int(start), int(end) + 1))
        else:
            out.append(int(part))

    return sorted(set(out))


def parse_str_list(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return default

    return [x.strip().upper() for x in value.split(",") if x.strip()]


def stat(stats: dict[str, Any], key: str) -> float | None:
    value = stats.get(key)
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_projection_json(
    *,
    session: requests.Session,
    api_key: str,
    season: int,
    week: int,
    position: str,
    timeout: int,
    sleep_seconds: float,
    max_retries: int,
    force: bool,
) -> dict[str, Any] | None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    raw_path = RAW_DIR / f"fantasypros_{season}_week_{week:02d}_{position}.json"

    if raw_path.exists() and not force:
        try:
            return json.loads(raw_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"[warn] cached JSON invalid, refetching: {raw_path}")

    url = BASE_URL.format(season=season)
    headers = {"x-api-key": api_key}
    params = {
        "week": week,
        "position": position,
    }

    for attempt in range(1, max_retries + 1):
        print(f"[fetch] season={season} week={week} position={position} attempt={attempt}")

        r = session.get(url, headers=headers, params=params, timeout=timeout)

        if r.status_code == 200:
            try:
                data = r.json()
            except Exception:
                print(f"[warn] bad JSON season={season} week={week} position={position}")
                print(r.text[:500])
                return None

            # Guardrail: FantasyPros silently defaults to RB if position param is wrong.
            returned_position = str(data.get("positions", "")).upper()
            if returned_position != position.upper():
                print(
                    f"[warn] position mismatch season={season} week={week}: "
                    f"requested={position} returned={returned_position}. Skipping."
                )
                return None

            raw_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

            return data

        if r.status_code == 429:
            wait_seconds = sleep_seconds * attempt * 3
            wait_seconds = max(wait_seconds, 3.0)
            print(
                f"[rate-limit] 429 season={season} week={week} position={position}. "
                f"Sleeping {wait_seconds:.1f}s..."
            )
            time.sleep(wait_seconds)
            continue

        print(
            f"[warn] status={r.status_code} season={season} week={week} position={position}"
        )
        print(r.text[:500])

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

        return None

    print(f"[error] failed after retries season={season} week={week} position={position}")
    return None


def flatten_projection_response(data: dict[str, Any]) -> list[dict[str, Any]]:
    season = int(data.get("season"))
    week = int(data.get("week"))
    returned_position = str(data.get("positions", "")).upper()
    scoring = data.get("scoring")

    rows: list[dict[str, Any]] = []

    for p in data.get("players", []):
        stats = p.get("stats") or {}

        player = p.get("name")
        position = str(p.get("position_id") or returned_position).upper()

        row = {
            "season": season,
            "week": week,
            "source": "fantasypros_api",
            "scoring": scoring,
            "position": position,
            "player": player,
            "player_clean": clean_player_name(player),
            "team": p.get("team_id"),
            "fpid": p.get("fpid"),
            "mflid": p.get("mflid"),
            "filename": p.get("filename"),

            # Fantasy points
            "fp_points_std": stat(stats, "points"),
            "fp_points_half": stat(stats, "points_half"),
            "fp_points_ppr": stat(stats, "points_ppr"),

            # Receiving
            "fp_receptions": stat(stats, "rec_rec"),
            "fp_receiving_yds": stat(stats, "rec_yds"),
            "fp_receiving_tds": stat(stats, "rec_tds"),

            # Rushing
            "fp_rush_att": stat(stats, "rush_att"),
            "fp_rush_yds": stat(stats, "rush_yds"),
            "fp_rush_tds": stat(stats, "rush_tds"),

            # Passing
            "fp_pass_att": stat(stats, "pass_att"),
            "fp_pass_cmp": stat(stats, "pass_cmp"),
            "fp_pass_yds": stat(stats, "pass_yds"),
            "fp_pass_tds": stat(stats, "pass_tds"),
            "fp_pass_int": stat(stats, "pass_int"),

            # Misc
            "fp_fumbles": stat(stats, "fumbles"),
            "fp_ret_tds": stat(stats, "ret_tds"),
            "fp_2pt_tds": stat(stats, "2pt_tds"),
        }

        rows.append(row)

    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--seasons",
        default=None,
        help="Comma/range list, e.g. 2021-2025 or 2024,2025. Default: 2021-2025.",
    )
    parser.add_argument(
        "--weeks",
        default=None,
        help="Comma/range list, e.g. 1-18 or 1,2,3. Default: 1-18.",
    )
    parser.add_argument(
        "--positions",
        default=None,
        help="Comma list. Default: QB,RB,WR,TE.",
    )
    parser.add_argument(
        "--output",
        default=str(OUT_FILE),
        help="Output CSV path.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.0,
        help="Seconds to sleep after successful requests.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=5,
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refetch even if cached raw JSON exists.",
    )
    args = parser.parse_args()

    api_key = get_api_key()

    seasons = parse_int_list(args.seasons, DEFAULT_SEASONS)
    weeks = parse_int_list(args.weeks, DEFAULT_WEEKS)
    positions = parse_str_list(args.positions, DEFAULT_POSITIONS)

    print("===== FANTASYPROS WEEKLY PROJECTIONS API INGEST =====")
    print(f"seasons={seasons}")
    print(f"weeks={weeks}")
    print(f"positions={positions}")
    print(f"output={args.output}")

    session = requests.Session()

    all_rows: list[dict[str, Any]] = []

    total_requests = len(seasons) * len(weeks) * len(positions)
    request_num = 0

    for season in seasons:
        for week in weeks:
            for position in positions:
                request_num += 1
                print(f"\n[{request_num}/{total_requests}] season={season} week={week} position={position}")

                data = fetch_projection_json(
                    session=session,
                    api_key=api_key,
                    season=season,
                    week=week,
                    position=position,
                    timeout=args.timeout,
                    sleep_seconds=args.sleep,
                    max_retries=args.max_retries,
                    force=args.force,
                )

                if not data:
                    continue

                rows = flatten_projection_response(data)
                print(f"[rows] {len(rows):,}")
                all_rows.extend(rows)

    if not all_rows:
        raise RuntimeError("No rows loaded from FantasyPros API.")

    df = pd.DataFrame(all_rows)

    numeric_cols = [c for c in df.columns if c.startswith("fp_")]
    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.drop_duplicates(
        subset=["season", "week", "position", "player_clean"],
        keep="last",
    )

    df = df.sort_values(
        ["season", "week", "position", "fp_points_ppr", "player_clean"],
        ascending=[True, True, True, False, True],
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)

    print("\n===== COMPLETE =====")
    print(f"rows={len(df):,}")
    print(f"output={output_path}")

    print("\nRows by season:")
    print(df.groupby("season").size().to_string())

    print("\nRows by position:")
    print(df.groupby("position").size().to_string())

    print("\nSample:")
    sample_cols = [
        "season",
        "week",
        "position",
        "player",
        "team",
        "fp_receptions",
        "fp_receiving_yds",
        "fp_rush_yds",
        "fp_pass_yds",
        "fp_points_ppr",
    ]
    print(df[[c for c in sample_cols if c in df.columns]].head(20).to_string(index=False))


if __name__ == "__main__":
    main()