from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from pff_content.analysis.qualifiers import QUALIFIERS, add_ol_snap_qualification, safe_divide
from pff_content.charts.receiving import receiving_tprr_vs_yprr_dataframe
from pff_content.charts.rushing import rb_before_vs_after_contact_dataframe


LONG_FORMAT_COLUMNS = [
    "season", "week", "period_type", "start_week", "end_week", "period_label", "section", "subsection", "rule_id", "entity_type", "entity_name",
    "team", "opponent", "metric_a", "value_a", "rank_a", "metric_b", "value_b", "rank_b",
    "sample_size", "qualifier", "observation",
]

SUPPORTED_WISHLIST = {
    "SUPPORTED": [
        "QB pressure rate faced, average time to throw, turnover-worthy plays, interceptions, TWP/INT relationship, sacks, pressure-to-sack rate",
        "Receiving target earning, routes, YPRR, aDOT",
        "Rushing yards after contact, YAC/attempt, before-contact production, missed tackles forced",
        "OL pressures/sacks/hits/hurries allowed, pass-block snaps, PBE, true-pass-set pass-block metrics",
        "Pass rush pressures, pressure rate, wins, win rate, PRP, true-pass-set metrics",
        "Run defense stops, stop rate, missed tackles, run-defense snaps",
        "Coverage targets, passer rating when targeted, yards allowed, completion/catch rate, forced incompletions, coverage snaps",
        "Team man/zone player-assignment shares from processed team_defense",
        "Rookie tagging via draft_season == season and processed rookie flags",
    ],
    "DERIVABLE": [
        "Before-contact rushing production as rushing yards minus yards after contact",
        "Rates with clear denominators: TPRR, YAC/attempt, pressure rate, stop rate, pressure rate allowed, forced incompletion rate",
        "Opponent context from processed player/team rows",
    ],
    "NOT CURRENTLY AVAILABLE": [
        "Separate games.csv in the weekly analysis output",
        "Separate passing.csv; processed QB data is available as qbs.csv",
        "Separate coverage_scheme.csv in weekly analysis output; processed assignment tendency data is available as team_defense.csv",
        "True team man/zone defensive play rates are not reliably derivable from current player-level coverage_scheme rows",
        "Separate time_in_pocket.csv; QB average time to throw is available",
        "Reliable blitz rate faced or team blitz rate from current PFF API data",
    ],
}


@dataclass(frozen=True)
class Qualifier:
    id: str
    description: str
    fields: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class DiscoveryObservation:
    season: int
    week: int
    period_type: str
    start_week: int
    end_week: int
    period_label: str
    section: str
    subsection: str
    rule_id: str
    entity_type: str
    entity_name: str
    team: str | None
    opponent: str | None
    metric_a: str
    value_a: float | int | str | None
    rank_a: int | None
    metric_b: str | None
    value_b: float | int | str | None
    rank_b: int | None
    sample_size: str
    qualifier: str
    observation: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def discovery_qualifiers() -> dict[str, Qualifier]:
    return {
        "qb": Qualifier("qb", f"QBs with at least {QUALIFIERS['qb_min_dropbacks']} dropbacks.", ("dropbacks",), "Keeps one-week QB rate lists to primary passers."),
        "receiving": Qualifier("receiving", f"WR/TE with at least {QUALIFIERS['receiving_min_routes']} routes.", ("position", "routes"), "Reuses the scatter chart WR/TE route qualifier."),
        "rushing": Qualifier("rushing", f"RB/HB/FB with at least {QUALIFIERS['rushing_min_attempts']} rushing attempts.", ("position", "attempts"), "Reuses the rushing scatter chart workload qualifier."),
        "offensive_line": Qualifier(
            "offensive_line",
            f"OL positions with pass-block snaps at least {QUALIFIERS['ol_snap_share']:.0%} of their team's maximum individual OL pass-block snap count.",
            ("position", "pass_block_snaps", "team_max_ol_pass_block_snaps", "ol_pass_block_snap_share"),
            "No separate offensive snap denominator is present in pass_blocking.csv, so the existing team OL maximum pass-block snap rule is used.",
        ),
        "pass_rush": Qualifier("pass_rush", f"Defenders with at least {QUALIFIERS['pass_rush_min_snaps']} pass-rush snaps.", ("pass_rush_snaps",), "Reuses the pass-rush scatter/leaderboard qualifier."),
        "run_defense": Qualifier("run_defense", f"Defenders with at least {QUALIFIERS['run_defense_min_snaps']} run-defense snaps.", ("run_defense_snaps",), "Week 1 threshold keeps 298 players, enough for rate context without tiny workloads."),
        "coverage": Qualifier("coverage", f"Defenders with at least {QUALIFIERS['coverage_min_snaps']} coverage snaps and at least {QUALIFIERS['coverage_min_targets']} targets for target-based efficiency metrics.", ("coverage_snaps", "targets"), "Week 1 threshold keeps 89 players for passer-rating/yards-per-target observations."),
    }


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _fmt(value: object, metric: str | None = None) -> str:
    if pd.isna(value):
        return "--"
    metric = metric or ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if metric in {"targets_per_route_run", "pressure_rate_faced", "pressure_rate", "pressure_rate_allowed", "run_stop_rate", "forced_incompletion_rate", "catch_rate_allowed", "man_coverage_rate", "zone_coverage_rate", "man_coverage_assignment_share", "zone_coverage_assignment_share"}:
        return f"{number:.1%}"
    if metric in {"pass_rush_win_rate", "true_pass_set_pass_rush_win_rate"}:
        return f"{number:.1%}" if number <= 1 else f"{number:.1f}%"
    if abs(number - round(number)) < 1e-9 and metric not in {"yards_per_route_run", "yards_per_carry", "yards_after_contact_per_attempt", "yards_before_contact_per_attempt", "avg_time_to_throw"}:
        return f"{int(round(number))}"
    return f"{number:.2f}"


