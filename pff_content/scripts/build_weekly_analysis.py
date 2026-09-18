from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pff_content.analysis import coverage, pass_blocking, pass_rush, qbs, receiving, rookies, rushing, run_defense, stories, team_defense
from pff_content.paths import period_output_dir, processed_week_dir
from pff_content.periods import Period, PeriodType, period_from_args
from pff_content.season_aggregation import aggregate_period
from pff_content.week_status import assert_finalized_week


DATASET_FILES = {
    "games": "games.csv",
    "passing": "passing.csv",
    "receiving": "receiving.csv",
    "rushing": "rushing.csv",
    "pass_blocking": "pass_blocking.csv",
    "pass_rush": "pass_rush.csv",
    "run_defense": "run_defense.csv",
    "coverage": "coverage.csv",
    "coverage_scheme": "coverage_scheme.csv",
    "time_in_pocket": "time_in_pocket.csv",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build period-aware PFF content-analysis outputs from processed CSVs.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int)
    parser.add_argument("--through-week", type=int)
    parser.add_argument("--period", choices=["week", "season", "both"], default="week")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--allow-incomplete", action="store_true", help="Allow provisional PFF data for development/testing only.")
    return parser.parse_args()


def load_processed(season: int, week: int) -> dict[str, pd.DataFrame]:
    base = processed_week_dir(season, week)
    missing = [name for name in DATASET_FILES.values() if not (base / name).exists()]
    if missing:
        raise RuntimeError(
            f"Missing processed PFF files in {base}: {', '.join(missing)}. "
            "Run scripts/fetch_week.py and scripts/build_processed_week.py first."
        )
    return {dataset: pd.read_csv(base / filename) for dataset, filename in DATASET_FILES.items()}


def load_period_processed(period: Period) -> dict[str, pd.DataFrame]:
    weekly = [load_processed(period.season, week) for week in period.weeks]
    return {
        dataset: aggregate_period(dataset, [week_data[dataset] for week_data in weekly], period)
        for dataset in DATASET_FILES
    }


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
        build_period(period, top_n=args.top_n, allow_incomplete=args.allow_incomplete)


def build_period(period: Period, *, top_n: int, allow_incomplete: bool) -> None:
    for week in period.weeks:
        assert_finalized_week(period.season, week, allow_incomplete=allow_incomplete)
    processed = load_period_processed(period)
    analysis = {
        "qbs": qbs.build(processed["passing"]),
        "receiving": receiving.build(processed["receiving"]),
        "rushing": rushing.build(processed["rushing"]),
        "pass_blocking": pass_blocking.build(processed["pass_blocking"]),
        "pass_rush": pass_rush.build(processed["pass_rush"]),
        "run_defense": run_defense.build(processed["run_defense"]),
        "coverage": coverage.build(processed["coverage"]),
    }
    team = team_defense.build(processed["coverage_scheme"])
    rookie_table = rookies.build(analysis, top_rank=top_n)
    story_table = stories.build_stories(analysis, team, rookie_table, top_n=top_n)

    out = period_output_dir(period)
    out.mkdir(parents=True, exist_ok=True)
    for name, df in analysis.items():
        df.to_csv(out / f"{name}.csv", index=False)
    team.to_csv(out / "team_defense.csv", index=False)
    rookie_table.to_csv(out / "rookies.csv", index=False)
    story_table.to_csv(out / "stories.csv", index=False)
    report = build_report(period, analysis, team, rookie_table, story_table, top_n)
    report_name = "weekly_research_report.md" if period.period_type == PeriodType.WEEK else "season_research_report.md"
    (out / report_name).write_text(report, encoding="utf-8")
    rows = {name: len(df) for name, df in analysis.items()}
    rows.update({"team_defense": len(team), "rookies": len(rookie_table), "stories": len(story_table)})
    print({"season": period.season, "period": period.period_type.value, "start_week": period.start_week, "end_week": period.end_week, "output_dir": str(out), "rows": rows})


