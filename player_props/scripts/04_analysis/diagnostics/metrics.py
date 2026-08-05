from __future__ import annotations

import math

import numpy as np
import pandas as pd


def numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def to_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    if pd.api.types.is_numeric_dtype(series):
        return numeric(series).eq(1)
    return series.astype("string").str.strip().str.lower().isin(
        {"1", "true", "t", "yes", "y", "win", "won"}
    )


def clean_side(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.strip().str.lower()
    mapped = values.replace({"o": "over", "ov": "over", "u": "under", "un": "under"})
    return mapped.where(mapped.isin(["over", "under"]), values)


def decimal_profit(odds: pd.Series, won: pd.Series, pushed: pd.Series) -> pd.Series:
    odds = numeric(odds)
    out = pd.Series(np.nan, index=odds.index, dtype="float64")
    out.loc[pushed.fillna(False)] = 0.0
    out.loc[~pushed.fillna(False) & ~won.fillna(False)] = -1.0
    out.loc[~pushed.fillna(False) & won.fillna(False)] = odds - 1.0
    return out


def american_implied_probability(odds: pd.Series) -> pd.Series:
    odds = numeric(odds)
    out = pd.Series(np.nan, index=odds.index, dtype="float64")
    positive = odds > 0
    negative = odds < 0
    out.loc[positive] = 100.0 / (odds.loc[positive] + 100.0)
    out.loc[negative] = odds.loc[negative].abs() / (odds.loc[negative].abs() + 100.0)
    return out


def summarize(group: pd.DataFrame) -> dict[str, float | int]:
    graded = group[group["profit_units"].notna()]
    decided = graded[~graded["pushed"]]
    wins = int(decided["won"].sum())
    losses = int((~decided["won"]).sum())
    pushes = int(graded["pushed"].sum())
    bets = int(len(graded))
    profit = float(graded["profit_units"].sum()) if bets else math.nan
    row: dict[str, float | int] = {
        "bets": bets,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": wins / (wins + losses) if wins + losses else math.nan,
        "profit_units": profit,
        "roi": profit / bets if bets else math.nan,
    }
    for source, output in [
        ("line_value", "avg_line"),
        ("projection_value", "avg_projection"),
        ("projection_minus_line_value", "avg_projection_minus_line"),
        ("predicted_probability", "avg_recommended_probability"),
        ("recommended_ev_percent_value", "avg_recommended_ev_percent"),
        ("bet_odds_value", "avg_bet_odds"),
        ("raw_edge_signed", "avg_raw_edge"),
        ("projection_edge", "avg_projection_edge"),
        ("absolute_projection_edge", "avg_absolute_projection_edge"),
    ]:
        row[output] = float(graded[source].mean()) if source in graded else math.nan
    return row


def roi_standard_error(frame: pd.DataFrame) -> float:
    profit = numeric(frame["profit_units"]).dropna()
    if len(profit) < 2:
        return math.nan
    return float(profit.std(ddof=1) / math.sqrt(len(profit)))


def roi_confidence_bounds(frame: pd.DataFrame, z: float = 1.96) -> tuple[float, float]:
    stats = summarize(frame)
    se = roi_standard_error(frame)
    if pd.isna(stats["roi"]) or pd.isna(se):
        return math.nan, math.nan
    return float(stats["roi"] - z * se), float(stats["roi"] + z * se)


def bootstrap_roi_interval(profit: pd.Series, samples: int, seed: int) -> tuple[float, float]:
    clean = numeric(profit).dropna().to_numpy(dtype=float)
    if samples <= 0 or clean.size < 2:
        return math.nan, math.nan
    rng = np.random.default_rng(seed)
    draws = rng.choice(clean, size=(samples, clean.size), replace=True)
    low, high = np.quantile(draws.mean(axis=1), [0.025, 0.975])
    return float(low), float(high)


def calibration_metrics(frame: pd.DataFrame, probability_col: str) -> dict[str, float]:
    valid = frame[
        frame[probability_col].between(0, 1, inclusive="both")
        & ~frame["pushed"]
        & frame["won"].notna()
    ]
    if valid.empty:
        return {
            "brier_score": math.nan,
            "expected_calibration_error": math.nan,
            "mean_predicted_probability": math.nan,
            "actual_win_rate": math.nan,
        }
    predicted = valid[probability_col].astype(float)
    actual = valid["won"].astype(float)
    return {
        "brier_score": float(((predicted - actual) ** 2).mean()),
        "expected_calibration_error": float(abs(predicted.mean() - actual.mean())),
        "mean_predicted_probability": float(predicted.mean()),
        "actual_win_rate": float(actual.mean()),
    }

