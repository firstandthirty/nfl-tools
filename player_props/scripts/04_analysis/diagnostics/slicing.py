from __future__ import annotations

import pandas as pd

from .metrics import summarize


def slice_table(df: pd.DataFrame, dimension: str, min_bets: int, max_categories: int) -> pd.DataFrame:
    if dimension not in df:
        return pd.DataFrame()
    non_null = df[df[dimension].notna()]
    if non_null.empty or non_null[dimension].nunique(dropna=True) > max_categories:
        return pd.DataFrame()
    rows = []
    for value, group in non_null.groupby(dimension, observed=True, dropna=False):
        stats = summarize(group)
        if stats["bets"] >= min_bets:
            rows.append({dimension: value, **stats})
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["roi", "bets"], ascending=[False, False])

