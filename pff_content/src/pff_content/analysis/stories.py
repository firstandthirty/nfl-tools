from __future__ import annotations

import pandas as pd


def build_stories(tables: dict[str, pd.DataFrame], team_defense: pd.DataFrame, rookies: pd.DataFrame, *, top_n: int = 10) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    _qb_stories(rows, tables.get("qbs"), top_n)
    _receiving_stories(rows, tables.get("receiving"), top_n)
    _rushing_stories(rows, tables.get("rushing"), top_n)
    _ol_stories(rows, tables.get("pass_blocking"), top_n)
    _pass_rush_stories(rows, tables.get("pass_rush"), top_n)
    _run_defense_stories(rows, tables.get("run_defense"), top_n)
    _coverage_stories(rows, tables.get("coverage"), top_n)
    _team_stories(rows, team_defense, top_n)
    for row in rookies.head(top_n).to_dict("records"):
        rows.append(_story("rookies", row.get("player"), row.get("team"), row.get("opponent"), row.get("metric"), {"rank": row.get("rank"), "value": row.get("value")}, "rookie_top_10_category", row.get("qualifier_context")))
    return pd.DataFrame(rows)


def _story(category: str, subject: object, team: object, opponent: object, headline_metric: object, supporting: dict[str, object], rule: str, sample: object) -> dict[str, object]:
    return {
        "category": category,
        "player_or_team": subject,
        "team": team,
        "opponent": opponent,
        "headline_metric": headline_metric,
        "supporting_metrics": "; ".join(f"{key}={value}" for key, value in supporting.items() if pd.notna(value)),
        "rule_triggered": rule,
        "sample_context": sample,
        "content_hook": _hook(category, subject, supporting, rule),
    }


def _hook(category: str, subject: object, supporting: dict[str, object], rule: str) -> str:
    name = str(subject)
    if category == "pass_rush":
        return f"{name} had {supporting.get('pressures')} pressures on {supporting.get('snaps')} pass-rush snaps with a {supporting.get('win_rate')} pass-rush win rate."
    if category == "receiving":
        return f"{name} drew {supporting.get('targets')} targets on {supporting.get('routes')} routes, a {supporting.get('tprr')} target-per-route rate."
    if category == "qbs" and rule == "twp_without_int":
        return f"{name} recorded {supporting.get('twp')} turnover-worthy plays without an interception."
    if category == "team_defense":
        return f"{name} had a {supporting.get('man_share')} man coverage assignment share and {supporting.get('zone_share')} zone assignment share in the player-level coverage scheme data."
    return f"{name}: {rule} ({'; '.join(f'{k}={v}' for k, v in supporting.items() if pd.notna(v))})."


def _qb_stories(rows: list[dict[str, object]], df: pd.DataFrame | None, top_n: int) -> None:
    if df is None or df.empty:
        return
    q = df[df["qualified_qb"]]
    for _, row in q.nlargest(top_n, "pressure_rate_faced").iterrows():
        rows.append(_story("qbs", row.player_name, row.team, row.opponent, "pressure_rate_faced", {"pressures": row.def_gen_pressures, "dropbacks": row.dropbacks, "pressure_rate": round(row.pressure_rate_faced, 3), "ttt": row.avg_time_to_throw}, "high_pressure_rate", f"dropbacks={row.dropbacks}"))
    for _, row in df[df["potential_turnover_fortune"]].sort_values("turnover_worthy_plays", ascending=False).head(top_n).iterrows():
        rows.append(_story("qbs", row.player_name, row.team, row.opponent, "turnover_worthy_plays", {"twp": row.turnover_worthy_plays, "interceptions": row.interceptions}, "twp_without_int", f"dropbacks={row.dropbacks}"))
    for _, row in df[df["potential_turnover_misfortune"]].sort_values("int_minus_twp", ascending=False).head(top_n).iterrows():
        rows.append(_story("qbs", row.player_name, row.team, row.opponent, "int_minus_twp", {"interceptions": row.interceptions, "twp": row.turnover_worthy_plays}, "int_greater_than_twp", f"dropbacks={row.dropbacks}"))


def _receiving_stories(rows: list[dict[str, object]], df: pd.DataFrame | None, top_n: int) -> None:
    if df is None or df.empty:
        return
    q = df[df["qualified_routes"]]
    for _, row in q.sort_values("targets_per_route_run", ascending=False).head(top_n).iterrows():
        rows.append(_story("receiving", row.player_name, row.team, row.opponent, "targets_per_route_run", {"targets": row.targets, "routes": row.routes, "tprr": round(row.targets_per_route_run, 3), "yprr": row.yprr}, "top_targets_per_route", f"routes={row.routes}"))
    for _, row in df[(df["targets"] >= 6) & (df["routes"] <= df["routes"].median())].sort_values("targets_per_route_run", ascending=False).head(top_n).iterrows():
        rows.append(_story("receiving", row.player_name, row.team, row.opponent, "targets_per_route_run", {"targets": row.targets, "routes": row.routes, "tprr": round(row.targets_per_route_run, 3)}, "high_targets_low_routes", f"routes={row.routes}"))


def _rushing_stories(rows: list[dict[str, object]], df: pd.DataFrame | None, top_n: int) -> None:
    if df is None or df.empty:
        return
    q = df[df["qualified_rushing"]]
    for _, row in q.nlargest(top_n, "yards_after_contact_per_attempt").iterrows():
        rows.append(_story("rushing", row.player_name, row.team, row.opponent, "yards_after_contact_per_attempt", {"attempts": row.attempts, "yac_per_att": round(row.yards_after_contact_per_attempt, 2), "yards": row.yards}, "top_yac_per_attempt", f"attempts={row.attempts}"))


