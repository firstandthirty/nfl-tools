from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .asof import select_source_snapshots
from .loader import DEFAULT_TZ, load_selected_source_rows, normalize_datetime, parse_as_of


def _dedupe_sources(sources: list[str] | tuple[str, ...] | None) -> list[str]:
    if not sources:
        return []
    unique: list[str] = []
    for source in sorted({str(item) for item in sources if str(item).strip()}):
        if source not in unique:
            unique.append(source)
    return unique


def _coalesce_value(values: list[Any]) -> Any:
    non_empty = [value for value in values if value is not None and str(value).strip() != ""]
    if not non_empty:
        return ""
    return non_empty[0]


def _list_field(values: list[str]) -> str:
    return "|".join(sorted({str(value) for value in values if str(value).strip()}))


def _collect_duplicates(frame: pd.DataFrame) -> list[dict[str, Any]]:
    duplicates = []
    if frame.empty:
        return duplicates
    key_cols = ["player_normalized", "market"]
    if not set(key_cols).issubset(frame.columns):
        return duplicates
    dup_mask = frame.duplicated(subset=key_cols, keep=False)
    for _, row in frame.loc[dup_mask].iterrows():
        duplicates.append({"player_normalized": row["player_normalized"], "market": row["market"]})
    return duplicates


def _make_consensus_row(group: pd.DataFrame, *, as_of_dt: datetime, season: int, week: int, min_sources: int, max_projection_std: float | None, max_projection_range: float | None, required_sources: list[str], max_snapshot_age_hours: float | None, max_source_time_gap_hours: float | None) -> dict[str, Any]:
    values = group["projection"].astype(float).tolist()
    projection_count = len(values)
    projection_mean = float(np.mean(values)) if values else np.nan
    projection_median = float(np.median(values)) if values else np.nan
    projection_std = float(np.std(values, ddof=1)) if projection_count > 1 else np.nan
    projection_min = float(np.min(values)) if values else np.nan
    projection_max = float(np.max(values)) if values else np.nan
    projection_range = projection_max - projection_min if values else np.nan
    projection_cv = (projection_std / projection_mean) if projection_mean not in (0, np.nan) and projection_std not in (None, np.nan) else np.nan
    source_names = sorted({str(value) for value in group["source"].dropna().astype(str).tolist()})
    source_values = [f"{source}={float(group.loc[group['source'].astype(str) == source, 'projection'].iloc[0]):g}" for source in source_names]
    earliest_snapshot = min(group["captured_at_dt"].tolist()) if not group.empty else as_of_dt
    latest_snapshot = max(group["captured_at_dt"].tolist()) if not group.empty else as_of_dt
    snapshot_time_range_hours = (latest_snapshot - earliest_snapshot).total_seconds() / 3600.0 if not group.empty else 0.0
    snapshot_age_hours = (as_of_dt - earliest_snapshot).total_seconds() / 3600.0 if not group.empty else 0.0
    max_absolute_deviation_from_mean = float(max(abs(value - projection_mean) for value in values)) if values else np.nan
    mean_absolute_deviation = float(np.mean([abs(value - projection_mean) for value in values])) if values else np.nan
    sources_above_mean = int(sum(1 for value in values if value > projection_mean)) if values else 0
    sources_below_mean = int(sum(1 for value in values if value < projection_mean)) if values else 0
    source_rank_order = "|".join([f"{source}={index + 1}" for index, source in enumerate(sorted(source_names))])

    player_values = [str(value) for value in group["player"].dropna().astype(str).tolist() if str(value).strip()]
    team_values = [str(value) for value in group["team"].dropna().astype(str).tolist() if str(value).strip()]
    position_values = [str(value) for value in group["position"].dropna().astype(str).tolist() if str(value).strip()]
    name_conflict = len(set(player_values)) > 1 if player_values else False
    team_conflict = len(set(team_values)) > 1 if team_values else False
    position_conflict = len(set(position_values)) > 1 if position_values else False

    meets_min_sources = projection_count >= min_sources
    meets_max_std = True if max_projection_std is None else projection_std is np.nan or projection_std <= max_projection_std
    meets_max_range = True if max_projection_range is None else projection_range is np.nan or projection_range <= max_projection_range
    has_required_sources = True if not required_sources else all(source in source_names for source in required_sources)
    meets_max_snapshot_age = True if max_snapshot_age_hours is None else snapshot_age_hours < max_snapshot_age_hours
    meets_max_source_time_gap = True if max_source_time_gap_hours is None else snapshot_time_range_hours <= max_source_time_gap_hours
    eligible = meets_min_sources and meets_max_std and meets_max_range and has_required_sources and meets_max_snapshot_age and meets_max_source_time_gap
    reasons = []
    if not meets_min_sources:
        reasons.append("insufficient_sources")
    if max_projection_std is not None and not meets_max_std:
        reasons.append("projection_std_exceeds_max")
    if max_projection_range is not None and not meets_max_range:
        reasons.append("projection_range_exceeds_max")
    if required_sources and not has_required_sources:
        reasons.append("missing_required_sources")
    if max_snapshot_age_hours is not None and not meets_max_snapshot_age:
        reasons.append("snapshot_age_exceeds_max")
    if max_source_time_gap_hours is not None and not meets_max_source_time_gap:
        reasons.append("source_time_gap_exceeds_max")

    return {
        "season": int(season),
        "week": int(week),
        "player": _coalesce_value(player_values),
        "player_normalized": str(group["player_normalized"].iloc[0]),
        "team": _coalesce_value(team_values),
        "position": _coalesce_value(position_values),
        "market": str(group["market"].iloc[0]),
        "as_of": as_of_dt.isoformat(),
        "projection_count": int(projection_count),
        "projection_mean": float(projection_mean) if not pd.isna(projection_mean) else np.nan,
        "projection_median": float(projection_median) if not pd.isna(projection_median) else np.nan,
        "projection_std": float(projection_std) if not pd.isna(projection_std) else np.nan,
        "projection_min": float(projection_min) if not pd.isna(projection_min) else np.nan,
        "projection_max": float(projection_max) if not pd.isna(projection_max) else np.nan,
        "projection_range": float(projection_range) if not pd.isna(projection_range) else np.nan,
        "projection_cv": float(projection_cv) if not pd.isna(projection_cv) else np.nan,
        "sources": "|".join(source_names),
        "source_values": "|".join(source_values),
        "earliest_selected_snapshot": earliest_snapshot.isoformat(),
        "latest_selected_snapshot": latest_snapshot.isoformat(),
        "snapshot_time_range_hours": float(snapshot_time_range_hours),
        "has_1_source": int(projection_count == 1),
        "has_2_sources": int(projection_count == 2),
        "has_3_sources": int(projection_count >= 3),
        "meets_min_sources": bool(meets_min_sources),
        "meets_max_std": bool(meets_max_std),
        "meets_max_range": bool(meets_max_range),
        "has_required_sources": bool(has_required_sources),
        "meets_max_snapshot_age": bool(meets_max_snapshot_age),
        "meets_max_source_time_gap": bool(meets_max_source_time_gap),
        "consensus_eligible": bool(eligible),
        "ineligibility_reasons": "|".join(reasons),
        "name_conflict": bool(name_conflict),
        "team_conflict": bool(team_conflict),
        "position_conflict": bool(position_conflict),
        "max_absolute_deviation_from_mean": float(max_absolute_deviation_from_mean) if not pd.isna(max_absolute_deviation_from_mean) else np.nan,
        "mean_absolute_deviation": float(mean_absolute_deviation) if not pd.isna(mean_absolute_deviation) else np.nan,
        "sources_above_mean": int(sources_above_mean),
        "sources_below_mean": int(sources_below_mean),
        "source_rank_order": source_rank_order,
    }


