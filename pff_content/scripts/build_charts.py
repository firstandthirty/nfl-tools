from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pff_content.charts import (
    build_coverage_targets_vs_passer_rating_chart,
    build_pass_rush_win_rate_vs_pressure_rate_chart,
    build_qb_pressure_rate_vs_time_to_throw_chart,
    build_qb_twp_vs_interceptions_chart,
    build_rb_before_vs_after_contact_chart,
    build_rb_ypa_vs_yaco_chart,
    build_receiving_tprr_vs_yprr_chart,
)
from pff_content.charts.dense_labels import clear_label_stats, label_stats_report
from pff_content.paths import period_chart_dir, period_output_dir
from pff_content.periods import Period, period_from_args
from pff_content.week_status import assert_finalized_week


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build social-ready period-aware PFF charts from analysis CSVs.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int)
    parser.add_argument("--through-week", type=int)
    parser.add_argument("--period", choices=["week", "season", "both"], default="week")
    parser.add_argument("--min-rb-attempts", type=int, default=8)
    parser.add_argument("--min-receiving-routes", type=int, default=15)
    parser.add_argument("--min-pass-rush-snaps", type=int, default=15)
    parser.add_argument("--min-qb-dropbacks", type=int, default=20)
    parser.add_argument("--min-coverage-snaps", type=int, default=20)
    parser.add_argument("--min-coverage-targets", type=int, default=4)
    parser.add_argument("--allow-incomplete", action="store_true", help="Allow provisional PFF data for development/testing only.")
    return parser.parse_args()


def read_analysis_csv(base: Path, name: str) -> pd.DataFrame:
    path = base / f"{name}.csv"
    if not path.exists():
        raise RuntimeError(f"Missing analysis {name} file at {path}. Run scripts/build_weekly_analysis.py first.")
    return pd.read_csv(path)


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
    for week in period.weeks:
        assert_finalized_week(period.season, week, allow_incomplete=args.allow_incomplete)
    base = period_output_dir(period)
    rushing = read_analysis_csv(base, "rushing")
    receiving = read_analysis_csv(base, "receiving")
    pass_rush = read_analysis_csv(base, "pass_rush")
    qbs = read_analysis_csv(base, "qbs")
    coverage = read_analysis_csv(base, "coverage")
    out = period_chart_dir(period)
    clear_label_stats()
    charts = [
        build_rb_ypa_vs_yaco_chart(
            rushing,
            output_dir=out,
            season=period.season,
            week=period.end_week,
            min_attempts=args.min_rb_attempts,
            period_label=period.display_label,
        ),
        build_rb_before_vs_after_contact_chart(
            rushing,
            output_dir=out,
            season=period.season,
            week=period.end_week,
            min_attempts=args.min_rb_attempts,
            period_label=period.display_label,
        ),
        build_receiving_tprr_vs_yprr_chart(
            receiving,
            output_dir=out,
            season=period.season,
            week=period.end_week,
            min_routes=args.min_receiving_routes,
            period_label=period.display_label,
        ),
        build_pass_rush_win_rate_vs_pressure_rate_chart(
            pass_rush,
            output_dir=out,
            season=period.season,
            week=period.end_week,
            min_pass_rush_snaps=args.min_pass_rush_snaps,
            period_label=period.display_label,
        ),
        build_qb_pressure_rate_vs_time_to_throw_chart(
            qbs,
            output_dir=out,
            season=period.season,
            week=period.end_week,
            min_dropbacks=args.min_qb_dropbacks,
            period_label=period.display_label,
        ),
        build_coverage_targets_vs_passer_rating_chart(
            coverage,
            output_dir=out,
            season=period.season,
            week=period.end_week,
            min_coverage_snaps=args.min_coverage_snaps,
            min_targets=args.min_coverage_targets,
            period_label=period.display_label,
        ),
        build_qb_twp_vs_interceptions_chart(
            qbs,
            output_dir=out,
            season=period.season,
            week=period.end_week,
            min_dropbacks=args.min_qb_dropbacks,
            period_label=period.display_label,
        ),
    ]
    print(json.dumps({"season": period.season, "period": period.period_type.value, "start_week": period.start_week, "end_week": period.end_week, "charts": [str(path) for path in charts], "label_stats": label_stats_report()}, indent=2))


if __name__ == "__main__":
    main()



