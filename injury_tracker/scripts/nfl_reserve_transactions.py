from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .injury_schema import PROJECT_ROOT, load_json, load_teams, normalize_player_name
from .official_injury_reports import USER_AGENT
from .pff_enrichment import (
    build_pff_player_index,
    load_persisted_mappings,
    match_player,
    profiles_by_alias,
    profiles_by_exact_normalized_name,
    profiles_by_normalized_name,
)


RAW_ROOT = PROJECT_ROOT / "data" / "raw" / "nfl_transactions"
PROCESSED_ROOT = PROJECT_ROOT / "data" / "processed"
PARSER_VERSION = "nfl_transactions_reserve_list_table_v1"
BASE_URL = "https://www.nfl.com/transactions/league/reserve-list/{year}/{month}"
RESERVE_STATUSES = {"IR", "PUP", "NFI", "OTHER_RESERVE"}
PLACEMENT_EVENT_TYPES = {"PLACED_ON_IR", "PLACED_ON_PUP", "PLACED_ON_NFI"}
ACTIVATION_EVENT_TYPES = {"ACTIVATED_FROM_IR", "ACTIVATED_FROM_PUP", "ACTIVATED_FROM_NFI"}


@dataclass
class TransactionPage:
    url: str
    fetched_at: str
    status: str
    http_status: int | None = None
    content_type: str | None = None
    body: str | None = None
    error: str | None = None


@dataclass
class TransactionCell:
    text: str = ""
    href: str | None = None


@dataclass
class TransactionTable:
    headers: list[str]
    rows: list[list[TransactionCell]] = field(default_factory=list)


class TransactionTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[TransactionTable] = []
        self.next_page: str | None = None
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._cell_href: str | None = None
        self._current_row: list[TransactionCell] = []
        self._current_table: list[list[TransactionCell]] = []
        self._current_link_href: str | None = None
        self._current_link_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_dict = dict(attrs)
        if tag == "table":
            self._in_table = True
            self._current_table = []
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._current_row = []
        elif self._in_table and tag in {"td", "th"}:
            self._in_cell = True
            self._cell_parts = []
            self._cell_href = None
        elif tag == "a":
            href = attrs_dict.get("href")
            if self._in_cell and href:
                self._cell_href = href
            self._current_link_href = href
            self._current_link_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._in_table and tag in {"td", "th"}:
            self._current_row.append(TransactionCell(clean_text(" ".join(self._cell_parts)), self._cell_href))
            self._in_cell = False
            self._cell_parts = []
            self._cell_href = None
        elif self._in_table and tag == "tr":
            if any(cell.text for cell in self._current_row):
                self._current_table.append(self._current_row)
            self._in_row = False
            self._current_row = []
        elif tag == "table" and self._in_table:
            if self._current_table:
                headers = [canonical_header(cell.text) for cell in self._current_table[0]]
                self.tables.append(TransactionTable(headers=headers, rows=self._current_table[1:]))
            self._in_table = False
            self._current_table = []
        elif tag == "a" and self._current_link_href:
            text = clean_text(" ".join(self._current_link_parts)).lower()
            if text == "next page":
                self.next_page = self._current_link_href
            self._current_link_href = None
            self._current_link_parts = []

    def handle_data(self, data: str) -> None:
        text = clean_text(data)
        if not text:
            return
        if self._in_cell:
            self._cell_parts.append(text)
        if self._current_link_href:
            self._current_link_parts.append(text)


