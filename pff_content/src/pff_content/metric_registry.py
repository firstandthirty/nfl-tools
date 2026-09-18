from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AggregationClass(StrEnum):
    ADDITIVE = "ADDITIVE"
    RATIO_RECOMPUTABLE = "RATIO_RECOMPUTABLE"
    WEIGHTED_RECOMPUTABLE = "WEIGHTED_RECOMPUTABLE"
    NATIVE_NONADDITIVE = "NATIVE_NONADDITIVE"
    UNSUPPORTED_FOR_MULTI_WEEK = "UNSUPPORTED_FOR_MULTI_WEEK"


@dataclass(frozen=True)
class MetricAggregationSpec:
    dataset: str
    metric: str
    source_fields: tuple[str, ...]
    aggregation_class: AggregationClass
    numerator: str | None = None
    denominator: str | None = None
    formula: str = ""
    exact: bool = True
    supported_season_to_date: bool = True
    caveat: str = ""


METRIC_REGISTRY: tuple[MetricAggregationSpec, ...] = (
    MetricAggregationSpec("passing", "pressure_rate_faced", ("def_gen_pressures", "dropbacks"), AggregationClass.RATIO_RECOMPUTABLE, "def_gen_pressures", "dropbacks", "SUM(def_gen_pressures) / SUM(dropbacks)"),
    MetricAggregationSpec("passing", "twp_per_dropback", ("turnover_worthy_plays", "dropbacks"), AggregationClass.RATIO_RECOMPUTABLE, "turnover_worthy_plays", "dropbacks", "SUM(turnover_worthy_plays) / SUM(dropbacks)"),
    MetricAggregationSpec("passing", "btt_per_dropback", ("big_time_throws", "dropbacks"), AggregationClass.RATIO_RECOMPUTABLE, "big_time_throws", "dropbacks", "SUM(big_time_throws) / SUM(dropbacks)"),
    MetricAggregationSpec("passing", "avg_time_to_throw", ("avg_time_to_throw", "dropbacks"), AggregationClass.WEIGHTED_RECOMPUTABLE, "avg_time_to_throw * dropbacks", "dropbacks", "SUM(avg_time_to_throw * dropbacks) / SUM(dropbacks)", exact=False, caveat="PFF exposes a weekly average; weighted recomputation is used after Week 1 reconciliation."),
    MetricAggregationSpec("receiving", "targets_per_route_run", ("targets", "routes"), AggregationClass.RATIO_RECOMPUTABLE, "targets", "routes", "SUM(targets) / SUM(routes)"),
    MetricAggregationSpec("receiving", "yprr", ("yards", "routes"), AggregationClass.RATIO_RECOMPUTABLE, "yards", "routes", "SUM(yards) / SUM(routes)"),
    MetricAggregationSpec("receiving", "avg_depth_of_target", ("avg_depth_of_target", "targets"), AggregationClass.WEIGHTED_RECOMPUTABLE, "avg_depth_of_target * targets", "targets", "SUM(avg_depth_of_target * targets) / SUM(targets)", exact=False),
    MetricAggregationSpec("rushing", "yards_per_carry", ("yards", "attempts"), AggregationClass.RATIO_RECOMPUTABLE, "yards", "attempts", "SUM(yards) / SUM(attempts)"),
    MetricAggregationSpec("rushing", "yards_after_contact_per_attempt", ("yards_after_contact", "attempts"), AggregationClass.RATIO_RECOMPUTABLE, "yards_after_contact", "attempts", "SUM(yards_after_contact) / SUM(attempts)"),
    MetricAggregationSpec("rushing", "missed_tackles_forced_per_attempt", ("avoided_tackles", "attempts"), AggregationClass.RATIO_RECOMPUTABLE, "avoided_tackles", "attempts", "SUM(avoided_tackles) / SUM(attempts)"),
    MetricAggregationSpec("pass_blocking", "pressure_rate_allowed", ("pressures_allowed", "pass_block_snaps"), AggregationClass.RATIO_RECOMPUTABLE, "pressures_allowed", "pass_block_snaps", "SUM(pressures_allowed) / SUM(pass_block_snaps)"),
    MetricAggregationSpec("pass_blocking", "pass_blocking_efficiency", ("pass_blocking_efficiency",), AggregationClass.NATIVE_NONADDITIVE, None, None, "Not recomputed from current components.", supported_season_to_date=False),
    MetricAggregationSpec("pass_rush", "pressure_rate", ("total_pressures", "pass_rush_snaps"), AggregationClass.RATIO_RECOMPUTABLE, "total_pressures", "pass_rush_snaps", "SUM(total_pressures) / SUM(pass_rush_snaps)"),
    MetricAggregationSpec("pass_rush", "pass_rush_win_rate", ("pass_rush_wins", "pass_rush_opp"), AggregationClass.RATIO_RECOMPUTABLE, "pass_rush_wins", "pass_rush_opp", "SUM(pass_rush_wins) / SUM(pass_rush_opp)"),
    MetricAggregationSpec("pass_rush", "pass_rush_productivity", ("pass_rush_productivity",), AggregationClass.NATIVE_NONADDITIVE, None, None, "PRP is not reconstructed yet.", supported_season_to_date=False),
    MetricAggregationSpec("run_defense", "run_stop_rate", ("stops", "run_defense_snaps"), AggregationClass.RATIO_RECOMPUTABLE, "stops", "run_defense_snaps", "SUM(stops) / SUM(run_defense_snaps)"),
    MetricAggregationSpec("coverage", "forced_incompletion_rate", ("forced_incompletes", "targets"), AggregationClass.RATIO_RECOMPUTABLE, "forced_incompletes", "targets", "SUM(forced_incompletes) / SUM(targets)"),
    MetricAggregationSpec("coverage", "passer_rating_when_targeted", ("receptions", "targets", "yards", "touchdowns_allowed", "interceptions"), AggregationClass.RATIO_RECOMPUTABLE, None, "targets", "NFL passer rating from cumulative completions/targets/yards/TD/INT"),
    MetricAggregationSpec("coverage", "yards_per_coverage_snap", ("yards", "coverage_snaps"), AggregationClass.RATIO_RECOMPUTABLE, "yards", "coverage_snaps", "SUM(yards) / SUM(coverage_snaps)"),
    MetricAggregationSpec("team_defense", "man_coverage_assignment_share", ("man_snap_counts_coverage", "zone_snap_counts_coverage"), AggregationClass.RATIO_RECOMPUTABLE, "man_snap_counts_coverage", "man+zone assignments", "SUM(man assignments) / SUM(man + zone assignments)"),
)


def registry_by_dataset() -> dict[str, list[MetricAggregationSpec]]:
    out: dict[str, list[MetricAggregationSpec]] = {}
    for spec in METRIC_REGISTRY:
        out.setdefault(spec.dataset, []).append(spec)
    return out