def _ranked(df: pd.DataFrame, metric: str, *, ascending: bool = False, volume: str | None = None, name_col: str = "player_name") -> pd.DataFrame:
    out = df.copy()
    out[metric] = _num(out[metric])
    cols = [metric]
    asc = [ascending]
    if volume and volume in out.columns:
        out[volume] = _num(out[volume])
        cols.append(volume)
        asc.append(False)
    cols.append(name_col)
    asc.append(True)
    out = out[out[metric].notna()].sort_values(cols, ascending=asc, kind="mergesort").reset_index(drop=True)
    out[f"{metric}_discovery_rank"] = range(1, len(out) + 1)
    return out


def _assign_ranks(df: pd.DataFrame, metric: str, *, ascending: bool = False) -> pd.Series:
    ranked = _ranked(df, metric, ascending=ascending)
    values = ranked.set_index("player_name")[f"{metric}_discovery_rank"].reindex(df["player_name"]).to_numpy()
    return pd.Series(values, index=df.index, dtype="Int64")


def top_n_both(df: pd.DataFrame, metric_a: str, metric_b: str, *, n: int = 10, metric_b_ascending: bool = False) -> pd.DataFrame:
    out = df.copy()
    out["rank_a"] = _assign_ranks(out, metric_a)
    out["rank_b"] = _assign_ranks(out, metric_b, ascending=metric_b_ascending)
    return out[(out["rank_a"] <= n) & (out["rank_b"] <= n)].copy()


def rank_discrepancy(df: pd.DataFrame, metric_a: str, metric_b: str, *, threshold: int = 20) -> pd.DataFrame:
    out = df.copy()
    out["rank_a"] = _assign_ranks(out, metric_a)
    out["rank_b"] = _assign_ranks(out, metric_b)
    out["rank_difference"] = out["rank_a"].astype(int) - out["rank_b"].astype(int)
    return out[out["rank_difference"].abs() >= threshold].copy()


def zero_on_volume(df: pd.DataFrame, event_col: str, volume_col: str, *, min_volume: int) -> pd.DataFrame:
    return df[(_num(df[event_col]) == 0) & (_num(df[volume_col]) >= min_volume)].copy()


def high_rate_high_volume(df: pd.DataFrame, rate_metric: str, volume_metric: str, *, n: int = 10) -> pd.DataFrame:
    return top_n_both(df, rate_metric, volume_metric, n=n)


def _obs(
    season: int, week: int, section: str, subsection: str, rule_id: str, entity_type: str,
    row: pd.Series, metric_a: str, value_a: object, observation: str, *,
    rank_a: int | None = None, metric_b: str | None = None, value_b: object = None, rank_b: int | None = None,
    sample_size: str = "", qualifier: str = "", name_col: str = "player_name",
) -> DiscoveryObservation:
    return DiscoveryObservation(
        season, week, "week", week, week, f"{season} Week {week}", section, subsection, rule_id, entity_type, str(row.get(name_col, row.get("team", ""))),
        None if pd.isna(row.get("team", None)) else str(row.get("team")),
        None if pd.isna(row.get("opponent", None)) else str(row.get("opponent")),
        metric_a, None if pd.isna(value_a) else value_a, rank_a, metric_b, None if pd.isna(value_b) else value_b,
        rank_b, sample_size, qualifier, observation,
    )


def _top_list(
    rows: pd.DataFrame, *, season: int, week: int, section: str, subsection: str, metric: str,
    qualifier: str, entity_type: str = "player", ascending: bool = False, volume: str | None = None,
    n: int = 10, sample_cols: tuple[str, ...] = (), name_col: str = "player_name",
) -> list[DiscoveryObservation]:
    if metric not in rows.columns:
        return []
    ranked = _ranked(rows, metric, ascending=ascending, volume=volume, name_col=name_col).head(n)
    out: list[DiscoveryObservation] = []
    for _, row in ranked.iterrows():
        rank = int(row[f"{metric}_discovery_rank"])
        sample = "; ".join(f"{col}={_fmt(row[col], col)}" for col in sample_cols if col in row)
        name = str(row[name_col])
        observation = f"{name} ranked {rank} in {metric} at {_fmt(row[metric], metric)}"
        if sample:
            observation += f" with {sample}."
        else:
            observation += "."
        out.append(_obs(season, week, section, subsection, "EXTREME_WITH_CONTEXT", entity_type, row, metric, row[metric], observation, rank_a=rank, sample_size=sample, qualifier=qualifier, name_col=name_col))
    return out


