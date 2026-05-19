from pathlib import Path
import pandas as pd
import numpy as np


BASE_DIR = Path(r"C:\Users\brady\OneDrive\Desktop\nfl-tools\player props")
PFF_DIR = BASE_DIR / "data" / "processed" / "pff"
EDA_DIR = BASE_DIR / "data" / "processed" / "eda"

MASTER_PATH = PFF_DIR / "pff_player_weekly_master.csv"

EDA_DIR.mkdir(parents=True, exist_ok=True)


STATS_TO_ANALYZE = [
    # Passing
    "passing_yards",
    "pass_attempts",
    "passing_tds",
    "passing_ypa",

    # Receiving
    "receiving_yards",
    "targets",
    "receptions",
    "routes",
    "yprr",
    "receiving_adot",

    # Rushing
    "rushing_yards",
    "rush_attempts",
    "rushing_tds",
    "rushing_ypa",
]


CORRELATION_PAIRS = [
    ("pass_attempts", "passing_yards"),
    ("passing_ypa", "passing_yards"),
    ("routes", "targets"),
    ("targets", "receptions"),
    ("targets", "receiving_yards"),
    ("routes", "receiving_yards"),
    ("yprr", "receiving_yards"),
    ("receiving_adot", "receiving_yards"),
    ("rush_attempts", "rushing_yards"),
    ("rushing_ypa", "rushing_yards"),
]


def safe_numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def stat_summary(df: pd.DataFrame, stat_cols: list[str]) -> pd.DataFrame:
    rows = []

    for col in stat_cols:
        if col not in df.columns:
            rows.append({"stat": col, "status": "missing"})
            continue

        s = df[col].dropna()

        if s.empty:
            rows.append({"stat": col, "status": "all_null"})
            continue

        mean = s.mean()
        median = s.median()
        sd = s.std()

        rows.append({
            "stat": col,
            "status": "ok",
            "count": int(s.count()),
            "nonzero_count": int((s != 0).sum()),
            "zero_count": int((s == 0).sum()),
            "mean": mean,
            "median": median,
            "mean_minus_median": mean - median,
            "mean_to_median_ratio": mean / median if median not in [0, np.nan] and median != 0 else np.nan,
            "std": sd,
            "cv": sd / mean if mean != 0 else np.nan,
            "skew": s.skew(),
            "kurtosis": s.kurtosis(),
            "min": s.min(),
            "p10": s.quantile(0.10),
            "p25": s.quantile(0.25),
            "p75": s.quantile(0.75),
            "p90": s.quantile(0.90),
            "p95": s.quantile(0.95),
            "max": s.max(),
        })

    return pd.DataFrame(rows)


def stat_summary_by_position(df: pd.DataFrame, stat_cols: list[str]) -> pd.DataFrame:
    rows = []

    if "position" not in df.columns:
        return pd.DataFrame()

    for pos, g in df.groupby("position"):
        for col in stat_cols:
            if col not in g.columns:
                continue

            s = g[col].dropna()
            if s.empty:
                continue

            mean = s.mean()
            median = s.median()
            sd = s.std()

            rows.append({
                "position": pos,
                "stat": col,
                "count": int(s.count()),
                "mean": mean,
                "median": median,
                "mean_minus_median": mean - median,
                "std": sd,
                "cv": sd / mean if mean != 0 else np.nan,
                "skew": s.skew(),
                "p25": s.quantile(0.25),
                "p75": s.quantile(0.75),
                "p90": s.quantile(0.90),
                "max": s.max(),
            })

    return pd.DataFrame(rows)


