from __future__ import annotations

import csv
import html
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .injury_schema import load_teams, normalize_player_name, validate_team_abbr
from .schedule_context import ScheduleGameContext, load_schedule_context, schedule_for_team


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = PROJECT_ROOT / "data" / "raw" / "official_team"
PROCESSED_ROOT = PROJECT_ROOT / "data" / "processed"
PARSER_VERSION = "official_team_common_table_v1"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "FirstAndThirty-InjuryTracker/0.1"
)

DAY_COLUMNS = {
    "MON": "Monday",
    "TUE": "Tuesday",
    "WED": "Wednesday",
    "THU": "Thursday",
    "FRI": "Friday",
    "SAT": "Saturday",
    "SUN": "Sunday",
}

PARTICIPATION_MAP = {
    "DID NOT PARTICIPATE": "DNP",
    "DNP": "DNP",
    "LIMITED PARTICIPATION": "LP",
    "LIMITED": "LP",
    "LP": "LP",
    "FULL PARTICIPATION": "FP",
    "FULL": "FP",
    "FP": "FP",
}

GAME_STATUS_MAP = {
    "OUT": "Out",
    "DOUBTFUL": "Doubtful",
    "QUESTIONABLE": "Questionable",
    "UNSPECIFIED": None,
    "": None,
}


@dataclass
class FetchResult:
    team: str
    url: str
    status: str
    fetched_at: str
    http_status: int | None = None
    content_type: str | None = None
    body: str | None = None
    error: str | None = None


@dataclass
class ParseResult:
    team: str
    fetch_status: str
    parse_status: str
    current_week_status: str
    players_found: int = 0
    report_dates_found: list[str] = field(default_factory=list)
    report_days_found: list[str] = field(default_factory=list)
    opponent: str | None = None
    page_opponent: str | None = None
    schedule_opponent: str | None = None
    schedule_home_away: str | None = None
    schedule_game_date: str | None = None
    schedule_kickoff: str | None = None
    schedule_source: str | None = None
    match_validation: str = "MATCH_CONTEXT_UNAVAILABLE"
    parsed_source_rows: int = 0
    meaningful_injury_records: int = 0
    selected_week: int | None = None
    parser_strategy: str = PARSER_VERSION
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class TableSnapshot:
    rows: list[list[str]]
    context: str


class InjuryTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[TableSnapshot] = []
        self._recent_text: list[str] = []
        self._in_table = False
        self._in_cell = False
        self._current_table: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] = []
        self._table_context = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            self._in_table = True
            self._current_table = []
            self._table_context = clean_text(" ".join(self._recent_text[-120:]))
        elif self._in_table and tag == "tr":
            self._current_row = []
        elif self._in_table and tag in {"td", "th"}:
            self._in_cell = True
            self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._in_table and tag in {"td", "th"}:
            if self._current_row is not None:
                self._current_row.append(clean_text(" ".join(self._current_cell)))
            self._in_cell = False
            self._current_cell = []
        elif self._in_table and tag == "tr":
            if self._current_row and any(cell for cell in self._current_row):
                self._current_table.append(self._current_row)
            self._current_row = None
        elif tag == "table" and self._in_table:
            self.tables.append(TableSnapshot(rows=self._current_table, context=self._table_context))
            self._in_table = False
            self._current_table = []

    def handle_data(self, data: str) -> None:
        text = clean_text(data)
        if not text:
            return
        if self._in_table and self._in_cell:
            self._current_cell.append(text)
        elif not self._in_table:
            self._recent_text.append(text)
            if len(self._recent_text) > 300:
                self._recent_text = self._recent_text[-300:]


