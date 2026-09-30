from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .injury_schema import PROJECT_ROOT, load_json, load_teams, normalize_player_name, validate_team_abbr
from .official_injury_reports import USER_AGENT
from .pff_enrichment import (
    PFF_DIRECTORY_ROOT,
    build_pff_player_index,
    enrich_record,
    load_manual_override_map,
    load_persisted_mappings,
    match_player,
    persist_pff_index,
    profiles_by_alias,
    profiles_by_exact_normalized_name,
    profiles_by_normalized_name,
)


REPO_ROOT = PROJECT_ROOT.parent
PFF_CONTENT_SRC = REPO_ROOT / "pff_content" / "src"
if str(PFF_CONTENT_SRC) not in sys.path:
    sys.path.insert(0, str(PFF_CONTENT_SRC))

from pff_content.player_directory import PlayerSearchRequest, build_player_directory  # noqa: E402


RAW_ROOT = PROJECT_ROOT / "data" / "raw" / "official_roster"
PROCESSED_ROOT = PROJECT_ROOT / "data" / "processed"
PARSER_VERSION = "official_club_roster_common_table_v1"

INJURY_RELATED_CANONICAL = {"IR", "PUP", "NFI"}
NON_INJURY_RESERVE_TERMS = ("suspended", "retired", "exempt")


@dataclass
class RosterFetchResult:
    team: str
    url: str
    status: str
    fetched_at: str
    http_status: int | None = None
    content_type: str | None = None
    body: str | None = None
    error: str | None = None


@dataclass
class RosterParseResult:
    team: str
    fetch_status: str
    parse_status: str
    total_roster_rows: int = 0
    parsed_status_buckets: list[str] = field(default_factory=list)
    injury_related_reserve_players: int = 0
    ir: int = 0
    ir_designated_for_return: int = 0
    reserve_pup: int = 0
    reserve_nfi: int = 0
    active_pup_like: int = 0
    other_injury_related: int = 0
    other_non_injury_reserve: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    parser_strategy: str = PARSER_VERSION


@dataclass
class RosterTable:
    raw_status: str
    rows: list[list[dict[str, str | None]]]


class RosterTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[RosterTable] = []
        self._recent_text: list[str] = []
        self._last_heading: str | None = None
        self._in_heading = False
        self._heading_parts: list[str] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._current_table: list[list[dict[str, str | None]]] = []
        self._current_row: list[dict[str, str | None]] = []
        self._current_cell: list[str] = []
        self._current_href: str | None = None
        self._table_status: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_dict = dict(attrs)
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._in_heading = True
            self._heading_parts = []
        elif tag == "table":
            self._in_table = True
            self._current_table = []
            self._table_status = infer_status_from_context(self._last_heading, self._recent_text)
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._current_row = []
        elif self._in_table and tag in {"td", "th"}:
            self._in_cell = True
            self._current_cell = []
            self._current_href = None
        elif self._in_table and self._in_cell and tag == "a":
            href = attrs_dict.get("href")
            if href:
                self._current_href = href

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and self._in_heading:
            heading = clean_text(" ".join(self._heading_parts))
            if heading:
                self._last_heading = heading
                self._recent_text.append(heading)
                self._recent_text = self._recent_text[-120:]
            self._in_heading = False
            self._heading_parts = []
        elif self._in_table and tag in {"td", "th"}:
            self._current_row.append(
                {
                    "text": clean_text(" ".join(self._current_cell)),
                    "href": self._current_href,
                }
            )
            self._in_cell = False
            self._current_cell = []
            self._current_href = None
        elif self._in_table and tag == "tr":
            if any(cell["text"] for cell in self._current_row):
                self._current_table.append(self._current_row)
            self._in_row = False
            self._current_row = []
        elif tag == "table" and self._in_table:
            self.tables.append(RosterTable(raw_status=self._table_status or "Unknown", rows=self._current_table))
            self._in_table = False
            self._current_table = []
            self._table_status = None

    def handle_data(self, data: str) -> None:
        text = clean_text(data)
        if not text:
            return
        if self._in_heading:
            self._heading_parts.append(text)
        elif self._in_table and self._in_cell:
            self._current_cell.append(text)
        elif not self._in_table:
            self._recent_text.append(text)
            self._recent_text = self._recent_text[-120:]


def fetch_roster_page(team: dict[str, Any], *, timeout: int = 25, retries: int = 2, retry_sleep: float = 1.0) -> RosterFetchResult:
    fetched_at = datetime.now(timezone.utc).isoformat()
    request = urllib.request.Request(team["roster_url"], headers={"User-Agent": USER_AGENT})
    last_error: str | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                return RosterFetchResult(
                    team=team["abbr"],
                    url=team["roster_url"],
                    status="OK",
                    fetched_at=fetched_at,
                    http_status=response.status,
                    content_type=response.headers.get("content-type"),
                    body=raw.decode(charset, errors="replace"),
                )
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(retry_sleep * (attempt + 1))
    return RosterFetchResult(team=team["abbr"], url=team["roster_url"], status="FETCH_FAILED", fetched_at=fetched_at, error=last_error)


