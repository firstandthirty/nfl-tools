import pandas as pd
import numpy as np
from pathlib import Path

INPUT = Path("data/historical_props/merged_props_with_context.csv")
OUTDIR = Path("outputs/context")
OUTDIR.mkdir(parents=True, exist_ok=True)

MARKET = "player_pass_yds"


def american_profit(price):
    price = float(price)
    if price > 0:
        return price / 100
    return 100 / abs(price)


def spread_bucket(x):
    if pd.isna(x):
        return "unknown"
    x = float(x)

    # assuming spread is from player's team perspective:
    # negative = favorite, positive = underdog
    if x <= -10:
        return "fav_10+"
    if x <= -7:
        return "fav_7_to_10"
    if x <= -3:
        return "fav_3_to_7"
    if x < 3:
        return "pickem"
    if x < 7:
        return "dog_3_to_7"
    if x < 10:
        return "dog_7_to_10"
    return "dog_10+"


def total_bucket(x):
    if pd.isna(x):
        return "unknown"
    x = float(x)
    if x < 38:
        return "under_38"
    if x < 42:
        return "38_to_42"
    if x < 46:
        return "42_to_46"
    if x < 50:
        return "46_to_50"
    return "50+"


def line_bucket(x):
    if pd.isna(x):
        return "unknown"
    x = float(x)
    if x < 180:
        return "under_180"
    if x < 210:
        return "180_to_210"
    if x < 240:
        return "210_to_240"
    if x < 270:
        return "240_to_270"
    return "270+"


def summarize(df, group_cols):
    g = df.groupby(group_cols, dropna=False)

    out = g.agg(
        rows=("actual", "size"),
        over_rate=("is_over", "mean"),
        avg_line=("line", "mean"),
        avg_actual=("actual", "mean"),
        avg_actual_minus_line=("actual_minus_line", "mean"),
        avg_over_price=("over_price", "mean"),
        avg_under_price=("under_price", "mean"),
        blind_over_roi=("over_profit", "mean"),
        blind_under_roi=("under_profit", "mean"),
    ).reset_index()

    return out.sort_values(["blind_over_roi", "rows"], ascending=[False, False])


df = pd.read_csv(INPUT)

# ---- normalize column names if needed ----
df.columns = [c.strip() for c in df.columns]

# adjust these if your file names differ
required = [
    "market_key",
    "line",
    "actual_value",
    "over_price",
    "under_price",
]

missing = [c for c in required if c not in df.columns]
if missing:
    raise ValueError(f"Missing required columns: {missing}\nAvailable: {list(df.columns)}")

df = df[df["market_key"].eq(MARKET)].copy()
df["actual"] = df["actual_value"]

# These are the key context columns.
# Rename here if your dataset uses different names.
# if "team_spread" not in df.columns:
#     possible = ["spread", "player_team_spread", "closing_spread"]
#     found = next((c for c in possible if c in df.columns), None)
#     if found:
#         df["team_spread"] = df[found]
#     else:
#         raise ValueError("Need a team spread column. Expected team_spread, spread, player_team_spread, or closing_spread.")

# if "game_total" not in df.columns:
#     possible = ["total", "closing_total", "over_under"]
#     found = next((c for c in possible if c in df.columns), None)
#     if found:
#         df["game_total"] = df[found]
#     else:
#         raise ValueError("Need a game total column. Expected game_total, total, closing_total, or over_under.")

# ---- results flags ----
df["actual_minus_line"] = df["actual"] - df["line"]
df["is_over"] = df["went_over"].astype(bool)
df["is_push"] = df["push"].astype(bool)
df["is_under"] = (~df["is_over"]) & (~df["is_push"])

df["over_profit"] = np.where(
    df["is_push"],
    0,
    np.where(df["is_over"], df["over_price"].apply(american_profit), -1)
)

df["under_profit"] = np.where(
    df["is_push"],
    0,
    np.where(df["is_under"], df["under_price"].apply(american_profit), -1)
)

# ---- engineered features ----
# df["spread_bucket"] = df["team_spread"].apply(spread_bucket)
# df["game_total_bucket"] = df["game_total"].apply(total_bucket)
df["line_bucket"] = df["line"].apply(line_bucket)
df["is_home"] = df["recent_team"] == df["home_team_abbr"]

# implied team total:
# team_total = game_total / 2 - team_spread / 2
# because negative spread means favorite
# df["team_total"] = (df["game_total"] / 2) - (df["team_spread"] / 2)

# df["team_total_bucket"] = pd.cut(
#     df["team_total"],
#     bins=[-999, 17, 20, 24, 28, 999],
#     labels=["under_17", "17_to_20", "20_to_24", "24_to_28", "28+"]
# )

# ---- outputs ----
df["spread_bucket"] = df["team_spread"].apply(spread_bucket)
df["game_total_bucket"] = df["game_total"].apply(total_bucket)

df["team_total_bucket"] = pd.cut(
    df["team_total"],
    bins=[-999, 17, 20, 24, 28, 999],
    labels=["under_17", "17_to_20", "20_to_24", "24_to_28", "28+"]
)

tables = {
    "line": summarize(df, ["line_bucket"]),
    "spread": summarize(df, ["spread_bucket"]),
    "team_total": summarize(df, ["team_total_bucket"]),
    "game_total": summarize(df, ["game_total_bucket"]),
    "spread_x_line": summarize(df, ["spread_bucket", "line_bucket"]),
    "spread_x_team_total": summarize(df, ["spread_bucket", "team_total_bucket"]),
    "spread_x_game_total": summarize(df, ["spread_bucket", "game_total_bucket"]),
    "line_x_home_away": summarize(df, ["line_bucket", "is_home"]),
}

for name, table in tables.items():
    path = OUTDIR / f"pass_yds_{name}.csv"
    table.to_csv(path, index=False)
    print(f"\n===== {name.upper()} =====")
    print(table.head(25).to_string(index=False))
    print(f"[saved] {path}")

featured = tables["line_x_home_away"]
featured = featured[featured["rows"] >= 20].copy()

print("\n===== BEST CONTEXT BUCKETS, MIN 20 ROWS =====")
print(
    featured[
        [
            "line_bucket",
            "is_home",
            "rows",
            "over_rate",
            "avg_line",
            "avg_actual",
            "avg_actual_minus_line",
            "blind_over_roi",
            "blind_under_roi",
        ]
    ]
    .sort_values("blind_over_roi", ascending=False)
    .head(20)
    .to_string(index=False)
)