def fetch_page(team: dict[str, Any], *, timeout: int = 25, retries: int = 2, retry_sleep: float = 1.0) -> FetchResult:
    fetched_at = datetime.now(timezone.utc).isoformat()
    request = urllib.request.Request(team["injury_report_url"], headers={"User-Agent": USER_AGENT})
    last_error: str | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                body = raw.decode(charset, errors="replace")
                return FetchResult(
                    team=team["abbr"],
                    url=team["injury_report_url"],
                    status="OK",
                    fetched_at=fetched_at,
                    http_status=response.status,
                    content_type=response.headers.get("content-type"),
                    body=body,
                )
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(retry_sleep * (attempt + 1))
    return FetchResult(
        team=team["abbr"],
        url=team["injury_report_url"],
        status="FETCH_FAILED",
        fetched_at=fetched_at,
        error=last_error,
    )


def parse_official_report(
    html_text: str,
    *,
    requested_team: str,
    season: int,
    week: int,
    source_url: str,
    fetched_at: str,
    raw_snapshot: str | None = None,
    teams: list[dict[str, Any]] | None = None,
    schedule_context: ScheduleGameContext | None = None,
) -> tuple[list[dict[str, Any]], ParseResult]:
    requested_team = validate_team_abbr(requested_team)
    all_teams = teams or load_teams()
    team_lookup = team_name_lookup(all_teams)
    selected_week = detect_selected_week(html_text)

    parser = InjuryTableParser()
    try:
        parser.feed(html_text)
    except Exception as exc:
        result = ParseResult(
            team=requested_team,
            fetch_status="OK",
            parse_status="PARSE_FAILED",
            current_week_status="UNKNOWN",
            selected_week=selected_week,
            match_validation="PARSE_FAILED",
            errors=[f"{type(exc).__name__}: {exc}"],
        )
        return [], result

    records: dict[tuple[str, str], dict[str, Any]] = {}
    report_days: set[str] = set()
    warnings: list[str] = []
    injury_tables = [table for table in parser.tables if is_injury_table(table.rows)]

    if not injury_tables:
        status = "NO_REPORT_YET" if "injury" in html_text.lower() else "PARSE_FAILED"
        match_validation = "NO_REPORT_YET" if status == "NO_REPORT_YET" else "PARSE_FAILED"
        return [], ParseResult(
            team=requested_team,
            fetch_status="OK",
            parse_status=status,
            current_week_status=current_week_status(status, selected_week, week, 0),
            selected_week=selected_week,
            match_validation=match_validation,
            **schedule_fields(schedule_context),
            warnings=["No recognizable injury-report table found."],
        )

    inferred_table_teams = []
    for index, table in enumerate(injury_tables):
        table_team = infer_table_team(table.context, team_lookup)
        if table_team is None and index == 0:
            table_team = requested_team
            warnings.append("First table team inferred from requested team.")
        elif table_team is None:
            table_team = f"UNKNOWN_{index + 1}"
            warnings.append(f"Could not infer team for table {index + 1}.")
        inferred_table_teams.append(table_team)
        for row in table_to_dicts(table.rows):
            record = record_from_row(
                row,
                season=season,
                week=week,
                team=table_team,
                source_url=source_url,
                fetched_at=fetched_at,
                raw_snapshot=raw_snapshot,
                game_date=schedule_context.game_date if schedule_context else None,
            )
            if record is None:
                continue
            record["has_report_data"] = has_report_data(record)
            key = (record["team"], record["normalized_player_name"])
            merge_record(records, key, record)
            for observation in record["practice_observations"]:
                if observation.get("day"):
                    report_days.add(observation["day"])

    requested_records = [record for record in records.values() if record["team"] == requested_team]
    requested_report_records = [record for record in requested_records if record.get("has_report_data")]
    if requested_records and not requested_report_records:
        warnings.append("Requested team table contained player rows but no injury/practice/status values.")
    opponent = next(
        (
            team
            for team in inferred_table_teams
            if team != requested_team and not team.startswith("UNKNOWN_")
        ),
        None,
    )
    parse_status = "OK" if records else "NO_REPORT_YET"
    match_validation = validate_match_context(
        parse_status=parse_status,
        selected_week=selected_week,
        requested_week=week,
        page_opponent=opponent,
        schedule_context=schedule_context,
        players_found=len(requested_report_records),
    )
    result = ParseResult(
        team=requested_team,
        fetch_status="OK",
        parse_status=parse_status,
        current_week_status=current_week_status(
            parse_status,
            selected_week,
            week,
            len(requested_report_records),
            match_validation=match_validation,
        ),
        players_found=len(requested_report_records),
        report_days_found=sorted(report_days),
        opponent=opponent,
        page_opponent=opponent,
        match_validation=match_validation,
        parsed_source_rows=len(requested_records),
        meaningful_injury_records=len(requested_report_records),
        selected_week=selected_week,
        **schedule_fields(schedule_context),
        warnings=warnings,
    )
    return sorted(records.values(), key=lambda row: (row["team"], row["normalized_player_name"])), result


