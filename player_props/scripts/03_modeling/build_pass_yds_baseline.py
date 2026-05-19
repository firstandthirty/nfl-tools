from pathlib import Path
import json

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

INPUT = Path("data/historical_props/merged_props_with_rolling.csv")
OUT_PATH = Path("data/historical_props/pass_yds_baseline_predictions.csv")
MODEL_META_PATH = Path("data/historical_props/pass_yds_baseline_model_meta.json")

MARKET = "player_pass_yds"
RANDOM_SEED = 42

FEATURES = [
    "line",
    "team_spread",
    "game_total",
    "team_total",
    "is_home",
    "is_favorite",
    "is_underdog",
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

TARGET = "actual_value"


def american_implied_prob(price):
    price = float(price)
    if price < 0:
        return abs(price) / (abs(price) + 100)
    return 100 / (price + 100)


def main():
    if not INPUT.exists():
        raise FileNotFoundError(f"Missing input file: {INPUT}")

    df = pd.read_csv(INPUT)
    df.columns = [c.strip() for c in df.columns]

    df = df[df["market_key"].eq(MARKET)].copy()

    print(f"[load] pass yards rows={len(df):,}")

    missing = [c for c in FEATURES + [TARGET] if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}\nAvailable: {list(df.columns)}")

    # Clean booleans
    for c in ["is_home", "is_favorite", "is_underdog"]:
        df[c] = df[c].astype(bool).astype(int)

    # Basic numeric cleanup
    for c in FEATURES + [TARGET, "over_price", "under_price"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    model_df = df.dropna(subset=["line", TARGET]).copy()

    # Fill weather/context missing values with medians.
    for c in FEATURES:
        if c not in model_df.columns:
            continue
        if model_df[c].isna().any():
            model_df[c] = model_df[c].fillna(model_df[c].median())

    # Time-ish split by week. Simple first version.
    train = model_df[model_df["week"] <= 13].copy()
    test = model_df[model_df["week"] >= 14].copy()

    if len(test) < 25:
        print("[warn] Small test set. Falling back to 80/20 chronological split.")
        model_df = model_df.sort_values(["season", "week", "game_date"])
        cutoff = int(len(model_df) * 0.8)
        train = model_df.iloc[:cutoff].copy()
        test = model_df.iloc[cutoff:].copy()

    X_train = train[FEATURES]
    y_train = train[TARGET]

    X_test = test[FEATURES]
    y_test = test[TARGET]

    model = RandomForestRegressor(
        n_estimators=500,
        min_samples_leaf=8,
        random_state=RANDOM_SEED,
        n_jobs=-1,
    )

    model.fit(X_train, y_train)

    train["pred_mean"] = model.predict(X_train)
    test["pred_mean"] = model.predict(X_test)

    # Residual-based std estimate.
    # First version: global residual std.
    train["residual"] = train[TARGET] - train["pred_mean"]
    global_std = float(train["residual"].std(ddof=1))

    # Add a slightly line-sensitive std estimate.
    # Lower lines tend to be more volatile relative to expectation.
    test["pred_std"] = global_std
    train["pred_std"] = global_std

    # Market baseline assumes mean = line.
    model_mae = mean_absolute_error(y_test, test["pred_mean"])
    market_mae = mean_absolute_error(y_test, test["line"])

    model_rmse = np.sqrt(mean_squared_error(y_test, test["pred_mean"]))
    market_rmse = np.sqrt(mean_squared_error(y_test, test["line"]))

    model_r2 = r2_score(y_test, test["pred_mean"])
    market_r2 = r2_score(y_test, test["line"])

    print("\n===== TEST SET EVALUATION =====")
    print(f"rows:        {len(test):,}")
    print(f"model MAE:   {model_mae:.2f}")
    print(f"market MAE:  {market_mae:.2f}")
    print(f"model RMSE:  {model_rmse:.2f}")
    print(f"market RMSE: {market_rmse:.2f}")
    print(f"model R2:    {model_r2:.3f}")
    print(f"market R2:   {market_r2:.3f}")
    print(f"pred_std:    {global_std:.2f}")

    # Score full dataset
    full = model_df.copy()
    full["pred_mean"] = model.predict(full[FEATURES])
    full["pred_std"] = global_std
    full["model_edge_yards"] = full["pred_mean"] - full["line"]

    if "over_price" in full.columns:
        full["market_over_prob"] = full["over_price"].apply(american_implied_prob)
    if "under_price" in full.columns:
        full["market_under_prob"] = full["under_price"].apply(american_implied_prob)

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
        "went_over",
        "push",
        "team_spread",
        "game_total",
        "team_total",
        "is_home",
        "is_favorite",
        "is_underdog",
        "temp",
        "wind",
        "pred_mean",
        "pred_std",
        "model_edge_yards",
    ]

    keep_cols = [c for c in keep_cols if c in full.columns]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    full[keep_cols].to_csv(OUT_PATH, index=False)

    meta = {
        "market": MARKET,
        "features": FEATURES,
        "target": TARGET,
        "rows_total": int(len(model_df)),
        "rows_train": int(len(train)),
        "rows_test": int(len(test)),
        "model_mae": model_mae,
        "market_mae": market_mae,
        "model_rmse": model_rmse,
        "market_rmse": market_rmse,
        "model_r2": model_r2,
        "market_r2": market_r2,
        "global_pred_std": global_std,
    }

    with open(MODEL_META_PATH, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\n[saved] {OUT_PATH}")
    print(f"[saved] {MODEL_META_PATH}")

    print("\n===== BIGGEST MODEL OVER EDGES =====")
    print(
        full.sort_values("model_edge_yards", ascending=False)
        [
            [
                "week",
                "player",
                "recent_team",
                "line",
                "actual_value",
                "pred_mean",
                "model_edge_yards",
                "team_spread",
                "team_total",
            ]
        ]
        .head(20)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()