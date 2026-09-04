from __future__ import annotations

import math
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_prop_residual_calibration import load_market_sample
from prop_probability import brier_score, clipped_probability, log_loss

MARKET = "player_reception_yds"
MIN_SIGNAL_TRAIN_WEEKS = 4
MIN_SIGNAL_TRAIN_ROWS = 50
MIN_CALIBRATION_ROWS = 50
BOOTSTRAP_SEED = 20260904


def projection_side(value: float) -> str:
    if float(value) > 0:
        return "over"
    if float(value) < 0:
        return "under"
    return "none"


def side_won(actual: float, line: float, side: str) -> bool:
    if side == "over":
        return float(actual) > float(line)
    if side == "under":
        return float(actual) < float(line)
    return False


def fit_linear_margin(train: pd.DataFrame) -> np.ndarray:
    x = train[["projection_edge", "line"]].astype(float).to_numpy()
    y = train["actual_margin"].astype(float).to_numpy()
    x = np.column_stack([np.ones(len(x)), x])
    return np.linalg.pinv(x.T @ x) @ x.T @ y


def predict_linear_margin(rows: pd.DataFrame, coef: np.ndarray) -> np.ndarray:
    x = rows[["projection_edge", "line"]].astype(float).to_numpy()
    x = np.column_stack([np.ones(len(x)), x])
    return x @ coef


def load_receiving_history(project_root: Path = PROJECT_ROOT) -> pd.DataFrame:
    rows = load_market_sample(project_root, MARKET).copy()
    rows["market"] = MARKET
    rows["projection_edge"] = rows["projection"].astype(float) - rows["line"].astype(float)
    rows["actual_margin"] = rows["actual"].astype(float) - rows["line"].astype(float)
    rows["raw_indicated_side"] = rows["projection_edge"].map(projection_side)
    rows["push"] = rows["actual"].astype(float).eq(rows["line"].astype(float))
    rows["position"] = rows.get("position", "UNKNOWN")
    rows["position"] = rows["position"].fillna("UNKNOWN").astype(str).str.upper().replace({"HB": "RB"})
    cols = [
        "market",
        "season",
        "week",
        "player",
        "player_norm",
        "team",
        "opponent",
        "position",
        "game_id",
        "line",
        "over_price",
        "under_price",
        "projection",
        "projection_edge",
        "raw_indicated_side",
        "actual",
        "actual_margin",
        "push",
    ]
    for col in cols:
        if col not in rows.columns:
            rows[col] = ""
    return rows[cols].sort_values(["season", "week", "player_norm", "line"], kind="mergesort").reset_index(drop=True)


