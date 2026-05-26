from pathlib import Path
from io import StringIO
import sys
import time

import pandas as pd
import requests


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.name_utils import clean_player_name, clean_team


POSITIONS = ["rb", "wr", "te"]
SEASONS = [2021, 2022, 2023, 2024, 2025]
WEEKS = list(range(1, 19))

RAW_DIR = Path("data/raw/fantasypros/receiving_web")
OUT_FILE = Path("data/processed/fantasypros_receiving_weekly_projections.csv")

BASE_URL = "https://www.fantasypros.com/nfl/projections/{position}.php"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

SLEEP_SECONDS = 1.0

VALID_TEAMS = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAC", "JAX",
    "KC", "LAC", "LAR", "LV", "LVR", "MIA", "MIN", "NE",
    "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB",
    "TEN", "WAS", "WSH"
}


def build_url(position: str, season: int, week: int) -> str:
    return f"{BASE_URL.format(position=position)}?week={week}&year={season}&print=true"


def fetch_html(position: str, season: int, week: int, force: bool = False) -> str:
    source_dir = RAW_DIR / position
    source_dir.mkdir(parents=True, exist_ok=True)

    raw_file = source_dir / f"fantasypros_{position}_{season}_week_{week}.html"

    if raw_file.exists() and not force:
        return raw_file.read_text(encoding="utf-8")

    url = build_url(position, season, week)
    print(f"[request] {url}")

    r = requests.get(url, headers=HEADERS, timeout=30)
    print(f"[status] {r.status_code}")

    r.raise_for_status()

    html = r.text
    raw_file.write_text(html, encoding="utf-8")

    time.sleep(SLEEP_SECONDS)

    return html


def flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            "_".join([str(x) for x in col if str(x) != "nan"]).strip()
            for col in df.columns
        ]
    else:
        df.columns = [str(c).strip() for c in df.columns]

    return df


def parse_player_team(player_raw: str):
    parts = str(player_raw).strip().split()

    if len(parts) < 2:
        return str(player_raw).strip(), None

    last = parts[-1].upper()

    if last in VALID_TEAMS:
        team = last
        player = " ".join(parts[:-1])
        return player, team

    return str(player_raw).strip(), None


def find_projection_table(html: str):
    tables = pd.read_html(StringIO(html))

    for df in tables:
        df = flatten_columns(df)
        normalized_cols = [str(c).upper() for c in df.columns]

        has_player = any("PLAYER" in c for c in normalized_cols)
        has_fpts = any("FPTS" in c for c in normalized_cols)
        has_any_yds = any("YDS" in c for c in normalized_cols)
        has_any_rec = any("REC" in c for c in normalized_cols)

        if has_player and has_fpts and has_any_yds and has_any_rec:
            return df

    return None


def get_col(df: pd.DataFrame, candidates, required=True):
    upper_map = {str(c).upper(): c for c in df.columns}

    for candidate in candidates:
        candidate_upper = str(candidate).upper()
        if candidate_upper in upper_map:
            return upper_map[candidate_upper]

    for c in df.columns:
        cu = str(c).upper()
        for candidate in candidates:
            if str(candidate).upper() in cu:
                return c

    if required:
        return None
    return None


def find_stat_col(df: pd.DataFrame, positive_tokens, negative_tokens=None):
    matches = []
    for c in df.columns:
        cu = str(c).upper()
        if all(tok in cu for tok in positive_tokens):
            if negative_tokens and any(tok in cu for tok in negative_tokens):
                continue
            matches.append(c)

    if len(matches) == 1:
        return matches[0]
    return None


