from pathlib import Path
import pandas as pd

ROOT_DIR = Path("data")
ODDS_FILE = ROOT_DIR / "processed" / "fanduel_pass_yds_history.csv"
OUTPUT_DIR = ROOT_DIR / "analysis"
AUDIT_CSV = OUTPUT_DIR / "actuals_source_audit.csv"

ACTUAL_COL_CANDIDATES = [
    "actual_passing_yards",
    "actual_pass_yds",
    "actual_value",
    "actual",
    "passing_yards",
    "pass_yds",
    "yards",
]
PLAYER_COL_CANDIDATES = [
    "player",
    "player_name",
    "description",
    "player_display_name",
    "player_clean",
    "player_fp",
    "player_ffa",
]
EVENT_ID_COL_CANDIDATES = ["event_id"]
SEASON_COL_CANDIDATES = ["season"]
WEEK_COL_CANDIDATES = ["week"]
GAME_DATE_COL_CANDIDATES = ["game_date", "commence_time"]
TEAM_COL_CANDIDATES = ["team", "recent_team", "home_team_abbr", "away_team_abbr"]

CANDIDATE_DIRS = [ROOT_DIR / "processed", ROOT_DIR / "historical_props", ROOT_DIR / "raw" / "pff"]
RAW_PFF_AGGREGATED_PATH = ROOT_DIR / "raw" / "pff" / "passing_summary_aggregated.csv"

SUPPORTED_SUFFIXES = {".csv", ".parquet"}


def normalize_text(value):
    if pd.isna(value):
        return ""
    text = str(value)
    text = text.replace(".", "")
    text = " ".join(text.split())
    return text.strip().lower()


def find_best_col(df, candidates):
    for col in candidates:
        if col in df.columns:
            return col
    lower_map = {c.lower(): c for c in df.columns}
    for col in candidates:
        if col.lower() in lower_map:
            return lower_map[col.lower()]
    return None


def find_actual_col(df):
    return find_best_col(df, ACTUAL_COL_CANDIDATES)