def parse_roster_page(
    html_text: str,
    *,
    team: str,
    season: int,
    week: int,
    source_url: str,
    fetched_at: str,
    raw_snapshot: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], RosterParseResult]:
    team = validate_team_abbr(team)
    parser = RosterTableParser()
    try:
        parser.feed(html_text)
    except Exception as exc:
        result = RosterParseResult(team=team, fetch_status="OK", parse_status="PARSE_FAILED", errors=[f"{type(exc).__name__}: {exc}"])
        return [], [], result

    source_rows: list[dict[str, Any]] = []
    injury_rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for table in parser.tables:
        if not is_roster_table(table.rows):
            continue
        for row in roster_table_to_dicts(table.rows):
            record = reserve_record_from_row(
                row,
                season=season,
                week=week,
                team=team,
                raw_roster_status=table.raw_status,
                source_url=source_url,
                fetched_at=fetched_at,
                raw_snapshot=raw_snapshot,
            )
            if record is None:
                continue
            source_rows.append(record)
            if record["injury_related"] and record["canonical_roster_status"] != "ACTIVE":
                injury_rows.append(record)

    if not source_rows:
        warnings.append("No recognizable roster table rows found.")
    result = build_parse_result(team, source_rows, injury_rows, warnings=warnings)
    return injury_rows, source_rows, result


def reserve_record_from_row(
    row: dict[str, dict[str, str | None]],
    *,
    season: int,
    week: int,
    team: str,
    raw_roster_status: str,
    source_url: str,
    fetched_at: str,
    raw_snapshot: str | None,
) -> dict[str, Any] | None:
    player_cell = row.get("Player") or row.get("Name")
    player = clean_text(player_cell.get("text") if player_cell else None)
    if not player or player.upper() in {"PLAYER", "NAME"}:
        return None
    position_cell = row.get("Pos") or row.get("Position")
    status = canonicalize_status(raw_roster_status)
    profile_url = player_cell.get("href") if player_cell else None
    profile_url = absolute_url(source_url, profile_url)
    return {
        "season": int(season),
        "week": int(week),
        "team": team,
        "player_name": player,
        "normalized_player_name": normalize_player_name(player),
        "source_position": clean_text(position_cell.get("text") if position_cell else None) or None,
        "raw_roster_status": status["raw_roster_status"],
        "canonical_roster_status": status["canonical_roster_status"],
        "injury_related": status["injury_related"],
        "reserve_list": status["reserve_list"],
        "active_roster": status["active_roster"],
        "designated_for_return": status["designated_for_return"],
        "pup_related": status["pup_related"],
        "nfi_related": status["nfi_related"],
        "source_url": source_url,
        "fetched_at": fetched_at,
        "player_profile_url": profile_url,
        "source_metadata": {
            "source": "official_club_roster",
            "parser_version": PARSER_VERSION,
            "raw_snapshot": raw_snapshot,
            "raw_row": {key: value.get("text") for key, value in row.items()},
        },
        "game_status": None,
        "injury": None,
    }


def canonicalize_status(raw_status: str) -> dict[str, Any]:
    raw = clean_text(raw_status) or "Unknown"
    text = raw.lower()
    reserve_list = text.startswith("reserve/")
    active_roster = text.startswith("active") or raw == "Active"
    designated = "designated for return" in text
    pup_related = "physically unable to perform" in text or re.search(r"\bpup\b", text) is not None
    nfi_related = "non-football" in text or re.search(r"\bnfi\b", text) is not None

    if "injured" in text and reserve_list:
        canonical = "IR"
        injury_related = True
    elif pup_related:
        canonical = "PUP" if reserve_list else "ACTIVE"
        injury_related = True
    elif nfi_related:
        canonical = "NFI" if reserve_list else "ACTIVE"
        injury_related = True
    elif reserve_list:
        canonical = "OTHER_RESERVE"
        injury_related = not any(term in text for term in NON_INJURY_RESERVE_TERMS)
    else:
        canonical = "ACTIVE"
        injury_related = False

    return {
        "raw_roster_status": raw,
        "canonical_roster_status": canonical,
        "injury_related": bool(injury_related),
        "reserve_list": bool(reserve_list),
        "active_roster": bool(active_roster or canonical == "ACTIVE" and not reserve_list),
        "designated_for_return": bool(designated),
        "pup_related": bool(pup_related),
        "nfi_related": bool(nfi_related),
    }