def _metric_population(data: dict[str, pd.DataFrame], table: str, qualifier_id: str) -> pd.DataFrame:
    if table not in data:
        return pd.DataFrame()
    df = data[table].copy()
    if qualifier_id == "qb":
        return df[_num(df["dropbacks"]) >= QUALIFIERS["qb_min_dropbacks"]].copy()
    if qualifier_id == "receiving":
        return receiving_tprr_vs_yprr_dataframe(df, min_routes=QUALIFIERS["receiving_min_routes"])
    if qualifier_id == "rushing":
        rush = rb_before_vs_after_contact_dataframe(df, min_attempts=QUALIFIERS["rushing_min_attempts"])
        if "avoided_tackles" in df.columns:
            rush = rush.merge(df[["player_name", "team", "avoided_tackles"]], on=["player_name", "team"], how="left")
            rush["missed_tackles_forced_per_attempt"] = safe_divide(rush["avoided_tackles"], rush["attempts"])
        return rush
    if qualifier_id == "offensive_line":
        if "qualified_ol" not in df.columns:
            df = add_ol_snap_qualification(df)
        return df[df["qualified_ol"].fillna(False)].copy()
    if qualifier_id == "pass_rush":
        df = df[_num(df["pass_rush_snaps"]) >= QUALIFIERS["pass_rush_min_snaps"]].copy()
        if "pressure_rate" not in df.columns and {"total_pressures", "pass_rush_snaps"}.issubset(df.columns):
            df["pressure_rate"] = safe_divide(df["total_pressures"], df["pass_rush_snaps"])
        return df
    if qualifier_id == "run_defense":
        df = df[_num(df["run_defense_snaps"]) >= QUALIFIERS["run_defense_min_snaps"]].copy()
        if "run_stop_rate" not in df.columns and {"stops", "run_defense_snaps"}.issubset(df.columns):
            df["run_stop_rate"] = safe_divide(df["stops"], df["run_defense_snaps"])
        return df
    if qualifier_id == "coverage":
        return df[(_num(df["coverage_snaps"]) >= QUALIFIERS["coverage_min_snaps"]) & (_num(df["targets"]) >= QUALIFIERS["coverage_min_targets"])].copy()
    return df


SectionBuilder = Callable[[dict[str, pd.DataFrame], int, int, dict[str, Qualifier]], list[DiscoveryObservation]]


def _qb(data: dict[str, pd.DataFrame], season: int, week: int, qualifiers: dict[str, Qualifier]) -> list[DiscoveryObservation]:
    qbs = _metric_population(data, "qbs", "qb")
    if qbs.empty:
        return []
    qualifier = qualifiers["qb"].description
    obs = _top_list(qbs, season=season, week=week, section="QB", subsection="Pressure", metric="pressure_rate_faced", qualifier=qualifier, volume="dropbacks", sample_cols=("dropbacks", "def_gen_pressures", "avg_time_to_throw"))
    obs += _top_list(qbs, season=season, week=week, section="QB", subsection="Fastest Time To Throw", metric="avg_time_to_throw", qualifier=qualifier, ascending=True, volume="dropbacks", sample_cols=("dropbacks", "pressure_rate_faced"))
    obs += _top_list(qbs, season=season, week=week, section="QB", subsection="Slowest Time To Throw", metric="avg_time_to_throw", qualifier=qualifier, volume="dropbacks", sample_cols=("dropbacks", "pressure_rate_faced"))
    qbs["twp_minus_int"] = _num(qbs["turnover_worthy_plays"]) - _num(qbs["interceptions"])
    qbs["int_minus_twp"] = _num(qbs["interceptions"]) - _num(qbs["turnover_worthy_plays"])
    for _, row in _ranked(qbs[qbs["twp_minus_int"] > 0], "twp_minus_int", volume="dropbacks").head(10).iterrows():
        text = f"{row.player_name} had {int(row.twp_minus_int)} more turnover-worthy plays than interceptions ({int(row.turnover_worthy_plays)} TWP, {int(row.interceptions)} INT) on {int(row.dropbacks)} dropbacks."
        obs.append(_obs(season, week, "QB", "TWP vs INT", "TWP_INT_DISCREPANCY", "player", row, "turnover_worthy_plays", row.turnover_worthy_plays, text, metric_b="interceptions", value_b=row.interceptions, sample_size=f"dropbacks={int(row.dropbacks)}", qualifier=qualifier))
    for _, row in _ranked(qbs[qbs["int_minus_twp"] > 0], "int_minus_twp", volume="dropbacks").head(10).iterrows():
        text = f"{row.player_name} had {int(row.int_minus_twp)} more interceptions than turnover-worthy plays ({int(row.interceptions)} INT, {int(row.turnover_worthy_plays)} TWP) on {int(row.dropbacks)} dropbacks."
        obs.append(_obs(season, week, "QB", "TWP vs INT", "TWP_INT_DISCREPANCY", "player", row, "interceptions", row.interceptions, text, metric_b="turnover_worthy_plays", value_b=row.turnover_worthy_plays, sample_size=f"dropbacks={int(row.dropbacks)}", qualifier=qualifier))
    return obs


