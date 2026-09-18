from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pff_content.content_discovery import build_content_discovery
from pff_content.paths import period_output_dir, period_content_dir
from pff_content.periods import Period, period_from_args
from pff_content.week_status import assert_finalized_week


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build period-aware PFF content discovery report.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int)
    parser.add_argument("--through-week", type=int)
    parser.add_argument("--period", choices=["week", "season", "both"], default="week")
    parser.add_argument("--allow-incomplete", action="store_true", help="Allow provisional PFF data for development/testing only.")
    return parser.parse_args()


def read_available_csvs(base: Path) -> dict[str, pd.DataFrame]:
    names = [
        "games",
        "passing",
        "qbs",
        "receiving",
        "rushing",
        "pass_blocking",
        "pass_rush",
        "run_defense",
        "coverage",
        "coverage_scheme",
        "time_in_pocket",
        "team_defense",
        "rookies",
    ]
    data: dict[str, pd.DataFrame] = {}
    for name in names:
        path = base / f"{name}.csv"
        if path.exists():
            data[name] = pd.read_csv(path)
    return data


def main() -> None:
    args = parse_args()
    periods = []
    if args.period == "both":
        week = args.week if args.week is not None else args.through_week
        if week is None:
            raise ValueError("--week or --through-week is required for --period both")
        periods = [Period.week(args.season, week), Period.season_to_date(args.season, week)]
    else:
        periods = [period_from_args(season=args.season, week=args.week, through_week=args.through_week, period=args.period)]
    for period in periods:
        build_period(period, args)


def build_period(period: Period, args: argparse.Namespace) -> None:
    statuses = [assert_finalized_week(period.season, week, allow_incomplete=args.allow_incomplete) for week in period.weeks]
    week_complete = all(status.is_complete for status in statuses)
    base = period_output_dir(period)
    result = build_content_discovery(
        read_available_csvs(base),
        period_content_dir(period),
        season=period.season,
        week=period.end_week,
        week_complete=week_complete,
        docs_dir=ROOT / "docs",
        period=period,
    )
    print(
        json.dumps(
            {
                "season": period.season,
                "period": period.period_type.value,
                "start_week": period.start_week,
                "end_week": period.end_week,
                "week_complete": week_complete,
                "markdown": str(result["markdown"]),
                "csv": str(result["csv"]),
                "manifest": str(result["manifest"]),
                "observation_count": result["observation_count"],
                "observations_by_section": result["observations_by_section"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
