from __future__ import annotations

import pandas as pd

from .metrics import calibration_metrics, summarize


def calibration_table(df: pd.DataFrame, value_col: str, bucket_col: str, label: str, is_probability: bool = False, min_bets: int = 15) -> pd.DataFrame:
    if value_col not in df or bucket_col not in df:
        return pd.DataFrame()
    valid = df[df[value_col].notna() & df[bucket_col].notna()].copy()
    if is_probability:
        valid = valid[valid[value_col].between(0, 1, inclusive="both") & ~valid["pushed"]]
    if valid.empty:
        return pd.DataFrame()
    rows = []
    for bucket, group in valid.groupby(bucket_col, observed=True, dropna=False):
        stats = summarize(group)
        if stats["bets"] < min_bets:
            continue
        row = {
            "calibration_field": label,
            "bucket": bucket,
            "bets": stats["bets"],
            "actual_win_rate": stats["win_rate"],
            "roi": stats["roi"],
            "profit_units": stats["profit_units"],
            "avg_odds": stats["avg_bet_odds"],
            f"avg_{label}": float(group[value_col].mean()),
        }
        if is_probability:
            predicted = float(group[value_col].mean())
            row["avg_predicted_probability"] = predicted
            row["calibration_error"] = stats["win_rate"] - predicted
            row["absolute_calibration_error"] = abs(stats["win_rate"] - predicted)
        rows.append(row)
    out = pd.DataFrame(rows)
    if is_probability and not out.empty:
        metrics = calibration_metrics(valid, value_col)
        for key, value in metrics.items():
            out[f"overall_{key}"] = value
    return out