def enrich_reserve_records(records: list[dict[str, Any]], *, season: int, week: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    through_week = week - 1
    profiles = build_pff_player_index(season, through_week, directory_week=week)
    index_json, index_csv = persist_pff_index(profiles, season=season, through_week=through_week)
    prior_season = season - 1
    prior_profiles = build_pff_player_index(prior_season, 18, directory_week=18)
    prior_index_json, prior_index_csv = persist_pff_index(prior_profiles, season=prior_season, through_week=18)
    by_name = profiles_by_normalized_name(profiles)
    by_exact_name = profiles_by_exact_normalized_name(profiles)
    by_alias = profiles_by_alias(profiles)
    persisted = load_persisted_mappings()
    manual_overrides = load_manual_override_map()
    relevance_rules = load_json(PROJECT_ROOT / "config" / "relevance_rules.json")

    enriched = []
    for record in records:
        match = match_player(
            record,
            profiles=profiles,
            by_name=by_name,
            by_exact_name=by_exact_name,
            by_alias=by_alias,
            persisted=persisted,
        )
        manual = manual_overrides.get((record["team"], record["normalized_player_name"]), {})
        prior_profile = None
        if match.profile is not None:
            prior_profile = prior_profiles.get(match.profile.player_id)
        enriched.append(
            enrich_record(
                record,
                match,
                manual,
                relevance_rules,
                prior_season_profile=prior_profile,
                prior_season=prior_season,
                enable_prior_season_fallback=True,
            )
        )

    manifest = build_enrichment_manifest(
        enriched,
        season=season,
        week=week,
        through_week=through_week,
        index_json=index_json,
        index_csv=index_csv,
        prior_season=prior_season,
        prior_index_json=prior_index_json,
        prior_index_csv=prior_index_csv,
    )
    return enriched, manifest


def expand_directory_for_unmatched_reserves(
    records: list[dict[str, Any]],
    *,
    season: int,
    week: int,
) -> dict[str, Any]:
    unmatched = [row for row in records if row.get("pff_identity_status") == "UNMATCHED"]
    requests = [
        PlayerSearchRequest(
            official_name=row["player_name"],
            search_name=row["player_name"],
        )
        for row in unmatched
    ]
    output_dir = PFF_DIRECTORY_ROOT / str(season) / f"week_{week:02d}"
    summary = build_player_directory(requests, season=season, week=week, output_dir=output_dir, request_sleep=0.75)
    searches = summary.get("searches", [])
    summary["previously_unmatched"] = len(unmatched)
    summary["lookups_requested"] = len(searches)
    summary["live_lookups"] = sum(1 for row in searches if not row.get("cache_hit"))
    summary["cache_hits"] = sum(1 for row in searches if row.get("cache_hit"))
    summary["searches_with_results"] = sum(1 for row in searches if int(row.get("results") or 0) > 0)
    summary["searches_without_results"] = sum(1 for row in searches if int(row.get("results") or 0) == 0)
    return summary


def reenrich_reserve_snapshot(
    run_dir: Path,
    *,
    season: int,
    week: int,
    expand_directory: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    reserve_path = run_dir / "reserve_players.json"
    if not reserve_path.exists():
        raise FileNotFoundError(f"Missing reserve snapshot: {reserve_path}")
    before_records = json.loads(reserve_path.read_text(encoding="utf-8"))
    if not isinstance(before_records, list):
        raise ValueError(f"Expected list in {reserve_path}")

    expansion_summary = None
    if expand_directory:
        expansion_summary = expand_directory_for_unmatched_reserves(before_records, season=season, week=week)

    source_records = [strip_enrichment_fields(row) for row in before_records]
    after_records, pff_manifest = enrich_reserve_records(source_records, season=season, week=week)
    before_after = compare_reserve_enrichment(before_records, after_records)
    summary = build_identity_expansion_summary(
        before_records=before_records,
        after_records=after_records,
        before_after=before_after,
        pff_manifest=pff_manifest,
        expansion_summary=expansion_summary,
        season=season,
        week=week,
        run_dir=run_dir,
    )
    write_reenrichment_outputs(run_dir, before_records, after_records, before_after, summary)
    return after_records, summary


def strip_enrichment_fields(record: dict[str, Any]) -> dict[str, Any]:
    keep = {
        "season",
        "week",
        "team",
        "player_name",
        "normalized_player_name",
        "source_position",
        "raw_roster_status",
        "canonical_roster_status",
        "injury_related",
        "reserve_list",
        "active_roster",
        "designated_for_return",
        "pup_related",
        "nfi_related",
        "source_url",
        "fetched_at",
        "player_profile_url",
        "source_metadata",
        "game_status",
        "injury",
    }
    return {key: record.get(key) for key in keep}


def compare_reserve_enrichment(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    before_by_key = {reserve_key(row): row for row in before}
    output = []
    for row in after:
        old = before_by_key.get(reserve_key(row), {})
        old_candidate = old.get("key_candidate")
        new_candidate = row.get("key_candidate")
        if old_candidate is True and new_candidate is True:
            movement = "YES_TO_YES"
        elif old_candidate is True and new_candidate is False:
            movement = "YES_TO_NO"
        elif old_candidate is False and new_candidate is True:
            movement = "NO_TO_YES"
        elif old_candidate is False and new_candidate is False:
            movement = "NO_TO_NO"
        else:
            movement = "UNKNOWN"
        output.append(
            {
                "team": row.get("team"),
                "player_name": row.get("player_name"),
                "normalized_player_name": row.get("normalized_player_name"),
                "raw_roster_status": row.get("raw_roster_status"),
                "before_identity_status": old.get("pff_identity_status"),
                "after_identity_status": row.get("pff_identity_status"),
                "before_match_status": old.get("match_status"),
                "after_match_status": row.get("match_status"),
                "before_snap_data_status": old.get("snap_data_status"),
                "after_snap_data_status": row.get("snap_data_status"),
                "before_prior_season_snap_data_status": old.get("prior_season_snap_data_status"),
                "after_prior_season_snap_data_status": row.get("prior_season_snap_data_status"),
                "before_prior_season_relevant_snap_pct": old.get("prior_season_relevant_snap_pct"),
                "after_prior_season_relevant_snap_pct": row.get("prior_season_relevant_snap_pct"),
                "after_participation_source_season": row.get("participation_source_season"),
                "before_candidate": old_candidate,
                "after_candidate": new_candidate,
                "candidate_change": movement,
                "before_pff_player_id": old.get("pff_player_id"),
                "after_pff_player_id": row.get("pff_player_id"),
                "after_pff_player_name": row.get("pff_player_name"),
                "after_pff_position": row.get("pff_position"),
                "after_match_method": row.get("match_method"),
            }
        )
    return output


def build_identity_expansion_summary(
    *,
    before_records: list[dict[str, Any]],
    after_records: list[dict[str, Any]],
    before_after: list[dict[str, Any]],
    pff_manifest: dict[str, Any],
    expansion_summary: dict[str, Any] | None,
    season: int,
    week: int,
    run_dir: Path,
) -> dict[str, Any]:
    before_identity = Counter(row.get("pff_identity_status") for row in before_records)
    after_identity = Counter(row.get("pff_identity_status") for row in after_records)
    before_snap = Counter(row.get("snap_data_status") for row in before_records)
    after_snap = Counter(row.get("snap_data_status") for row in after_records)
    prior_snap = Counter(row.get("prior_season_snap_data_status") for row in after_records)
    before_candidate = Counter(bool(row.get("key_candidate")) for row in before_records)
    after_candidate = Counter(bool(row.get("key_candidate")) for row in after_records)
    movement = Counter(row["candidate_change"] for row in before_after)
    newly_matched = [row for row in before_after if row["before_identity_status"] == "UNMATCHED" and row["after_identity_status"] == "MATCHED"]
    after_by_key = {reserve_key(row): row for row in after_records}
    newly_matched_records = [after_by_key[(row["team"], row["normalized_player_name"], row["raw_roster_status"])] for row in newly_matched]
    return {
        "season": season,
        "week": week,
        "run_dir": str(run_dir),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "directory_expansion": expansion_summary,
        "before": {
            "identity": dict(sorted(before_identity.items())),
            "snap_data": dict(sorted(before_snap.items())),
            "candidate_yes": before_candidate[True],
            "candidate_no": before_candidate[False],
        },
        "after": {
            "identity": dict(sorted(after_identity.items())),
            "snap_data": dict(sorted(after_snap.items())),
            "prior_season_snap_data": dict(sorted(prior_snap.items())),
            "candidate_yes": after_candidate[True],
            "candidate_no": after_candidate[False],
        },
        "previously_unmatched": before_identity["UNMATCHED"],
        "newly_identity_matched": len(newly_matched_records),
        "review_required": after_identity["REVIEW_REQUIRED"],
        "still_unmatched": after_identity["UNMATCHED"],
        "newly_discovered_offense_defense": sum(1 for row in before_after if row["before_snap_data_status"] != "OFFENSE_DEFENSE" and row["after_snap_data_status"] == "OFFENSE_DEFENSE"),
        "newly_discovered_st_only": sum(1 for row in before_after if row["before_snap_data_status"] != "ST_ONLY" and row["after_snap_data_status"] == "ST_ONLY"),
        "matched_but_no_data": sum(1 for row in after_records if row.get("pff_identity_status") == "MATCHED" and row.get("snap_data_status") == "NO_DATA"),
        "candidate_movement": dict(sorted(movement.items())),
        "candidate_no_to_yes": movement["NO_TO_YES"],
        "candidate_yes_to_no": movement["YES_TO_NO"],
        "prior_season_fallback_promotions": sum(
            1
            for row in after_records
            if row.get("key_candidate")
            and any(str(reason).startswith("prior_season_snap_pct=") for reason in row.get("candidate_reasons") or [])
        ),
        "prior_season_no_data_current_no_data_candidate_no": sum(
            1
            for row in after_records
            if not row.get("key_candidate")
            and row.get("snap_data_status") == "NO_DATA"
            and row.get("prior_season_snap_data_status") == "NO_DATA"
        ),
        "pff_manifest": pff_manifest,
        "newly_matched_players": [
            {
                "team": row["team"],
                "official_roster_name": row["player_name"],
                "pff_player_name": row.get("pff_player_name"),
                "pff_player_id": row.get("pff_player_id"),
                "pff_position": row.get("pff_position"),
                "match_method": row.get("match_method"),
                "snap_data_status": row.get("snap_data_status"),
                "key_candidate": row.get("key_candidate"),
                "candidate_reasons": row.get("candidate_reasons"),
            }
            for row in newly_matched_records
        ],
        "review_required_players": player_issue_list(after_records, "REVIEW_REQUIRED"),
        "unmatched_players": player_issue_list(after_records, "UNMATCHED"),
    }


def write_reenrichment_outputs(
    run_dir: Path,
    before_records: list[dict[str, Any]],
    after_records: list[dict[str, Any]],
    comparison: list[dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    before_json = run_dir / "reserve_players_before_identity_expansion.json"
    before_csv = run_dir / "reserve_players_before_identity_expansion.csv"
    if not before_json.exists():
        before_json.write_text(json.dumps(before_records, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        write_reserve_players_csv(before_csv, before_records)
    (run_dir / "reserve_players.json").write_text(json.dumps(after_records, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_reserve_players_csv(run_dir / "reserve_players.csv", after_records)
    (run_dir / "reserve_identity_expansion_comparison.json").write_text(json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_identity_comparison_csv(run_dir / "reserve_identity_expansion_comparison.csv", comparison)
    write_prior_season_promotion_csv(run_dir / "reserve_prior_season_promotions.csv", after_records)
    write_prior_season_unresolved_csv(run_dir / "reserve_prior_season_unresolved.csv", after_records)
    write_prior_season_below_threshold_csv(run_dir / "reserve_prior_season_below_threshold.csv", after_records)
    (run_dir / "reserve_identity_expansion_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_path = run_dir / "reserve_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["identity_expansion"] = summary
        manifest["pff"] = summary["pff_manifest"]
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_identity_comparison_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "team",
        "player_name",
        "raw_roster_status",
        "before_identity_status",
        "after_identity_status",
        "before_snap_data_status",
        "after_snap_data_status",
        "before_prior_season_snap_data_status",
        "after_prior_season_snap_data_status",
        "before_prior_season_relevant_snap_pct",
        "after_prior_season_relevant_snap_pct",
        "after_participation_source_season",
        "before_candidate",
        "after_candidate",
        "candidate_change",
        "before_pff_player_id",
        "after_pff_player_id",
        "after_pff_player_name",
        "after_pff_position",
        "after_match_method",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) for column in columns})


def write_prior_season_promotion_csv(path: Path, records: list[dict[str, Any]]) -> None:
    rows = [
        row
        for row in records
        if any(str(reason).startswith("prior_season_snap_pct=") for reason in row.get("candidate_reasons") or [])
    ]
    columns = [
        "team",
        "player_name",
        "pff_player_id",
        "canonical_position",
        "position_group",
        "canonical_roster_status",
        "snap_data_status",
        "prior_season_team",
        "prior_season_relevant_unit",
        "prior_season_relevant_snap_pct",
        "candidate_reasons",
    ]
    write_selected_reserve_rows(path, rows, columns)


def write_prior_season_unresolved_csv(path: Path, records: list[dict[str, Any]]) -> None:
    rows = [
        row
        for row in records
        if not row.get("key_candidate")
        and row.get("snap_data_status") == "NO_DATA"
        and row.get("prior_season_snap_data_status") == "NO_DATA"
    ]
    columns = [
        "team",
        "player_name",
        "pff_player_id",
        "canonical_position",
        "position_group",
        "canonical_roster_status",
        "snap_data_status",
        "prior_season_snap_data_status",
        "candidate_reasons",
    ]
    write_selected_reserve_rows(path, rows, columns)


def write_prior_season_below_threshold_csv(path: Path, records: list[dict[str, Any]]) -> None:
    rows = [
        row
        for row in records
        if not row.get("key_candidate")
        and row.get("snap_data_status") == "NO_DATA"
        and row.get("prior_season_snap_data_status") == "OFFENSE_DEFENSE"
        and row.get("prior_season_relevant_snap_pct") is not None
    ]
    columns = [
        "team",
        "player_name",
        "pff_player_id",
        "canonical_position",
        "position_group",
        "canonical_roster_status",
        "snap_data_status",
        "prior_season_team",
        "prior_season_relevant_unit",
        "prior_season_relevant_snap_pct",
        "candidate_reasons",
    ]
    write_selected_reserve_rows(path, rows, columns)


def write_selected_reserve_rows(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            item = {column: row.get(column) for column in columns}
            if "candidate_reasons" in item:
                item["candidate_reasons"] = "|".join(row.get("candidate_reasons") or [])
            writer.writerow(item)


def player_issue_list(records: list[dict[str, Any]], status: str) -> list[dict[str, Any]]:
    return [
        {
            "team": row["team"],
            "player_name": row["player_name"],
            "source_position": row.get("source_position"),
            "raw_roster_status": row.get("raw_roster_status"),
            "canonical_roster_status": row.get("canonical_roster_status"),
            "match_status": row.get("match_status"),
            "match_method": row.get("match_method"),
            "match_candidates": row.get("match_candidates"),
        }
        for row in records
        if row.get("pff_identity_status") == status
    ]


def reserve_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (str(row.get("team")), str(row.get("normalized_player_name")), str(row.get("raw_roster_status")))


def run_ingestion(
    *,
    season: int,
    week: int,
    selected_team_abbrs: list[str],
    delay_seconds: float = 0.25,
    timeout: int = 25,
    retries: int = 2,
) -> tuple[Path, list[dict[str, Any]], dict[str, Any]]:
    teams = load_teams()
    requested = {validate_team_abbr(team) for team in selected_team_abbrs}
    selected = [team for team in teams if team["abbr"] in requested]
    missing = sorted(requested - {team["abbr"] for team in selected})
    if missing:
        raise ValueError(f"Unknown teams: {missing}")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    all_reserve_records: list[dict[str, Any]] = []
    all_source_rows: list[dict[str, Any]] = []
    team_results: list[dict[str, Any]] = []

    for index, team in enumerate(selected):
        if index and delay_seconds > 0:
            time.sleep(delay_seconds)
        fetch = fetch_roster_page(team, timeout=timeout, retries=retries)
        raw_path, metadata_path = save_raw_fetch(fetch, season=season, week=week, run_id=run_id)
        if fetch.status != "OK" or fetch.body is None:
            parse_result = RosterParseResult(
                team=team["abbr"],
                fetch_status=fetch.status,
                parse_status="FETCH_FAILED",
                errors=[fetch.error or "Fetch failed."],
            )
            reserve_records: list[dict[str, Any]] = []
            source_rows: list[dict[str, Any]] = []
        else:
            reserve_records, source_rows, parse_result = parse_roster_page(
                fetch.body,
                team=team["abbr"],
                season=season,
                week=week,
                source_url=team["roster_url"],
                fetched_at=fetch.fetched_at,
                raw_snapshot=str(raw_path) if raw_path else None,
            )
        all_reserve_records.extend(reserve_records)
        all_source_rows.extend(source_rows)
        item = asdict(parse_result)
        item["raw_file"] = str(raw_path) if raw_path else None
        item["raw_metadata_file"] = str(metadata_path)
        item["source_url"] = team["roster_url"]
        team_results.append(item)

    enriched, pff_manifest = enrich_reserve_records(all_reserve_records, season=season, week=week)
    manifest = build_run_manifest(
        season=season,
        week=week,
        run_id=run_id,
        team_results=team_results,
        source_rows=all_source_rows,
        reserve_records=enriched,
        pff_manifest=pff_manifest,
    )
    out_dir = write_processed_outputs(
        season=season,
        week=week,
        run_id=run_id,
        reserve_records=enriched,
        source_rows=all_source_rows,
        manifest=manifest,
    )
    return out_dir, enriched, manifest


def save_raw_fetch(fetch: RosterFetchResult, *, season: int, week: int, run_id: str) -> tuple[Path | None, Path]:
    run_dir = RAW_ROOT / str(season) / f"week_{week:02d}" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    html_path = run_dir / f"{fetch.team}.html"
    raw_ref: Path | None = None
    if fetch.body is not None:
        html_path.write_text(fetch.body, encoding="utf-8")
        raw_ref = html_path
    metadata = {
        "team": fetch.team,
        "source_url": fetch.url,
        "fetch_status": fetch.status,
        "fetch_timestamp": fetch.fetched_at,
        "http_status": fetch.http_status,
        "season": int(season),
        "week": int(week),
        "content_type": fetch.content_type,
        "parser_version": PARSER_VERSION,
        "error": fetch.error,
        "raw_file": str(html_path) if raw_ref else None,
    }
    metadata_path = run_dir / f"{fetch.team}.metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return raw_ref, metadata_path


def write_processed_outputs(
    *,
    season: int,
    week: int,
    run_id: str,
    reserve_records: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> Path:
    out_dir = PROCESSED_ROOT / str(season) / f"week_{week:02d}" / run_id
    out_dir.mkdir(parents=True, exist_ok=False)
    (out_dir / "reserve_players.json").write_text(json.dumps(reserve_records, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "official_roster_source_rows.json").write_text(json.dumps(source_rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "reserve_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_reserve_players_csv(out_dir / "reserve_players.csv", reserve_records)
    write_records_csv(out_dir / "official_roster_source_rows.csv", source_rows)
    return out_dir


def build_parse_result(team: str, source_rows: list[dict[str, Any]], injury_rows: list[dict[str, Any]], *, warnings: list[str]) -> RosterParseResult:
    statuses = Counter(row["canonical_roster_status"] for row in injury_rows)
    raw_statuses = sorted({row["raw_roster_status"] for row in source_rows})
    active_pup = sum(1 for row in source_rows if row["canonical_roster_status"] == "ACTIVE" and row.get("pup_related"))
    non_injury_reserve = sum(1 for row in source_rows if row["reserve_list"] and not row["injury_related"])
    return RosterParseResult(
        team=team,
        fetch_status="OK",
        parse_status="OK" if source_rows else "PARSE_FAILED",
        total_roster_rows=len(source_rows),
        parsed_status_buckets=raw_statuses,
        injury_related_reserve_players=len(injury_rows),
        ir=statuses["IR"],
        ir_designated_for_return=sum(1 for row in injury_rows if row["canonical_roster_status"] == "IR" and row["designated_for_return"]),
        reserve_pup=sum(1 for row in injury_rows if row["canonical_roster_status"] == "PUP" and row["reserve_list"]),
        reserve_nfi=sum(1 for row in injury_rows if row["canonical_roster_status"] == "NFI" and row["reserve_list"]),
        active_pup_like=active_pup,
        other_injury_related=statuses["OTHER_RESERVE"],
        other_non_injury_reserve=non_injury_reserve,
        warnings=warnings,
    )


def build_enrichment_manifest(
    enriched: list[dict[str, Any]],
    *,
    season: int,
    week: int,
    through_week: int,
    index_json: Path,
    index_csv: Path,
    prior_season: int | None = None,
    prior_index_json: Path | None = None,
    prior_index_csv: Path | None = None,
) -> dict[str, Any]:
    identity = Counter(row.get("pff_identity_status") for row in enriched)
    match = Counter(row.get("match_status") for row in enriched)
    snap = Counter(row.get("snap_data_status") for row in enriched)
    prior_snap = Counter(row.get("prior_season_snap_data_status") for row in enriched)
    prior_promotions = [
        row
        for row in enriched
        if any(str(reason).startswith("prior_season_snap_pct=") for reason in row.get("candidate_reasons") or [])
    ]
    return {
        "season": season,
        "week": week,
        "through_week": through_week,
        "pff_index_json": str(index_json),
        "pff_index_csv": str(index_csv),
        "prior_season": prior_season,
        "prior_season_pff_index_json": str(prior_index_json) if prior_index_json else None,
        "prior_season_pff_index_csv": str(prior_index_csv) if prior_index_csv else None,
        "reserve_players": len(enriched),
        "pff_identity_matched": identity["MATCHED"],
        "pff_identity_review_required": identity["REVIEW_REQUIRED"],
        "pff_identity_unmatched": identity["UNMATCHED"],
        "exact_matches": match["EXACT"],
        "normalized_matches": match["NORMALIZED"],
        "persisted_matches": match["PERSISTED"],
        "review_required_matches": match["REVIEW_REQUIRED"],
        "unmatched": match["UNMATCHED"],
        "snap_status": dict(sorted(snap.items())),
        "prior_season_snap_status": dict(sorted(prior_snap.items())),
        "prior_season_fallback_promotions": len(prior_promotions),
        "candidates": sum(1 for row in enriched if row.get("key_candidate")),
        "non_candidates": sum(1 for row in enriched if not row.get("key_candidate")),
    }


def build_run_manifest(
    *,
    season: int,
    week: int,
    run_id: str,
    team_results: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    reserve_records: list[dict[str, Any]],
    pff_manifest: dict[str, Any],
) -> dict[str, Any]:
    status_counts = Counter(row["canonical_roster_status"] for row in reserve_records)
    by_raw = Counter(row["raw_roster_status"] for row in source_rows)
    by_team: dict[str, dict[str, Any]] = {}
    for item in team_results:
        team_rows = [row for row in reserve_records if row["team"] == item["team"]]
        identity = Counter(row.get("pff_identity_status") for row in team_rows)
        item = dict(item)
        item.update(
            {
                "pff_identity_matched": identity["MATCHED"],
                "pff_review_required": identity["REVIEW_REQUIRED"],
                "pff_unmatched": identity["UNMATCHED"],
                "candidates": sum(1 for row in team_rows if row.get("key_candidate")),
                "non_candidates": sum(1 for row in team_rows if not row.get("key_candidate")),
            }
        )
        by_team[item["team"]] = item
    return {
        "season": season,
        "week": week,
        "run_id": run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "parser_version": PARSER_VERSION,
        "teams_requested": [item["team"] for item in team_results],
        "fetch_ok": sum(1 for item in team_results if item["fetch_status"] == "OK"),
        "fetch_failed": sum(1 for item in team_results if item["fetch_status"] != "OK"),
        "parse_ok": sum(1 for item in team_results if item["parse_status"] == "OK"),
        "parse_failed": sum(1 for item in team_results if item["parse_status"] != "OK"),
        "total_roster_rows": len(source_rows),
        "injury_related_reserve_players": len(reserve_records),
        "canonical_status_counts": dict(sorted(status_counts.items())),
        "raw_status_counts": dict(sorted(by_raw.items())),
        "ir": status_counts["IR"],
        "ir_designated_for_return": sum(1 for row in reserve_records if row["canonical_roster_status"] == "IR" and row["designated_for_return"]),
        "reserve_pup": sum(1 for row in reserve_records if row["canonical_roster_status"] == "PUP" and row["reserve_list"]),
        "reserve_nfi": sum(1 for row in reserve_records if row["canonical_roster_status"] == "NFI" and row["reserve_list"]),
        "active_pup_like_states_encountered": sum(1 for row in source_rows if row["canonical_roster_status"] == "ACTIVE" and row.get("pup_related")),
        "other_non_injury_reserve_states_encountered": sum(1 for row in source_rows if row["reserve_list"] and not row["injury_related"]),
        "pff": pff_manifest,
        "teams": by_team,
    }


def is_roster_table(rows: list[list[dict[str, str | None]]]) -> bool:
    if not rows:
        return False
    headers = {clean_header(cell["text"]) for cell in rows[0]}
    return "PLAYER" in headers and bool(headers & {"POS", "POSITION"})


def roster_table_to_dicts(rows: list[list[dict[str, str | None]]]) -> list[dict[str, dict[str, str | None]]]:
    headers = [canonical_header(cell["text"]) for cell in rows[0]]
    output = []
    for row in rows[1:]:
        values = row + [{"text": "", "href": None}] * (len(headers) - len(row))
        output.append({header: values[index] for index, header in enumerate(headers)})
    return output


def infer_status_from_context(last_heading: str | None, recent_text: list[str]) -> str:
    candidates = []
    if last_heading:
        candidates.append(last_heading)
    candidates.extend(reversed(recent_text[-8:]))
    for text in candidates:
        cleaned = clean_status_label(text)
        if is_roster_status_label(cleaned):
            return cleaned
    return "Unknown"


def is_roster_status_label(value: str) -> bool:
    text = value.lower()
    return text == "active" or text == "practice squad" or text.startswith("reserve/") or text.startswith("active/")


def clean_status_label(value: Any) -> str:
    text = clean_text(value)
    text = re.sub(r"\s+", " ", text)
    return text


def canonical_header(value: Any) -> str:
    header = clean_header(value)
    if header in {"NO", "#"}:
        return "Number"
    if header in {"POS", "POSITION"}:
        return "Pos"
    if header == "PLAYER":
        return "Player"
    return clean_text(value)


def clean_header(value: Any) -> str:
    text = clean_text(value).upper()
    text = re.sub(r"[^A-Z0-9#]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_text(value: Any) -> str:
    return html.unescape("" if value is None else str(value)).strip()


def absolute_url(source_url: str, href: str | None) -> str | None:
    if not href:
        return None
    return urllib.parse.urljoin(source_url, href)


def write_records_csv(path: Path, records: list[dict[str, Any]]) -> None:
    columns = [
        "season",
        "week",
        "team",
        "player_name",
        "normalized_player_name",
        "source_position",
        "raw_roster_status",
        "canonical_roster_status",
        "injury_related",
        "reserve_list",
        "active_roster",
        "designated_for_return",
        "pup_related",
        "nfi_related",
        "source_url",
        "fetched_at",
        "player_profile_url",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in records:
            writer.writerow({column: record.get(column) for column in columns})


def write_reserve_players_csv(path: Path, records: list[dict[str, Any]]) -> None:
    columns = [
        "season",
        "week",
        "team",
        "player_name",
        "normalized_player_name",
        "source_position",
        "raw_roster_status",
        "canonical_roster_status",
        "injury_related",
        "reserve_list",
        "active_roster",
        "designated_for_return",
        "pup_related",
        "nfi_related",
        "pff_player_id",
        "pff_player_name",
        "pff_position",
        "canonical_position",
        "position_group",
        "position_source",
        "match_status",
        "match_method",
        "pff_identity_status",
        "snap_data_status",
        "season_relevant_snap_pct",
        "previous_game_relevant_snap_pct",
        "recent_healthy_snap_pct",
        "games_appeared",
        "last_week_played",
        "primary_unit",
        "st_only",
        "prior_season",
        "prior_season_snap_data_status",
        "prior_season_relevant_unit",
        "prior_season_relevant_snap_pct",
        "prior_season_team",
        "prior_season_games_appeared",
        "prior_season_st_only",
        "participation_source_season",
        "key_candidate",
        "candidate_reasons",
        "manual_note",
        "manual_publish",
        "player_profile_url",
        "source_url",
        "fetched_at",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in records:
            row = {column: record.get(column) for column in columns}
            row["candidate_reasons"] = "|".join(record.get("candidate_reasons") or [])
            writer.writerow(row)


def selected_teams(args: argparse.Namespace) -> list[str]:
    if args.all:
        return [team["abbr"] for team in load_teams()]
    if not args.team:
        raise ValueError("Supply --team at least once or use --all.")
    return [validate_team_abbr(team) for team in args.team]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch and parse official NFL club roster reserve-state buckets.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--team", action="append", help="Team abbreviation. May be supplied more than once.")
    parser.add_argument("--all", action="store_true", help="Fetch all configured teams.")
    parser.add_argument("--reserve-run-dir", type=Path, help="Re-enrich an existing reserve snapshot without refetching club roster pages.")
    parser.add_argument("--no-expand-pff-directory", action="store_true", help="Skip targeted /v1/players directory expansion in re-enrichment mode.")
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--retries", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.reserve_run_dir:
        records, manifest = reenrich_reserve_snapshot(
            args.reserve_run_dir,
            season=args.season,
            week=args.week,
            expand_directory=not args.no_expand_pff_directory,
        )
        summary = {
            "output_dir": str(args.reserve_run_dir),
            "reserve_players": len(records),
            "lookups_requested": (manifest.get("directory_expansion") or {}).get("lookups_requested", 0),
            "live_lookups": (manifest.get("directory_expansion") or {}).get("live_lookups", 0),
            "cache_hits": (manifest.get("directory_expansion") or {}).get("cache_hits", 0),
            "newly_identity_matched": manifest["newly_identity_matched"],
            "review_required": manifest["review_required"],
            "still_unmatched": manifest["still_unmatched"],
            "before": manifest["before"],
            "after": manifest["after"],
            "candidate_movement": manifest["candidate_movement"],
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        return
    out_dir, records, manifest = run_ingestion(
        season=args.season,
        week=args.week,
        selected_team_abbrs=selected_teams(args),
        delay_seconds=args.delay,
        timeout=args.timeout,
        retries=args.retries,
    )
    summary = {
        "output_dir": str(out_dir),
        "teams": len(manifest["teams_requested"]),
        "fetch_ok": manifest["fetch_ok"],
        "parse_ok": manifest["parse_ok"],
        "injury_related_reserve_players": len(records),
        "canonical_status_counts": manifest["canonical_status_counts"],
        "ir_designated_for_return": manifest["ir_designated_for_return"],
        "active_pup_like_states_encountered": manifest["active_pup_like_states_encountered"],
        "pff_identity_matched": manifest["pff"]["pff_identity_matched"],
        "pff_review_required": manifest["pff"]["pff_identity_review_required"],
        "pff_unmatched": manifest["pff"]["pff_identity_unmatched"],
        "candidates": manifest["pff"]["candidates"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
