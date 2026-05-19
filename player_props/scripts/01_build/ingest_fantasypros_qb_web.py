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


SEASONS = [2021, 2022, 2023, 2024, 2025]
WEEKS = list(range(1, 19))

RAW_DIR = Path("data/raw/fantasypros/qb_web")
OUT_FILE = Path("data/processed/fantasypros_qb_weekly_projections.csv")

BASE_URL = "https://www.fantasypros.com/nfl/projections/qb.php"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

SLEEP_SECONDS = 1.0


def build_url(season: int, week: int) -> str:
    return f"{BASE_URL}?week={week}&year={season}&print=true"


def fetch_html(season: int, week: int, force: bool = False) -> str:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    raw_file = RAW_DIR / f"fantasypros_qb_{season}_week_{week}.html"

    if raw_file.exists() and not force:
        return raw_file.read_text(encoding="utf-8")

    url = build_url(season, week)
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


VALID_TEAMS = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAC", "JAX",
    "KC", "LAC", "LAR", "LV", "LVR", "MIA", "MIN", "NE",
    "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB",
    "TEN", "WAS", "WSH"
}


def parse_player_team(player_raw: str):
    """
    FantasyPros print format appears to be:
      Patrick Mahomes II KC
      Kyler Murray MIN
      Tua Tagovailoa ATL

    Team is the LAST token when that token is a valid NFL team abbreviation.
    """
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
        has_yds = any("YDS" in c for c in normalized_cols)

        if has_player and has_fpts and has_yds:
            return df

    return None


def get_col(df: pd.DataFrame, candidates):
    upper_map = {str(c).upper(): c for c in df.columns}

    for candidate in candidates:
        candidate = candidate.upper()
        if candidate in upper_map:
            return upper_map[candidate]

    for c in df.columns:
        cu = str(c).upper()
        for candidate in candidates:
            if candidate.upper() in cu:
                return c

    return None


def parse_projection_table(html: str, season: int, week: int):
    df = find_projection_table(html)

    if df is None:
        print(f"[warn] no projection table found season={season} week={week}")
        return []

    player_col = get_col(df, ["Player"])
    fpts_col = get_col(df, ["FPTS"])

    # With multi-level headers, pandas usually creates names like:
    # PASSING_ATT, PASSING_CMP, PASSING_YDS, PASSING_TDS, PASSING_INTS
    pass_att_col = get_col(df, ["PASSING_ATT", "ATT"])
    pass_cmp_col = get_col(df, ["PASSING_CMP", "CMP"])
    pass_yds_col = get_col(df, ["PASSING_YDS", "YDS"])
    pass_tds_col = get_col(df, ["PASSING_TDS", "TDS"])
    pass_ints_col = get_col(df, ["PASSING_INTS", "INTS"])

    rush_att_col = get_col(df, ["RUSHING_ATT"])
    rush_yds_col = get_col(df, ["RUSHING_YDS"])
    rush_tds_col = get_col(df, ["RUSHING_TDS"])

    misc_fl_col = get_col(df, ["MISC_FL", "FL"])

    if player_col is None or pass_yds_col is None:
        print(f"[warn] required cols missing season={season} week={week}")
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
            "player": player,
            "player_raw": player_raw,
            "player_clean": clean_player_name(player),
            "team": clean_team(team),

            "fp_pass_att": r.get(pass_att_col),
            "fp_pass_cmp": r.get(pass_cmp_col),
            "fp_pass_yds": r.get(pass_yds_col),
            "fp_pass_tds": r.get(pass_tds_col),
            "fp_pass_ints": r.get(pass_ints_col),

            "fp_rush_att": r.get(rush_att_col),
            "fp_rush_yds": r.get(rush_yds_col),
            "fp_rush_tds": r.get(rush_tds_col),

            "fp_fumbles_lost": r.get(misc_fl_col),
            "fp_fantasy_points": r.get(fpts_col),
        })

    return rows


def main(force: bool = False):
    all_rows = []

    for season in SEASONS:
        for week in WEEKS:
            html = fetch_html(season, week, force=force)
            rows = parse_projection_table(html, season, week)

            print(f"[parse] season={season} week={week} rows={len(rows):,}")

            all_rows.extend(rows)

    if not all_rows:
        raise RuntimeError("No FantasyPros projection rows parsed.")

    df = pd.DataFrame(all_rows)

    numeric_cols = [
        "fp_pass_att",
        "fp_pass_cmp",
        "fp_pass_yds",
        "fp_pass_tds",
        "fp_pass_ints",
        "fp_rush_att",
        "fp_rush_yds",
        "fp_rush_tds",
        "fp_fumbles_lost",
        "fp_fantasy_points",
    ]

    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = (
        df.dropna(subset=["fp_pass_yds"])
        .drop_duplicates(["season", "week", "player_clean"])
        .sort_values(["season", "week", "fp_fantasy_points"], ascending=[True, True, False])
    )

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_FILE, index=False)

    print("\n===== FANTASYPROS QB WEB INGEST COMPLETE =====")
    print(f"rows: {len(df):,}")
    print(f"output: {OUT_FILE}")

    print("\nRows by season:")
    print(df.groupby("season").size())

    print("\nRows by week:")
    print(df.groupby("week").size())

    print("\nSample:")
    print(df.head(20).to_string(index=False))


if __name__ == "__main__":
    main(force=False)