def _ol_stories(rows: list[dict[str, object]], df: pd.DataFrame | None, top_n: int) -> None:
    if df is None or df.empty:
        return
    q = df[df["qualified_ol"]]
    for _, row in q[(q["pressures_allowed"] == 0)].sort_values("pass_block_snaps", ascending=False).head(top_n).iterrows():
        rows.append(_story("pass_blocking", row.player_name, row.team, row.opponent, "zero_pressures_allowed", {"snaps": row.pass_block_snaps, "position": row.position}, "zero_pressures_high_volume", f"snap_share={round(row.ol_pass_block_snap_share, 2)}"))
    for _, row in q[q["pressures_allowed"] >= 4].sort_values("pressures_allowed", ascending=False).head(top_n).iterrows():
        rows.append(_story("pass_blocking", row.player_name, row.team, row.opponent, "pressures_allowed", {"pressures_allowed": row.pressures_allowed, "snaps": row.pass_block_snaps, "rate": round(row.pressure_rate_allowed, 3)}, "multiple_pressures_allowed_high_volume", f"snap_share={round(row.ol_pass_block_snap_share, 2)}"))


def _pass_rush_stories(rows: list[dict[str, object]], df: pd.DataFrame | None, top_n: int) -> None:
    if df is None or df.empty:
        return
    q = df[df["qualified_pass_rush"]]
    win_q75 = q["pass_rush_win_rate"].quantile(0.75)
    median_pressures = q["total_pressures"].median()
    pressure_ranks = pd.to_numeric(q["total_pressures_rank"], errors="coerce")
    for _, row in q[(pressure_ranks <= top_n) & (q["pass_rush_win_rate"] >= win_q75)].iterrows():
        rows.append(_story("pass_rush", row.player_name, row.team, row.opponent, "total_pressures", {"pressures": row.total_pressures, "snaps": row.pass_rush_snaps, "win_rate": row.pass_rush_win_rate}, "top_pressure_total_top_quartile_win_rate", f"qualified_pass_rush={row.qualified_pass_rush}"))
    for _, row in q[(q["pass_rush_win_rate"] >= win_q75) & (q["total_pressures"] < median_pressures)].sort_values("pass_rush_win_rate", ascending=False).head(top_n).iterrows():
        rows.append(_story("pass_rush", row.player_name, row.team, row.opponent, "pass_rush_win_rate", {"pressures": row.total_pressures, "snaps": row.pass_rush_snaps, "win_rate": row.pass_rush_win_rate}, "high_win_rate_low_pressure_total", f"median_pressures={median_pressures}"))


def _run_defense_stories(rows: list[dict[str, object]], df: pd.DataFrame | None, top_n: int) -> None:
    if df is None or df.empty:
        return
    q = df[df["qualified_run_defense"]]
    stop_ranks = pd.to_numeric(q["stops_rank"], errors="coerce")
    rate_ranks = pd.to_numeric(q["run_stop_rate_rank"], errors="coerce")
    for _, row in q[(stop_ranks <= top_n) & (rate_ranks <= top_n)].iterrows():
        rows.append(_story("run_defense", row.player_name, row.team, row.opponent, "stops", {"stops": row.stops, "snaps": row.run_defense_snaps, "stop_rate": round(row.run_stop_rate, 3)}, "high_stop_volume_high_stop_rate", f"run_defense_snaps={row.run_defense_snaps}"))


def _coverage_stories(rows: list[dict[str, object]], df: pd.DataFrame | None, top_n: int) -> None:
    if df is None or df.empty:
        return
    q = df[df["qualified_coverage"]]
    for _, row in q.nsmallest(top_n, "passer_rating_when_targeted").iterrows():
        rows.append(_story("coverage", row.player_name, row.team, row.opponent, "passer_rating_when_targeted", {"targets": row.targets, "receptions": row.receptions, "yards": row.yards, "rating": row.passer_rating_when_targeted}, "low_rating_allowed_meaningful_targets", f"coverage_snaps={row.coverage_snaps}; targets={row.targets}"))
    for _, row in q.nlargest(top_n, "forced_incompletion_rate").iterrows():
        rows.append(_story("coverage", row.player_name, row.team, row.opponent, "forced_incompletion_rate", {"targets": row.targets, "forced_incompletes": row.forced_incompletes, "rate": round(row.forced_incompletion_rate, 3)}, "strong_forced_incompletion_rate", f"coverage_snaps={row.coverage_snaps}; targets={row.targets}"))


def _team_stories(rows: list[dict[str, object]], df: pd.DataFrame | None, top_n: int) -> None:
    if df is None or df.empty:
        return
    man_col = "man_coverage_assignment_share" if "man_coverage_assignment_share" in df.columns else "man_coverage_rate"
    zone_col = "zone_coverage_assignment_share" if "zone_coverage_assignment_share" in df.columns else "zone_coverage_rate"
    total_col = "total_scheme_coverage_assignments" if "total_scheme_coverage_assignments" in df.columns else "total_scheme_coverage_snaps"
    for _, row in df.nlargest(top_n, man_col).iterrows():
        rows.append(
            _story(
                "team_defense",
                row.team,
                row.team,
                row.opponent,
                man_col,
                {"man_share": round(row[man_col], 3), "zone_share": round(row[zone_col], 3), "assignments": row[total_col]},
                "extreme_man_zone_assignment_share",
                "player-level coverage assignments; blitz_rate unavailable from current PFF API dataset",
            )
        )
