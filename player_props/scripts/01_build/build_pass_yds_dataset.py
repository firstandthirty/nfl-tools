from pathlib import Path
import sys

import pandas as pd


# ------------------------------------------------------------
# Project root imports
# ------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.name_utils import clean_player_name


# ------------------------------------------------------------
# File paths
# ------------------------------------------------------------
FFA_FILE = Path("data/processed/ffa_weekly_projections.csv")

PROPS_FILE = Path(
    "data/processed/merged_props_with_rolling.csv"
)

OUT_DIR = Path("data/processed")
OUT_FILE = OUT_DIR / "pass_yds_dataset.csv"


def main():

    print("[load] reading FFA projections...")
    ffa = pd.read_csv(FFA_FILE)

    print("[load] reading props dataset...")
    props = pd.read_csv(PROPS_FILE)

    # --------------------------------------------------------
    # Filter FFA to QBs only
    # --------------------------------------------------------
    ffa = ffa[ffa["position"] == "QB"].copy()

    # --------------------------------------------------------
    # Filter props to passing yards only
    # --------------------------------------------------------
    props = props[
        props["market_key"] == "player_pass_yds"
    ].copy()

    # --------------------------------------------------------
    # Normalize names
    # --------------------------------------------------------
    ffa["player_clean"] = (
        ffa["player"]
        .apply(clean_player_name)
    )

    props["player_clean"] = (
        props["player"]
        .apply(clean_player_name)
    )

    # --------------------------------------------------------
    # Rename FFA projection columns
    # --------------------------------------------------------
    ffa = ffa.rename(columns={
        "points": "ffa_points",
        "sd_pts": "ffa_sd_pts",
        "floor": "ffa_floor",
        "ceiling": "ffa_ceiling",
        "uncertainty": "ffa_uncertainty",
        "rank": "ffa_rank",
        "tier": "ffa_tier",
    })

    # --------------------------------------------------------
    # Keep only needed FFA cols
    # --------------------------------------------------------
    ffa_keep = [
        "season",
        "week",
        "player_clean",
        "player",
        "team",
        "ffa_points",
        "ffa_sd_pts",
        "ffa_floor",
        "ffa_ceiling",
        "ffa_uncertainty",
        "ffa_rank",
        "ffa_tier",
    ]

    ffa = ffa[ffa_keep].copy()

    # --------------------------------------------------------
    # Merge
    # --------------------------------------------------------
    print("[merge] joining projections to props...")

    merged = props.merge(
        ffa,
        on=["season", "week", "player_clean"],
        how="left",
        suffixes=("", "_ffa")
    )

    # --------------------------------------------------------
    # Core target variables
    # --------------------------------------------------------
    merged["actual_minus_line"] = (
        merged["actual_value"] - merged["line"]
    )

    # --------------------------------------------------------
    # Sort
    # --------------------------------------------------------
    merged = merged.sort_values(
        ["season", "week", "player"]
    )

    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    merged.to_csv(OUT_FILE, index=False)

    # --------------------------------------------------------
    # Diagnostics
    # --------------------------------------------------------
    print("\n===== PASS YDS DATASET COMPLETE =====")

    print(f"rows: {len(merged):,}")

    matched = merged["ffa_points"].notna().sum()

    print(f"matched projections: {matched:,}")
    print(f"match rate: {matched / len(merged):.2%}")

    print(f"\noutput: {OUT_FILE}")

    missing = (
        merged[merged["ffa_points"].isna()]
        [["season", "week", "player"]]
        .drop_duplicates()
    )

    print(f"\nmissing projection rows: {len(missing):,}")

    if len(missing):
        print("\nSample missing players:")
        print(missing.head(20).to_string(index=False))


if __name__ == "__main__":
    main()