def _receiving(data: dict[str, pd.DataFrame], season: int, week: int, qualifiers: dict[str, Qualifier]) -> list[DiscoveryObservation]:
    rec = _metric_population(data, "receiving", "receiving")
    if rec.empty:
        return []
    qualifier = qualifiers["receiving"].description
    obs: list[DiscoveryObservation] = []
    for metric in ["targets_per_route_run", "yards_per_route_run", "targets", "receiving_yards", "average_depth_of_target"]:
        obs += _top_list(rec, season=season, week=week, section="Receiving", subsection=metric, metric=metric, qualifier=qualifier, volume="routes", sample_cols=("routes", "targets"))
    for _, row in top_n_both(rec, "targets_per_route_run", "yards_per_route_run", n=10).iterrows():
        text = f"{row.player_name} ranked top 10 in both TPRR ({_fmt(row.targets_per_route_run, 'targets_per_route_run')}) and YPRR ({_fmt(row.yards_per_route_run, 'yards_per_route_run')})."
        obs.append(_obs(season, week, "Receiving", "Combinations", "TOP_N_BOTH", "player", row, "targets_per_route_run", row.targets_per_route_run, text, rank_a=int(row.rank_a), metric_b="yards_per_route_run", value_b=row.yards_per_route_run, rank_b=int(row.rank_b), sample_size=f"routes={int(row.routes)}", qualifier=qualifier))
    for _, row in rank_discrepancy(rec, "targets_per_route_run", "yards_per_route_run", threshold=20).sort_values("rank_difference", key=lambda s: s.abs(), ascending=False).head(20).iterrows():
        text = f"{row.player_name} ranked {int(row.rank_a)} in TPRR and {int(row.rank_b)} in YPRR among qualified WR/TEs."
        obs.append(_obs(season, week, "Receiving", "Rank Contrasts", "RANK_DISCREPANCY", "player", row, "targets_per_route_run", row.targets_per_route_run, text, rank_a=int(row.rank_a), metric_b="yards_per_route_run", value_b=row.yards_per_route_run, rank_b=int(row.rank_b), sample_size=f"routes={int(row.routes)}", qualifier=qualifier))
    return obs


def _rushing(data: dict[str, pd.DataFrame], season: int, week: int, qualifiers: dict[str, Qualifier]) -> list[DiscoveryObservation]:
    rush = _metric_population(data, "rushing", "rushing")
    if rush.empty:
        return []
    qualifier = qualifiers["rushing"].description
    obs: list[DiscoveryObservation] = []
    for metric in ["yards_per_carry", "yards_after_contact_per_attempt", "yards_before_contact_per_attempt", "missed_tackles_forced_per_attempt", "avoided_tackles"]:
        obs += _top_list(rush, season=season, week=week, section="Rushing", subsection=metric, metric=metric, qualifier=qualifier, volume="attempts", sample_cols=("attempts", "rushing_yards"))
    obs += _top_list(rush, season=season, week=week, section="Rushing", subsection="bottom_before_contact", metric="yards_before_contact_per_attempt", qualifier=qualifier, ascending=True, volume="attempts", sample_cols=("attempts", "rushing_yards"))
    for _, row in top_n_both(rush, "yards_per_carry", "yards_after_contact_per_attempt", n=10).iterrows():
        text = f"{row.player_name} ranked top 10 in both YPC ({_fmt(row.yards_per_carry, 'yards_per_carry')}) and YAC/attempt ({_fmt(row.yards_after_contact_per_attempt, 'yards_after_contact_per_attempt')})."
        obs.append(_obs(season, week, "Rushing", "Combinations", "TOP_N_BOTH", "player", row, "yards_per_carry", row.yards_per_carry, text, rank_a=int(row.rank_a), metric_b="yards_after_contact_per_attempt", value_b=row.yards_after_contact_per_attempt, rank_b=int(row.rank_b), sample_size=f"attempts={int(row.attempts)}", qualifier=qualifier))
    for _, row in rank_discrepancy(rush, "yards_after_contact_per_attempt", "yards_before_contact_per_attempt", threshold=10).sort_values("rank_difference", key=lambda s: s.abs(), ascending=False).head(20).iterrows():
        text = f"{row.player_name} ranked {int(row.rank_a)} in YAC/attempt and {int(row.rank_b)} in before-contact yards/attempt among qualified RBs."
        obs.append(_obs(season, week, "Rushing", "Before/After Contact", "RANK_DISCREPANCY", "player", row, "yards_after_contact_per_attempt", row.yards_after_contact_per_attempt, text, rank_a=int(row.rank_a), metric_b="yards_before_contact_per_attempt", value_b=row.yards_before_contact_per_attempt, rank_b=int(row.rank_b), sample_size=f"attempts={int(row.attempts)}", qualifier=qualifier))
    return obs


