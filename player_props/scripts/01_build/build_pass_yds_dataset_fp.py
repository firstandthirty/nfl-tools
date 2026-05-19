from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.name_utils import clean_player_name


PROPS_FILE = Path("data/processed/merged_props_with_rolling.csv")
FP_FILE = Path("data/processed/fantasypros_qb_weekly_projections.csv")
OUT_FILE = Path("data/processed/pass_yds_dataset_fp.csv")


def main():
    props = pd.read_csv(PROPS_FILE)
    fp = pd.read_csv(FP_FILE)

    props = props[props["market_key"] == "player_pass_yds"].copy()

    props["player_clean"] = props["player"].apply(clean_player_name)
    fp["player_clean"] = fp["player"].apply(clean_player_name)

    fp_keep = [
        "season",
        "week",
        "player_clean",
        "player",
        "team",
        "fp_pass_att",
        "fp_pass_cmp",
        "fp_pass_yds",
        "fp_pass_tds",
        "fp_pass_ints",
        "fp_rush_att",
        "fp_rush_yds",
        "fp_rush_tds",
        "fp_fumbles_lost",
        "fp_fantasy_points",
    ]

    fp = fp[fp_keep].copy()

    # In case FantasyPros has duplicate player/week rows, keep highest fantasy-point projection
    fp = (
        fp.sort_values(["season", "week", "player_clean", "fp_fantasy_points"], ascending=[True, True, True, False])
        .drop_duplicates(["season", "week", "player_clean"], keep="first")
    )

    merged = props.merge(
        fp,
        on=["season", "week", "player_clean"],
        how="left",
        suffixes=("", "_fp"),
    )

    merged["actual_minus_fp"] = merged["actual_value"] - merged["fp_pass_yds"]
    merged["line_minus_fp"] = merged["line"] - merged["fp_pass_yds"]
    merged["actual_minus_line"] = merged["actual_value"] - merged["line"]

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(OUT_FILE, index=False)

    matched = merged["fp_pass_yds"].notna().sum()

    print("\n===== PASS YDS DATASET FP COMPLETE =====")
    print(f"rows: {len(merged):,}")
    print(f"matched projections: {matched:,}")
    print(f"match rate: {matched / len(merged):.2%}")
    print(f"output: {OUT_FILE}")

    missing = (
        merged[merged["fp_pass_yds"].isna()]
        [["season", "week", "player"]]
        .drop_duplicates()
        .sort_values(["season", "week", "player"])
    )

    if len(missing):
        print("\nMissing projection players:")
        print(missing.to_string(index=False))


if __name__ == "__main__":
    main()