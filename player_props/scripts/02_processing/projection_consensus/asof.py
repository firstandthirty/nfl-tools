from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .loader import DEFAULT_TZ, normalize_datetime, parse_as_of


def _source_list_to_names(sources: list[str] | str | None) -> list[str]:
    if sources is None:
        return []
    if isinstance(sources, str):
        return [sources]
    return [str(item) for item in sources if str(item).strip()]


def select_source_snapshots(registry_df: pd.DataFrame, *, project_root: Path | str, season: int | str, week: int | str, as_of: str | datetime, sources: list[str] | str | None = None) -> tuple[pd.DataFrame, list[str]]:
    project_root = Path(project_root).resolve()
    requested_sources = _source_list_to_names(sources)
    as_of_dt = parse_as_of(as_of)
    if registry_df.empty:
        selection_rows: list[dict[str, Any]] = []
        for source in requested_sources:
            selection_rows.append({
                "source": source,
                "season": int(season),
                "week": int(week),
                "requested_as_of": as_of_dt.isoformat(),
                "selected_captured_at": "",
                "selected_raw_file": "",
                "selected_processed_file": "",
                "raw_file_sha256": "",
                "canonical_rows": 0,
                "unique_players": 0,
                "markets_covered": "",
                "selection_status": "source_not_available",
                "exclusion_reason": "source_not_available",
                "snapshot_age_hours": None,
            })
        return pd.DataFrame(selection_rows), requested_sources

    filtered = registry_df.loc[(registry_df["season"].astype(int) == int(season)) & (registry_df["week"].astype(int) == int(week))].copy()
    if requested_sources:
        filtered = filtered.loc[filtered["source"].isin(requested_sources)].copy()
    else:
        filtered = filtered.loc[~filtered["source"].isin([""])].copy()

    available_sources = sorted({str(source) for source in filtered["source"].dropna().astype(str).tolist()})
    selection_rows: list[dict[str, Any]] = []
    for source in requested_sources or available_sources:
        source_rows = filtered.loc[filtered["source"].astype(str) == source]
        if source_rows.empty:
            selection_rows.append({
                "source": source,
                "season": int(season),
                "week": int(week),
                "requested_as_of": as_of_dt.isoformat(),
                "selected_captured_at": "",
                "selected_raw_file": "",
                "selected_processed_file": "",
                "raw_file_sha256": "",
                "canonical_rows": 0,
                "unique_players": 0,
                "markets_covered": "",
                "selection_status": "source_not_available",
                "exclusion_reason": "source_not_available",
                "snapshot_age_hours": None,
            })
            continue
        eligible = source_rows.loc[source_rows["captured_at_dt"] <= as_of_dt].copy()
        if eligible.empty:
            selection_rows.append({
                "source": source,
                "season": int(season),
                "week": int(week),
                "requested_as_of": as_of_dt.isoformat(),
                "selected_captured_at": "",
                "selected_raw_file": "",
                "selected_processed_file": "",
                "raw_file_sha256": "",
                "canonical_rows": 0,
                "unique_players": 0,
                "markets_covered": "",
                "selection_status": "no_snapshot_before_as_of",
                "exclusion_reason": "no_snapshot_before_as_of",
                "snapshot_age_hours": None,
            })
            continue
        eligible = eligible.sort_values(["captured_at_dt", "raw_file"], ascending=[True, True])
        selected_row = eligible.iloc[-1].to_dict()
        if len(eligible) > 1 and eligible["captured_at_dt"].nunique() == 1:
            status = "conflict"
            reason = "multiple_snapshots_same_timestamp"
        else:
            status = "selected"
            reason = ""
        snapshot_age_hours = (as_of_dt - normalize_datetime(selected_row["captured_at"])).total_seconds() / 3600.0
        selection_rows.append({
            "source": source,
            "season": int(season),
            "week": int(week),
            "requested_as_of": as_of_dt.isoformat(),
            "selected_captured_at": normalize_datetime(selected_row["captured_at"]).isoformat(),
            "selected_raw_file": selected_row.get("raw_file_repo", selected_row.get("raw_file", "")),
            "selected_processed_file": selected_row.get("processed_long_file_repo", selected_row.get("processed_long_file", "")),
            "raw_file_sha256": selected_row.get("raw_file_sha256", ""),
            "canonical_rows": int(selected_row.get("canonical_rows", 0) or 0),
            "unique_players": int(selected_row.get("unique_players", 0) or 0),
            "markets_covered": str(selected_row.get("markets_covered", "")),
            "selection_status": status,
            "exclusion_reason": reason,
            "snapshot_age_hours": float(snapshot_age_hours),
        })

    selection_df = pd.DataFrame(selection_rows)
    if not selection_df.empty and "source" in selection_df.columns:
        selection_df = selection_df.sort_values(["source"]).reset_index(drop=True)
    return selection_df, requested_sources or available_sources
