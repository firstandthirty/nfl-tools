from __future__ import annotations

import itertools
import math

import pandas as pd

from .metrics import roi_confidence_bounds, roi_standard_error, summarize


def interaction_table(df: pd.DataFrame, dimensions: list[str], min_bets: int, max_categories: int) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    usable = [d for d in dimensions if d in df and 1 < df[d].nunique(dropna=True) <= max_categories]
    for dim_a, dim_b in itertools.combinations(usable, 2):
        subset = df[df[dim_a].notna() & df[dim_b].notna()]
        for values, group in subset.groupby([dim_a, dim_b], observed=True, dropna=False):
            stats = summarize(group)
            if stats["bets"] < min_bets:
                continue
            low, high = roi_confidence_bounds(group)
            bets = int(stats["bets"])
            roi = float(stats["roi"])
            rows.append({
                "dimension_1": dim_a,
                "value_1": values[0],
                "dimension_2": dim_b,
                "value_2": values[1],
                **stats,
                "roi_standard_error": roi_standard_error(group),
                "roi_ci_95_low": low,
                "roi_ci_95_high": high,
                "roi_x_sqrt_n": roi * math.sqrt(bets),
                "conservative_score": low,
                "ranking_note": "exploratory",
            })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["conservative_score", "bets"], ascending=[False, False])

