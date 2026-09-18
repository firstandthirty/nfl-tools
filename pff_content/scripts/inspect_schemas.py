from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pff_content.paths import processed_week_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect processed weekly PFF schema inventory.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = processed_week_dir(args.season, args.week) / "schema_inventory.csv"
    if not path.exists():
        raise RuntimeError(f"Missing schema inventory: {path}")
    df = pd.read_csv(path)
    print(df.groupby("dataset")["raw_field"].count().to_string())


if __name__ == "__main__":
    main()
