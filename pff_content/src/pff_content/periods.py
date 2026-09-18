from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PeriodType(StrEnum):
    WEEK = "week"
    SEASON_TO_DATE = "season"
    BOTH = "both"


@dataclass(frozen=True)
class Period:
    season: int
    period_type: PeriodType
    start_week: int
    end_week: int

    @classmethod
    def week(cls, season: int, week: int) -> "Period":
        return cls(season=season, period_type=PeriodType.WEEK, start_week=week, end_week=week)

    @classmethod
    def season_to_date(cls, season: int, through_week: int) -> "Period":
        return cls(season=season, period_type=PeriodType.SEASON_TO_DATE, start_week=1, end_week=through_week)

    @property
    def display_label(self) -> str:
        if self.period_type == PeriodType.WEEK:
            return f"{self.season} Week {self.end_week}"
        if self.period_type == PeriodType.SEASON_TO_DATE:
            return f"{self.season} Season Through Week {self.end_week}"
        raise ValueError(f"Unsupported period type: {self.period_type}")

    @property
    def short_label(self) -> str:
        if self.period_type == PeriodType.WEEK:
            return f"Week {self.end_week}"
        if self.period_type == PeriodType.SEASON_TO_DATE:
            return f"Season Through Week {self.end_week}"
        raise ValueError(f"Unsupported period type: {self.period_type}")

    @property
    def output_slug(self) -> str:
        if self.period_type == PeriodType.WEEK:
            return f"week_{self.end_week:02d}"
        if self.period_type == PeriodType.SEASON_TO_DATE:
            return f"season_through_week_{self.end_week:02d}"
        raise ValueError(f"Unsupported period type: {self.period_type}")

    @property
    def weeks(self) -> range:
        return range(self.start_week, self.end_week + 1)

    @property
    def is_week(self) -> bool:
        return self.period_type == PeriodType.WEEK

    @property
    def is_multi_week(self) -> bool:
        return self.start_week != self.end_week or self.period_type != PeriodType.WEEK


def period_from_args(*, season: int, week: int | None = None, through_week: int | None = None, period: str = "week") -> Period:
    value = PeriodType(period)
    if value == PeriodType.WEEK:
        if week is None:
            raise ValueError("--week is required for --period week")
        return Period.week(season, week)
    if value == PeriodType.SEASON_TO_DATE:
        end = through_week if through_week is not None else week
        if end is None:
            raise ValueError("--through-week or --week is required for --period season")
        return Period.season_to_date(season, end)
    raise ValueError("Use explicit week/season periods when building a single output")
