from __future__ import annotations

import pandas as pd

from .qualifiers import QUALIFIERS, add_rank, safe_divide


def build(rushing: pd.DataFrame) -> pd.DataFrame:
    df = rushing.copy()
    df["yards_after_contact_per_attempt"] = safe_divide(df["yards_after_contact"], df["attempts"])
    mtf = "avoided_tackles" if "avoided_tackles" in df.columns else "elu_rush_mtf"
    df["missed_tackles_forced_per_attempt"] = safe_divide(df[mtf], df["attempts"])
    df["yards_per_carry"] = safe_divide(df["yards"], df["attempts"])
    df["qualified_rushing"] = df["attempts"] >= QUALIFIERS["rushing_min_attempts"]
    for metric in ["yards_after_contact_per_attempt", "missed_tackles_forced_per_attempt", "yards_per_carry", "yards", mtf]:
        if metric in df.columns:
            df = add_rank(df, metric, f"{metric}_rank", ascending=False, qualified_col=None if metric in {"yards", mtf} else "qualified_rushing")
    return df.sort_values(["yards", "yards_after_contact_per_attempt"], ascending=[False, False])
