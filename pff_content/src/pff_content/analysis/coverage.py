from __future__ import annotations

import pandas as pd

from .qualifiers import QUALIFIERS, add_rank, safe_divide


def build(coverage: pd.DataFrame) -> pd.DataFrame:
    df = coverage.copy()
    df["catch_rate_allowed"] = safe_divide(df["receptions"], df["targets"])
    df["yards_per_target_allowed"] = safe_divide(df["yards"], df["targets"])
    df["forced_incompletion_rate"] = safe_divide(df["forced_incompletes"], df["targets"])
    df["qualified_coverage"] = (df["coverage_snaps"] >= QUALIFIERS["coverage_min_snaps"]) & (df["targets"] >= QUALIFIERS["coverage_min_targets"])
    for metric, ascending in [
        ("passer_rating_when_targeted", True),
        ("yards_per_target_allowed", True),
        ("forced_incompletes", False),
        ("forced_incompletion_rate", False),
        ("targets", False),
    ]:
        if metric in df.columns:
            df = add_rank(df, metric, f"{metric}_rank", ascending=ascending, qualified_col=None if metric in {"targets", "forced_incompletes"} else "qualified_coverage")
    return df.sort_values(["targets", "yards_per_target_allowed"], ascending=[False, True])