def _offensive_line(data: dict[str, pd.DataFrame], season: int, week: int, qualifiers: dict[str, Qualifier]) -> list[DiscoveryObservation]:
    ol = _metric_population(data, "pass_blocking", "offensive_line")
    if ol.empty:
        return []
    qualifier = qualifiers["offensive_line"].description
    obs: list[DiscoveryObservation] = []
    for metric, ascending in [("pressures_allowed", False), ("pressures_allowed", True), ("pressure_rate_allowed", False), ("sacks_allowed", False), ("hits_allowed", False), ("hurries_allowed", False), ("pass_blocking_efficiency", True), ("true_pass_set_pressures_allowed", False), ("true_pass_set_pbe", True)]:
        obs += _top_list(ol, season=season, week=week, section="Offensive Line", subsection=("fewest_" + metric if ascending else metric), metric=metric, qualifier=qualifier, ascending=ascending, volume="pass_block_snaps", sample_cols=("position", "pass_block_snaps"))
    for metric in ["pressures_allowed", "sacks_allowed", "hits_allowed", "hurries_allowed"]:
        if metric in ol.columns:
            for _, row in zero_on_volume(ol, metric, "pass_block_snaps", min_volume=QUALIFIERS["qb_min_dropbacks"]).sort_values(["pass_block_snaps", "player_name"], ascending=[False, True]).head(25).iterrows():
                text = f"{row.player_name} allowed 0 {metric.replace('_', ' ')} on {int(row.pass_block_snaps)} pass-block snaps."
                obs.append(_obs(season, week, "Offensive Line", "Zero Events", "ZERO_ON_VOLUME", "player", row, metric, 0, text, sample_size=f"position={row.position}; pass_block_snaps={int(row.pass_block_snaps)}", qualifier=qualifier))
    if {"pressure_rate_allowed", "true_pass_set_pressures_allowed", "true_pass_set_snap_counts_pass_block"}.issubset(ol.columns):
        ol["true_pass_set_pressure_rate_allowed"] = safe_divide(ol["true_pass_set_pressures_allowed"], ol["true_pass_set_snap_counts_pass_block"])
        ol["tps_pressure_rate_minus_normal"] = _num(ol["true_pass_set_pressure_rate_allowed"]) - _num(ol["pressure_rate_allowed"])
        for _, row in _ranked(ol[ol["true_pass_set_snap_counts_pass_block"] >= 10], "tps_pressure_rate_minus_normal", volume="true_pass_set_snap_counts_pass_block").head(10).iterrows():
            text = f"{row.player_name}'s true-pass-set pressure rate allowed was {_fmt(row.true_pass_set_pressure_rate_allowed, 'pressure_rate_allowed')} versus {_fmt(row.pressure_rate_allowed, 'pressure_rate_allowed')} overall."
            obs.append(_obs(season, week, "Offensive Line", "True Pass Set", "RANK_DISCREPANCY", "player", row, "true_pass_set_pressure_rate_allowed", row.true_pass_set_pressure_rate_allowed, text, metric_b="pressure_rate_allowed", value_b=row.pressure_rate_allowed, sample_size=f"TPS snaps={int(row.true_pass_set_snap_counts_pass_block)}", qualifier=qualifier))
    return obs