def crossfit_signal_predictions(rows: pd.DataFrame) -> pd.DataFrame:
    out = []
    weeks = sorted(int(value) for value in rows["week"].dropna().unique())
    for week in weeks:
        prior_weeks = [value for value in weeks if value < week]
        train = rows[rows["week"].isin(prior_weeks)].copy()
        test = rows[rows["week"].eq(week)].copy()
        if len(prior_weeks) < MIN_SIGNAL_TRAIN_WEEKS or len(train) < MIN_SIGNAL_TRAIN_ROWS or test.empty:
            continue
        coef = fit_linear_margin(train)
        pred = predict_linear_margin(test, coef)
        temp = test.copy()
        temp["training_start_week"] = min(prior_weeks)
        temp["training_end_week"] = max(prior_weeks)
        temp["predicted_week"] = int(week)
        temp["training_row_count"] = int(len(train))
        temp["signal_intercept"] = float(coef[0])
        temp["signal_coef_projection_edge"] = float(coef[1])
        temp["signal_coef_line"] = float(coef[2])
        temp["predicted_margin"] = pred
        temp["predicted_actual"] = temp["line"].astype(float) + temp["predicted_margin"].astype(float)
        temp["model_indicated_side"] = temp["predicted_margin"].map(projection_side)
        temp["model_indicated_won"] = [
            side_won(actual, line, side) and not push
            for actual, line, side, push in zip(temp["actual"], temp["line"], temp["model_indicated_side"], temp["push"])
        ]
        temp["raw_indicated_won"] = [
            side_won(actual, line, side) and not push
            for actual, line, side, push in zip(temp["actual"], temp["line"], temp["raw_indicated_side"], temp["push"])
        ]
        out.append(temp)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def roc_auc_score_binary(y_true: pd.Series, score: pd.Series) -> float:
    y = y_true.astype(int).to_numpy()
    s = score.astype(float).to_numpy()
    positives = int(y.sum())
    negatives = int(len(y) - positives)
    if positives == 0 or negatives == 0:
        return math.nan
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), dtype=float)
    sorted_s = s[order]
    start = 0
    while start < len(s):
        end = start + 1
        while end < len(s) and sorted_s[end] == sorted_s[start]:
            end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2.0
        start = end
    rank_sum = float(ranks[y == 1].sum())
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def signal_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    candidates = [
        ("improved_signal", "predicted_margin", "model_indicated_won"),
        ("raw_projection_edge", "projection_edge", "raw_indicated_won"),
    ]
    decided = predictions[predictions["push"] == False].copy()
    for label, score_col, win_col in candidates:
        work = decided[decided[score_col].astype(float).ne(0)].copy()
        score = work[score_col].astype(float).abs()
        pred_sign = np.sign(work[score_col].astype(float))
        actual_sign = np.sign(work["actual_margin"].astype(float))
        error = (work["line"].astype(float) + work[score_col].astype(float)) - work["actual"].astype(float)
        rows.append({
            "candidate": label,
            "n": int(len(work)),
            "directional_accuracy": float(work[win_col].mean()) if not work.empty else math.nan,
            "auc": roc_auc_score_binary(work[win_col], score) if not work.empty else math.nan,
            "balanced_accuracy": float((pred_sign == actual_sign).mean()) if not work.empty else math.nan,
            "over_accuracy": float(work.loc[work[score_col].gt(0), win_col].mean()) if work[score_col].gt(0).any() else math.nan,
            "under_accuracy": float(work.loc[work[score_col].lt(0), win_col].mean()) if work[score_col].lt(0).any() else math.nan,
            "mae_predicted_actual": float(error.abs().mean()) if not work.empty else math.nan,
            "rmse_predicted_actual": float(np.sqrt((error ** 2).mean())) if not work.empty else math.nan,
            "corr_predicted_margin_actual_margin": float(work[score_col].corr(work["actual_margin"])) if work[score_col].nunique() > 1 else math.nan,
            "sign_accuracy": float((pred_sign == actual_sign).mean()) if not work.empty else math.nan,
        })
    return pd.DataFrame(rows)


