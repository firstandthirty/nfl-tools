import pandas as pd
from pathlib import Path


MERGED_PATH = Path("data/historical_props/merged_props_actuals.csv")
OUT_PATH = Path("data/historical_props/market_results_summary.csv")


def american_profit_per_1_unit(price):
    """
    Profit on a 1-unit bet, not including returned stake.
    -110 -> 0.9091
    +120 -> 1.2
    """
    if pd.isna(price):
        return None

    price = float(price)

    if price < 0:
        return 100 / abs(price)

    return price / 100


def calc_bet_profit(row, side):
    """
    Return profit/loss for a 1-unit bet on Over or Under.
    Push = 0.
    Win = payout based on American odds.
    Loss = -1.
    """
    actual = row["actual_value"]
    line = row["line"]

    if pd.isna(actual) or pd.isna(line):
        return None

    if actual == line:
        return 0

    if side == "over":
        won = actual > line
        price = row["over_price"]
    elif side == "under":
        won = actual < line
        price = row["under_price"]
    else:
        raise ValueError(f"Unknown side: {side}")

    if won:
        return american_profit_per_1_unit(price)

    return -1


def main():
    df = pd.read_csv(MERGED_PATH)

    print(f"[load] rows={len(df):,}")

    snapshot_diff_minutes = (
        (
            pd.to_datetime(df["commence_time"], utc=True) -
            pd.to_datetime(df["actual_snapshot_time"], utc=True)
        )
        .dt.total_seconds()
        / 60
    )

    df["snapshot_diff_minutes"] = snapshot_diff_minutes

    df = df.loc[
        df["snapshot_diff_minutes"].between(20, 45)
    ].copy()

    print("[pre-filter] rows:", len(df))

    df = df.loc[
        (df["over_price"].between(-150, 130)) &
        (df["under_price"].between(-150, 130))
    ].copy()

    print("[post-filter] rows:", len(df))

    print(f"[load] rows={len(df):,}")

    df["over_profit_1u"] = df.apply(
        lambda row: calc_bet_profit(row, "over"),
        axis=1,
    )

    df["under_profit_1u"] = df.apply(
        lambda row: calc_bet_profit(row, "under"),
        axis=1,
    )

    df["went_under"] = (df["actual_value"] < df["line"]).astype(int)
    df["push"] = (df["actual_value"] == df["line"]).astype(int)
    df["actual_minus_line"] = df["actual_value"] - df["line"]

    pass_df = df.loc[
        df["market_key"] == "player_pass_yds"
    ].copy()

    pass_df["line_bucket"] = pd.cut(
        pass_df["line"],
        bins=[0, 200, 225, 250, 275, 999],
        labels=[
            "<200",
            "200-225",
            "225-250",
            "250-275",
            "275+",
        ]
    )

    summary = df.groupby("market_key").agg(
        rows=("market_key", "size"),
        over_rate=("went_over", "mean"),
        under_rate=("went_under", "mean"),
        push_rate=("push", "mean"),
        avg_line=("line", "mean"),
        avg_actual=("actual_value", "mean"),
        avg_actual_minus_line=("actual_minus_line", "mean"),
        avg_over_price=("over_price", "mean"),
        avg_under_price=("under_price", "mean"),
        blind_over_roi=("over_profit_1u", "mean"),
        blind_under_roi=("under_profit_1u", "mean"),
    ).reset_index()

    for col in [
        "over_rate",
        "under_rate",
        "push_rate",
        "avg_line",
        "avg_actual",
        "avg_actual_minus_line",
        "avg_over_price",
        "avg_under_price",
        "blind_over_roi",
        "blind_under_roi",
    ]:
        summary[col] = summary[col].round(4)

    print()
    print("===== Market Results Summary =====")
    print(summary.to_string(index=False))

    print()
    print("===== Overall =====")
    overall = {
        "rows": len(df),
        "over_rate": round(df["went_over"].mean(), 4),
        "under_rate": round(df["went_under"].mean(), 4),
        "push_rate": round(df["push"].mean(), 4),
        "avg_actual_minus_line": round(df["actual_minus_line"].mean(), 4),
        "blind_over_roi": round(df["over_profit_1u"].mean(), 4),
        "blind_under_roi": round(df["under_profit_1u"].mean(), 4),
    }

    for k, v in overall.items():
        print(f"{k}: {v}")

    print()
    print("===== Snapshot Timing =====")

    snapshot_diff = (
        pd.to_datetime(df["commence_time"], utc=True) -
        pd.to_datetime(df["actual_snapshot_time"], utc=True)
    )

    print(snapshot_diff.describe())

    print()
    print("===== Pass Yard Results by Line Bucket =====")

    bucket_summary = pass_df.groupby("line_bucket").agg(
        rows=("line_bucket", "size"),
        over_rate=("went_over", "mean"),
        avg_actual_minus_line=("actual_minus_line", "mean"),
        blind_over_roi=("over_profit_1u", "mean"),
        avg_line=("line", "mean"),
    ).reset_index()

    for col in [
        "over_rate",
        "avg_actual_minus_line",
        "blind_over_roi",
        "avg_line",
    ]:
        bucket_summary[col] = bucket_summary[col].round(4)

    print(bucket_summary.to_string(index=False))

    print()
    print("===== <200 Pass Yard Bucket =====")

    low_qb = pass_df.loc[
        pass_df["line_bucket"] == "<200"
    ].copy()

    cols = [
        "player",
        "home_team",
        "away_team",
        "line",
        "actual_value",
        "actual_minus_line",
        "over_price",
    ]

    print(
        low_qb.sort_values(
            "actual_minus_line",
            ascending=False
        )[cols].to_string(index=False)
    )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(OUT_PATH, index=False)

    print()
    print(f"[saved] {OUT_PATH}")

    print()
    print("===== Biggest Pass Yard Over Results =====")

    pass_df = df.loc[
        df["market_key"] == "player_pass_yds"
    ].copy()

    pass_df["actual_minus_line"] = (
        pass_df["actual_value"] - pass_df["line"]
    )

    cols = [
        "player",
        "home_team",
        "away_team",
        "line",
        "actual_value",
        "actual_minus_line",
        "over_price",
        "under_price",
    ]

    print(
        pass_df.sort_values(
            "actual_minus_line",
            ascending=False
        )[cols].head(25).to_string(index=False)
)


if __name__ == "__main__":
    main()