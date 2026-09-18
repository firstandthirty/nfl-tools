from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from pff_content.analysis.qualifiers import safe_divide
from pff_content.periods import Period


IDENTITY_COLUMNS = ["player_id", "player_name"]
TEAM_IDENTITY_COLUMNS = ["season", "team"]


def nfl_passer_rating(completions: pd.Series, attempts: pd.Series, yards: pd.Series, touchdowns: pd.Series, interceptions: pd.Series) -> pd.Series:
    att = pd.to_numeric(attempts, errors="coerce")
    comp = pd.to_numeric(completions, errors="coerce")
    yds = pd.to_numeric(yards, errors="coerce")
    td = pd.to_numeric(touchdowns, errors="coerce")
    ints = pd.to_numeric(interceptions, errors="coerce")
    a = ((comp / att) - 0.3) * 5
    b = ((yds / att) - 3) * 0.25
    c = (td / att) * 20
    d = 2.375 - ((ints / att) * 25)
    rating = ((a.clip(0, 2.375) + b.clip(0, 2.375) + c.clip(0, 2.375) + d.clip(0, 2.375)) / 6) * 100
    return rating.where(att > 0)


def aggregate_period(dataset: str, weekly_frames: Iterable[pd.DataFrame], period: Period) -> pd.DataFrame:
    frames = [frame.copy() for frame in weekly_frames if frame is not None and not frame.empty]
    if not frames:
        return pd.DataFrame()
    if period.is_week:
        out = frames[-1].copy()
        out["period_type"] = period.period_type.value
        out["start_week"] = period.start_week
        out["end_week"] = period.end_week
        out["period_label"] = period.display_label
        return out
    df = pd.concat(frames, ignore_index=True, sort=False)
    if dataset == "games":
        return df.drop_duplicates(subset=["game_id"], keep="last").reset_index(drop=True)
    if dataset == "coverage_scheme":
        return _aggregate_player_dataset(df, period, _coverage_scheme_additive_columns(df))
    if dataset in {"passing", "receiving", "rushing", "pass_blocking", "pass_rush", "run_defense", "coverage", "time_in_pocket"}:
        df = _add_weighted_components(dataset, df)
        out = _aggregate_player_dataset(df, period, _additive_columns(dataset, df))
        return _recompute_dataset_metrics(dataset, out)
    return df


def _group_columns(df: pd.DataFrame) -> list[str]:
    if "player_id" in df.columns and df["player_id"].notna().any():
        return ["player_id"]
    return ["player_name"]


def _aggregate_player_dataset(df: pd.DataFrame, period: Period, additive_cols: list[str]) -> pd.DataFrame:
    group_cols = _group_columns(df)
    additive_cols = [col for col in additive_cols if col in df.columns and col not in group_cols]
    rows = []
    for _, group in df.groupby(group_cols, dropna=False, sort=False):
        sort_cols = ["week"] + (["player_game_count"] if "player_game_count" in group.columns else [])
        latest = group.sort_values(sort_cols, ascending=[True] * len(sort_cols), kind="mergesort").iloc[-1]
        row = {
            "season": period.season,
            "week": period.end_week,
            "period_type": period.period_type.value,
            "start_week": period.start_week,
            "end_week": period.end_week,
            "period_label": period.display_label,
        }
        for col in group_cols:
            row[col] = latest.get(col)
        for col in ["player_name", "position", "draft_season", "rookie", "team_name", "franchise_id", "jersey_number"]:
            if col in group.columns and col not in row:
                row[col] = latest.get(col)
        teams = [str(v) for v in group.sort_values("week")["team"].dropna().unique().tolist()] if "team" in group.columns else []
        row["team"] = teams[-1] if teams else latest.get("team")
        row["team_list"] = ",".join(teams)
        row["team_count"] = len(teams)
        row["opponent"] = "MULTI"
        row["games_represented"] = int(group["game_id"].nunique()) if "game_id" in group.columns else int(group["week"].nunique())
        for col in additive_cols:
            row[col] = pd.to_numeric(group[col], errors="coerce").sum(min_count=1)
        rows.append(row)
    return pd.DataFrame(rows)


def _additive_columns(dataset: str, df: pd.DataFrame) -> list[str]:
    by_dataset = {
        "passing": ["attempts", "completions", "yards", "touchdowns", "interceptions", "turnover_worthy_plays", "big_time_throws", "def_gen_pressures", "dropbacks", "sacks", "passing_snaps", "scrambles", "spikes", "thrown_aways", "drops", "avg_time_to_throw_x_dropbacks", "avg_depth_of_target_x_attempts"],
        "receiving": ["targets", "routes", "receptions", "yards", "yards_after_catch", "touchdowns", "drops", "avoided_tackles", "slot_snaps", "wide_snaps", "inline_snaps", "pass_plays", "interceptions", "avg_depth_of_target_x_targets"],
        "rushing": ["attempts", "yards", "yards_after_contact", "avoided_tackles", "elu_rush_mtf", "breakaway_attempts", "breakaway_yards", "receptions", "routes", "targets", "touchdowns", "total_touches", "scrambles", "scramble_yards"],
        "pass_blocking": ["pass_block_snaps", "pressures_allowed", "sacks_allowed", "hits_allowed", "hurries_allowed", "snap_counts_pass_play", "true_pass_set_pressures_allowed", "true_pass_set_sacks_allowed", "true_pass_set_hits_allowed", "true_pass_set_hurries_allowed", "true_pass_set_snap_counts_pass_block", "true_pass_set_snap_counts_pass_play"],
        "pass_rush": ["pass_rush_snaps", "total_pressures", "sacks", "hits", "hurries", "pass_rush_wins", "pass_rush_opp", "batted_passes", "snap_counts_pass_play", "true_pass_set_total_pressures", "true_pass_set_sacks", "true_pass_set_hits", "true_pass_set_hurries", "true_pass_set_pass_rush_wins", "true_pass_set_pass_rush_opp", "true_pass_set_snap_counts_pass_rush", "true_pass_set_snap_counts_pass_play"],
        "run_defense": ["run_defense_snaps", "run_stop_opp", "stops", "tackles", "assists", "missed_tackles", "forced_fumbles"],
        "coverage": ["coverage_snaps", "snap_counts_pass_play", "targets", "receptions", "yards", "touchdowns_allowed", "interceptions", "forced_incompletes", "pass_break_ups", "yards_after_catch", "stops", "tackles", "assists", "missed_tackles", "dropped_ints"],
        "time_in_pocket": ["dropbacks", "avg_ttt_attempts", "avg_ttt_sacks", "avg_ttt_scrambles"],
    }
    cols = list(by_dataset.get(dataset, []))
    for col in df.columns:
        if col.endswith("_count") and col not in cols:
            cols.append(col)
    return cols


