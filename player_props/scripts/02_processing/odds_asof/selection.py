from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .loader import load_selected_odds, normalize_datetime, parse_as_of


def _requested_books(registry: pd.DataFrame, sportsbooks: list[str] | str | None) -> list[str]:
    if isinstance(sportsbooks, str):
        return [sportsbooks]
    if sportsbooks:
        return sorted({str(book) for book in sportsbooks if str(book).strip()})
    books: set[str] = set()
    if "sportsbooks" in registry.columns:
        for value in registry["sportsbooks"].dropna().astype(str):
            books.update(part for part in value.split("|") if part)
    return sorted(books)


def _select_with_stale_sportsbook_backfill(*, registry: pd.DataFrame, project_root: Path, season: int | str, week: int | str, as_of_dt: Any, requested: list[str], market: str | None) -> dict[str, Any]:
    project_root = Path(project_root).resolve()
    rows: list[dict] = []
    selected_frames: list[pd.DataFrame] = []
    filtered = registry.loc[(registry["season"].astype(int) == int(season)) & (registry["week"].astype(int) == int(week))].copy() if not registry.empty else pd.DataFrame()

    for sportsbook in requested:
        book_rows = filtered.loc[filtered["sportsbooks"].astype(str).str.split("|").apply(lambda parts: sportsbook in parts)].copy() if not filtered.empty else pd.DataFrame()
        if market and not book_rows.empty:
            book_rows = book_rows.loc[book_rows["markets_covered"].astype(str).str.split("|").apply(lambda parts: market in parts)].copy()
        if book_rows.empty:
            rows.append({"sportsbook": sportsbook, "season": int(season), "week": int(week), "requested_as_of": as_of_dt.isoformat(), "selected_captured_at": "", "selected_raw_file": "", "selected_processed_file": "", "selection_status": "sportsbook_not_available", "exclusion_reason": "sportsbook_not_available", "snapshot_age_hours": None})
            continue
        eligible = book_rows.loc[book_rows["captured_at_dt"] <= as_of_dt].copy()
        if eligible.empty:
            rows.append({"sportsbook": sportsbook, "season": int(season), "week": int(week), "requested_as_of": as_of_dt.isoformat(), "selected_captured_at": "", "selected_raw_file": "", "selected_processed_file": "", "selection_status": "no_snapshot_before_as_of", "exclusion_reason": "no_snapshot_before_as_of", "snapshot_age_hours": None})
            continue
        eligible = eligible.sort_values(["captured_at_dt", "raw_file_repo"], ascending=[True, True])
        selected = eligible.iloc[-1].to_dict()
        same_latest = eligible.loc[eligible["captured_at_dt"] == selected["captured_at_dt"]]
        status = "conflict" if len(same_latest["raw_file_sha256"].dropna().astype(str).unique()) > 1 else "selected"
        reason = "multiple_snapshots_same_timestamp" if status == "conflict" else ""
        rows.append({"sportsbook": sportsbook, "season": int(season), "week": int(week), "requested_as_of": as_of_dt.isoformat(), "selected_captured_at": normalize_datetime(selected["captured_at"]).isoformat(), "selected_raw_file": selected.get("raw_file_repo", selected.get("raw_file", "")), "selected_processed_file": selected.get("processed_long_file_repo", selected.get("processed_long_file", "")), "selection_status": status, "exclusion_reason": reason, "snapshot_age_hours": (as_of_dt - normalize_datetime(selected["captured_at"])).total_seconds() / 3600.0})
        if status == "selected":
            selected_df = load_selected_odds(selected, project_root=project_root, sportsbook=sportsbook, market=market)
            selected_frames.append(selected_df)

    selected_snapshots = pd.DataFrame(rows)
    selected_odds = pd.concat(selected_frames, ignore_index=True) if selected_frames else pd.DataFrame()
    coverage = _coverage(selected_odds)
    return {"selected_snapshots": selected_snapshots, "selected_odds": selected_odds, "coverage": coverage, "as_of": as_of_dt, "requested_sportsbooks": requested, "selection_mode": "stale_sportsbook_backfill"}


def _coverage(selected_odds: pd.DataFrame) -> pd.DataFrame:
    coverage_rows: list[dict] = []
    if not selected_odds.empty:
        for book, grouped in selected_odds.groupby("sportsbook", sort=True):
            coverage_rows.append({"sportsbook": book, "rows": len(grouped), "unique_events": grouped["event_id"].nunique(), "unique_players": grouped["player_normalized"].nunique(), "markets": "|".join(sorted(grouped["market"].dropna().astype(str).unique())), "main_line_rows": int((grouped["is_alternate"] == False).sum()), "alternate_line_rows": int((grouped["is_alternate"] == True).sum())})
    return pd.DataFrame(coverage_rows, columns=["sportsbook", "rows", "unique_events", "unique_players", "markets", "main_line_rows", "alternate_line_rows"])


