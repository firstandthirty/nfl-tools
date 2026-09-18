from __future__ import annotations

import pandas as pd


QUALIFIERS = {
    "qb_min_dropbacks": 20,
    "receiving_min_routes": 15,
    "rushing_min_attempts": 8,
    "ol_snap_share": 0.75,
    "pass_rush_min_snaps": 15,
    "run_defense_min_snaps": 15,
    "coverage_min_snaps": 20,
    "coverage_min_targets": 4,
}

OL_POSITIONS = {"C", "G", "T", "LG", "RG", "LT", "RT"}


def add_rank(df: pd.DataFrame, metric: str, rank_col: str, *, ascending: bool = False, qualified_col: str | None = None) -> pd.DataFrame:
    out = df.copy()
    mask = out[metric].notna()
    if qualified_col:
        mask &= out[qualified_col].fillna(False)
    out[rank_col] = pd.NA
    out[f"{rank_col}_qualified_count"] = int(mask.sum())
    out.loc[mask, rank_col] = out.loc[mask, metric].rank(method="min", ascending=ascending).astype("Int64")
    return out


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    num = pd.to_numeric(numerator, errors="coerce")
    den = pd.to_numeric(denominator, errors="coerce")
    return num.where(den > 0) / den.where(den > 0)


def add_ol_snap_qualification(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    normal_ol = out["position"].isin(OL_POSITIONS) if "position" in out.columns else pd.Series(False, index=out.index)
    team_max = out.loc[normal_ol].groupby("team")["pass_block_snaps"].transform("max")
    out["team_max_ol_pass_block_snaps"] = pd.NA
    out.loc[normal_ol, "team_max_ol_pass_block_snaps"] = team_max
    out["ol_pass_block_snap_share"] = safe_divide(out["pass_block_snaps"], out["team_max_ol_pass_block_snaps"])
    out["qualified_ol"] = normal_ol & (out["ol_pass_block_snap_share"] >= QUALIFIERS["ol_snap_share"])
    return out
