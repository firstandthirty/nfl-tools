from pathlib import Path
import re
import numpy as np
import pandas as pd

SEASON = 2026
WEEK = 1
POSITION = "QB"

INPUT_DIR = Path(f"data/processed/projections/{SEASON}/week_{WEEK:02d}")
OUT_PATH = INPUT_DIR / "qb_projection_ensemble.csv"

# Your QB projection files have duplicate headers:
# "ATT","CMP","YDS","TDS","INTS","ATT","YDS","TDS","FL","FPTS"
# Pandas will rename duplicates as:
# ATT, CMP, YDS, TDS, INTS, ATT.1, YDS.1, TDS.1, FL, FPTS
PASS_YDS_COL = "YDS"
PASS_ATT_COL = "ATT"
PASS_TD_COL = "TDS"
INT_COL = "INTS"

RUSH_ATT_COL = "ATT.1"
RUSH_YDS_COL = "YDS.1"
RUSH_TD_COL = "TDS.1"

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


def norm_player_name(x):
    if pd.isna(x):
        return np.nan

    s = str(x).strip().lower()

    # remove common suffixes
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", s)

    # keep letters/numbers/spaces only
    s = re.sub(r"[^a-z0-9\s]", "", s)

    # collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()

    return s


def source_name_from_file(path):
    stem = path.stem
    stem = stem.replace(f"{POSITION}_", "")
    return stem


def read_projection_file(path):
    source = source_name_from_file(path)

    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]

    required = ["Player", "Team", PASS_YDS_COL]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"{path} missing required columns: {missing}\n"
            f"Available: {list(df.columns)}"
        )

    out = pd.DataFrame()
    out["player"] = df["Player"].astype(str).str.strip()
    out["player_norm"] = out["player"].apply(norm_player_name)
    out["team"] = df["Team"].apply(norm_team)
    out["source"] = source

    # Passing
    out["pass_att"] = pd.to_numeric(df.get(PASS_ATT_COL), errors="coerce")
    out["pass_yds"] = pd.to_numeric(df.get(PASS_YDS_COL), errors="coerce")
    out["pass_td"] = pd.to_numeric(df.get(PASS_TD_COL), errors="coerce")
    out["int"] = pd.to_numeric(df.get(INT_COL), errors="coerce")

    # Rushing
    out["rush_att"] = pd.to_numeric(df.get(RUSH_ATT_COL), errors="coerce")
    out["rush_yds"] = pd.to_numeric(df.get(RUSH_YDS_COL), errors="coerce")
    out["rush_td"] = pd.to_numeric(df.get(RUSH_TD_COL), errors="coerce")

    out["fpts"] = pd.to_numeric(df.get("FPTS"), errors="coerce")

    return out


def summarize_metric(grouped, metric):
    return grouped[metric].agg(
        **{
            f"{metric}_mean": "mean",
            f"{metric}_median": "median",
            f"{metric}_std_sources": lambda s: s.std(ddof=1),
            f"{metric}_min": "min",
            f"{metric}_max": "max",
        }
    )


def main():
    if not INPUT_DIR.exists():
        raise FileNotFoundError(f"Missing projection directory: {INPUT_DIR}")

    files = sorted(INPUT_DIR.glob(f"{POSITION}_*.csv"))

    # Do not re-ingest ensemble output if rerun
    files = [p for p in files if "ensemble" not in p.stem.lower()]

    if not files:
        raise FileNotFoundError(f"No projection files found in: {INPUT_DIR}")

    print(f"[load] projection files found: {len(files)}")
    for p in files:
        print(f" - {p.name}")

    all_rows = []

    for path in files:
        temp = read_projection_file(path)
        print(f"[read] {path.name}: rows={len(temp):,}")
        all_rows.append(temp)

    long = pd.concat(all_rows, ignore_index=True)

    # Drop rows without a pass yards projection
    long = long.dropna(subset=["player_norm", "team", "pass_yds"]).copy()

    long_path = INPUT_DIR / "qb_projection_sources_long.csv"
    long.to_csv(long_path, index=False)

    group_cols = ["player_norm", "team"]

    grouped = long.groupby(group_cols, dropna=False)

    base = grouped.agg(
        player=("player", lambda s: s.mode().iloc[0] if not s.mode().empty else s.iloc[0]),
        source_count=("source", "nunique"),
        sources=("source", lambda s: ",".join(sorted(set(s)))),
    ).reset_index()

    metrics = [
        "pass_att",
        "pass_yds",
        "pass_td",
        "int",
        "rush_att",
        "rush_yds",
        "rush_td",
        "fpts",
    ]

    summary_parts = [base]

    for metric in metrics:
        if metric in long.columns:
            summary_parts.append(summarize_metric(grouped, metric).reset_index())

    ensemble = summary_parts[0]

    for part in summary_parts[1:]:
        ensemble = ensemble.merge(part, on=group_cols, how="left")

    # Projection disagreement features
    ensemble["pass_yds_range_sources"] = ensemble["pass_yds_max"] - ensemble["pass_yds_min"]

    ensemble["pass_yds_cv_sources"] = np.where(
        ensemble["pass_yds_mean"].abs() > 0,
        ensemble["pass_yds_std_sources"] / ensemble["pass_yds_mean"],
        np.nan,
    )

    # With only 1 source, std is NaN. Treat disagreement as 0 but flag low source count.
    ensemble["pass_yds_std_sources"] = ensemble["pass_yds_std_sources"].fillna(0)
    ensemble["pass_yds_cv_sources"] = ensemble["pass_yds_cv_sources"].fillna(0)

    ensemble["low_source_count"] = ensemble["source_count"] < 3

    # Clean sort
    ensemble = ensemble.sort_values(
        ["source_count", "pass_yds_mean"],
        ascending=[False, False],
    ).reset_index(drop=True)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ensemble.to_csv(OUT_PATH, index=False)

    print(f"\n[saved] long source file: {long_path}")
    print(f"[saved] ensemble file: {OUT_PATH}")
    print(f"[rows] {len(ensemble):,}")

    show_cols = [
        "player",
        "team",
        "source_count",
        "sources",
        "pass_yds_mean",
        "pass_yds_median",
        "pass_yds_std_sources",
        "pass_yds_range_sources",
        "pass_att_mean",
        "pass_td_mean",
        "int_mean",
        "rush_yds_mean",
        "fpts_mean",
    ]

    show_cols = [c for c in show_cols if c in ensemble.columns]

    print("\n===== TOP PASS YDS PROJECTIONS =====")
    print(
        ensemble[show_cols]
        .sort_values("pass_yds_mean", ascending=False)
        .head(25)
        .to_string(index=False)
    )

    print("\n===== HIGHEST PROJECTION DISAGREEMENT =====")
    print(
        ensemble[show_cols]
        .sort_values("pass_yds_range_sources", ascending=False)
        .head(25)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()