def parse_projection_table(html: str, season: int, week: int, position: str):
    df = find_projection_table(html)

    if df is None:
        print(f"[warn] no projection table found position={position} season={season} week={week}")
        return []

    player_col = get_col(df, ["PLAYER"])
    fpts_col = get_col(df, ["FPTS", "FPTS"], required=False)

    rec_col = get_col(df, ["RECEIVING_REC", "REC", "RECEPTIONS"], required=False)
    rec_yds_col = get_col(df, ["RECEIVING_YDS", "REC_YDS", "RECEIVING_YARDS"], required=False)
    if rec_yds_col is None:
        rec_yds_col = find_stat_col(df, ["YDS", "RECEIV"], negative_tokens=["RUSH", "RUSHING"])
        if rec_yds_col is None:
            rec_yds_col = find_stat_col(df, ["YDS", "REC"], negative_tokens=["RUSH", "RUSHING"])

    rec_tds_col = get_col(df, ["RECEIVING_TDS", "REC_TDS", "RECEIVING_TD"], required=False)
    if rec_tds_col is None:
        rec_tds_col = find_stat_col(df, ["TDS", "RECEIV"], negative_tokens=["RUSH", "RUSHING"])
        if rec_tds_col is None:
            rec_tds_col = find_stat_col(df, ["TDS", "REC"], negative_tokens=["RUSH", "RUSHING"])

    rush_att_col = get_col(df, ["RUSHING_ATT", "RUSH_ATT", "ATT"], required=False)
    rush_yds_col = get_col(df, ["RUSHING_YDS", "RUSH_YDS"], required=False)
    rush_tds_col = get_col(df, ["RUSHING_TDS", "RUSH_TDS"], required=False)

    if player_col is None or fpts_col is None or rec_yds_col is None:
        print(f"[warn] required cols missing position={position} season={season} week={week}")
        print(df.columns.tolist())
        return []

    rows = []
    for _, r in df.iterrows():
        player_raw = str(r[player_col]).strip()
        if not player_raw or player_raw.lower() == "nan" or player_raw.upper() == "PLAYER":
            continue

        player, team = parse_player_team(player_raw)

        rows.append({
            "season": season,
            "week": week,
            "source": "fantasypros_web",
            "position": position.upper(),
            "player": player,
            "player_raw": player_raw,
            "player_clean": clean_player_name(player),
            "team": clean_team(team),
            "fp_receptions": r.get(rec_col),
            "fp_receiving_yds": r.get(rec_yds_col),
            "fp_receiving_tds": r.get(rec_tds_col),
            "fp_rush_att": r.get(rush_att_col),
            "fp_rush_yds": r.get(rush_yds_col),
            "fp_rush_tds": r.get(rush_tds_col),
            "fp_fantasy_points": r.get(fpts_col),
        })

    return rows


def main(force: bool = False):
    all_rows = []

    for position in POSITIONS:
        for season in SEASONS:
            for week in WEEKS:
                html = fetch_html(position, season, week, force=force)
                rows = parse_projection_table(html, season, week, position)
                print(f"[parse] position={position} season={season} week={week} rows={len(rows):,}")
                all_rows.extend(rows)

    if not all_rows:
        raise RuntimeError("No FantasyPros receiving projection rows parsed.")

    df = pd.DataFrame(all_rows)

    numeric_cols = [
        "fp_receptions",
        "fp_receiving_yds",
        "fp_receiving_tds",
        "fp_rush_att",
        "fp_rush_yds",
        "fp_rush_tds",
        "fp_fantasy_points",
    ]

    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = (
        df.dropna(subset=["fp_receiving_yds"])
          .drop_duplicates(["season", "week", "position", "player_clean"])
          .sort_values(["season", "week", "position", "fp_fantasy_points"], ascending=[True, True, True, False])
    )

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_FILE, index=False)

    print("\n===== FANTASYPROS RECEIVING WEB INGEST COMPLETE =====")
    print(f"rows: {len(df):,}")
    print(f"output: {OUT_FILE}")

    print("\nRows by season:")
    print(df.groupby("season").size())

    print("\nRows by position:")
    print(df.groupby("position").size())

    print("\nSample:")
    print(df.head(20).to_string(index=False))


if __name__ == "__main__":
    main(force=False)