def run_week3_reserve_transaction_reconciliation(
    *,
    season: int,
    week: int,
    reserve_run_dir: Path,
    months: list[int] | None = None,
    delay_seconds: float = 0.25,
    timeout: int = 25,
    retries: int = 2,
) -> dict[str, Any]:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    selected_months = months or default_months_for_week(season, week)
    raw_month_files = []
    all_events: list[dict[str, Any]] = []
    pages_by_month: dict[int, int] = {}
    for index, month in enumerate(selected_months):
        if index and delay_seconds > 0:
            time.sleep(delay_seconds)
        bundle = fetch_month_pages(season, month, timeout=timeout, retries=retries, delay_seconds=delay_seconds)
        raw_path, metadata_path = save_month_bundle(bundle, season=season, run_id=run_id, month=month)
        raw_month_files.append({"month": month, "raw_file": str(raw_path), "metadata_file": str(metadata_path)})
        pages_by_month[month] = len(bundle["pages"])
        all_events.extend(parse_month_bundle(bundle, season=season, month=month, raw_file=str(raw_path)))

    enriched_events, identity_summary = enrich_transaction_identities(all_events, season=season, week=week)
    current_reserves = load_json(reserve_run_dir / "reserve_players.json")
    enriched_reserves, reconciliation_rows = attach_events_to_current_reserves(current_reserves, enriched_events)
    summary = build_summary(
        season=season,
        week=week,
        run_id=run_id,
        reserve_run_dir=reserve_run_dir,
        months=selected_months,
        pages_by_month=pages_by_month,
        raw_month_files=raw_month_files,
        events=enriched_events,
        current_reserves=enriched_reserves,
        reconciliation_rows=reconciliation_rows,
        identity_summary=identity_summary,
    )
    write_outputs(reserve_run_dir, enriched_events, enriched_reserves, reconciliation_rows, summary)
    return summary


def default_months_for_week(season: int, week: int) -> list[int]:
    if season == 2026 and week <= 3:
        return [8, 9]
    return [8, 9]


def fetch_month_pages(
    year: int,
    month: int,
    *,
    timeout: int = 25,
    retries: int = 2,
    delay_seconds: float = 0.25,
) -> dict[str, Any]:
    url = BASE_URL.format(year=year, month=month)
    pages = []
    seen: set[str] = set()
    seen_body_hashes: set[str] = set()
    while url and url not in seen:
        seen.add(url)
        page = fetch_page(url, timeout=timeout, retries=retries)
        if page.body:
            body_hash = hashlib.sha256(page.body.encode("utf-8")).hexdigest()
            if body_hash in seen_body_hashes:
                duplicate = dict(page.__dict__)
                duplicate["duplicate_body"] = True
                pages.append(duplicate)
                break
            seen_body_hashes.add(body_hash)
        pages.append(page.__dict__)
        if page.status != "OK" or not page.body:
            break
        parser = TransactionTableParser()
        parser.feed(page.body)
        next_url = urllib.parse.urljoin(url, parser.next_page) if parser.next_page else None
        url = next_url
        if url and delay_seconds > 0:
            time.sleep(delay_seconds)
    return {
        "source": "nfl_transactions_reserve_list",
        "parser_version": PARSER_VERSION,
        "year": int(year),
        "month": int(month),
        "requested_url": BASE_URL.format(year=year, month=month),
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "pages": pages,
    }


def fetch_page(url: str, *, timeout: int, retries: int) -> TransactionPage:
    fetched_at = datetime.now(timezone.utc).isoformat()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error: str | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                return TransactionPage(
                    url=url,
                    fetched_at=fetched_at,
                    status="OK",
                    http_status=response.status,
                    content_type=response.headers.get("content-type"),
                    body=raw.decode(charset, errors="replace"),
                )
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
    return TransactionPage(url=url, fetched_at=fetched_at, status="FETCH_FAILED", error=last_error)


