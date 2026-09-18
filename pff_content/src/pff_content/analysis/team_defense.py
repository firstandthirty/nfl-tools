from __future__ import annotations

import pandas as pd

from .qualifiers import add_rank, safe_divide


def build(coverage_scheme: pd.DataFrame) -> pd.DataFrame:
    df = coverage_scheme.copy()
    agg_cols = [
        "man_snap_counts_coverage", "zone_snap_counts_coverage", "man_targets", "zone_targets",
        "man_receptions", "zone_receptions", "man_yards", "zone_yards", "man_forced_incompletes",
        "zone_forced_incompletes", "man_touchdowns", "zone_touchdowns", "man_interceptions", "zone_interceptions",
    ]
    present = [col for col in agg_cols if col in df.columns]
    team = df.groupby(["season", "week", "team", "opponent"], dropna=False)[present].sum(min_count=1).reset_index()
    total_assignments = team.get("man_snap_counts_coverage", 0) + team.get("zone_snap_counts_coverage", 0)
    team["total_scheme_coverage_assignments"] = total_assignments
    team["man_coverage_assignment_share"] = safe_divide(team["man_snap_counts_coverage"], total_assignments)
    team["zone_coverage_assignment_share"] = safe_divide(team["zone_snap_counts_coverage"], total_assignments)
    team["man_zone_assignment_balance_delta"] = (team["man_coverage_assignment_share"] - 0.5).abs()
    team["coverage_tendency_classification"] = "VALID_PLAYER_ASSIGNMENT_RATE_ONLY"
    team["coverage_tendency_note"] = (
        "coverage_scheme rows are player-level; shares use summed player man/zone coverage assignments, "
        "not team defensive coverage plays"
    )
    # Backward-compatible aliases. These are assignment shares, not literal team play rates.
    team["total_scheme_coverage_snaps"] = team["total_scheme_coverage_assignments"]
    team["man_coverage_rate"] = team["man_coverage_assignment_share"]
    team["zone_coverage_rate"] = team["zone_coverage_assignment_share"]
    team["man_zone_balance_delta"] = team["man_zone_assignment_balance_delta"]
    team["blitz_rate_available"] = False
    team["blitz_rate_note"] = "blitz rate unavailable from current PFF API dataset"
    team = add_rank(team, "man_coverage_rate", "man_coverage_rate_rank", ascending=False)
    team = add_rank(team, "zone_coverage_rate", "zone_coverage_rate_rank", ascending=False)
    team = add_rank(team, "man_zone_balance_delta", "man_zone_balance_rank", ascending=True)
    team = add_rank(team, "man_coverage_assignment_share", "man_coverage_assignment_share_rank", ascending=False)
    team = add_rank(team, "zone_coverage_assignment_share", "zone_coverage_assignment_share_rank", ascending=False)
    return team.sort_values(["man_coverage_assignment_share"], ascending=False)