def build_report(
    period: Period,
    analysis: dict[str, pd.DataFrame],
    team: pd.DataFrame,
    rookie_table: pd.DataFrame,
    story_table: pd.DataFrame,
    top_n: int,
) -> str:
    lines = [f"# PFF {period.short_label} Research Report", "", f"Season: {period.season}", "", "Internal research notes only. No polished social copy.", ""]
    lines.extend(section("Quarterbacks", [
        ("Pressure Leaders", top(analysis["qbs"], "pressure_rate_faced", top_n, ["player_name", "team", "opponent", "def_gen_pressures", "dropbacks", "pressure_rate_faced", "avg_time_to_throw"], qualified="qualified_qb")),
        ("Turnover-Worthy Play vs INT", top(analysis["qbs"], "turnover_worthy_plays", top_n, ["player_name", "team", "opponent", "turnover_worthy_plays", "interceptions", "int_minus_twp"], qualified=None)),
        ("Time To Throw", top(analysis["qbs"], "avg_time_to_throw", top_n, ["player_name", "team", "opponent", "dropbacks", "avg_time_to_throw"], qualified="qualified_qb")),
        ("QB Notes", story_bullets(story_table, "qbs", top_n)),
    ]))
    lines.extend(section("Receivers", [
        ("Most Targets", top(analysis["receiving"], "targets", top_n, ["player_name", "team", "opponent", "targets", "routes", "targets_per_route_run", "yprr"])),
        ("Targets Per Route", top(analysis["receiving"], "targets_per_route_run", top_n, ["player_name", "team", "opponent", "targets", "routes", "targets_per_route_run", "yprr"], qualified="qualified_routes")),
        ("Usage Extremes", top(analysis["receiving"], "slot_rate", top_n, ["player_name", "team", "opponent", "position", "routes", "slot_rate", "wide_rate", "inline_rate"], qualified="qualified_routes")),
    ]))
    lines.extend(section("Running Backs", [
        ("YAC Per Attempt", top(analysis["rushing"], "yards_after_contact_per_attempt", top_n, ["player_name", "team", "opponent", "attempts", "yards", "yards_after_contact", "yards_after_contact_per_attempt"], qualified="qualified_rushing")),
        ("Missed Tackles Forced Per Attempt", top(analysis["rushing"], "missed_tackles_forced_per_attempt", top_n, ["player_name", "team", "opponent", "attempts", "avoided_tackles", "missed_tackles_forced_per_attempt"], qualified="qualified_rushing")),
    ]))
    lines.extend(section("Pass Blocking", [
        ("Pressures Allowed", top(analysis["pass_blocking"], "pressures_allowed", top_n, ["player_name", "team", "opponent", "position", "pass_block_snaps", "pressures_allowed", "pressure_rate_allowed", "pass_blocking_efficiency"], qualified="qualified_ol")),
        ("Zero Pressures Allowed", table_md(analysis["pass_blocking"][(analysis["pass_blocking"]["qualified_ol"]) & (analysis["pass_blocking"]["pressures_allowed"] == 0)].sort_values("pass_block_snaps", ascending=False).head(top_n), ["player_name", "team", "position", "pass_block_snaps", "pass_blocking_efficiency"])),
    ]))
    lines.extend(section("Pass Rush", [
        ("Most Pressures", top(analysis["pass_rush"], "total_pressures", top_n, ["player_name", "team", "opponent", "position", "pass_rush_snaps", "total_pressures", "pressure_rate", "pass_rush_win_rate"])),
        ("Pressure Rate", top(analysis["pass_rush"], "pressure_rate", top_n, ["player_name", "team", "opponent", "position", "pass_rush_snaps", "total_pressures", "pressure_rate", "pass_rush_win_rate"], qualified="qualified_pass_rush")),
    ]))
    lines.extend(section("Run Defense", [
        ("Run Stops", top(analysis["run_defense"], "stops", top_n, ["player_name", "team", "opponent", "position", "run_defense_snaps", "stops", "run_stop_rate", "missed_tackles"])),
        ("Stop Rate", top(analysis["run_defense"], "run_stop_rate", top_n, ["player_name", "team", "opponent", "position", "run_defense_snaps", "stops", "run_stop_rate"], qualified="qualified_run_defense")),
    ]))
    lines.extend(section("Coverage", [
        ("Lowest Passer Rating Allowed", top(analysis["coverage"], "passer_rating_when_targeted", top_n, ["player_name", "team", "opponent", "position", "coverage_snaps", "targets", "receptions", "yards", "passer_rating_when_targeted"], ascending=True, qualified="qualified_coverage")),
        ("Forced Incompletion Rate", top(analysis["coverage"], "forced_incompletion_rate", top_n, ["player_name", "team", "opponent", "position", "coverage_snaps", "targets", "forced_incompletes", "forced_incompletion_rate"], qualified="qualified_coverage")),
    ]))
    lines.extend(section("Team Coverage Assignment Tendencies", [
        ("Highest Man Coverage Assignment Share", top(team, "man_coverage_assignment_share", top_n, ["team", "opponent", "man_snap_counts_coverage", "zone_snap_counts_coverage", "total_scheme_coverage_assignments", "man_coverage_assignment_share", "zone_coverage_assignment_share", "coverage_tendency_classification", "blitz_rate_note"])),
        ("Closest To 50/50 Assignment Split", top(team, "man_zone_assignment_balance_delta", top_n, ["team", "opponent", "man_coverage_assignment_share", "zone_coverage_assignment_share", "man_zone_assignment_balance_delta", "coverage_tendency_classification", "blitz_rate_note"], ascending=True)),
    ]))
    lines.extend(section("Rookie Standouts", [("Top Rookie Category Appearances", table_md(rookie_table.head(top_n), ["player", "team", "position", "category", "metric", "value", "rank", "qualifier_context"]))]))
    lines.extend(["## Potential Content Hooks", ""])
    lines.extend(f"- {text}" for text in story_table["content_hook"].head(max(top_n, 20)).fillna("").tolist())
    lines.append("")
    return "\n".join(lines)


def section(title: str, parts: list[tuple[str, str]]) -> list[str]:
    lines = [f"## {title}", ""]
    for subtitle, body in parts:
        lines.extend([f"### {subtitle}", "", body, ""])
    return lines


def top(df: pd.DataFrame, metric: str, n: int, cols: list[str], *, ascending: bool = False, qualified: str | None = None) -> str:
    view = df.copy()
    if qualified and qualified in view.columns:
        view = view[view[qualified].fillna(False)]
    view = view[view[metric].notna()].sort_values(metric, ascending=ascending).head(n)
    return table_md(view, cols)


def table_md(df: pd.DataFrame, cols: list[str]) -> str:
    present = [col for col in cols if col in df.columns]
    if df.empty or not present:
        return "_No rows._"
    return df[present].to_markdown(index=False, floatfmt=".3f")


def story_bullets(story_table: pd.DataFrame, category: str, n: int) -> str:
    rows = story_table[story_table["category"] == category]["content_hook"].head(n).tolist() if not story_table.empty else []
    return "\n".join(f"- {row}" for row in rows) if rows else "_No rows._"


if __name__ == "__main__":
    main()

