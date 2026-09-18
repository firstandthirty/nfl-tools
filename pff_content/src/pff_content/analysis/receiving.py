from __future__ import annotations

import pandas as pd

from .qualifiers import QUALIFIERS, add_rank, safe_divide


def build(receiving: pd.DataFrame) -> pd.DataFrame:
    df = receiving.copy()
    df["targets_per_route_run"] = safe_divide(df["targets"], df["routes"])
    df["catch_rate_derived"] = safe_divide(df["receptions"], df["targets"])
    df["yards_per_target"] = safe_divide(df["yards"], df["targets"])
    df["qualified_routes"] = df["routes"] >= QUALIFIERS["receiving_min_routes"]
    for metric in ["targets", "targets_per_route_run", "yprr", "yards_per_target", "slot_rate", "wide_rate", "inline_rate"]:
        if metric in df.columns:
            df = add_rank(df, metric, f"{metric}_rank", ascending=False, qualified_col=None if metric == "targets" else "qualified_routes")
    return df.sort_values(["targets", "targets_per_route_run"], ascending=[False, False])