def record_from_row(
    row: dict[str, str],
    *,
    season: int,
    week: int,
    team: str,
    source_url: str,
    fetched_at: str,
    raw_snapshot: str | None,
    game_date: str | None = None,
) -> dict[str, Any] | None:
    player = row.get("Player") or row.get("Name")
    if not player or player.upper() in {"PLAYER", "NAME"}:
        return None
    position = none_if_blank(row.get("Position") or row.get("Pos"))
    injury = none_if_blank(row.get("Injury"))
    game_status_raw = none_if_blank(row.get("Game Status") or row.get("Status") or row.get("Designation"))
    game_status = normalize_game_status(game_status_raw)
    observations = []
    practice_by_day: dict[str, str] = {}

    for column, value in row.items():
        day = normalize_day_column(column)
        if not day:
            continue
        raw_value = none_if_blank(value)
        participation = normalize_participation(raw_value)
        if participation is None:
            continue
        observations.append(
            {
                "date": infer_practice_date(game_date, day),
                "day": day,
                "column": column,
                "participation": participation,
                "raw_participation": raw_value,
                "practice_date_source": "schedule_inferred" if infer_practice_date(game_date, day) else None,
            }
        )
        practice_by_day[day] = participation

    return {
        "season": int(season),
        "week": int(week),
        "team": team,
        "player_name": clean_text(player),
        "normalized_player_name": normalize_player_name(player),
        "source_position": position,
        "injury": injury,
        "game_status": game_status,
        "game_status_raw": game_status_raw,
        "practice_observations": observations,
        "practice_by_day": practice_by_day,
        "source_url": source_url,
        "fetched_at": fetched_at,
        "source_metadata": {
            "source": "official_team",
            "parser_version": PARSER_VERSION,
            "raw_snapshot": raw_snapshot,
            "raw_row": row,
        },
    }


def schedule_fields(schedule_context: ScheduleGameContext | None) -> dict[str, Any]:
    if schedule_context is None:
        return {
            "schedule_opponent": None,
            "schedule_home_away": None,
            "schedule_game_date": None,
            "schedule_kickoff": None,
            "schedule_source": None,
        }
    return {
        "schedule_opponent": schedule_context.opponent,
        "schedule_home_away": schedule_context.home_away,
        "schedule_game_date": schedule_context.game_date,
        "schedule_kickoff": schedule_context.kickoff,
        "schedule_source": schedule_context.schedule_source,
    }


def validate_match_context(
    *,
    parse_status: str,
    selected_week: int | None,
    requested_week: int,
    page_opponent: str | None,
    schedule_context: ScheduleGameContext | None,
    players_found: int,
) -> str:
    if parse_status == "FETCH_FAILED":
        return "FETCH_FAILED"
    if parse_status == "PARSE_FAILED":
        return "PARSE_FAILED"
    if selected_week is not None and selected_week != int(requested_week):
        return "MATCH_MISMATCH"
    if not players_found:
        return "NO_REPORT_YET"
    if schedule_context is None or page_opponent is None:
        return "MATCH_CONTEXT_UNAVAILABLE"
    if page_opponent != schedule_context.opponent:
        return "MATCH_MISMATCH"
    return "MATCH_CONFIRMED"