def _coverage_scheme_additive_columns(df: pd.DataFrame) -> list[str]:
    prefixes = ("man_", "zone_", "base_")
    return [col for col in df.columns if col.startswith(prefixes) and any(token in col for token in ("snap_counts", "targets", "receptions", "yards", "forced_incompletes", "touchdowns", "interceptions", "tackles", "stops", "pass_break_ups"))]


def _add_weighted_components(dataset: str, df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if dataset == "passing":
        if {"avg_time_to_throw", "dropbacks"}.issubset(out.columns):
            out["avg_time_to_throw_x_dropbacks"] = pd.to_numeric(out["avg_time_to_throw"], errors="coerce") * pd.to_numeric(out["dropbacks"], errors="coerce")
        if {"avg_depth_of_target", "attempts"}.issubset(out.columns):
            out["avg_depth_of_target_x_attempts"] = pd.to_numeric(out["avg_depth_of_target"], errors="coerce") * pd.to_numeric(out["attempts"], errors="coerce")
    if dataset == "receiving" and {"avg_depth_of_target", "targets"}.issubset(out.columns):
        out["avg_depth_of_target_x_targets"] = pd.to_numeric(out["avg_depth_of_target"], errors="coerce") * pd.to_numeric(out["targets"], errors="coerce")
    return out


def _recompute_dataset_metrics(dataset: str, df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if dataset == "passing":
        out["pressure_rate_faced"] = safe_divide(out["def_gen_pressures"], out["dropbacks"])
        out["twp_per_dropback"] = safe_divide(out["turnover_worthy_plays"], out["dropbacks"])
        out["btt_per_dropback"] = safe_divide(out["big_time_throws"], out["dropbacks"])
        out["avg_time_to_throw"] = safe_divide(out.get("avg_time_to_throw_x_dropbacks", pd.Series(pd.NA, index=out.index)), out["dropbacks"])
        out["avg_depth_of_target"] = safe_divide(out.get("avg_depth_of_target_x_attempts", pd.Series(pd.NA, index=out.index)), out["attempts"])
    if dataset == "receiving":
        out["targets_per_route_run"] = safe_divide(out["targets"], out["routes"])
        out["yprr"] = safe_divide(out["yards"], out["routes"])
        out["avg_depth_of_target"] = safe_divide(out.get("avg_depth_of_target_x_targets", pd.Series(pd.NA, index=out.index)), out["targets"])
        out["slot_rate"] = safe_divide(out.get("slot_snaps", pd.Series(0, index=out.index)), out["routes"])
        out["wide_rate"] = safe_divide(out.get("wide_snaps", pd.Series(0, index=out.index)), out["routes"])
        out["inline_rate"] = safe_divide(out.get("inline_snaps", pd.Series(0, index=out.index)), out["routes"])
    if dataset == "rushing":
        out["yards_per_carry"] = safe_divide(out["yards"], out["attempts"])
        out["ypa"] = out["yards_per_carry"]
        out["yards_after_contact_per_attempt"] = safe_divide(out["yards_after_contact"], out["attempts"])
        out["yco_attempt"] = out["yards_after_contact_per_attempt"]
    if dataset == "pass_blocking":
        out["pressure_rate_allowed"] = safe_divide(out["pressures_allowed"], out["pass_block_snaps"])
        out["pass_blocking_efficiency"] = pd.NA
        out["true_pass_set_pbe"] = pd.NA
    if dataset == "pass_rush":
        out["pressure_rate"] = safe_divide(out["total_pressures"], out["pass_rush_snaps"])
        out["pass_rush_win_rate"] = safe_divide(out["pass_rush_wins"], out["pass_rush_opp"]) * 100
        out["pass_rush_productivity"] = pd.NA
        out["true_pass_set_pass_rush_win_rate"] = safe_divide(out["true_pass_set_pass_rush_wins"], out["true_pass_set_pass_rush_opp"]) * 100
        out["true_pass_set_prp"] = pd.NA
    if dataset == "run_defense":
        out["run_stop_rate"] = safe_divide(out["stops"], out["run_defense_snaps"])
        out["run_stop_percent"] = out["run_stop_rate"] * 100
    if dataset == "coverage":
        out["catch_rate_allowed"] = safe_divide(out["receptions"], out["targets"])
        out["forced_incompletion_rate"] = safe_divide(out["forced_incompletes"], out["targets"])
        out["yards_per_coverage_snap"] = safe_divide(out["yards"], out["coverage_snaps"])
        out["passer_rating_when_targeted"] = nfl_passer_rating(out["receptions"], out["targets"], out["yards"], out["touchdowns_allowed"], out["interceptions"])
    return out
