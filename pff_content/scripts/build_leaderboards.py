from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pff_content.leaderboards import build_all_leaderboards
from pff_content.paths import week_label
from pff_content.week_status import assert_finalized_week


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build social-ready weekly leaderboard graphics from analysis CSVs.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--allow-incomplete", action="store_true", help="Allow provisional PFF data for development/testing only.")
    return parser.parse_args()


def analysis_dir(season: int, week: int) -> Path:
    return ROOT / "outputs" / str(season) / week_label(week)


def leaderboard_dir(season: int, week: int) -> Path:
    return analysis_dir(season, week) / "leaderboards"


def read_analysis_csv(base: Path, name: str) -> pd.DataFrame:
    path = base / f"{name}.csv"
    if not path.exists():
        raise RuntimeError(f"Missing analysis {name} file at {path}. Run scripts/build_weekly_analysis.py first.")
    return pd.read_csv(path)


def main() -> None:
    args = parse_args()
    assert_finalized_week(args.season, args.week, allow_incomplete=args.allow_incomplete)
    base = analysis_dir(args.season, args.week)
    data = {
        "receiving": read_analysis_csv(base, "receiving"),
        "rushing": read_analysis_csv(base, "rushing"),
        "pass_rush": read_analysis_csv(base, "pass_rush"),
    }
    out = leaderboard_dir(args.season, args.week)
    results = build_all_leaderboards(data, out, season=args.season, week=args.week, use_bars=True)
    print(
        json.dumps(
            {
                "season": args.season,
                "week": args.week,
                "leaderboards": [
                    {
                        "id": result.definition.id,
                        "png": str(result.png_path),
                        "csv": str(result.csv_path),
                        "rows": int(len(result.rows)),
                    }
                    for result in results
                ],
                "manifest": str(out / "manifest.json"),
                "content_ideas": str(out / "content_ideas.md"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