def infer_practice_date(game_date: str | None, day: str | None) -> str | None:
    if not game_date or not day:
        return None
    try:
        game_day = date.fromisoformat(game_date[:10])
    except ValueError:
        return None
    weekday_by_name = {
        "Monday": 0,
        "Tuesday": 1,
        "Wednesday": 2,
        "Thursday": 3,
        "Friday": 4,
        "Saturday": 5,
        "Sunday": 6,
    }
    target = weekday_by_name.get(day)
    if target is None:
        return None
    days_back = (game_day.weekday() - target) % 7
    if days_back == 0:
        days_back = 7
    if days_back > 6:
        return None
    return (game_day - timedelta(days=days_back)).isoformat()


def merge_record(records: dict[tuple[str, str], dict[str, Any]], key: tuple[str, str], record: dict[str, Any]) -> None:
    existing = records.get(key)
    if existing is None:
        records[key] = record
        return
    for field_name in ["source_position", "injury", "game_status", "game_status_raw"]:
        if not existing.get(field_name) and record.get(field_name):
            existing[field_name] = record[field_name]
    existing_observations = {
        (item.get("date"), item.get("day")): item for item in existing["practice_observations"]
    }
    for observation in record["practice_observations"]:
        existing_observations[(observation.get("date"), observation.get("day"))] = observation
    existing["practice_observations"] = list(existing_observations.values())
    existing["practice_by_day"].update(record["practice_by_day"])
    existing["has_report_data"] = has_report_data(existing)


def has_report_data(record: dict[str, Any]) -> bool:
    return bool(
        record.get("injury")
        or record.get("game_status")
        or record.get("game_status_raw")
        or record.get("practice_observations")
    )