def score_bucket_rows(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, score_col, win_col in [("improved_signal", "predicted_margin", "model_indicated_won"), ("raw_projection_edge", "projection_edge", "raw_indicated_won")]:
        work = predictions[predictions["push"] == False].copy()
        work = work[work[score_col].astype(float).ne(0)].copy()
        work["score_abs"] = work[score_col].abs()
        work["score_bucket"] = pd.qcut(work["score_abs"], q=4, duplicates="drop")
        ranked = work.sort_values("score_abs", kind="mergesort").copy()
        ranked["half"] = pd.qcut(np.arange(len(ranked)), q=2, labels=["bottom_half", "top_half"])
        ranked["third"] = pd.qcut(np.arange(len(ranked)), q=3, labels=["bottom_third", "middle_third", "top_third"])
        for bucket_type, frame in [("score_bucket", work), ("half", ranked), ("third", ranked)]:
            for bucket, group in frame.groupby(bucket_type, observed=True):
                rows.append({
                    "candidate": label,
                    "bucket_type": bucket_type,
                    "bucket": str(bucket),
                    "n": int(len(group)),
                    "mean_predicted_margin": float(group[score_col].mean()),
                    "median_absolute_predicted_margin": float(group[score_col].abs().median()),
                    "actual_directional_hit_rate": float(group[win_col].mean()),
                    "average_actual_margin": float(group["actual_margin"].mean()),
                    "auc": roc_auc_score_binary(group[win_col], group[score_col].abs()),
                })
    return pd.DataFrame(rows)


def side_diagnostics(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, side_col, score_col, win_col in [
        ("improved_signal", "model_indicated_side", "predicted_margin", "model_indicated_won"),
        ("raw_projection_edge", "raw_indicated_side", "projection_edge", "raw_indicated_won"),
    ]:
        work = predictions[(predictions["push"] == False) & predictions[side_col].isin(["over", "under"])].copy()
        for side, group in work.groupby(side_col, observed=True):
            rows.append({
                "candidate": label,
                "side": side,
                "n": int(len(group)),
                "hit_rate": float(group[win_col].mean()),
                "auc": roc_auc_score_binary(group[win_col], group[score_col].abs()),
                "mean_predicted_margin_magnitude": float(group[score_col].abs().mean()),
                "mean_actual_margin": float(group["actual_margin"].mean()),
            })
    return pd.DataFrame(rows)


def position_diagnostics(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, score_col, win_col in [("improved_signal", "predicted_margin", "model_indicated_won"), ("raw_projection_edge", "projection_edge", "raw_indicated_won")]:
        work = predictions[predictions["push"] == False].copy()
        for position, group in work.groupby("position", observed=True):
            if len(group) < 20:
                continue
            error = (group["line"].astype(float) + group[score_col].astype(float)) - group["actual"].astype(float)
            rows.append({
                "candidate": label,
                "position": position,
                "n": int(len(group)),
                "hit_rate": float(group[win_col].mean()),
                "auc": roc_auc_score_binary(group[win_col], group[score_col].abs()),
                "mae_predicted_actual": float(error.abs().mean()),
                "mean_predicted_margin": float(group[score_col].mean()),
            })
    return pd.DataFrame(rows)


def fit_logistic_calibrator(train: pd.DataFrame, score_col: str, target_col: str) -> np.ndarray:
    x_score = train[score_col].astype(float).to_numpy()
    x = np.column_stack([np.ones(len(x_score)), x_score])
    y = train[target_col].astype(float).to_numpy()
    beta = np.zeros(2, dtype=float)
    penalty = np.diag([0.0, 1.0])
    for _ in range(50):
        linear = x @ beta
        pred = 1.0 / (1.0 + np.exp(-np.clip(linear, -35.0, 35.0)))
        weights = np.clip(pred * (1.0 - pred), 1e-8, None)
        gradient = x.T @ (y - pred) - penalty @ beta
        hessian = x.T @ (x * weights[:, None]) + penalty
        try:
            delta = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError:
            break
        beta += delta
        if np.max(np.abs(delta)) < 1e-8:
            break
    return beta


def predict_logistic_probability(score: pd.Series, coef: np.ndarray) -> np.ndarray:
    x = np.column_stack([np.ones(len(score)), score.astype(float).to_numpy()])
    return 1.0 / (1.0 + np.exp(-np.clip(x @ coef, -35.0, 35.0)))


def fit_isotonic(x: pd.Series, y: pd.Series) -> list[dict[str, float]]:
    ordered = pd.DataFrame({"x": x.astype(float), "y": y.astype(float)}).sort_values("x", kind="mergesort")
    blocks: list[dict[str, Any]] = []
    for _, row in ordered.iterrows():
        blocks.append({"min_x": float(row["x"]), "max_x": float(row["x"]), "sum_y": float(row["y"]), "n": 1})
        while len(blocks) >= 2:
            prev = blocks[-2]["sum_y"] / blocks[-2]["n"]
            curr = blocks[-1]["sum_y"] / blocks[-1]["n"]
            if prev <= curr:
                break
            merged = {
                "min_x": blocks[-2]["min_x"],
                "max_x": blocks[-1]["max_x"],
                "sum_y": blocks[-2]["sum_y"] + blocks[-1]["sum_y"],
                "n": blocks[-2]["n"] + blocks[-1]["n"],
            }
            blocks = blocks[:-2] + [merged]
    return [{"min_x": b["min_x"], "max_x": b["max_x"], "probability": b["sum_y"] / b["n"], "n": b["n"]} for b in blocks]


def predict_isotonic(x: pd.Series, blocks: list[dict[str, float]]) -> np.ndarray:
    values = []
    for value in x.astype(float):
        selected = blocks[0]
        for block in blocks:
            selected = block
            if value <= block["max_x"]:
                break
        values.append(float(selected["probability"]))
    return np.asarray(values)


def empirical_bucket_probability(train: pd.DataFrame, test: pd.DataFrame, score_col: str, target_col: str, buckets: int = 4) -> np.ndarray:
    work = train.copy()
    work["bucket"] = pd.qcut(work[score_col], q=min(buckets, max(2, len(work) // 20)), duplicates="drop")
    stats = work.groupby("bucket", observed=True)[target_col].agg(["sum", "count"]).reset_index()
    fallback = float((work[target_col].sum() + 1.0) / (len(work) + 2.0))
    probs = []
    for value in test[score_col].astype(float):
        selected = None
        for _, row in stats.iterrows():
            interval = row["bucket"]
            if value in interval:
                selected = float((row["sum"] + 1.0) / (row["count"] + 2.0))
                break
        probs.append(selected if selected is not None else fallback)
    return np.asarray(probs)


def prepare_calibration_frame(predictions: pd.DataFrame, candidate: str) -> pd.DataFrame:
    if candidate == "improved_signal":
        side_col = "model_indicated_side"
        score_col = "predicted_margin"
        win_col = "model_indicated_won"
    elif candidate == "raw_projection_edge":
        side_col = "raw_indicated_side"
        score_col = "projection_edge"
        win_col = "raw_indicated_won"
    else:
        raise ValueError(candidate)
    out = predictions[(predictions["push"] == False) & predictions[side_col].isin(["over", "under"])].copy()
    out["signal_candidate"] = candidate
    out["selected_side"] = out[side_col]
    out["side_oriented_score"] = out[score_col].abs()
    out["selected_side_won"] = out[win_col].astype(bool)
    return out


def nested_calibrated_predictions(crossfit: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for candidate in ["improved_signal", "raw_projection_edge"]:
        base = prepare_calibration_frame(crossfit, candidate)
        weeks = sorted(int(value) for value in base["predicted_week"].dropna().unique())
        for week in weeks:
            train = base[base["predicted_week"] < week].copy()
            test = base[base["predicted_week"] == week].copy()
            if len(train) < MIN_CALIBRATION_ROWS or test.empty:
                continue
            train_rate = float(train["selected_side_won"].mean())
            methods: list[tuple[str, np.ndarray, dict[str, Any]]] = []
            methods.append(("constant_50", np.repeat(0.5, len(test)), {}))
            methods.append(("training_base_rate", np.repeat(train_rate, len(test)), {"base_rate": train_rate}))
            coef = fit_logistic_calibrator(train, "side_oriented_score", "selected_side_won")
            logistic = predict_logistic_probability(test["side_oriented_score"], coef)
            methods.append(("logistic", logistic, {"intercept": float(coef[0]), "coef_score": float(coef[1])}))
            blocks = fit_isotonic(train["side_oriented_score"], train["selected_side_won"])
            methods.append(("isotonic", predict_isotonic(test["side_oriented_score"], blocks), {"blocks": len(blocks)}))
            methods.append(("empirical_bucket", empirical_bucket_probability(train, test, "side_oriented_score", "selected_side_won"), {}))
            for alpha in [0.25, 0.5, 0.75]:
                methods.append((f"logistic_shrunk_alpha_{alpha:.2f}", 0.5 + alpha * (logistic - 0.5), {"alpha": alpha}))
            for method, probs, meta in methods:
                temp = test.copy()
                temp["calibration_method"] = method
                temp["calibration_training_start_week"] = int(train["predicted_week"].min())
                temp["calibration_training_end_week"] = int(train["predicted_week"].max())
                temp["calibration_sample_size"] = int(len(train))
                temp["calibrated_probability"] = [clipped_probability(v) for v in probs]
                temp["calibration_metadata"] = json.dumps(meta, sort_keys=True)
                frames.append(temp)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def probability_metrics(rows: pd.DataFrame) -> pd.DataFrame:
    out = []
    for (candidate, method), group in rows.groupby(["signal_candidate", "calibration_method"], observed=True):
        y = group["selected_side_won"].astype(float)
        p = group["calibrated_probability"].astype(float)
        out.append({
            "signal_candidate": candidate,
            "calibration_method": method,
            "n": int(len(group)),
            "brier_score": brier_score(y, p),
            "log_loss": log_loss(y, p),
            "mean_predicted_probability": float(p.mean()),
            "actual_win_rate": float(y.mean()),
            "calibration_bias": float(p.mean() - y.mean()),
            "auc": roc_auc_score_binary(y, p),
            "directional_hit_rate": float(y.mean()),
        })
    return pd.DataFrame(out)


def reliability_buckets(rows: pd.DataFrame) -> pd.DataFrame:
    out = []
    work = rows.copy()
    work["probability_bucket"] = pd.cut(
        work["calibrated_probability"],
        bins=[0.0, 0.5, 0.525, 0.55, 0.575, 0.60, 0.65, 1.0],
        labels=["<50%", "50-52.5%", "52.5-55%", "55-57.5%", "57.5-60%", "60-65%", "65%+"],
        include_lowest=True,
        right=False,
    )
    for (candidate, method, bucket), group in work.groupby(["signal_candidate", "calibration_method", "probability_bucket"], observed=True):
        if len(group) < 5:
            continue
        out.append({
            "signal_candidate": candidate,
            "calibration_method": method,
            "probability_bucket": str(bucket),
            "n": int(len(group)),
            "mean_predicted_probability": float(group["calibrated_probability"].mean()),
            "actual_win_rate": float(group["selected_side_won"].mean()),
            "calibration_gap": float(group["calibrated_probability"].mean() - group["selected_side_won"].mean()),
            "brier_score": brier_score(group["selected_side_won"].astype(float), group["calibrated_probability"].astype(float)),
            "average_raw_score": float(group["side_oriented_score"].mean()),
        })
    return pd.DataFrame(out)


def weekly_stability(rows: pd.DataFrame) -> pd.DataFrame:
    out = []
    for (candidate, method, week), group in rows.groupby(["signal_candidate", "calibration_method", "predicted_week"], observed=True):
        if len(group) < 5:
            continue
        y = group["selected_side_won"].astype(float)
        p = group["calibrated_probability"].astype(float)
        out.append({
            "signal_candidate": candidate,
            "calibration_method": method,
            "predicted_week": int(week),
            "n": int(len(group)),
            "directional_accuracy": float(y.mean()),
            "auc": roc_auc_score_binary(y, p),
            "brier_score": brier_score(y, p),
            "log_loss": log_loss(y, p),
            "mean_probability": float(p.mean()),
            "actual_win_rate": float(y.mean()),
        })
    return pd.DataFrame(out)


def bootstrap_probability_metrics(rows: pd.DataFrame, iterations: int = 5000, seed: int = BOOTSTRAP_SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    out = []
    for (candidate, method), group in rows.groupby(["signal_candidate", "calibration_method"], observed=True):
        group = group.reset_index(drop=True)
        y = group["selected_side_won"].astype(float).to_numpy()
        p = group["calibrated_probability"].astype(float).to_numpy()
        values = {"brier": [], "brier_diff_vs_50": [], "log_loss": [], "logloss_diff_vs_50": [], "auc": [], "directional_hit_rate": []}
        for _ in range(iterations):
            idx = rng.integers(0, len(group), len(group))
            y_s = pd.Series(y[idx])
            p_s = pd.Series(p[idx])
            brier = brier_score(y_s, p_s)
            ll = log_loss(y_s, p_s)
            values["brier"].append(brier)
            values["brier_diff_vs_50"].append(brier - 0.25)
            values["log_loss"].append(ll)
            values["logloss_diff_vs_50"].append(ll - math.log(2))
            values["auc"].append(roc_auc_score_binary(y_s, p_s))
            values["directional_hit_rate"].append(float(y_s.mean()))
        for metric, vals in values.items():
            arr = np.asarray(vals, dtype=float)
            arr = arr[~np.isnan(arr)]
            observed = {
                "brier": brier_score(pd.Series(y), pd.Series(p)),
                "brier_diff_vs_50": brier_score(pd.Series(y), pd.Series(p)) - 0.25,
                "log_loss": log_loss(pd.Series(y), pd.Series(p)),
                "logloss_diff_vs_50": log_loss(pd.Series(y), pd.Series(p)) - math.log(2),
                "auc": roc_auc_score_binary(pd.Series(y), pd.Series(p)),
                "directional_hit_rate": float(y.mean()),
            }[metric]
            out.append({
                "signal_candidate": candidate,
                "calibration_method": method,
                "metric": metric,
                "observed": float(observed),
                "ci_low_95": float(np.quantile(arr, 0.025)) if len(arr) else math.nan,
                "ci_high_95": float(np.quantile(arr, 0.975)) if len(arr) else math.nan,
                "iterations": int(iterations),
                "seed": int(seed),
            })
    return pd.DataFrame(out)