def missingness_report(df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    for col in df.columns:
        null_count = df[col].isna().sum()
        rows.append({
            "column": col,
            "rows": len(df),
            "null_count": int(null_count),
            "null_rate": null_count / len(df) if len(df) else np.nan,
            "non_null_count": int(len(df) - null_count),
        })

    return pd.DataFrame(rows).sort_values("null_rate", ascending=False)


def duplicate_check(df: pd.DataFrame) -> pd.DataFrame:
    key_cols = ["season", "week", "player_id", "team_name"]

    missing = [c for c in key_cols if c not in df.columns]
    if missing:
        return pd.DataFrame([{
            "status": "missing_key_columns",
            "missing": ",".join(missing),
        }])

    dups = (
        df[df.duplicated(key_cols, keep=False)]
        .sort_values(key_cols)
        [key_cols + ["player", "position"]]
    )

    return dups


def correlation_report(df: pd.DataFrame, pairs: list[tuple[str, str]]) -> pd.DataFrame:
    rows = []

    for x, y in pairs:
        if x not in df.columns or y not in df.columns:
            rows.append({
                "x": x,
                "y": y,
                "status": "missing_column",
                "correlation": np.nan,
                "n": 0,
            })
            continue

        temp = df[[x, y]].dropna()
        temp = temp[(temp[x] != 0) | (temp[y] != 0)]

        if len(temp) < 5:
            rows.append({
                "x": x,
                "y": y,
                "status": "too_few_rows",
                "correlation": np.nan,
                "n": len(temp),
            })
            continue

        rows.append({
            "x": x,
            "y": y,
            "status": "ok",
            "correlation": temp[x].corr(temp[y]),
            "n": len(temp),
        })

    return pd.DataFrame(rows)


def player_volatility(df: pd.DataFrame) -> pd.DataFrame:
    target_stats = [
        "passing_yards",
        "receiving_yards",
        "rushing_yards",
        "targets",
        "receptions",
        "rush_attempts",
        "pass_attempts",
    ]

    rows = []

    group_cols = ["player_id", "player", "position"]

    for col in target_stats:
        if col not in df.columns:
            continue

        temp = df.dropna(subset=[col]).copy()

        grouped = temp.groupby(group_cols)[col]

        out = grouped.agg(["count", "mean", "median", "std"]).reset_index()
        out = out[out["count"] >= 8].copy()
        out["stat"] = col
        out["cv"] = out["std"] / out["mean"].replace(0, np.nan)
        out["mean_minus_median"] = out["mean"] - out["median"]

        rows.append(out)

    if not rows:
        return pd.DataFrame()

    combined = pd.concat(rows, ignore_index=True)
    combined = combined.sort_values(["stat", "cv"], ascending=[True, False])

    return combined


def simple_archetypes(df: pd.DataFrame) -> pd.DataFrame:
    """
    First-pass archetype labeling. This is intentionally simple and can be improved later.
    """
    out = df.copy()

    out["archetype"] = "other"

    if {"position", "slot_rate", "receiving_adot", "routes", "targets"}.issubset(out.columns):
        wr_te = out["position"].isin(["WR", "TE"])

        out.loc[
            wr_te & (out["slot_rate"] >= 50) & (out["routes"] >= 10),
            "archetype"
        ] = "slot_receiver"

        out.loc[
            wr_te & (out["receiving_adot"] >= 12) & (out["routes"] >= 10),
            "archetype"
        ] = "deep_receiver"

        out.loc[
            wr_te & (out["targets"] >= 8),
            "archetype"
        ] = "high_target_receiver"

    if {"position", "rush_attempts", "targets"}.issubset(out.columns):
        out.loc[
            (out["position"] == "HB") & (out["rush_attempts"] >= 12),
            "archetype"
        ] = "early_down_rb"

        out.loc[
            (out["position"] == "HB") & (out["targets"] >= 4),
            "archetype"
        ] = "receiving_rb"

    if {"position", "rushing_yards"}.issubset(out.columns):
        out.loc[
            (out["position"] == "QB") & (out["rushing_yards"] >= 25),
            "archetype"
        ] = "mobile_qb_game"

    return out


def archetype_summary(df: pd.DataFrame) -> pd.DataFrame:
    stat_cols = [
        "receiving_yards",
        "targets",
        "receptions",
        "routes",
        "rushing_yards",
        "rush_attempts",
        "passing_yards",
        "pass_attempts",
    ]

    rows = []

    if "archetype" not in df.columns:
        return pd.DataFrame()

    for archetype, g in df.groupby("archetype"):
        for col in stat_cols:
            if col not in g.columns:
                continue

            s = g[col].dropna()
            if len(s) < 20:
                continue

            rows.append({
                "archetype": archetype,
                "stat": col,
                "count": int(len(s)),
                "mean": s.mean(),
                "median": s.median(),
                "mean_minus_median": s.mean() - s.median(),
                "std": s.std(),
                "cv": s.std() / s.mean() if s.mean() != 0 else np.nan,
                "skew": s.skew(),
                "p25": s.quantile(0.25),
                "p75": s.quantile(0.75),
                "p90": s.quantile(0.90),
                "max": s.max(),
            })

    return pd.DataFrame(rows)


def main() -> None:
    print(f"[load] {MASTER_PATH}")
    df = pd.read_csv(MASTER_PATH)

    df = safe_numeric(df, STATS_TO_ANALYZE + ["slot_rate"])

    print(f"[rows] {len(df):,}")
    print(f"[cols] {len(df.columns):,}")

    missing = missingness_report(df)
    missing.to_csv(EDA_DIR / "missingness_report.csv", index=False)
    print(f"[saved] {EDA_DIR / 'missingness_report.csv'}")

    dups = duplicate_check(df)
    dups.to_csv(EDA_DIR / "duplicate_check.csv", index=False)
    print(f"[saved] {EDA_DIR / 'duplicate_check.csv'} rows={len(dups):,}")

    summary = stat_summary(df, STATS_TO_ANALYZE)
    summary.to_csv(EDA_DIR / "stat_summary_overall.csv", index=False)
    print(f"[saved] {EDA_DIR / 'stat_summary_overall.csv'}")

    by_pos = stat_summary_by_position(df, STATS_TO_ANALYZE)
    by_pos.to_csv(EDA_DIR / "stat_summary_by_position.csv", index=False)
    print(f"[saved] {EDA_DIR / 'stat_summary_by_position.csv'}")

    corr = correlation_report(df, CORRELATION_PAIRS)
    corr.to_csv(EDA_DIR / "correlation_report.csv", index=False)
    print(f"[saved] {EDA_DIR / 'correlation_report.csv'}")

    vol = player_volatility(df)
    vol.to_csv(EDA_DIR / "player_volatility.csv", index=False)
    print(f"[saved] {EDA_DIR / 'player_volatility.csv'}")

    archetyped = simple_archetypes(df)
    arch_summary = archetype_summary(archetyped)
    arch_summary.to_csv(EDA_DIR / "archetype_summary.csv", index=False)
    print(f"[saved] {EDA_DIR / 'archetype_summary.csv'}")

    print("[done]")


if __name__ == "__main__":
    main()