def save_month_bundle(bundle: dict[str, Any], *, season: int, run_id: str, month: int) -> tuple[Path, Path]:
    run_dir = RAW_ROOT / str(season) / run_id
    run_dir.mkdir(parents=True, exist_ok=False if not run_dir.exists() else True)
    raw_path = run_dir / f"{season}_{month:02d}.json"
    metadata_path = run_dir / f"{season}_{month:02d}.metadata.json"
    raw_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    metadata = {
        "source": bundle["source"],
        "parser_version": PARSER_VERSION,
        "year": season,
        "month": month,
        "run_id": run_id,
        "pages": len(bundle["pages"]),
        "fetch_status_counts": dict(Counter(page["status"] for page in bundle["pages"])),
        "raw_file": str(raw_path),
        "fetched_at_utc": bundle["fetched_at_utc"],
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return raw_path, metadata_path


def parse_month_bundle(bundle: dict[str, Any], *, season: int, month: int, raw_file: str | None = None) -> list[dict[str, Any]]:
    events = []
    row_index = 0
    team_lookup = team_label_lookup()
    for page_index, page in enumerate(bundle.get("pages") or [], start=1):
        if page.get("duplicate_body"):
            continue
        body = page.get("body")
        if page.get("status") != "OK" or not body:
            continue
        parser = TransactionTableParser()
        parser.feed(str(body))
        for table in parser.tables:
            if not is_transaction_table(table.headers):
                continue
            for cells in table.rows:
                row = row_from_cells(table.headers, cells)
                if not row.get("Name"):
                    continue
                row_index += 1
                raw_transaction = row.get("Transaction") or ""
                event_type, reserve_status = classify_transaction(raw_transaction)
                from_team = normalize_transaction_team(row.get("From"), team_lookup)
                to_team = normalize_transaction_team(row.get("To"), team_lookup)
                team = derive_event_team(from_team, to_team)
                transaction_date = parse_transaction_date(row.get("Date"), season=season, month=month)
                events.append(
                    {
                        "season": int(season),
                        "month": int(month),
                        "source": "nfl_transactions_reserve_list",
                        "source_url": page.get("url"),
                        "source_page": page_index,
                        "source_row_number": row_index,
                        "fetched_at": page.get("fetched_at"),
                        "raw_file": raw_file,
                        "transaction_date": transaction_date,
                        "player_name": clean_text(row.get("Name")),
                        "normalized_player_name": normalize_player_name(row.get("Name")),
                        "source_position": clean_text(row.get("Position")) or None,
                        "from_team_raw": clean_text(row.get("From")) or None,
                        "to_team_raw": clean_text(row.get("To")) or None,
                        "from_team": from_team,
                        "to_team": to_team,
                        "team": team,
                        "raw_transaction": clean_text(raw_transaction),
                        "event_type": event_type,
                        "reserve_status": reserve_status,
                        "raw_source_row": row,
                    }
                )
    return events


def enrich_transaction_identities(events: list[dict[str, Any]], *, season: int, week: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    profiles = build_pff_player_index(season, week - 1, directory_week=week)
    by_name = profiles_by_normalized_name(profiles)
    by_exact_name = profiles_by_exact_normalized_name(profiles)
    by_alias = profiles_by_alias(profiles)
    persisted = load_persisted_mappings()
    enriched = []
    for event in events:
        if event.get("team"):
            match = match_player(
                event,
                profiles=profiles,
                by_name=by_name,
                by_exact_name=by_exact_name,
                by_alias=by_alias,
                persisted=persisted,
            )
        else:
            match = None
        out = dict(event)
        profile = match.profile if match else None
        out.update(
            {
                "pff_player_id": profile.player_id if profile else None,
                "pff_player_name": profile.player_name if profile else None,
                "pff_position": profile.primary_position() if profile else None,
                "match_status": match.status if match else "UNMATCHED",
                "match_method": match.method if match else None,
                "match_candidates": match.candidates if match else [],
                "pff_identity_status": "MATCHED" if match and match.status in {"PERSISTED", "EXACT", "NORMALIZED"} else ("REVIEW_REQUIRED" if match and match.status == "REVIEW_REQUIRED" else "UNMATCHED"),
            }
        )
        enriched.append(out)
    counts = Counter(row["pff_identity_status"] for row in enriched if is_relevant_reserve_event(row))
    return enriched, {"relevant_transaction_identity_counts": dict(sorted(counts.items()))}


def attach_events_to_current_reserves(current_rows: list[dict[str, Any]], events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_pff: dict[tuple[str, str], list[dict[str, Any]]] = {}
    by_team_name: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for event in events:
        if not is_relevant_reserve_event(event):
            continue
        if event.get("team") and event.get("pff_player_id"):
            by_pff.setdefault((event["team"], str(event["pff_player_id"])), []).append(event)
        if event.get("team") and event.get("normalized_player_name"):
            by_team_name.setdefault((event["team"], event["normalized_player_name"]), []).append(event)

    enriched = []
    reconciliation_rows = []
    for row in current_rows:
        matched = []
        match_source = "NONE"
        if row.get("team") and row.get("pff_player_id"):
            matched = list(by_pff.get((row["team"], str(row["pff_player_id"])), []))
            if matched:
                match_source = "PFF_ID_TEAM"
        if not matched and row.get("team") and row.get("normalized_player_name"):
            exact_events = by_team_name.get((row["team"], row["normalized_player_name"]), [])
            matched = [event for event in exact_events if event.get("pff_identity_status") != "REVIEW_REQUIRED"]
            if matched:
                match_source = "TEAM_EXACT_NORMALIZED_NAME"
        matched = sorted(matched, key=lambda item: (item.get("transaction_date") or "", item.get("source_row_number") or 0))
        status = reconciliation_status(row, matched)
        placement = documented_current_placement(row, matched)
        dfr_event = latest_event(matched, "DESIGNATED_FOR_RETURN")
        latest = matched[-1] if matched else None
        out = dict(row)
        out.update(
            {
                "reserve_events": [event_for_current_output(event) for event in matched],
                "reserve_transaction_date": placement.get("transaction_date") if placement else None,
                "reserve_transaction_type": placement.get("event_type") if placement else None,
                "latest_reserve_event_date": latest.get("transaction_date") if latest else None,
                "latest_reserve_event_type": latest.get("event_type") if latest else None,
                "designated_for_return_date": dfr_event.get("transaction_date") if dfr_event else None,
                "transaction_history_match_source": match_source,
                "reconciliation_status": status,
            }
        )
        enriched.append(out)
        reconciliation_rows.append(
            {
                "team": row.get("team"),
                "player_name": row.get("player_name"),
                "canonical_roster_status": row.get("canonical_roster_status"),
                "raw_roster_status": row.get("raw_roster_status"),
                "designated_for_return": row.get("designated_for_return"),
                "pff_player_id": row.get("pff_player_id"),
                "pff_identity_status": row.get("pff_identity_status"),
                "matched_events": len(matched),
                "reserve_transaction_date": out["reserve_transaction_date"],
                "reserve_transaction_type": out["reserve_transaction_type"],
                "latest_reserve_event_date": out["latest_reserve_event_date"],
                "latest_reserve_event_type": out["latest_reserve_event_type"],
                "designated_for_return_date": out["designated_for_return_date"],
                "transaction_history_match_source": match_source,
                "reconciliation_status": status,
            }
        )
    return enriched, reconciliation_rows


def reconciliation_status(row: dict[str, Any], events: list[dict[str, Any]]) -> str:
    if not events:
        return "CURRENT_STATE_WITHOUT_MATCHED_HISTORY"
    current_status = row.get("canonical_roster_status")
    later_activation = latest_activation_after_placement(current_status, events)
    if later_activation:
        return "HISTORY_HAS_LATER_ACTIVATION"
    if documented_current_placement(row, events):
        return "HISTORY_CONFIRMS_CURRENT_STATE"
    if any(event.get("reserve_status") == current_status for event in events):
        return "HISTORY_CONFIRMS_CURRENT_STATE"
    if any(event.get("event_type") == "OTHER_RESERVE_EVENT" for event in events):
        return "HISTORY_UNRESOLVED"
    return "HISTORY_STATUS_CONFLICT"


def documented_current_placement(row: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any] | None:
    current_status = row.get("canonical_roster_status")
    wanted = {
        "IR": "PLACED_ON_IR",
        "PUP": "PLACED_ON_PUP",
        "NFI": "PLACED_ON_NFI",
    }.get(str(current_status))
    if not wanted:
        return None
    activations = [event for event in events if event.get("event_type") in ACTIVATION_EVENT_TYPES]
    latest_activation_date = max([event.get("transaction_date") or "" for event in activations], default="")
    placements = [event for event in events if event.get("event_type") == wanted and (event.get("transaction_date") or "") >= latest_activation_date]
    return placements[-1] if placements else None


def latest_activation_after_placement(current_status: Any, events: list[dict[str, Any]]) -> dict[str, Any] | None:
    wanted = {
        "IR": "PLACED_ON_IR",
        "PUP": "PLACED_ON_PUP",
        "NFI": "PLACED_ON_NFI",
    }.get(str(current_status))
    if not wanted:
        return None
    placements = [event for event in events if event.get("event_type") == wanted]
    if not placements:
        return None
    placement_date = placements[-1].get("transaction_date") or ""
    later = [event for event in events if event.get("event_type") in ACTIVATION_EVENT_TYPES and (event.get("transaction_date") or "") > placement_date]
    return later[-1] if later else None


def latest_event(events: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    matches = [event for event in events if event.get("event_type") == event_type]
    return matches[-1] if matches else None


def event_for_current_output(event: dict[str, Any]) -> dict[str, Any]:
    keep = [
        "transaction_date",
        "event_type",
        "reserve_status",
        "raw_transaction",
        "team",
        "from_team_raw",
        "to_team_raw",
        "source_url",
        "fetched_at",
        "source_row_number",
        "pff_player_id",
        "pff_player_name",
        "pff_identity_status",
    ]
    return {key: event.get(key) for key in keep}


def build_summary(
    *,
    season: int,
    week: int,
    run_id: str,
    reserve_run_dir: Path,
    months: list[int],
    pages_by_month: dict[int, int],
    raw_month_files: list[dict[str, Any]],
    events: list[dict[str, Any]],
    current_reserves: list[dict[str, Any]],
    reconciliation_rows: list[dict[str, Any]],
    identity_summary: dict[str, Any],
) -> dict[str, Any]:
    event_counts = Counter(event["event_type"] for event in events)
    relevant_events = [event for event in events if is_relevant_reserve_event(event)]
    rec_counts = Counter(row["reconciliation_status"] for row in reconciliation_rows)
    conflicts = [row for row in reconciliation_rows if row["reconciliation_status"] in {"HISTORY_HAS_LATER_ACTIVATION", "HISTORY_STATUS_CONFLICT", "HISTORY_UNRESOLVED"}]
    candidate_counts = Counter(bool(row.get("key_candidate")) for row in current_reserves)
    return {
        "season": season,
        "week": week,
        "run_id": run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "reserve_run_dir": str(reserve_run_dir),
        "months_fetched": months,
        "month_selection_reason": month_selection_reason(months),
        "pages_by_month": {str(key): value for key, value in sorted(pages_by_month.items())},
        "raw_month_files": raw_month_files,
        "transaction_rows_parsed": len(events),
        "relevant_reserve_events": len(relevant_events),
        "event_type_counts": dict(sorted(event_counts.items())),
        "unclassified_reserve_events": event_counts["OTHER_RESERVE_EVENT"],
        "current_reserve_players": len(current_reserves),
        "current_reserve_players_with_matched_history": sum(1 for row in reconciliation_rows if row["matched_events"]),
        "current_reserve_players_without_matched_history": sum(1 for row in reconciliation_rows if not row["matched_events"]),
        "players_with_documented_reserve_transaction_dates": sum(1 for row in reconciliation_rows if row["reserve_transaction_date"]),
        "designated_for_return_dates_found": sum(1 for row in reconciliation_rows if row["designated_for_return_date"]),
        "reconciliation_status_counts": dict(sorted(rec_counts.items())),
        "conflicts_or_warnings": conflicts,
        "candidate_yes": candidate_counts[True],
        "candidate_no": candidate_counts[False],
        **identity_summary,
    }


def month_selection_reason(months: list[int]) -> str:
    if 7 in months:
        return "July, August, and September were fetched because August/September covered cutdown and in-season reserve moves, while current Week 3 PUP/NFI reserve players made July training-camp reserve-list history necessary to inspect."
    return "August and September were selected as the initial narrow range for Week 3 because they cover cutdown/preseason reserve moves and current in-season reserve moves."


def write_outputs(
    out_dir: Path,
    events: list[dict[str, Any]],
    enriched_reserves: list[dict[str, Any]],
    reconciliation_rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    (out_dir / "nfl_reserve_transactions.json").write_text(json.dumps(events, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "reserve_players_with_transaction_history.json").write_text(json.dumps(enriched_reserves, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "reserve_transaction_reconciliation.json").write_text(json.dumps(reconciliation_rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "reserve_transaction_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_csv(out_dir / "nfl_reserve_transactions.csv", events, transaction_columns())
    write_csv(out_dir / "reserve_players_with_transaction_history.csv", enriched_reserves, enriched_reserve_columns())
    write_csv(out_dir / "reserve_transaction_reconciliation.csv", reconciliation_rows, reconciliation_columns())


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            out = {}
            for column in columns:
                value = row.get(column)
                if isinstance(value, (list, dict)):
                    value = json.dumps(value, sort_keys=True)
                out[column] = value
            writer.writerow(out)


def transaction_columns() -> list[str]:
    return [
        "transaction_date",
        "team",
        "player_name",
        "source_position",
        "from_team_raw",
        "to_team_raw",
        "raw_transaction",
        "event_type",
        "reserve_status",
        "pff_player_id",
        "pff_player_name",
        "pff_position",
        "pff_identity_status",
        "match_status",
        "match_method",
        "source_url",
        "fetched_at",
    ]


def enriched_reserve_columns() -> list[str]:
    return [
        "team",
        "player_name",
        "source_position",
        "raw_roster_status",
        "canonical_roster_status",
        "designated_for_return",
        "reserve_transaction_date",
        "reserve_transaction_type",
        "latest_reserve_event_date",
        "latest_reserve_event_type",
        "designated_for_return_date",
        "reconciliation_status",
        "transaction_history_match_source",
        "pff_player_id",
        "pff_player_name",
        "pff_identity_status",
        "snap_data_status",
        "key_candidate",
        "candidate_reasons",
    ]


def reconciliation_columns() -> list[str]:
    return [
        "team",
        "player_name",
        "canonical_roster_status",
        "raw_roster_status",
        "designated_for_return",
        "pff_player_id",
        "pff_identity_status",
        "matched_events",
        "reserve_transaction_date",
        "reserve_transaction_type",
        "latest_reserve_event_date",
        "latest_reserve_event_type",
        "designated_for_return_date",
        "transaction_history_match_source",
        "reconciliation_status",
    ]


def classify_transaction(value: Any) -> tuple[str, str | None]:
    text = clean_text(value)
    lower = text.lower()
    if "designated" in lower and "return" in lower:
        return "DESIGNATED_FOR_RETURN", "IR" if "injured" in lower else None
    if "activated" in lower or "activation" in lower:
        if "physically unable" in lower or re.search(r"\bpup\b", lower):
            return "ACTIVATED_FROM_PUP", "PUP"
        if "non-football" in lower or re.search(r"\bnfi\b", lower):
            return "ACTIVATED_FROM_NFI", "NFI"
        if "injured" in lower or re.search(r"\bir\b", lower):
            return "ACTIVATED_FROM_IR", "IR"
        return "OTHER_RESERVE_EVENT", None
    if "injured" in lower or lower in {"reserve/injured", "injured reserve"}:
        return "PLACED_ON_IR", "IR"
    if "physically unable" in lower or re.search(r"\bpup\b", lower):
        return "PLACED_ON_PUP", "PUP"
    if "non-football" in lower or re.search(r"\bnfi\b", lower):
        return "PLACED_ON_NFI", "NFI"
    if "reserve" in lower:
        return "OTHER_RESERVE_EVENT", "OTHER_RESERVE"
    return "OTHER_RESERVE_EVENT", None


def is_relevant_reserve_event(event: dict[str, Any]) -> bool:
    return bool(event.get("reserve_status") in RESERVE_STATUSES or event.get("event_type") in PLACEMENT_EVENT_TYPES | ACTIVATION_EVENT_TYPES | {"DESIGNATED_FOR_RETURN", "OTHER_RESERVE_EVENT"})


def parse_transaction_date(value: Any, *, season: int, month: int) -> str | None:
    text = clean_text(value)
    match = re.search(r"(\d{1,2})/(\d{1,2})", text)
    if not match:
        return None
    parsed_month = int(match.group(1))
    parsed_day = int(match.group(2))
    if parsed_month != int(month):
        parsed_month = int(month)
    return f"{int(season):04d}-{parsed_month:02d}-{parsed_day:02d}"


def row_from_cells(headers: list[str], cells: list[TransactionCell]) -> dict[str, str]:
    values = cells + [TransactionCell()] * (len(headers) - len(cells))
    return {header: values[index].text for index, header in enumerate(headers)}


def is_transaction_table(headers: list[str]) -> bool:
    return {"From", "To", "Date", "Name", "Position", "Transaction"}.issubset(set(headers))


def team_label_lookup() -> dict[str, str]:
    lookup = {}
    for team in load_teams():
        labels = [team["full_name"], team["abbr"], *team.get("aliases", [])]
        if team["abbr"] == "WAS":
            labels.append("Washington Football Team")
        for label in labels:
            lookup[normalize_team_label(label)] = team["abbr"]
    return lookup


def normalize_transaction_team(value: Any, lookup: dict[str, str] | None = None) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    lookup = lookup or team_label_lookup()
    key = normalize_team_label(text)
    if key in lookup:
        return lookup[key]
    parts = text.split()
    for part_count in range(len(parts), 0, -1):
        candidate = normalize_team_label(" ".join(parts[:part_count]))
        if candidate in lookup:
            return lookup[candidate]
        candidate = normalize_team_label(" ".join(parts[-part_count:]))
        if candidate in lookup:
            return lookup[candidate]
    return None


def derive_event_team(from_team: str | None, to_team: str | None) -> str | None:
    return to_team or from_team


def normalize_team_label(value: Any) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    words = text.split()
    if len(words) >= 2 and words[: len(words) // 2] == words[len(words) // 2 :]:
        words = words[: len(words) // 2]
    return " ".join(words)


def canonical_header(value: Any) -> str:
    text = clean_text(value).lower()
    mapping = {
        "from": "From",
        "to": "To",
        "date": "Date",
        "name": "Name",
        "position": "Position",
        "transaction": "Transaction",
    }
    return mapping.get(text, clean_text(value))


def clean_text(value: Any) -> str:
    text = html.unescape("" if value is None else str(value))
    return re.sub(r"\s+", " ", text).strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch and reconcile official NFL reserve-list transaction history.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--reserve-run-dir", type=Path, required=True)
    parser.add_argument("--month", type=int, action="append", help="Month number to fetch. Defaults to the narrow Week 3 range.")
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--retries", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_week3_reserve_transaction_reconciliation(
        season=args.season,
        week=args.week,
        reserve_run_dir=args.reserve_run_dir,
        months=args.month,
        delay_seconds=args.delay,
        timeout=args.timeout,
        retries=args.retries,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