def _pass_rush(data: dict[str, pd.DataFrame], season: int, week: int, qualifiers: dict[str, Qualifier]) -> list[DiscoveryObservation]:
    pr = _metric_population(data, "pass_rush", "pass_rush")
    if pr.empty:
        return []
    qualifier = qualifiers["pass_rush"].description
    obs: list[DiscoveryObservation] = []
    for metric in ["total_pressures", "pressure_rate", "pass_rush_wins", "pass_rush_win_rate", "sacks", "pass_rush_productivity", "true_pass_set_pass_rush_win_rate", "true_pass_set_total_pressures", "true_pass_set_prp"]:
        obs += _top_list(pr, season=season, week=week, section="Pass Rush", subsection=metric, metric=metric, qualifier=qualifier, volume="pass_rush_snaps", sample_cols=("pass_rush_snaps",))
    for _, row in high_rate_high_volume(pr, "pressure_rate", "total_pressures", n=10).iterrows():
        text = f"{row.player_name} ranked top 10 in both pressure rate ({_fmt(row.pressure_rate, 'pressure_rate')}) and pressures ({int(row.total_pressures)})."
        obs.append(_obs(season, week, "Pass Rush", "Combinations", "HIGH_RATE_HIGH_VOLUME", "player", row, "pressure_rate", row.pressure_rate, text, rank_a=int(row.rank_a), metric_b="total_pressures", value_b=row.total_pressures, rank_b=int(row.rank_b), sample_size=f"rush snaps={int(row.pass_rush_snaps)}", qualifier=qualifier))
    if {"pass_rush_win_rate", "true_pass_set_pass_rush_win_rate", "true_pass_set_snap_counts_pass_rush"}.issubset(pr.columns):
        pr["tps_win_rate_minus_normal"] = _num(pr["true_pass_set_pass_rush_win_rate"]) - _num(pr["pass_rush_win_rate"])
        for _, row in _ranked(pr[pr["true_pass_set_snap_counts_pass_rush"] >= 10], "tps_win_rate_minus_normal", volume="true_pass_set_snap_counts_pass_rush").head(10).iterrows():
            text = f"{row.player_name}'s true-pass-set win rate was {_fmt(row.true_pass_set_pass_rush_win_rate, 'pass_rush_win_rate')} versus {_fmt(row.pass_rush_win_rate, 'pass_rush_win_rate')} overall."
            obs.append(_obs(season, week, "Pass Rush", "True Pass Set", "RANK_DISCREPANCY", "player", row, "true_pass_set_pass_rush_win_rate", row.true_pass_set_pass_rush_win_rate, text, metric_b="pass_rush_win_rate", value_b=row.pass_rush_win_rate, sample_size=f"TPS rush snaps={int(row.true_pass_set_snap_counts_pass_rush)}", qualifier=qualifier))
    return obs


def _run_defense(data: dict[str, pd.DataFrame], season: int, week: int, qualifiers: dict[str, Qualifier]) -> list[DiscoveryObservation]:
    rd = _metric_population(data, "run_defense", "run_defense")
    if rd.empty:
        return []
    qualifier = qualifiers["run_defense"].description
    obs: list[DiscoveryObservation] = []
    for metric in ["stops", "run_stop_rate", "missed_tackles"]:
        obs += _top_list(rd, season=season, week=week, section="Run Defense", subsection=metric, metric=metric, qualifier=qualifier, volume="run_defense_snaps", sample_cols=("run_defense_snaps",))
    for _, row in high_rate_high_volume(rd, "run_stop_rate", "stops", n=10).iterrows():
        text = f"{row.player_name} ranked top 10 in both run-stop rate ({_fmt(row.run_stop_rate, 'run_stop_rate')}) and run stops ({int(row.stops)})."
        obs.append(_obs(season, week, "Run Defense", "Combinations", "HIGH_RATE_HIGH_VOLUME", "player", row, "run_stop_rate", row.run_stop_rate, text, rank_a=int(row.rank_a), metric_b="stops", value_b=row.stops, rank_b=int(row.rank_b), sample_size=f"run-defense snaps={int(row.run_defense_snaps)}", qualifier=qualifier))
    return obs


def _coverage(data: dict[str, pd.DataFrame], season: int, week: int, qualifiers: dict[str, Qualifier]) -> list[DiscoveryObservation]:
    cov = _metric_population(data, "coverage", "coverage")
    if cov.empty:
        return []
    qualifier = qualifiers["coverage"].description
    obs: list[DiscoveryObservation] = []
    for metric, ascending, subsection in [
        ("targets", False, "targets"), ("yards", False, "yards_allowed"), ("yards_per_coverage_snap", True, "lowest_yards_per_coverage_snap"),
        ("passer_rating_when_targeted", True, "lowest_passer_rating_allowed"), ("passer_rating_when_targeted", False, "highest_passer_rating_allowed"),
        ("forced_incompletes", False, "forced_incompletes"), ("forced_incompletion_rate", False, "forced_incompletion_rate"),
    ]:
        obs += _top_list(cov, season=season, week=week, section="Coverage", subsection=subsection, metric=metric, qualifier=qualifier, ascending=ascending, volume="coverage_snaps", sample_cols=("coverage_snaps", "targets"))
    for _, row in top_n_both(cov, "targets", "passer_rating_when_targeted", n=10, metric_b_ascending=True).iterrows():
        text = f"{row.player_name} ranked top 10 in targets and top 10 lowest passer rating allowed at {_fmt(row.passer_rating_when_targeted, 'passer_rating_when_targeted')}."
        obs.append(_obs(season, week, "Coverage", "Combinations", "HIGH_RATE_HIGH_VOLUME", "player", row, "targets", row.targets, text, rank_a=int(row.rank_a), metric_b="passer_rating_when_targeted", value_b=row.passer_rating_when_targeted, rank_b=int(row.rank_b), sample_size=f"coverage snaps={int(row.coverage_snaps)}; targets={int(row.targets)}", qualifier=qualifier))
    return obs


