from __future__ import annotations

import pandas as pd

from .qualifiers import add_ol_snap_qualification, add_rank, safe_divide


def build(pass_blocking: pd.DataFrame) -> pd.DataFrame:
    df = pass_blocking.copy()
    df["pressure_rate_allowed"] = safe_divide(df["pressures_allowed"], df["pass_block_snaps"])
    df = add_ol_snap_qualification(df)
    for metric, ascending in [("pressures_allowed", False), ("sacks_allowed", False), ("pass_blocking_efficiency", True), ("pressure_rate_allowed", False)]:
        if metric in df.columns:
            df = add_rank(df, metric, f"{metric}_rank", ascending=ascending, qualified_col="qualified_ol")
    return df.sort_values(["qualified_ol", "pressures_allowed"], ascending=[False, False])
