from __future__ import annotations

import pandas as pd

from .qualifiers import QUALIFIERS, add_rank, safe_divide


def build(run_defense: pd.DataFrame) -> pd.DataFrame:
    df = run_defense.copy()
    df["run_stop_rate"] = safe_divide(df["stops"], df["run_defense_snaps"])
    df["qualified_run_defense"] = df["run_defense_snaps"] >= QUALIFIERS["run_defense_min_snaps"]
    for metric in ["stops", "run_stop_rate", "missed_tackles"]:
        if metric in df.columns:
            df = add_rank(df, metric, f"{metric}_rank", ascending=False, qualified_col=None if metric in {"stops", "missed_tackles"} else "qualified_run_defense")
    return df.sort_values(["stops", "run_stop_rate"], ascending=[False, False])