def _team(data: dict[str, pd.DataFrame], season: int, week: int, qualifiers: dict[str, Qualifier]) -> list[DiscoveryObservation]:
    if "team_defense" not in data:
        return []
    team = data["team_defense"].copy()
    if "man_coverage_assignment_share" not in team.columns and "man_coverage_rate" in team.columns:
        team["man_coverage_assignment_share"] = team["man_coverage_rate"]
    if "zone_coverage_assignment_share" not in team.columns and "zone_coverage_rate" in team.columns:
        team["zone_coverage_assignment_share"] = team["zone_coverage_rate"]
    if "total_scheme_coverage_assignments" not in team.columns and "total_scheme_coverage_snaps" in team.columns:
        team["total_scheme_coverage_assignments"] = team["total_scheme_coverage_snaps"]
    qualifier = "Player-level coverage-scheme assignment shares from processed PFF data; not team defensive play rates."
    obs: list[DiscoveryObservation] = []
    for metric in ["man_coverage_assignment_share", "zone_coverage_assignment_share"]:
        obs += _top_list(team, season=season, week=week, section="Team Tendencies", subsection=metric, metric=metric, qualifier=qualifier, entity_type="team", volume="total_scheme_coverage_assignments", sample_cols=("total_scheme_coverage_assignments",), name_col="team")
    return obs


def _rookies(data: dict[str, pd.DataFrame], season: int, week: int, qualifiers: dict[str, Qualifier]) -> list[DiscoveryObservation]:
    specs = [
        ("receiving", "receiving", "routes", ["yards_per_route_run", "targets_per_route_run"]),
        ("rushing", "rushing", "attempts", ["yards_after_contact_per_attempt", "yards_per_carry"]),
        ("pass_blocking", "offensive_line", "pass_block_snaps", ["pressures_allowed", "pass_blocking_efficiency"]),
        ("pass_rush", "pass_rush", "pass_rush_snaps", ["total_pressures", "pass_rush_win_rate"]),
        ("run_defense", "run_defense", "run_defense_snaps", ["stops", "run_stop_rate"]),
        ("coverage", "coverage", "coverage_snaps", ["passer_rating_when_targeted", "forced_incompletion_rate"]),
        ("qbs", "qb", "dropbacks", ["pressure_rate_faced", "avg_time_to_throw"]),
    ]
    obs: list[DiscoveryObservation] = []
    for table, qid, volume, metrics in specs:
        df = _metric_population(data, table, qid)
        if df.empty or "rookie" not in df.columns:
            continue
        rookies = df[df["rookie"].fillna(False).astype(bool)].copy()
        if len(rookies) < 2:
            continue
        for metric in metrics:
            if metric in rookies.columns:
                obs += _top_list(rookies, season=season, week=week, section="Rookies", subsection=f"{table}_{metric}", metric=metric, qualifier=qualifiers[qid].description, volume=volume, n=min(10, len(rookies)), sample_cols=(volume,))
    return obs


def build_observations(data: dict[str, pd.DataFrame], *, season: int, week: int) -> list[DiscoveryObservation]:
    qualifiers = discovery_qualifiers()
    builders: list[SectionBuilder] = [_qb, _receiving, _rushing, _offensive_line, _pass_rush, _run_defense, _coverage, _team, _rookies]
    observations: list[DiscoveryObservation] = []
    for builder in builders:
        observations.extend(builder(data, season, week, qualifiers))
    return observations


def observations_to_dataframe(observations: Iterable[DiscoveryObservation]) -> pd.DataFrame:
    rows = [asdict(obs) for obs in observations]
    df = pd.DataFrame(rows, columns=LONG_FORMAT_COLUMNS)
    if df.empty:
        return df
    return df.sort_values(["section", "subsection", "rule_id", "rank_a", "entity_name"], kind="mergesort").reset_index(drop=True)


def apply_period_to_observations(observations: pd.DataFrame, period: Period) -> pd.DataFrame:
    out = observations.copy()
    for column, value in {
        "period_type": period.period_type.value,
        "start_week": period.start_week,
        "end_week": period.end_week,
        "period_label": period.display_label,
        "week": period.end_week,
    }.items():
        out[column] = value
    if period.is_multi_week and "observation" in out.columns:
        suffix = f" through Week {period.end_week}"
        out["observation"] = out["observation"].astype(str).str.replace(r"\.$", suffix + ".", regex=True)
    return out[LONG_FORMAT_COLUMNS]


def _schema_inventory(data: dict[str, pd.DataFrame]) -> dict[str, object]:
    wanted = ["games", "passing", "qbs", "receiving", "rushing", "pass_blocking", "pass_rush", "run_defense", "coverage", "coverage_scheme", "time_in_pocket", "team_defense", "rookies"]
    return {name: {"available": name in data, "rows": int(len(data[name])) if name in data else 0, "columns": list(data[name].columns) if name in data else []} for name in wanted}


