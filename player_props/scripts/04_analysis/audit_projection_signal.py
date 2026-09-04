from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELING_DIR = PROJECT_ROOT / "scripts" / "03_modeling"
if str(MODELING_DIR) not in sys.path:
    sys.path.insert(0, str(MODELING_DIR))

from build_prop_residual_calibration import load_market_sample
from prop_probability import MODELED_MARKETS, select_chronological_split

OUTPUT_DIR = PROJECT_ROOT / "data" / "analysis" / "model_signal" / "projection_signal_audit_v1"
BOOTSTRAP_ITERATIONS = 5000
BOOTSTRAP_SEED = 20260904
MIN_TRAIN_ROWS = 50

HISTORY_FILES = {
    "player_pass_yds": PROJECT_ROOT / "data" / "analysis" / "pass_yds_market_analysis_rows.csv",
    "player_reception_yds": PROJECT_ROOT / "data" / "analysis" / "reception_yds_market_analysis_rows.csv",
    "player_rush_yds": PROJECT_ROOT / "data" / "analysis" / "rush_yds_market_analysis_rows.csv",
}

SAFE_CONTEXT_COLS = [
    "home_team",
    "away_team",
    "home_team_abbr",
    "away_team_abbr",
    "recent_team",
    "position",
    "home_spread",
    "away_spread",
    "game_total",
    "is_home",
    "is_away",
    "team_spread",
    "opponent_spread",
    "is_favorite",
    "is_underdog",
    "is_pickem",
    "team_total",
    "bookmaker_key",
    "bookmaker_title",
    "market_last_update",
    "bookmaker_last_update",
]

ROLLING_CONTEXT_COLS = [
    "rolling_pass_yds_3g",
    "rolling_pass_yds_5g",
    "rolling_actual_minus_line_3g",
    "rolling_actual_minus_line_5g",
    "rolling_std_pass_yds_3g",
    "rolling_std_pass_yds_5g",
    "rolling_over_rate_3g",
    "rolling_over_rate_5g",
    "season_avg_pass_yds_pre",
    "season_avg_actual_minus_line_pre",
    "games_played_pre",
]

LEAKY_COL_KEYWORDS = [
    "actual",
    "hit_",
    "went_over",
    "push",
    "roi",
    "profit",
    "passing_yards",
    "rushing_yards",
    "receiving_yards",
    "receptions",
]


def american_to_profit(price: float) -> float:
    odds = float(price)
    if odds > 0:
        return odds / 100.0
    return 100.0 / abs(odds)


def bettor_roi(won: bool, pushed: bool, price: float) -> float:
    if pushed:
        return 0.0
    return american_to_profit(price) if won else -1.0


def projection_direction(edge: float) -> str:
    if edge > 0:
        return "over"
    if edge < 0:
        return "under"
    return "none"


def side_score_from_margin(predicted_margin: pd.Series, side: pd.Series) -> pd.Series:
    sign = np.where(side.astype(str).str.lower().eq("over"), 1.0, -1.0)
    return pd.Series(predicted_margin.to_numpy(dtype=float) * sign, index=predicted_margin.index)


def relative_edge(projection: pd.Series, line: pd.Series) -> pd.Series:
    denominator = line.astype(float).abs().clip(lower=1.0)
    return (projection.astype(float) - line.astype(float)) / denominator


def standardized_edge(edge: pd.Series, residual_sigma: float) -> pd.Series:
    return edge.astype(float) / max(float(residual_sigma), 1e-9)


def fit_linear_model(train: pd.DataFrame, feature_cols: list[str], target_col: str, ridge: float = 1e-6) -> np.ndarray:
    x = train[feature_cols].astype(float).fillna(0.0).to_numpy()
    y = train[target_col].astype(float).to_numpy()
    x = np.column_stack([np.ones(len(x)), x])
    penalty = np.eye(x.shape[1]) * ridge
    penalty[0, 0] = 0.0
    return np.linalg.pinv(x.T @ x + penalty) @ x.T @ y


def predict_linear(df: pd.DataFrame, feature_cols: list[str], coef: np.ndarray) -> np.ndarray:
    x = df[feature_cols].astype(float).fillna(0.0).to_numpy()
    x = np.column_stack([np.ones(len(x)), x])
    return x @ coef