def save_raw_fetch(fetch: FetchResult, *, season: int, week: int, run_id: str) -> tuple[Path | None, Path]:
    run_dir = RAW_ROOT / str(season) / f"week_{week:02d}" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    html_path = run_dir / f"{fetch.team}.html"
    if fetch.body is not None:
        html_path.write_text(fetch.body, encoding="utf-8")
        raw_ref: Path | None = html_path
    else:
        raw_ref = None
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
    records: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    manifest: list[dict[str, Any]],
) -> Path:
    out_dir = PROCESSED_ROOT / str(season) / f"week_{week:02d}" / run_id
    out_dir.mkdir(parents=True, exist_ok=False)
    (out_dir / "official_injury_reports.json").write_text(
        json.dumps(records, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_dir / "official_injury_source_rows.json").write_text(
        json.dumps(source_rows, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_records_csv(out_dir / "official_injury_reports.csv", records)
    write_records_csv(out_dir / "official_injury_source_rows.csv", source_rows)
    write_summary(out_dir / "summary.md", manifest)
    return out_dir


def write_records_csv(path: Path, records: list[dict[str, Any]]) -> None:
    columns = [
        "season",
        "week",
        "team",
        "player_name",
        "normalized_player_name",
        "source_position",
        "injury",
        "practice_mon",
        "practice_tue",
        "practice_wed",
        "practice_thu",
        "practice_fri",
        "practice_sat",
        "practice_sun",
        "game_status",
        "game_status_raw",
        "has_report_data",
        "source_page_team",
        "source_url",
        "fetched_at",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in records:
            by_day = record.get("practice_by_day", {})
            row = {column: record.get(column) for column in columns}
            for day in DAY_COLUMNS.values():
                row[f"practice_{day[:3].lower()}"] = by_day.get(day)
            writer.writerow(row)


def write_summary(path: Path, manifest: list[dict[str, Any]]) -> None:
    lines = ["# Official Team Injury Report Fetch Summary", ""]
    for item in manifest:
        lines.extend(
            [
                f"## {item['team']}",
                "",
                f"- Fetch: {item['fetch_status']}",
                f"- Parse: {item['parse_status']}",
                f"- Current week: {item['current_week_status']}",
                f"- Match validation: {item.get('match_validation')}",
                f"- Meaningful injury records: {item.get('meaningful_injury_records', item['players_found'])}",
                f"- Parsed source rows: {item.get('parsed_source_rows', 0)}",
                f"- Report days: {', '.join(item.get('report_days_found') or []) or 'none'}",
                f"- Page opponent: {item.get('page_opponent') or item.get('opponent') or 'unknown'}",
                f"- Schedule opponent: {item.get('schedule_opponent') or 'unknown'}",
                f"- Schedule home/away: {item.get('schedule_home_away') or 'unknown'}",
                f"- Schedule game date: {item.get('schedule_game_date') or 'unknown'}",
                f"- Parser: {item['parser_strategy']}",
            ]
        )
        if item.get("warnings"):
            lines.append(f"- Warnings: {'; '.join(item['warnings'])}")
        if item.get("errors"):
            lines.append(f"- Errors: {'; '.join(item['errors'])}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def run_ingestion(
    *,
    season: int,
    week: int,
    selected_team_abbrs: list[str],
    delay_seconds: float = 0.25,
    timeout: int = 25,
    retries: int = 2,
) -> tuple[Path, list[dict[str, Any]], list[dict[str, Any]]]:
    teams = load_teams()
    selected = [team for team in teams if team["abbr"] in set(selected_team_abbrs)]
    missing = sorted(set(selected_team_abbrs) - {team["abbr"] for team in selected})
    if missing:
        raise ValueError(f"Unknown teams: {missing}")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    all_records: list[dict[str, Any]] = []
    all_source_rows: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []
    schedule_contexts = load_schedule_context(teams=teams)

    for index, team in enumerate(selected):
        if index and delay_seconds > 0:
            time.sleep(delay_seconds)
        fetch = fetch_page(team, timeout=timeout, retries=retries)
        raw_path, metadata_path = save_raw_fetch(fetch, season=season, week=week, run_id=run_id)
        if fetch.status != "OK" or fetch.body is None:
            schedule_context = schedule_for_team(season, week, team["abbr"], contexts=schedule_contexts, teams=teams)
            parse_result = ParseResult(
                team=team["abbr"],
                fetch_status=fetch.status,
                parse_status="FETCH_FAILED",
                current_week_status="UNKNOWN",
                match_validation="FETCH_FAILED",
                **schedule_fields(schedule_context),
                errors=[fetch.error or "Fetch failed."],
            )
            records = []
        else:
            schedule_context = schedule_for_team(season, week, team["abbr"], contexts=schedule_contexts, teams=teams)
            records, parse_result = parse_official_report(
                fetch.body,
                requested_team=team["abbr"],
                season=season,
                week=week,
                source_url=team["injury_report_url"],
                fetched_at=fetch.fetched_at,
                raw_snapshot=str(raw_path) if raw_path else None,
                teams=teams,
                schedule_context=schedule_context,
            )
        requested_records = [record for record in records if record["team"] == team["abbr"]]
        requested_meaningful_records = [record for record in requested_records if record.get("has_report_data")]
        for record in records:
            record["source_page_team"] = team["abbr"]
        all_source_rows.extend(records)
        all_records.extend(requested_meaningful_records)
        item = asdict(parse_result)
        item["raw_file"] = str(raw_path) if raw_path else None
        item["raw_metadata_file"] = str(metadata_path)
        item["source_url"] = team["injury_report_url"]
        manifest.append(item)

    out_dir = write_processed_outputs(
        season=season,
        week=week,
        run_id=run_id,
        records=all_records,
        source_rows=all_source_rows,
        manifest=manifest,
    )
    return out_dir, all_records, manifest


def is_injury_table(rows: list[list[str]]) -> bool:
    if not rows:
        return False
    headers = {clean_header(cell) for cell in rows[0]}
    return {"PLAYER", "POSITION", "INJURY"}.issubset(headers) and (
        bool(headers & set(DAY_COLUMNS)) or "GAME STATUS" in headers
    )


def table_to_dicts(rows: list[list[str]]) -> list[dict[str, str]]:
    if not rows:
        return []
    headers = [canonical_header(cell) for cell in rows[0]]
    output = []
    for row in rows[1:]:
        values = row + [""] * (len(headers) - len(row))
        output.append({header: values[index] for index, header in enumerate(headers)})
    return output


def team_name_lookup(teams: list[dict[str, Any]]) -> dict[str, str]:
    lookup = {}
    for team in teams:
        labels = [team["full_name"], team["abbr"], *team.get("aliases", [])]
        for label in labels:
            lookup[clean_text(label).lower()] = team["abbr"]
    return lookup


def infer_table_team(context: str, lookup: dict[str, str]) -> str | None:
    text = clean_text(context).lower()
    best: tuple[int, int, str] | None = None
    for label, abbr in lookup.items():
        pattern = r"(?<![a-z0-9])" + re.escape(label) + r"(?![a-z0-9])"
        matches = list(re.finditer(pattern, text, re.I))
        if not matches:
            continue
        index = matches[-1].start()
        candidate = (index, len(label), abbr)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    return best[2] if best else None


def detect_selected_week(html_text: str) -> int | None:
    match = re.search(r'value=["\']/team/injury-report/week/REG-(\d+)["\'][^>]*\bselected\b', html_text, re.I)
    if match:
        return int(match.group(1))
    return None


def current_week_status(
    parse_status: str,
    selected_week: int | None,
    requested_week: int,
    players_found: int,
    *,
    match_validation: str | None = None,
) -> str:
    if parse_status == "FETCH_FAILED":
        return "UNKNOWN"
    if selected_week is not None and selected_week != int(requested_week):
        return "SUCCESS_BUT_STALE" if players_found else "NO_REPORT_YET"
    if match_validation == "MATCH_MISMATCH":
        return "SUCCESS_BUT_STALE" if players_found else "NO_REPORT_YET"
    if selected_week == int(requested_week):
        return "SUCCESS_CURRENT" if players_found else "NO_REPORT_YET"
    if parse_status == "OK":
        return "UNKNOWN"
    return "NO_REPORT_YET"


def normalize_participation(value: Any) -> str | None:
    text = clean_text(value).upper()
    if not text or text in {"NAN", "NONE", "UNSPECIFIED", "--", "-"}:
        return None
    return PARTICIPATION_MAP.get(text, text)


def normalize_game_status(value: Any) -> str | None:
    text = clean_text(value).upper()
    if text in GAME_STATUS_MAP:
        return GAME_STATUS_MAP[text]
    return clean_text(value) or None


def normalize_day_column(value: str) -> str | None:
    header = clean_header(value)
    return DAY_COLUMNS.get(header)


def canonical_header(value: str) -> str:
    header = clean_header(value)
    if header == "POS":
        return "Position"
    if header in DAY_COLUMNS or header in {"PLAYER", "POSITION", "INJURY"}:
        return header.title() if header not in DAY_COLUMNS else header.title()
    if header in {"GAME STATUS", "STATUS", "DESIGNATION"}:
        return "Game Status"
    return clean_text(value)


def clean_header(value: Any) -> str:
    return clean_text(value).upper()


def none_if_blank(value: Any) -> str | None:
    text = clean_text(value)
    if not text or text.upper() in {"NAN", "NONE", "UNSPECIFIED", "--", "-"}:
        return None
    return text


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    return re.sub(r"\s+", " ", text).strip()