def load_dataframe(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    raise RuntimeError(f"Unsupported file type: {path}")


def prepare_join_keys(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    if "event_id" in df.columns:
        df["event_id_str"] = df["event_id"].astype(str).str.strip()
    if "player_norm" in df.columns:
        df["player_norm"] = df["player_norm"].apply(normalize_text)
    else:
        player_col = find_best_col(df, PLAYER_COL_CANDIDATES)
        if player_col is not None:
            df["player_norm"] = df[player_col].apply(normalize_text)
    if "season" in df.columns:
        df["season_str"] = df["season"].astype(str).str.strip()
    if "week" in df.columns:
        df["week_str"] = df["week"].astype(str).str.strip()
    if "game_date" in df.columns:
        df["game_date_str"] = pd.to_datetime(df["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if "commence_time" in df.columns and "game_date_str" not in df.columns:
        df["game_date_str"] = pd.to_datetime(df["commence_time"], errors="coerce").dt.strftime("%Y-%m-%d")
    return df


def build_odds_frame() -> pd.DataFrame:
    if not ODDS_FILE.exists():
        raise FileNotFoundError(f"Odds input file not found: {ODDS_FILE}")

    df = pd.read_csv(ODDS_FILE)
    if "event_id" not in df.columns or "player" not in df.columns:
        raise RuntimeError("Odds file must include event_id and player columns.")

    df["event_id_str"] = df["event_id"].astype(str).str.strip()
    df["player_norm"] = df["player"].apply(normalize_text)
    if "season_guess" in df.columns:
        df["season_str"] = df["season_guess"].astype(str).str.strip()
    if "week_guess" in df.columns:
        df["week_str"] = df["week_guess"].astype(str).str.strip()
    if "game_date" in df.columns:
        df["game_date_str"] = pd.to_datetime(df["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if "commence_time" in df.columns and "game_date_str" not in df.columns:
        df["game_date_str"] = pd.to_datetime(df["commence_time"], errors="coerce").dt.strftime("%Y-%m-%d")
    return df


def join_statistics(odds_df: pd.DataFrame, candidate_df: pd.DataFrame, candidate_path: Path) -> dict:
    candidate_df = candidate_df.copy()
    candidate_df = prepare_join_keys(candidate_df, str(candidate_path))

    actual_col = find_actual_col(candidate_df)
    event_id_col = find_best_col(candidate_df, EVENT_ID_COL_CANDIDATES)
    player_col = find_best_col(candidate_df, PLAYER_COL_CANDIDATES)
    player_norm_present = "player_norm" in candidate_df.columns and candidate_df["player_norm"].notna().any()
    season_present = "season_str" in candidate_df.columns and candidate_df["season_str"].notna().any()
    week_present = "week_str" in candidate_df.columns and candidate_df["week_str"].notna().any()
    game_date_present = "game_date_str" in candidate_df.columns and candidate_df["game_date_str"].notna().any()

    result = {
        "candidate_path": str(candidate_path),
        "candidate_rows": len(candidate_df),
        "actual_col": actual_col or "<missing>",
        "has_event_id": bool(event_id_col),
        "has_player_col": bool(player_col),
        "has_player_norm": bool(player_norm_present),
        "has_season": bool(season_present),
        "has_week": bool(week_present),
        "has_game_date": bool(game_date_present),
    }

    if actual_col is None:
        result.update(
            {
                "best_join_method": "no_actual",
                "matched_odds_rows": 0,
                "match_rate": 0.0,
                "note": "no actual column",
            }
        )
        return result

    odds = odds_df.copy()
    candidate_df["actual_nonnull"] = candidate_df[actual_col].notna().astype(int)
    sort_cols = [c for c in ["event_id_str", "player_norm", "actual_nonnull"] if c in candidate_df.columns]
    if sort_cols:
        ascending = [True] * (len(sort_cols) - 1) + [False]
        candidate_df = candidate_df.sort_values(sort_cols, ascending=ascending)

    join_options = []
    if event_id_col and player_norm_present:
        join_options.append(("event_id+player_norm", ["event_id_str", "player_norm"]))
    if season_present and week_present and player_norm_present:
        join_options.append(("season+week+player_norm", ["season_str", "week_str", "player_norm"]))
    if game_date_present and player_norm_present:
        join_options.append(("game_date+player_norm", ["game_date_str", "player_norm"]))
    if event_id_col:
        join_options.append(("event_id", ["event_id_str"]))
    if player_norm_present:
        join_options.append(("player_norm", ["player_norm"]))

    best_method = "none"
    best_match_rate = 0.0
    best_matched = 0
    best_candidate_rows = 0

    for method_name, keys in join_options:
        if not all(k in odds.columns for k in keys):
            continue
        if not all(k in candidate_df.columns for k in keys):
            continue

        candidate_dedup = candidate_df.drop_duplicates(subset=keys, keep="first")
        merged = odds.merge(
            candidate_dedup[[*keys, actual_col]],
            on=keys,
            how="left",
            suffixes=("", "_src"),
        )

        matched = merged[actual_col].notna().sum()
        match_rate = matched / len(odds) if len(odds) else 0.0

        if match_rate > best_match_rate:
            best_method = method_name
            best_match_rate = match_rate
            best_matched = matched
            best_candidate_rows = len(candidate_dedup)

    result.update(
        {
            "best_join_method": best_method,
            "matched_odds_rows": best_matched,
            "match_rate": best_match_rate,
            "candidate_dedup_rows": best_candidate_rows,
            "note": "",
        }
    )
    return result


def find_candidate_files():
    files = []
    files = []
    for folder in CANDIDATE_DIRS:
        if not folder.exists():
            continue
        if folder.name == "pff" and folder.is_dir():
            files.append(RAW_PFF_AGGREGATED_PATH)
            continue
        for path in folder.rglob("*"):
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                if path == ODDS_FILE:
                    continue
                files.append(path)
    return sorted(files)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    odds_df = build_odds_frame()

    candidate_paths = find_candidate_files()
    if not candidate_paths:
        raise RuntimeError("No candidate actuals source files were found.")

    rows = []
    for path in candidate_paths:
        try:
            if path == RAW_PFF_AGGREGATED_PATH:
                pff_folder = path.parent
                pff_files = sorted(pff_folder.rglob("passing_summary.csv"))
                if not pff_files:
                    raise RuntimeError("No raw PFF passing_summary.csv files were found.")
                df = pd.concat([pd.read_csv(p) for p in pff_files], ignore_index=True)
            else:
                df = load_dataframe(path)

            info = join_statistics(odds_df, df, path)
            rows.append(info)
        except Exception as exc:
            rows.append(
                {
                    "candidate_path": str(path),
                    "candidate_rows": None,
                    "actual_col": None,
                    "has_event_id": False,
                    "has_player_col": False,
                    "has_player_norm": False,
                    "has_season": False,
                    "has_week": False,
                    "has_game_date": False,
                    "best_join_method": "error",
                    "matched_odds_rows": 0,
                    "match_rate": 0.0,
                    "candidate_dedup_rows": None,
                    "note": f"error: {exc}",
                }
            )

    audit_df = pd.DataFrame(rows).sort_values(
        ["match_rate", "candidate_rows"], ascending=[False, False]
    )
    audit_df.to_csv(AUDIT_CSV, index=False)

    print(f"Audit results written to: {AUDIT_CSV}")
    print(audit_df.to_string(index=False))


if __name__ == "__main__":
    main()
