from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


MODELED_MARKETS = {"player_pass_yds", "player_rush_yds", "player_reception_yds"}
PROBABILITY_FLOOR = 1e-6


@dataclass(frozen=True)
class SplitDefinition:
    train_weeks: list[int]
    validation_weeks: list[int]
    method: str


def forecast_residual(actual: float, projection: float) -> float:
    return float(actual) - float(projection)


def actual_minus_line(actual: float, line: float) -> float:
    return float(actual) - float(line)


def normal_cdf(x: float, mu: float, sigma: float) -> float:
    sigma = max(float(sigma), PROBABILITY_FLOOR)
    z = (float(x) - float(mu)) / (sigma * math.sqrt(2.0))
    return 0.5 * (1.0 + math.erf(z))


def normal_probabilities(projection: float, line: float, mu: float, sigma: float) -> dict[str, float]:
    threshold = float(line) - float(projection)
    p_under = normal_cdf(threshold, mu, sigma)
    p_over = 1.0 - p_under
    return {"p_over": p_over, "p_under": p_under, "p_push": 0.0}


def empirical_probabilities(projection: float, line: float, residuals: list[float] | np.ndarray) -> dict[str, float]:
    values = np.asarray(residuals, dtype="float64")
    values = values[~np.isnan(values)]
    if len(values) == 0:
        raise ValueError("empirical residuals are empty")
    threshold = float(line) - float(projection)
    p_over = float(np.mean(values > threshold))
    p_under = float(np.mean(values < threshold))
    p_push = float(np.mean(np.isclose(values, threshold, atol=1e-9)))
    total = p_over + p_under + p_push
    if total > 0:
        p_over /= total
        p_under /= total
        p_push /= total
    return {"p_over": p_over, "p_under": p_under, "p_push": p_push}


def clipped_probability(value: float) -> float:
    return min(max(float(value), PROBABILITY_FLOOR), 1.0 - PROBABILITY_FLOOR)


def log_loss(y_true: pd.Series, probability: pd.Series) -> float:
    p = probability.astype(float).map(clipped_probability)
    y = y_true.astype(float)
    return float((-(y * np.log(p) + (1.0 - y) * np.log(1.0 - p))).mean())


def brier_score(y_true: pd.Series, probability: pd.Series) -> float:
    return float(((probability.astype(float) - y_true.astype(float)) ** 2).mean())


def american_to_decimal(american: int | float) -> float:
    odds = float(american)
    if odds == 0:
        raise ValueError("American odds cannot be 0")
    return 1.0 + odds / 100.0 if odds > 0 else 1.0 + 100.0 / abs(odds)


def profit_per_unit_risked(american: int | float) -> float:
    odds = float(american)
    if odds == 0:
        raise ValueError("American odds cannot be 0")
    return odds / 100.0 if odds > 0 else 100.0 / abs(odds)


def break_even_probability(american: int | float) -> float:
    odds = float(american)
    if odds == 0:
        raise ValueError("American odds cannot be 0")
    return 100.0 / (odds + 100.0) if odds > 0 else abs(odds) / (abs(odds) + 100.0)


def expected_value_1u(win_probability: float, push_probability: float, american: int | float) -> float:
    win = float(win_probability)
    push = float(push_probability)
    loss = max(0.0, 1.0 - win - push)
    return win * profit_per_unit_risked(american) - loss


def select_chronological_split(df: pd.DataFrame, min_validation_rows: int = 50) -> SplitDefinition:
    weeks = sorted(int(value) for value in df["week"].dropna().unique())
    validation: list[int] = []
    for week in reversed(weeks):
        validation.insert(0, week)
        if int(df["week"].isin(validation).sum()) >= min_validation_rows:
            break
    train = [week for week in weeks if week not in validation]
    if not train or not validation:
        raise ValueError("chronological split produced an empty training or validation sample")
    return SplitDefinition(train_weeks=train, validation_weeks=validation, method="single_season_late_week_holdout")


def residual_summary(df: pd.DataFrame) -> dict[str, Any]:
    residual = pd.to_numeric(df["forecast_residual"], errors="coerce").dropna()
    return {
        "n": int(len(residual)),
        "mean_residual": float(residual.mean()),
        "median_residual": float(residual.median()),
        "std_residual": float(residual.std(ddof=1)),
        "mae": float(residual.abs().mean()),
        "rmse": float(np.sqrt((residual ** 2).mean())),
        "skewness": float(residual.skew()),
        "excess_kurtosis": float(residual.kurt()),
        "p05": float(residual.quantile(0.05)),
        "p10": float(residual.quantile(0.10)),
        "p25": float(residual.quantile(0.25)),
        "p50": float(residual.quantile(0.50)),
        "p75": float(residual.quantile(0.75)),
        "p90": float(residual.quantile(0.90)),
        "p95": float(residual.quantile(0.95)),
    }


def make_probability_buckets(probabilities: pd.Series) -> pd.Series:
    return pd.cut(
        probabilities,
        bins=[0.0, 0.5, 0.525, 0.55, 0.575, 0.60, 0.65, 1.0],
        labels=["<50%", "50-52.5%", "52.5-55%", "55-57.5%", "57.5-60%", "60-65%", "65%+"],
        right=False,
        include_lowest=True,
    )


def evaluate_probability_rows(df: pd.DataFrame, probability_col: str) -> dict[str, float]:
    valid = df[df["is_push"] == False].copy()
    if valid.empty:
        return {"n": 0, "brier_score": math.nan, "log_loss": math.nan, "calibration_error": math.nan}
    y = valid["won"].astype(float)
    p = valid[probability_col].astype(float)
    return {
        "n": int(len(valid)),
        "brier_score": brier_score(y, p),
        "log_loss": log_loss(y, p),
        "calibration_error": float(p.mean() - y.mean()),
    }


def load_calibration_artifact(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_calibration_artifact(path: Path | str, artifact: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")


def market_parameters(artifact: dict[str, Any], market: str) -> dict[str, Any]:
    if market not in artifact.get("markets", {}):
        raise KeyError(f"Missing calibration for market={market}")
    return artifact["markets"][market]


def model_probabilities(params: dict[str, Any], projection: float, line: float) -> dict[str, float]:
    method = params["selected_method"]
    if method == "normal":
        probs = normal_probabilities(projection, line, params["normal_mu"], params["normal_sigma"])
    elif method == "empirical":
        probs = empirical_probabilities(projection, line, params["empirical_residuals"])
    elif method == "conditional_empirical":
        threshold = float(line) - float(projection)
        bins = params["conditional_bins"]
        selected = None
        for item in bins:
            if item["projection_min"] <= float(projection) <= item["projection_max"]:
                selected = item
                break
        residuals = selected["empirical_residuals"] if selected is not None else params["empirical_residuals"]
        probs = empirical_probabilities(projection, line, residuals)
    else:
        raise ValueError(f"Unknown calibration method={method}")
    return {key: clipped_probability(value) if key != "p_push" else max(0.0, float(value)) for key, value in probs.items()}