def _markdown_table(df: pd.DataFrame, columns: list[str], *, limit: int = 10) -> list[str]:
    if df.empty:
        return ["No supported observations generated."]
    rows = df.head(limit)
    out = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for _, row in rows.iterrows():
        out.append("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |")
    return out


def write_markdown(observations: pd.DataFrame, path: Path, *, season: int, week: int, week_complete: bool, data: dict[str, pd.DataFrame], period_label: str | None = None) -> Path:
    title_label = period_label or f"Week {week}"
    lines = [f"# First & Thirty - {title_label} PFF Content Discovery", "", f"Week complete: `{str(week_complete).lower()}`", ""]
    lines.append("## Data Inventory")
    for name, item in _schema_inventory(data).items():
        status = "available" if item["available"] else "not available"
        lines.append(f"- {name}: {status}; rows={item['rows']}; columns={len(item['columns'])}")
    lines.append("")
    lines.append("## Wishlist Support")
    for status, items in SUPPORTED_WISHLIST.items():
        lines.append(f"### {status.title()}")
        for item in items:
            lines.append(f"- {item}")
        lines.append("")
    for section in ["QB", "Receiving", "Rushing", "Offensive Line", "Pass Rush", "Run Defense", "Coverage", "Team Tendencies", "Rookies"]:
        section_df = observations[observations["section"] == section] if not observations.empty else observations
        lines.append(f"## {section}")
        if section_df.empty:
            lines.append("No supported observations generated.")
            lines.append("")
            continue
        view = section_df[["subsection", "rule_id", "entity_name", "team", "opponent", "metric_a", "value_a", "rank_a", "sample_size"]].copy()
        lines.extend(_markdown_table(view, ["subsection", "rule_id", "entity_name", "team", "opponent", "metric_a", "value_a", "rank_a", "sample_size"], limit=12))
        lines.append("")
        lines.append("### Content Hooks")
        for observation in section_df["observation"].head(10):
            lines.append(f"- {observation}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return path


def write_inventory_doc(data: dict[str, pd.DataFrame], path: Path) -> Path:
    lines = ["# PFF Content Discovery Data Inventory", ""]
    for name, item in _schema_inventory(data).items():
        lines.append(f"## {name}")
        if not item["available"]:
            lines.append("Not currently available in the weekly analysis output.")
        else:
            lines.append(f"Rows: {item['rows']}")
            lines.append("")
            lines.extend(f"- {column}" for column in item["columns"])
        lines.append("")
    lines.append("## Wishlist Support")
    for status, items in SUPPORTED_WISHLIST.items():
        lines.append(f"### {status}")
        lines.extend(f"- {item}" for item in items)
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return path


def write_manifest(observations: pd.DataFrame, path: Path, *, season: int, week: int, week_complete: bool, data: dict[str, pd.DataFrame], period: Period | None = None) -> Path:
    payload = {
        "season": season,
        "week": week,
        "period_type": period.period_type.value if period else "week",
        "start_week": period.start_week if period else week,
        "end_week": period.end_week if period else week,
        "period_label": period.display_label if period else f"{season} Week {week}",
        "generated_at": utc_now(),
        "week_complete": bool(week_complete),
        "datasets_used": sorted(data.keys()),
        "qualifiers": {key: asdict(value) for key, value in discovery_qualifiers().items()},
        "sections_generated": sorted(observations["section"].dropna().unique().tolist()) if not observations.empty else [],
        "sections_unavailable": [name for name, item in _schema_inventory(data).items() if not item["available"]],
        "observation_count": int(len(observations)),
        "rookie_observation_count": int((observations["section"] == "Rookies").sum()) if not observations.empty else 0,
        "team_observation_count": int((observations["entity_type"] == "team").sum()) if not observations.empty else 0,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def build_content_discovery(data: dict[str, pd.DataFrame], output_dir: Path, *, season: int, week: int, week_complete: bool, docs_dir: Path | None = None, period: Period | None = None) -> dict[str, object]:
    period = period or Period.week(season, week)
    observations = observations_to_dataframe(build_observations(data, season=season, week=week))
    observations = apply_period_to_observations(observations, period)
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "weekly" if not period.is_multi_week else "season"
    csv_path = output_dir / f"{prefix}_discovery.csv"
    md_path = output_dir / f"{prefix}_discovery.md"
    manifest_path = output_dir / "discovery_manifest.json"
    observations.to_csv(csv_path, index=False)
    write_markdown(observations, md_path, season=season, week=week, week_complete=week_complete, data=data, period_label=period.short_label)
    write_manifest(observations, manifest_path, season=season, week=week, week_complete=week_complete, data=data, period=period)
    if docs_dir is not None:
        write_inventory_doc(data, docs_dir / "content_discovery_data_inventory.md")
    return {
        "markdown": md_path,
        "csv": csv_path,
        "manifest": manifest_path,
        "observation_count": int(len(observations)),
        "observations_by_section": observations["section"].value_counts().sort_index().astype(int).to_dict() if not observations.empty else {},
    }
from pff_content.periods import Period