def fit_logistic_model(train: pd.DataFrame, feature_cols: list[str], target_col: str, ridge: float = 1.0) -> np.ndarray:
    x = train[feature_cols].astype(float).fillna(0.0).to_numpy()
    y = train[target_col].astype(float).to_numpy()
    x = np.column_stack([np.ones(len(x)), x])
    beta = np.zeros(x.shape[1], dtype=float)
    penalty = np.eye(x.shape[1]) * ridge
    penalty[0, 0] = 0.0
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


def predict_logistic_score(df: pd.DataFrame, feature_cols: list[str], coef: np.ndarray) -> np.ndarray:
    x = df[feature_cols].astype(float).fillna(0.0).to_numpy()
    x = np.column_stack([np.ones(len(x)), x])
    return x @ coef


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
    positive_rank_sum = float(ranks[y == 1].sum())
    return (positive_rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def balanced_accuracy(df: pd.DataFrame, predicted_col: str = "predicted_win") -> float:
    y = df["won"].astype(bool)
    p = df[predicted_col].astype(bool)
    pos = y.eq(True)
    neg = y.eq(False)
    tpr = float((p[pos] == True).mean()) if pos.any() else math.nan
    tnr = float((p[neg] == False).mean()) if neg.any() else math.nan
    if math.isnan(tpr) or math.isnan(tnr):
        return math.nan
    return (tpr + tnr) / 2.0


def metric_row(df: pd.DataFrame, score_col: str, predicted_col: str = "predicted_win") -> dict[str, Any]:
    decided = df[df["push"] == False].copy()
    if decided.empty:
        return {"n": 0, "accuracy": math.nan, "auc": math.nan, "balanced_accuracy": math.nan, "over_accuracy": math.nan, "under_accuracy": math.nan, "roi": math.nan}
    over = decided[decided["side"].eq("over")]
    under = decided[decided["side"].eq("under")]
    return {
        "n": int(len(decided)),
        "accuracy": float(decided[predicted_col].astype(bool).eq(decided["won"].astype(bool)).mean()),
        "auc": roc_auc_score_binary(decided["won"], decided[score_col]),
        "balanced_accuracy": balanced_accuracy(decided, predicted_col),
        "over_accuracy": float(over[predicted_col].astype(bool).eq(over["won"].astype(bool)).mean()) if not over.empty else math.nan,
        "under_accuracy": float(under[predicted_col].astype(bool).eq(under["won"].astype(bool)).mean()) if not under.empty else math.nan,
        "roi": float(decided["roi"].mean()),
        "average_american_price": float(decided["price"].mean()),
    }


def margin_metrics(df: pd.DataFrame, prediction_col: str) -> dict[str, Any]:
    err = df[prediction_col].astype(float) - df["actual_minus_line"].astype(float)
    return {
        "margin_mae": float(err.abs().mean()),
        "margin_rmse": float(np.sqrt((err ** 2).mean())),
        "margin_correlation": float(df[prediction_col].corr(df["actual_minus_line"])) if df[prediction_col].nunique() > 1 else math.nan,
        "margin_sign_accuracy": float((np.sign(df[prediction_col]) == np.sign(df["actual_minus_line"])).mean()),
    }


def classify_feature(file_name: str, column: str) -> str:
    lower = column.lower()
    if any(keyword in lower for keyword in LEAKY_COL_KEYWORDS):
        return "potentially_leaky"
    if lower in {"projection", "projection_minus_line", "line", "over_price", "under_price", "season", "week", "team", "opponent", "player", "player_norm", "player_id", "game_id", "market_key"}:
        return "safe_available_pregame"
    if lower in {col.lower() for col in SAFE_CONTEXT_COLS}:
        return "safe_available_pregame"
    if "rolling" in lower:
        return "safe_if_shifted_insufficient_coverage"
    if lower in {"weather", "injury", "depth_chart", "starter", "snap_share", "routes", "targets", "carries", "attempts"}:
        return "unavailable_historically"
    return "insufficient_coverage_or_not_used"


def feature_inventory(project_root: Path) -> pd.DataFrame:
    files = [
        project_root / "data" / "analysis" / "pass_yds_model_bets_backtest_safe.csv",
        project_root / "data" / "analysis" / "rush_yds_model_bets_backtest_safe.csv",
        project_root / "data" / "analysis" / "reception_yds_model_bets_backtest_safe.csv",
        *HISTORY_FILES.values(),
        project_root / "data" / "historical_props" / "merged_props_with_rolling.csv",
    ]
    rows = []
    for path in files:
        if not path.exists():
            continue
        frame = pd.read_csv(path, nrows=500)
        full_rows = sum(1 for _ in path.open(encoding="utf-8")) - 1
        for column in frame.columns:
            rows.append({
                "file": str(path.relative_to(project_root)),
                "column": column,
                "non_null_in_sample": int(frame[column].notna().sum()),
                "sample_rows_checked": int(len(frame)),
                "file_rows": int(full_rows),
                "availability_class": classify_feature(path.name, column),
            })
    return pd.DataFrame(rows)


def load_context(project_root: Path, market: str) -> pd.DataFrame:
    path = HISTORY_FILES[market]
    history = pd.read_csv(path)
    history = history.copy()
    if "season" not in history.columns and "season_guess" in history.columns:
        history["season"] = history["season_guess"]
    if "week" not in history.columns and "week_guess" in history.columns:
        history["week"] = history["week_guess"]
    if "event_id" in history.columns:
        history["game_id"] = history["event_id"].astype(str)
    keep = ["season", "week", "game_id", "player_norm", "line"]
    optional = [col for col in SAFE_CONTEXT_COLS if col in history.columns]
    rolling_path = project_root / "data" / "historical_props" / "merged_props_with_rolling.csv"
    if rolling_path.exists():
        rolling_cols = ["season", "week", "market_key", "player_norm", *ROLLING_CONTEXT_COLS]
        rolling = pd.read_csv(rolling_path, usecols=lambda col: col in rolling_cols)
        rolling = rolling[rolling["market_key"].eq(market)].drop_duplicates(["season", "week", "market_key", "player_norm"])
        history = history.merge(
            rolling,
            left_on=["season", "week", "market_key", "player_norm"],
            right_on=["season", "week", "market_key", "player_norm"],
            how="left",
        )
        optional.extend([col for col in ROLLING_CONTEXT_COLS if col in history.columns])
    cols = keep + optional
    context = history[cols].drop_duplicates(keep)
    return context


def load_historical_rows(project_root: Path) -> pd.DataFrame:
    frames = []
    for market in sorted(MODELED_MARKETS):
        sample = load_market_sample(project_root, market)
        context = load_context(project_root, market)
        sample["game_id"] = sample["game_id"].astype(str)
        sample = sample.merge(context, on=["season", "week", "game_id", "player_norm", "line"], how="left", suffixes=("", "_context"))
        sample["market"] = market
        sample["projection_edge"] = sample["projection"].astype(float) - sample["line"].astype(float)
        sample["actual_minus_line"] = sample["actual"].astype(float) - sample["line"].astype(float)
        sample["projection_indicated_side"] = sample["projection_edge"].map(projection_direction)
        sample["position"] = sample.get("position", "UNKNOWN").fillna("UNKNOWN").astype(str).str.upper().replace({"HB": "RB"})
        for col in ["team_spread", "game_total", "team_total", "is_home", "is_favorite", "is_underdog", *ROLLING_CONTEXT_COLS]:
            if col not in sample.columns:
                sample[col] = np.nan
            sample[col] = pd.to_numeric(sample[col], errors="coerce")
        frames.append(sample)
    return pd.concat(frames, ignore_index=True, sort=False)


def to_side_rows(line_rows: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in line_rows.iterrows():
        push = bool(row["actual"] == row["line"])
        for side in ["over", "under"]:
            won = bool(row["actual"] > row["line"]) if side == "over" else bool(row["actual"] < row["line"])
            price = float(row["over_price"]) if side == "over" else float(row["under_price"])
            rows.append({
                "market": row["market"],
                "season": int(row["season"]),
                "week": int(row["week"]),
                "player": row.get("player", ""),
                "player_norm": row.get("player_norm", ""),
                "position": row.get("position", "UNKNOWN"),
                "team": row.get("team", ""),
                "opponent": row.get("opponent", ""),
                "game_id": row.get("game_id", ""),
                "line": float(row["line"]),
                "projection": float(row["projection"]),
                "actual": float(row["actual"]),
                "actual_minus_line": float(row["actual_minus_line"]),
                "projection_edge": float(row["projection_edge"]),
                "relative_edge": float(relative_edge(pd.Series([row["projection"]]), pd.Series([row["line"]])).iloc[0]),
                "side": side,
                "side_sign": 1.0 if side == "over" else -1.0,
                "side_score_raw_edge": float(row["projection_edge"]) if side == "over" else -float(row["projection_edge"]),
                "projection_indicated_side": row["projection_indicated_side"],
                "price": price,
                "won": won,
                "push": push,
                "roi": bettor_roi(won, push, price),
                "team_spread": row.get("team_spread", np.nan),
                "game_total": row.get("game_total", np.nan),
                "team_total": row.get("team_total", np.nan),
                "is_home": row.get("is_home", np.nan),
                "is_favorite": row.get("is_favorite", np.nan),
                "is_underdog": row.get("is_underdog", np.nan),
                **{col: row.get(col, np.nan) for col in ROLLING_CONTEXT_COLS},
            })
    return pd.DataFrame(rows)


def assign_split(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    split_frames = []
    split_rows = []
    for market, group in rows.groupby("market", observed=True):
        split = select_chronological_split(group, min_validation_rows=50)
        market_rows = group.copy()
        market_rows["split"] = np.where(market_rows["week"].isin(split.validation_weeks), "final_holdout", "train")
        split_frames.append(market_rows)
        split_rows.append({
            "market": market,
            "split_method": split.method,
            "train_weeks": "|".join(str(value) for value in split.train_weeks),
            "final_holdout_weeks": "|".join(str(value) for value in split.validation_weeks),
            "train_rows": int(market_rows["split"].eq("train").sum()),
            "final_holdout_rows": int(market_rows["split"].eq("final_holdout").sum()),
        })
    return pd.concat(split_frames, ignore_index=True), pd.DataFrame(split_rows)


def add_train_derived_features(line_rows: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for market, group in line_rows.groupby("market", observed=True):
        train = group[group["split"].eq("train")].copy()
        out = group.copy()
        overall_bias = float((train["actual"] - train["projection"]).mean())
        overall_sigma = float((train["actual"] - train["projection"]).std(ddof=1))
        out["bias_overall"] = overall_bias
        out["projection_bias_corrected_overall"] = out["projection"] + overall_bias
        out["edge_bias_corrected_overall"] = out["projection_bias_corrected_overall"] - out["line"]
        out["standardized_edge"] = standardized_edge(out["projection_edge"], overall_sigma)
        out["relative_edge"] = relative_edge(out["projection"], out["line"])
        train = train.copy()
        train["line_bucket_train"] = pd.qcut(train["line"], q=3, labels=False, duplicates="drop")
        boundaries = train.groupby("line_bucket_train", observed=True)["line"].agg(["min", "max"]).reset_index(drop=True)
        def line_bucket(value: float) -> int:
            for idx, row in boundaries.iterrows():
                if float(row["min"]) <= float(value) <= float(row["max"]):
                    return int(idx)
            return int(np.argmin(np.abs(((boundaries["min"] + boundaries["max"]) / 2.0) - float(value)))) if not boundaries.empty else -1
        out["line_bucket_train"] = out["line"].map(line_bucket)
        train["projection_bucket_train"] = pd.qcut(train["projection"], q=3, labels=False, duplicates="drop")
        projection_bounds = train.groupby("projection_bucket_train", observed=True)["projection"].agg(["min", "max"]).reset_index(drop=True)
        def projection_bucket(value: float) -> int:
            for idx, row in projection_bounds.iterrows():
                if float(row["min"]) <= float(value) <= float(row["max"]):
                    return int(idx)
            return int(np.argmin(np.abs(((projection_bounds["min"] + projection_bounds["max"]) / 2.0) - float(value)))) if not projection_bounds.empty else -1
        out["projection_bucket_train"] = out["projection"].map(projection_bucket)
        position_bias = train.groupby("position", observed=True).filter(lambda x: len(x) >= 30).groupby("position", observed=True).apply(lambda x: float((x["actual"] - x["projection"]).mean()), include_groups=False).to_dict()
        out["bias_position"] = out["position"].map(position_bias).fillna(overall_bias)
        out["projection_bias_corrected_position"] = out["projection"] + out["bias_position"]
        out["edge_bias_corrected_position"] = out["projection_bias_corrected_position"] - out["line"]
        projection_bucket_bias = train.groupby("projection_bucket_train", observed=True).apply(lambda x: float((x["actual"] - x["projection"]).mean()), include_groups=False).to_dict()
        out["bias_projection_bucket"] = out["projection_bucket_train"].map(projection_bucket_bias).fillna(overall_bias)
        out["projection_bias_corrected_projection_bucket"] = out["projection"] + out["bias_projection_bucket"]
        out["edge_bias_corrected_projection_bucket"] = out["projection_bias_corrected_projection_bucket"] - out["line"]
        frames.append(out)
    return pd.concat(frames, ignore_index=True)


def build_candidate_predictions(line_rows: pd.DataFrame, split_name: str) -> pd.DataFrame:
    frames = []
    for market, group in line_rows.groupby("market", observed=True):
        train = group[group["split"].eq("train")].copy()
        test = group[group["split"].eq(split_name)].copy()
        if test.empty:
            continue
        side_test = to_side_rows(test)
        candidates = []
        for name, edge_col in [
            ("raw_projection_edge", "projection_edge"),
            ("bias_corrected_overall", "edge_bias_corrected_overall"),
            ("bias_corrected_position", "edge_bias_corrected_position"),
            ("bias_corrected_projection_bucket", "edge_bias_corrected_projection_bucket"),
            ("relative_edge", "relative_edge"),
            ("standardized_edge", "standardized_edge"),
        ]:
            temp = side_test.copy()
            temp["candidate"] = name
            source = test.set_index(["season", "week", "player_norm", "line"])[edge_col]
            temp = temp.join(source, on=["season", "week", "player_norm", "line"], rsuffix="_candidate")
            temp["score"] = temp[edge_col] * temp["side_sign"]
            temp["predicted_win"] = temp["score"] > 0
            temp["predicted_margin"] = temp[edge_col]
            candidates.append(temp)
        for alpha in [0.25, 0.5, 0.75, 1.0]:
            temp = side_test.copy()
            temp["candidate"] = f"line_blend_alpha_{alpha:.2f}"
            temp["predicted_margin"] = temp["projection_edge"] * alpha
            temp["score"] = temp["predicted_margin"] * temp["side_sign"]
            temp["predicted_win"] = temp["score"] > 0
            candidates.append(temp)
        if len(train) >= MIN_TRAIN_ROWS:
            train_model = train.copy()
            train_model["target_margin"] = train_model["actual_minus_line"]
            linear_features = ["projection_edge", "line"]
            linear_coef = fit_linear_model(train_model, linear_features, "target_margin", ridge=1e-6)
            prediction_key = ["season", "week", "player_norm", "line"]
            line_predictions = test[prediction_key].copy()
            line_predictions["line_predicted_margin"] = predict_linear(test, linear_features, linear_coef)
            temp = side_test.copy()
            temp["candidate"] = "linear_margin_edge_line"
            temp = temp.merge(line_predictions, on=prediction_key, how="left")
            temp["predicted_margin"] = temp["line_predicted_margin"]
            temp = temp.drop(columns=["line_predicted_margin"])
            temp["score"] = temp["predicted_margin"] * temp["side_sign"]
            temp["predicted_win"] = temp["score"] > 0
            candidates.append(temp)

            context_features = ["projection_edge", "line", "team_spread", "game_total", "team_total", "is_home", "is_favorite", *ROLLING_CONTEXT_COLS]
            usable_features = [col for col in context_features if train_model[col].notna().mean() >= 0.8 and test[col].notna().mean() >= 0.8]
            if len(usable_features) >= 2:
                linear_context_coef = fit_linear_model(train_model, usable_features, "target_margin", ridge=1.0)
                context_predictions = test[prediction_key].copy()
                context_predictions["line_predicted_margin"] = predict_linear(test, usable_features, linear_context_coef)
                temp = side_test.copy()
                temp["candidate"] = "linear_margin_context"
                temp = temp.merge(context_predictions, on=prediction_key, how="left")
                temp["predicted_margin"] = temp["line_predicted_margin"]
                temp = temp.drop(columns=["line_predicted_margin"])
                temp["score"] = temp["predicted_margin"] * temp["side_sign"]
                temp["predicted_win"] = temp["score"] > 0
                candidates.append(temp)

            side_train = to_side_rows(train_model)
            side_train["signed_edge"] = side_train["projection_edge"] * side_train["side_sign"]
            side_train["signed_relative_edge"] = side_train["relative_edge"] * side_train["side_sign"]
            side_test_logit = side_test.copy()
            side_test_logit["signed_edge"] = side_test_logit["projection_edge"] * side_test_logit["side_sign"]
            side_test_logit["signed_relative_edge"] = side_test_logit["relative_edge"] * side_test_logit["side_sign"]
            logit_features = ["signed_edge", "line", "side_sign"]
            logit_coef = fit_logistic_model(side_train, logit_features, "won", ridge=1.0)
            temp = side_test_logit.copy()
            temp["candidate"] = "logistic_direction_edge_line_side"
            temp["score"] = predict_logistic_score(temp, logit_features, logit_coef)
            temp["predicted_margin"] = temp["score"] * temp["side_sign"]
            temp["predicted_win"] = temp["score"] > 0
            candidates.append(temp)
        frames.append(pd.concat(candidates, ignore_index=True))
    return pd.concat(frames, ignore_index=True)


def candidate_metrics(predictions: pd.DataFrame, label: str) -> pd.DataFrame:
    rows = []
    for (market, candidate), group in predictions.groupby(["market", "candidate"], observed=True):
        line_level = group[group["side"].eq("over")].copy()
        rows.append({
            "evaluation": label,
            "market": market,
            "candidate": candidate,
            **metric_row(group, "score"),
            **margin_metrics(line_level, "predicted_margin"),
        })
    return pd.DataFrame(rows)


def side_diagnostics(predictions: pd.DataFrame, label: str) -> pd.DataFrame:
    rows = []
    for (market, candidate, side), group in predictions.groupby(["market", "candidate", "side"], observed=True):
        rows.append({"evaluation": label, "market": market, "candidate": candidate, "side": side, **metric_row(group, "score")})
    return pd.DataFrame(rows)


def bucket_diagnostics(predictions: pd.DataFrame, label: str, candidate: str = "raw_projection_edge") -> pd.DataFrame:
    work = predictions[predictions["candidate"].eq(candidate)].copy()
    rows = []
    for market, group in work.groupby("market", observed=True):
        over_lines = group[group["side"].eq("over")].copy()
        over_lines["abs_score_bucket"] = pd.qcut(over_lines["score"].abs(), q=3, duplicates="drop")
        over_lines["line_bucket"] = pd.qcut(over_lines["line"], q=3, duplicates="drop")
        for bucket_col in ["abs_score_bucket", "line_bucket"]:
            for bucket, line_group in over_lines.groupby(bucket_col, observed=True):
                side_group = group.merge(line_group[["season", "week", "player_norm", "line"]], on=["season", "week", "player_norm", "line"], how="inner")
                rows.append({
                    "evaluation": label,
                    "market": market,
                    "candidate": candidate,
                    "bucket_type": bucket_col,
                    "bucket": str(bucket),
                    **metric_row(side_group, "score"),
                    "mean_abs_projection_edge": float(line_group["projection_edge"].abs().mean()),
                    "median_abs_projection_edge": float(line_group["projection_edge"].abs().median()),
                })
    return pd.DataFrame(rows)


def position_diagnostics(predictions: pd.DataFrame, label: str, candidate: str = "raw_projection_edge") -> pd.DataFrame:
    work = predictions[predictions["candidate"].eq(candidate)].copy()
    rows = []
    for (market, position), group in work.groupby(["market", "position"], observed=True):
        if len(group) < 20:
            continue
        rows.append({"evaluation": label, "market": market, "position": position, **metric_row(group, "score")})
    return pd.DataFrame(rows)


def bias_diagnostics(line_rows: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (market, split), group in line_rows.groupby(["market", "split"], observed=True):
        rows.append({
            "market": market,
            "split": split,
            "segment": "overall",
            "segment_value": "overall",
            "n": int(len(group)),
            "mean_actual_minus_projection": float((group["actual"] - group["projection"]).mean()),
            "mean_actual_minus_line": float(group["actual_minus_line"].mean()),
            "mean_projection_edge": float(group["projection_edge"].mean()),
            "mae_projection": float((group["actual"] - group["projection"]).abs().mean()),
        })
        for position, pos_group in group.groupby("position", observed=True):
            if len(pos_group) >= 20:
                rows.append({
                    "market": market,
                    "split": split,
                    "segment": "position",
                    "segment_value": position,
                    "n": int(len(pos_group)),
                    "mean_actual_minus_projection": float((pos_group["actual"] - pos_group["projection"]).mean()),
                    "mean_actual_minus_line": float(pos_group["actual_minus_line"].mean()),
                    "mean_projection_edge": float(pos_group["projection_edge"].mean()),
                    "mae_projection": float((pos_group["actual"] - pos_group["projection"]).abs().mean()),
                })
    return pd.DataFrame(rows)


def walk_forward_predictions(line_rows: pd.DataFrame, min_train_weeks: int = 4) -> pd.DataFrame:
    frames = []
    for market, group in line_rows.groupby("market", observed=True):
        weeks = sorted(int(value) for value in group["week"].dropna().unique())
        for week in weeks:
            prior_weeks = [value for value in weeks if value < week]
            if len(prior_weeks) < min_train_weeks:
                continue
            train = group[group["week"].isin(prior_weeks)].copy()
            test = group[group["week"].eq(week)].copy()
            if len(train) < MIN_TRAIN_ROWS or test.empty:
                continue
            temp = pd.concat([train.assign(split="train"), test.assign(split="walk_forward")], ignore_index=True)
            frames.append(build_candidate_predictions(temp, "walk_forward").assign(walk_forward_week=week))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def bootstrap_comparisons(predictions: pd.DataFrame, iterations: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    metrics = candidate_metrics(predictions, "final_holdout")
    baseline = metrics[metrics["candidate"].eq("raw_projection_edge")].set_index("market")
    side_keys = ["season", "week", "player_norm", "line", "side"]
    line_keys = ["season", "week", "player_norm", "line"]
    for (market, candidate), group in predictions.groupby(["market", "candidate"], observed=True):
        if candidate == "raw_projection_edge" or market not in baseline.index:
            continue
        raw = predictions[(predictions["market"].eq(market)) & predictions["candidate"].eq("raw_projection_edge")].sort_values(side_keys).reset_index(drop=True)
        cand = group.sort_values(side_keys).reset_index(drop=True)
        if len(cand) != len(raw) or cand.empty:
            continue
        cand_metric = metrics[(metrics["market"].eq(market)) & metrics["candidate"].eq(candidate)].iloc[0]
        raw_metric = baseline.loc[market]
        cand_won = cand["won"].astype(bool).to_numpy()
        cand_pred = cand["predicted_win"].astype(bool).to_numpy()
        raw_pred = raw["predicted_win"].astype(bool).to_numpy()
        cand_score = cand["score"].astype(float).to_numpy()
        raw_score = raw["score"].astype(float).to_numpy()
        cand_lines = cand[cand["side"].eq("over")].sort_values(line_keys).reset_index(drop=True)
        raw_lines = raw[raw["side"].eq("over")].sort_values(line_keys).reset_index(drop=True)
        cand_margin_error = (cand_lines["predicted_margin"].astype(float) - cand_lines["actual_minus_line"].astype(float)).abs().to_numpy()
        raw_margin_error = (raw_lines["predicted_margin"].astype(float) - raw_lines["actual_minus_line"].astype(float)).abs().to_numpy()
        diffs = {"accuracy_diff": [], "auc_diff": [], "mae_diff": []}
        for _ in range(iterations):
            idx = rng.integers(0, len(cand), len(cand))
            line_idx = rng.integers(0, len(cand_lines), len(cand_lines))
            diffs["accuracy_diff"].append(float((cand_pred[idx] == cand_won[idx]).mean() - (raw_pred[idx] == cand_won[idx]).mean()))
            diffs["auc_diff"].append(float(roc_auc_score_binary(pd.Series(cand_won[idx]), pd.Series(cand_score[idx])) - roc_auc_score_binary(pd.Series(cand_won[idx]), pd.Series(raw_score[idx]))))
            diffs["mae_diff"].append(float(cand_margin_error[line_idx].mean() - raw_margin_error[line_idx].mean()))
        for metric, values in diffs.items():
            arr = np.asarray(values, dtype=float)
            arr = arr[~np.isnan(arr)]
            if metric == "accuracy_diff":
                observed = float(cand_metric["accuracy"] - raw_metric["accuracy"])
            elif metric == "auc_diff":
                observed = float(cand_metric["auc"] - raw_metric["auc"])
            else:
                observed = float(cand_metric["margin_mae"] - raw_metric["margin_mae"])
            rows.append({
                "market": market,
                "candidate": candidate,
                "metric": metric,
                "observed": observed,
                "ci_low_95": float(np.quantile(arr, 0.025)) if len(arr) else math.nan,
                "ci_high_95": float(np.quantile(arr, 0.975)) if len(arr) else math.nan,
                "iterations": iterations,
                "seed": seed,
            })
    return pd.DataFrame(rows)


def run_audit(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    inventory = feature_inventory(PROJECT_ROOT)
    line_rows, split_report = assign_split(load_historical_rows(PROJECT_ROOT))
    line_rows = add_train_derived_features(line_rows)
    final_predictions = build_candidate_predictions(line_rows, "final_holdout")
    walk_predictions = walk_forward_predictions(line_rows)
    final_metrics = candidate_metrics(final_predictions, "final_holdout")
    edge_transform_candidates = [
        "raw_projection_edge",
        "relative_edge",
        "standardized_edge",
        "line_blend_alpha_0.25",
        "line_blend_alpha_0.50",
        "line_blend_alpha_0.75",
        "line_blend_alpha_1.00",
    ]

    inventory.to_csv(output_dir / "feature_inventory.csv", index=False)
    line_rows.to_csv(output_dir / "historical_evaluation_rows.csv", index=False)
    split_report.to_csv(output_dir / "split_report.csv", index=False)
    bias_diagnostics(line_rows).to_csv(output_dir / "bias_diagnostics.csv", index=False)
    final_metrics.to_csv(output_dir / "final_holdout_metrics.csv", index=False)
    final_metrics.to_csv(output_dir / "candidate_model_metrics.csv", index=False)
    final_metrics[final_metrics["candidate"].eq("raw_projection_edge")].to_csv(output_dir / "baseline_metrics.csv", index=False)
    final_metrics[final_metrics["candidate"].isin(edge_transform_candidates)].to_csv(output_dir / "edge_transform_comparison.csv", index=False)
    side_diagnostics(final_predictions, "final_holdout").to_csv(output_dir / "side_diagnostics.csv", index=False)
    bucket_diagnostics(final_predictions, "final_holdout", "raw_projection_edge").to_csv(output_dir / "line_bucket_diagnostics.csv", index=False)
    position_diagnostics(final_predictions, "final_holdout", "raw_projection_edge").to_csv(output_dir / "position_diagnostics.csv", index=False)
    final_predictions.to_csv(output_dir / "final_holdout_predictions.csv", index=False)
    if not walk_predictions.empty:
        walk_predictions.to_csv(output_dir / "walk_forward_predictions.csv", index=False)
        candidate_metrics(walk_predictions, "walk_forward").to_csv(output_dir / "walk_forward_metrics.csv", index=False)
    else:
        pd.DataFrame().to_csv(output_dir / "walk_forward_predictions.csv", index=False)
        pd.DataFrame().to_csv(output_dir / "walk_forward_metrics.csv", index=False)
    bootstrap_comparisons(final_predictions, args.bootstrap_iterations, BOOTSTRAP_SEED).to_csv(output_dir / "bootstrap_comparisons.csv", index=False)

    final_metrics = pd.read_csv(output_dir / "final_holdout_metrics.csv")
    walk_metrics = pd.read_csv(output_dir / "walk_forward_metrics.csv") if (output_dir / "walk_forward_metrics.csv").stat().st_size > 1 else pd.DataFrame()
    summary = {
        "output_dir": str(output_dir),
        "markets": sorted(MODELED_MARKETS),
        "receptions_excluded": True,
        "split_report": split_report.to_dict(orient="records"),
        "final_holdout_best_by_auc": final_metrics.sort_values(["market", "auc"], ascending=[True, False]).groupby("market", observed=True).head(3).to_dict(orient="records"),
        "final_holdout_best_by_accuracy": final_metrics.sort_values(["market", "accuracy"], ascending=[True, False]).groupby("market", observed=True).head(3).to_dict(orient="records"),
        "walk_forward_best_by_auc": walk_metrics.sort_values(["market", "auc"], ascending=[True, False]).groupby("market", observed=True).head(3).to_dict(orient="records") if not walk_metrics.empty else [],
        "feature_inventory_counts": inventory["availability_class"].value_counts().to_dict(),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit historical projection-vs-market signal for player props")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--bootstrap-iterations", type=int, default=BOOTSTRAP_ITERATIONS)
    args = parser.parse_args()
    summary = run_audit(args)
    print("[output_dir]", summary["output_dir"])
    for row in summary["split_report"]:
        print(
            f"[{row['market']}] train_weeks={row['train_weeks']} final_holdout_weeks={row['final_holdout_weeks']} "
            f"train_rows={row['train_rows']} final_holdout_rows={row['final_holdout_rows']}"
        )


if __name__ == "__main__":
    main()
