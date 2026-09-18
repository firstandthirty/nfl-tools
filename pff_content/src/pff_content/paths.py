from __future__ import annotations

from pathlib import Path

from pff_content.periods import Period


PROJECT_ROOT = Path(__file__).resolve().parents[2]
NFL_TOOLS_ROOT = PROJECT_ROOT.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_PFF_DIR = DATA_DIR / "raw" / "pff"
PROCESSED_PFF_DIR = DATA_DIR / "processed" / "pff"


def week_label(week: int) -> str:
    return f"week_{week:02d}"


def raw_week_dir(season: int, week: int) -> Path:
    return RAW_PFF_DIR / str(season) / week_label(week)


def processed_week_dir(season: int, week: int) -> Path:
    return PROCESSED_PFF_DIR / str(season) / week_label(week)


def period_output_dir(period: Period) -> Path:
    return PROJECT_ROOT / "outputs" / str(period.season) / period.output_slug


def period_chart_dir(period: Period) -> Path:
    return period_output_dir(period) / "charts"


def period_leaderboard_dir(period: Period) -> Path:
    return period_output_dir(period) / "leaderboards"


def period_content_dir(period: Period) -> Path:
    return period_output_dir(period) / "content"


def week_status_path(season: int, week: int) -> Path:
    return raw_week_dir(season, week) / "week_status.json"