def select_odds_asof(*, registry: pd.DataFrame, project_root: Path | str, season: int | str, week: int | str, as_of: str, sportsbooks: list[str] | str | None = None, market: str | None = None, allow_stale_sportsbook_backfill: bool = False) -> dict[str, Any]:
    project_root = Path(project_root).resolve()
    as_of_dt = parse_as_of(as_of)
    requested = _requested_books(registry, sportsbooks)
    filtered = registry.loc[(registry["season"].astype(int) == int(season)) & (registry["week"].astype(int) == int(week))].copy() if not registry.empty else pd.DataFrame()

    if allow_stale_sportsbook_backfill:
        return _select_with_stale_sportsbook_backfill(
            registry=registry,
            project_root=project_root,
            season=season,
            week=week,
            as_of_dt=as_of_dt,
            requested=requested,
            market=market,
        )

    rows: list[dict] = []
    selected_frames: list[pd.DataFrame] = []
    eligible = filtered.loc[filtered["captured_at_dt"] <= as_of_dt].copy() if not filtered.empty else pd.DataFrame()
    if market and not eligible.empty:
        eligible = eligible.loc[eligible["markets_covered"].astype(str).str.split("|").apply(lambda parts: market in parts)].copy()

    if eligible.empty:
        for sportsbook in requested:
            rows.append({"sportsbook": sportsbook, "season": int(season), "week": int(week), "requested_as_of": as_of_dt.isoformat(), "selected_captured_at": "", "selected_raw_file": "", "selected_processed_file": "", "selection_status": "no_snapshot_before_as_of", "exclusion_reason": "no_snapshot_before_as_of", "snapshot_age_hours": None})
        selected_snapshots = pd.DataFrame(rows)
        return {"selected_snapshots": selected_snapshots, "selected_odds": pd.DataFrame(), "coverage": _coverage(pd.DataFrame()), "as_of": as_of_dt, "requested_sportsbooks": requested, "selection_mode": "coherent_snapshot"}

    eligible = eligible.sort_values(["captured_at_dt", "raw_file_repo"], ascending=[True, True])
    selected = eligible.iloc[-1].to_dict()
    bundle_books = [book for book in str(selected.get("sportsbooks", "")).split("|") if book]
    selected_books = [book for book in requested if book in bundle_books] if sportsbooks else bundle_books
    missing_requested = [book for book in requested if book not in bundle_books] if sportsbooks else []
    same_latest = eligible.loc[eligible["captured_at_dt"] == selected["captured_at_dt"]]
    status = "conflict" if len(same_latest["raw_file_sha256"].dropna().astype(str).unique()) > 1 else "selected"
    reason = "multiple_snapshots_same_timestamp" if status == "conflict" else ""

    for sportsbook in selected_books:
        rows.append({"sportsbook": sportsbook, "season": int(season), "week": int(week), "requested_as_of": as_of_dt.isoformat(), "selected_captured_at": normalize_datetime(selected["captured_at"]).isoformat(), "selected_raw_file": selected.get("raw_file_repo", selected.get("raw_file", "")), "selected_processed_file": selected.get("processed_long_file_repo", selected.get("processed_long_file", "")), "selection_status": status, "exclusion_reason": reason, "snapshot_age_hours": (as_of_dt - normalize_datetime(selected["captured_at"])).total_seconds() / 3600.0})

    for sportsbook in missing_requested:
        rows.append({"sportsbook": sportsbook, "season": int(season), "week": int(week), "requested_as_of": as_of_dt.isoformat(), "selected_captured_at": normalize_datetime(selected["captured_at"]).isoformat(), "selected_raw_file": selected.get("raw_file_repo", selected.get("raw_file", "")), "selected_processed_file": selected.get("processed_long_file_repo", selected.get("processed_long_file", "")), "selection_status": "sportsbook_not_in_selected_snapshot", "exclusion_reason": "sportsbook_not_in_selected_snapshot", "snapshot_age_hours": (as_of_dt - normalize_datetime(selected["captured_at"])).total_seconds() / 3600.0})

    if status == "selected" and selected_books:
        selected_df = load_selected_odds(selected, project_root=project_root, sportsbook=None, market=market)
        if not selected_df.empty:
            selected_df = selected_df.loc[selected_df["sportsbook"].astype(str).isin(selected_books)].copy()
        selected_frames.append(selected_df)

    selected_snapshots = pd.DataFrame(rows)
    selected_odds = pd.concat(selected_frames, ignore_index=True) if selected_frames else pd.DataFrame()
    coverage = _coverage(selected_odds)
    return {"selected_snapshots": selected_snapshots, "selected_odds": selected_odds, "coverage": coverage, "as_of": as_of_dt, "requested_sportsbooks": selected_books if not sportsbooks else requested, "selection_mode": "coherent_snapshot"}