def build_consensus_rows(*, registry: pd.DataFrame, project_root: Path | str, season: int | str, week: int | str, as_of: str | datetime, sources: list[str] | str | None = None, min_sources: int = 3, max_projection_std: float | None = None, max_projection_range: float | None = None, required_sources: list[str] | tuple[str, ...] | None = None, max_snapshot_age_hours: float | None = None, max_source_time_gap_hours: float | None = None) -> dict[str, Any]:
    project_root = Path(project_root).resolve()
    as_of_dt = parse_as_of(as_of)
    requested_sources = _dedupe_sources(list(sources) if isinstance(sources, (list, tuple)) else [sources] if isinstance(sources, str) else None)
    if not requested_sources:
        requested_sources = sorted({str(value) for value in registry["source"].dropna().astype(str).tolist() if str(value).strip()})
    selection_df, selected_sources = select_source_snapshots(registry, project_root=project_root, season=season, week=week, as_of=as_of_dt, sources=requested_sources)

    selected_source_rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for _, row in selection_df.iterrows():
        if row["selection_status"] != "selected":
            continue
        try:
            frame = load_selected_source_rows(row.to_dict(), project_root=project_root)
        except (FileNotFoundError, ValueError) as exc:
            warnings.append(f"invalid_snapshot:{row['source']}:{exc}")
            continue
        frame = frame.loc[(frame["season"].astype(int) == int(season)) & (frame["week"].astype(int) == int(week))].copy()
        frame = frame.loc[frame["market"].astype(str).notna()].copy()
        duplicates = _collect_duplicates(frame)
        if duplicates:
            warnings.append("duplicate_canonical_keys")
        for _, projection in frame.iterrows():
            selected_source_rows.append({
                "season": int(season),
                "week": int(week),
                "source": row["source"],
                "player": projection["player"],
                "player_normalized": projection["player_normalized"],
                "team": projection["team"],
                "position": projection["position"],
                "market": projection["market"],
                "projection": float(projection["projection"]),
                "captured_at": projection["captured_at"],
                "captured_at_dt": normalize_datetime(projection["captured_at"]),
                "as_of": as_of_dt.isoformat(),
                "snapshot_age_hours": (as_of_dt - normalize_datetime(projection["captured_at"])).total_seconds() / 3600.0,
                "raw_file": projection.get("raw_file_repo", projection.get("raw_file", "")),
                "processed_file": projection.get("processed_file_repo", ""),
            })

    selected_source_df = pd.DataFrame(selected_source_rows)
    if selected_source_df.empty:
        consensus_rows_df = pd.DataFrame(columns=[
            "season", "week", "player", "player_normalized", "team", "position", "market", "as_of", "projection_count", "projection_mean", "projection_median", "projection_std", "projection_min", "projection_max", "projection_range", "projection_cv", "sources", "source_values", "earliest_selected_snapshot", "latest_selected_snapshot", "snapshot_time_range_hours", "has_1_source", "has_2_sources", "has_3_sources", "meets_min_sources", "meets_max_std", "meets_max_range", "has_required_sources", "meets_max_snapshot_age", "meets_max_source_time_gap", "consensus_eligible", "ineligibility_reasons", "name_conflict", "team_conflict", "position_conflict", "max_absolute_deviation_from_mean", "mean_absolute_deviation", "sources_above_mean", "sources_below_mean", "source_rank_order"
        ])
    else:
        consensus_rows_df = pd.DataFrame([
            _make_consensus_row(group, as_of_dt=as_of_dt, season=int(season), week=int(week), min_sources=min_sources, max_projection_std=max_projection_std, max_projection_range=max_projection_range, required_sources=list(required_sources or []), max_snapshot_age_hours=max_snapshot_age_hours, max_source_time_gap_hours=max_source_time_gap_hours)
            for _, group in selected_source_df.groupby(["player_normalized", "market"], sort=True)
        ])

    if consensus_rows_df.empty:
        consensus_rows_df = pd.DataFrame(columns=[
            "season", "week", "player", "player_normalized", "team", "position", "market", "as_of", "projection_count", "projection_mean", "projection_median", "projection_std", "projection_min", "projection_max", "projection_range", "projection_cv", "sources", "source_values", "earliest_selected_snapshot", "latest_selected_snapshot", "snapshot_time_range_hours", "has_1_source", "has_2_sources", "has_3_sources", "meets_min_sources", "meets_max_std", "meets_max_range", "has_required_sources", "meets_max_snapshot_age", "meets_max_source_time_gap", "consensus_eligible", "ineligibility_reasons", "name_conflict", "team_conflict", "position_conflict", "max_absolute_deviation_from_mean", "mean_absolute_deviation", "sources_above_mean", "sources_below_mean", "source_rank_order"
        ])

    pairwise_rows: list[dict[str, Any]] = []
    if not selected_source_df.empty:
        source_names = sorted({str(source) for source in selected_source_df["source"].dropna().astype(str).tolist()})
        for index_a, source_a in enumerate(source_names):
            for source_b in source_names[index_a + 1:]:
                a_rows = selected_source_df.loc[selected_source_df["source"].astype(str) == source_a]
                b_rows = selected_source_df.loc[selected_source_df["source"].astype(str) == source_b]
                pairs = set(zip(a_rows["player_normalized"].astype(str).tolist(), a_rows["market"].astype(str).tolist())) & set(zip(b_rows["player_normalized"].astype(str).tolist(), b_rows["market"].astype(str).tolist()))
                for player_normalized, market in sorted(pairs):
                    a_value = float(a_rows.loc[(a_rows["player_normalized"].astype(str) == player_normalized) & (a_rows["market"].astype(str) == market), "projection"].iloc[0])
                    b_value = float(b_rows.loc[(b_rows["player_normalized"].astype(str) == player_normalized) & (b_rows["market"].astype(str) == market), "projection"].iloc[0])
                    pairwise_rows.append({
                        "season": int(season),
                        "week": int(week),
                        "player_normalized": player_normalized,
                        "market": market,
                        "source_a": source_a,
                        "source_b": source_b,
                        "projection_a": a_value,
                        "projection_b": b_value,
                        "signed_difference_a_minus_b": b_value - a_value,
                        "absolute_difference": abs(a_value - b_value),
                        "percent_difference": ((a_value - b_value) / b_value) if b_value != 0 else np.nan,
                        "source_a_captured_at": a_rows.loc[(a_rows["player_normalized"].astype(str) == player_normalized) & (a_rows["market"].astype(str) == market), "captured_at"].iloc[0],
                        "source_b_captured_at": b_rows.loc[(b_rows["player_normalized"].astype(str) == player_normalized) & (b_rows["market"].astype(str) == market), "captured_at"].iloc[0],
                        "snapshot_time_difference_hours": (normalize_datetime(a_rows.loc[(a_rows["player_normalized"].astype(str) == player_normalized) & (a_rows["market"].astype(str) == market), "captured_at"].iloc[0]) - normalize_datetime(b_rows.loc[(b_rows["player_normalized"].astype(str) == player_normalized) & (b_rows["market"].astype(str) == market), "captured_at"].iloc[0])).total_seconds() / 3600.0,
                    })

    pairwise_df = pd.DataFrame(pairwise_rows)
    if pairwise_df.empty:
        pairwise_df = pd.DataFrame(columns=["season", "week", "player_normalized", "market", "source_a", "source_b", "projection_a", "projection_b", "signed_difference_a_minus_b", "absolute_difference", "percent_difference", "source_a_captured_at", "source_b_captured_at", "snapshot_time_difference_hours"])

    coverage_rows: list[dict[str, Any]] = []
    if not consensus_rows_df.empty:
        for market in sorted({str(value) for value in consensus_rows_df["market"].dropna().astype(str).tolist()}):
            market_rows = consensus_rows_df.loc[consensus_rows_df["market"].astype(str) == market]
            coverage_rows.append({
                "market": market,
                "selected_sources": market_rows["sources"].tolist()[0] if not market_rows.empty else "",
                "total_consensus_players": int(len(market_rows)),
                "one_source_players": int((market_rows["projection_count"] == 1).sum()),
                "two_source_players": int((market_rows["projection_count"] == 2).sum()),
                "three_plus_source_players": int((market_rows["projection_count"] >= 3).sum()),
                "eligible_players": int((market_rows["consensus_eligible"] == True).sum()),
                "projection_count_mean": float(market_rows["projection_count"].mean()) if not market_rows.empty else np.nan,
                "projection_count_median": float(market_rows["projection_count"].median()) if not market_rows.empty else np.nan,
                "mean_projection_std": float(market_rows["projection_std"].mean()) if not market_rows.empty else np.nan,
                "median_projection_std": float(market_rows["projection_std"].median()) if not market_rows.empty else np.nan,
                "mean_projection_range": float(market_rows["projection_range"].mean()) if not market_rows.empty else np.nan,
                "players_with_name_conflicts": int((market_rows["name_conflict"] == True).sum()),
                "players_with_team_conflicts": int((market_rows["team_conflict"] == True).sum()),
                "players_with_position_conflicts": int((market_rows["position_conflict"] == True).sum()),
            })
    coverage_df = pd.DataFrame(coverage_rows)
    if coverage_df.empty:
        coverage_df = pd.DataFrame(columns=["market", "selected_sources", "total_consensus_players", "one_source_players", "two_source_players", "three_plus_source_players", "eligible_players", "projection_count_mean", "projection_count_median", "mean_projection_std", "median_projection_std", "mean_projection_range", "players_with_name_conflicts", "players_with_team_conflicts", "players_with_position_conflicts"])

    overlap_rows: list[dict[str, Any]] = []
    sources = sorted({str(source) for source in selection_df.loc[selection_df["selection_status"] == "selected", "source"].dropna().astype(str).tolist()}) if not selection_df.empty else []
    for index_a, source_a in enumerate(sources):
        for source_b in sources[index_a + 1:]:
            a_players = set(selected_source_df.loc[selected_source_df["source"].astype(str) == source_a, ["player_normalized", "market"]].apply(tuple, axis=1).tolist())
            b_players = set(selected_source_df.loc[selected_source_df["source"].astype(str) == source_b, ["player_normalized", "market"]].apply(tuple, axis=1).tolist())
            shared = a_players & b_players
            overlap_rows.append({
                "source_a": source_a,
                "source_b": source_b,
                "market": "all",
                "players_source_a": int(len(a_players)),
                "players_source_b": int(len(b_players)),
                "shared_players": int(len(shared)),
                "only_source_a": int(len(a_players - b_players)),
                "only_source_b": int(len(b_players - a_players)),
                "overlap_rate_a": (len(shared) / len(a_players)) if a_players else np.nan,
                "overlap_rate_b": (len(shared) / len(b_players)) if b_players else np.nan,
                "jaccard_similarity": (len(shared) / max(len(a_players), len(b_players))) if max(len(a_players), len(b_players)) else np.nan,
            })
    overlap_df = pd.DataFrame(overlap_rows)
    if overlap_df.empty:
        overlap_df = pd.DataFrame(columns=["source_a", "source_b", "market", "players_source_a", "players_source_b", "shared_players", "only_source_a", "only_source_b", "overlap_rate_a", "overlap_rate_b", "jaccard_similarity"])

    selected_snapshots_df = selection_df.copy()
    selected_snapshots_df["selected_processed_file"] = selected_snapshots_df["selected_processed_file"].fillna("")
    selected_snapshots_df["selected_raw_file"] = selected_snapshots_df["selected_raw_file"].fillna("")

    metadata = {
        "run_timestamp": datetime.now(DEFAULT_TZ).isoformat(),
        "requested_as_of": as_of_dt.isoformat(),
        "season": int(season),
        "week": int(week),
        "requested_sources": "|".join(requested_sources),
        "selected_sources": "|".join(sorted({str(value) for value in selected_snapshots_df.loc[selected_snapshots_df["selection_status"] == "selected", "source"].tolist()})),
        "unavailable_sources": "|".join(sorted({str(value) for value in selected_snapshots_df.loc[selected_snapshots_df["selection_status"].isin(["source_not_available", "no_snapshot_before_as_of"]), "source"].tolist()})),
        "min_sources": int(min_sources),
        "max_projection_std": max_projection_std,
        "max_projection_range": max_projection_range,
        "max_snapshot_age_hours": max_snapshot_age_hours,
        "max_source_time_gap_hours": max_source_time_gap_hours,
        "selected_snapshot_count": int(len(selected_snapshots_df.loc[selected_snapshots_df["selection_status"] == "selected"])),
        "selected_projection_rows": int(len(selected_source_df)),
        "consensus_rows": int(len(consensus_rows_df)),
        "eligible_consensus_rows": int((consensus_rows_df["consensus_eligible"] == True).sum()) if not consensus_rows_df.empty else 0,
        "markets_covered": "|".join(sorted({str(value) for value in consensus_rows_df["market"].dropna().astype(str).tolist()})),
        "warnings": "|".join(warnings),
        "schema_version": "projection_consensus_v1",
    }

    return {
        "selected_snapshots": selected_snapshots_df,
        "selected_source_projections": selected_source_df,
        "consensus_rows": consensus_rows_df,
        "pairwise_differences": pairwise_df,
        "coverage_rows": coverage_df,
        "source_overlap": overlap_df,
        "metadata": metadata,
        "warnings": warnings,
        "requested_sources": requested_sources,
    }
