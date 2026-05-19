from pathlib import Path
import json
import numpy as np
import pandas as pd

from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

MARKET = "player_pass_yds"
RANDOM_SEED = 42

INPUT_CANDIDATES = [
    Path("data/processed/merged_props_with_rolling.csv"),
    Path("data/historical_props/merged_props_with_rolling.csv"),
    Path("data/processed/merged_props_with_context.csv"),
    Path("data/historical_props/merged_props_with_context.csv"),
]

OUT_PATH = Path("outputs/simulations/pass_yds_residual_predictions.csv")
META_PATH = Path("models/pass_yds_residual_model_meta.json")

TARGET = "residual_yards"

BASE_FEATURES = [
    "line",
    "team_spread",
    "game_total",
    "team_total",
    "is_home",
    "is_favorite",
    "is_underdog",
]

ROLLING_FEATURES = [
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


def find_input():
    for p in INPUT_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Could not find input file. Tried:\n"
        + "\n".join(f" - {p}" for p in INPUT_CANDIDATES)
    )


def rmse(y_true, y_pred):
    return float(np.sqrt(mean_squared_error(y_true, y_pred)))


def main():
    input_path = find_input()
    print(f"[load] using input: {input_path}")

    df = pd.read_csv(input_path)
    df.columns = [c.strip() for c in df.columns]

    df = df[df["market_key"].eq(MARKET)].copy()
    print(f"[load] pass yards rows={len(df):,}")

    required = ["line", "actual_value", "season", "week"]
    missing_required = [c for c in required if c not in df.columns]
    if missing_required:
        raise ValueError(f"Missing required columns: {missing_required}")

    for c in ["line", "actual_value", "season", "week"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df["residual_yards"] = df["actual_value"] - df["line"]

    for c in ["is_home", "is_favorite", "is_underdog"]:
        if c in df.columns:
            df[c] = df[c].astype(bool).astype(int)

    available_features = [
        c for c in BASE_FEATURES + ROLLING_FEATURES
        if c in df.columns
    ]

    print("\n[features used]")
    for c in available_features:
        print(f" - {c}")

    model_df = df.dropna(subset=["line", "actual_value", TARGET]).copy()

    for c in available_features:
        model_df[c] = pd.to_numeric(model_df[c], errors="coerce")
        if model_df[c].isna().any():
            model_df[c] = model_df[c].fillna(model_df[c].median())

    train = model_df[model_df["week"] <= 13].copy()
    test = model_df[model_df["week"] >= 14].copy()

    if len(test) < 25:
        print("[warn] Small test set. Falling back to 80/20 chronological split.")
        sort_cols = [c for c in ["season", "week", "game_date"] if c in model_df.columns]
        model_df = model_df.sort_values(sort_cols)
        cutoff = int(len(model_df) * 0.8)
        train = model_df.iloc[:cutoff].copy()
        test = model_df.iloc[cutoff:].copy()

    X_train = train[available_features]
    y_train = train[TARGET]

    X_test = test[available_features]
    y_test = test[TARGET]

    model = RandomForestRegressor(
        n_estimators=500,
        min_samples_leaf=10,
        max_features="sqrt",
        random_state=RANDOM_SEED,
        n_jobs=-1,
    )

    model.fit(X_train, y_train)

    train["pred_residual"] = model.predict(X_train)
    test["pred_residual"] = model.predict(X_test)

    train["pred_mean"] = train["line"] + train["pred_residual"]
    test["pred_mean"] = test["line"] + test["pred_residual"]

    # Baseline market prediction:
    # predicted actual = line
    # predicted residual = 0
    market_pred_actual = test["line"]
    market_pred_residual = np.zeros(len(test))

    model_mae_actual = mean_absolute_error(test["actual_value"], test["pred_mean"])
    market_mae_actual = mean_absolute_error(test["actual_value"], market_pred_actual)

    model_rmse_actual = rmse(test["actual_value"], test["pred_mean"])
    market_rmse_actual = rmse(test["actual_value"], market_pred_actual)

    model_r2_actual = r2_score(test["actual_value"], test["pred_mean"])
    market_r2_actual = r2_score(test["actual_value"], market_pred_actual)

    model_mae_resid = mean_absolute_error(y_test, test["pred_residual"])
    zero_mae_resid = mean_absolute_error(y_test, market_pred_residual)

    model_rmse_resid = rmse(y_test, test["pred_residual"])
    zero_rmse_resid = rmse(y_test, market_pred_residual)

    model_r2_resid = r2_score(y_test, test["pred_residual"])

    train["residual_error"] = train[TARGET] - train["pred_residual"]
    residual_std = float(train["residual_error"].std(ddof=1))

    print("\n===== TEST SET: ACTUAL YARDS PREDICTION =====")
    print(f"rows:         {len(test):,}")
    print(f"model MAE:    {model_mae_actual:.2f}")
    print(f"market MAE:   {market_mae_actual:.2f}")
    print(f"model RMSE:   {model_rmse_actual:.2f}")
    print(f"market RMSE:  {market_rmse_actual:.2f}")
    print(f"model R2:     {model_r2_actual:.3f}")
    print(f"market R2:    {market_r2_actual:.3f}")

    print("\n===== TEST SET: RESIDUAL PREDICTION =====")
    print(f"model residual MAE:   {model_mae_resid:.2f}")
    print(f"zero residual MAE:    {zero_mae_resid:.2f}")
    print(f"model residual RMSE:  {model_rmse_resid:.2f}")
    print(f"zero residual RMSE:   {zero_rmse_resid:.2f}")
    print(f"model residual R2:    {model_r2_resid:.3f}")
    print(f"train residual std:   {residual_std:.2f}")

    full = model_df.copy()
    full["pred_residual"] = model.predict(full[available_features])
    full["pred_mean"] = full["line"] + full["pred_residual"]
    full["pred_std"] = residual_std
    full["model_edge_yards"] = full["pred_mean"] - full["line"]

    # This is the same as pred_residual, but named explicitly.
    full["market_error_estimate"] = full["pred_residual"]

    keep_cols = [
        "season",
        "week",
        "game_date",
        "player",
        "recent_team",
        "home_team_abbr",
        "away_team_abbr",
        "market_key",
        "line",
        "over_price",
        "under_price",
        "actual_value",
        "residual_yards",
        "went_over",
        "push",
        "team_spread",
        "game_total",
        "team_total",
        "is_home",
        "is_favorite",
        "is_underdog",
        *available_features,
        "pred_residual",
        "pred_mean",
        "pred_std",
        "model_edge_yards",
        "market_error_estimate",
    ]

    # de-dupe while preserving order
    seen = set()
    keep_cols = [c for c in keep_cols if c in full.columns and not (c in seen or seen.add(c))]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    full[keep_cols].to_csv(OUT_PATH, index=False)

    importances = (
        pd.DataFrame({
            "feature": available_features,
            "importance": model.feature_importances_,
        })
        .sort_values("importance", ascending=False)
    )

    meta = {
        "market": MARKET,
        "input_path": str(input_path),
        "features": available_features,
        "target": TARGET,
        "rows_total": int(len(model_df)),
        "rows_train": int(len(train)),
        "rows_test": int(len(test)),
        "model_mae_actual": float(model_mae_actual),
        "market_mae_actual": float(market_mae_actual),
        "model_rmse_actual": float(model_rmse_actual),
        "market_rmse_actual": float(market_rmse_actual),
        "model_r2_actual": float(model_r2_actual),
        "market_r2_actual": float(market_r2_actual),
        "model_mae_residual": float(model_mae_resid),
        "zero_mae_residual": float(zero_mae_resid),
        "model_rmse_residual": float(model_rmse_resid),
        "zero_rmse_residual": float(zero_rmse_resid),
        "model_r2_residual": float(model_r2_resid),
        "train_residual_std": residual_std,
        "feature_importances": importances.to_dict(orient="records"),
    }

    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\n[saved] {OUT_PATH}")
    print(f"[saved] {META_PATH}")

    print("\n===== FEATURE IMPORTANCE =====")
    print(importances.to_string(index=False))

    print("\n===== BIGGEST POSITIVE MARKET ERROR ESTIMATES =====")
    show_cols = [
        "week",
        "player",
        "recent_team",
        "line",
        "actual_value",
        "residual_yards",
        "pred_residual",
        "pred_mean",
        "team_spread",
        "team_total",
    ]
    show_cols = [c for c in show_cols if c in full.columns]
    print(
        full.sort_values("pred_residual", ascending=False)
        [show_cols]
        .head(20)
        .to_string(index=False)
    )

    print("\n===== BIGGEST NEGATIVE MARKET ERROR ESTIMATES =====")
    print(
        full.sort_values("pred_residual", ascending=True)
        [show_cols]
        .head(20)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()