from __future__ import annotations

import pandas as pd

from .qualifiers import QUALIFIERS, add_rank, safe_divide


def build(pass_rush: pd.DataFrame) -> pd.DataFrame:
    df = pass_rush.copy()
    df["pressure_rate"] = safe_divide(df["total_pressures"], df["pass_rush_snaps"])
    df["qualified_pass_rush"] = df["pass_rush_snaps"] >= QUALIFIERS["pass_rush_min_snaps"]
    for metric in ["total_pressures", "pressure_rate", "pass_rush_win_rate", "pass_rush_productivity"]:
        if metric in df.columns:
            df = add_rank(df, metric, f"{metric}_rank", ascending=False, qualified_col=None if metric == "total_pressures" else "qualified_pass_rush")
    return df.sort_values(["total_pressures", "pressure_rate"], ascending=[False, False])
