from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts" / "02_processing") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "02_processing"))

from ingest_odds_snapshots import ingest_snapshot_file
from odds_adapters.common import discover_snapshot_files
from odds_adapters.odds_api import load_json_payload
from odds_asof.loader import load_odds_registry
from odds_asof.reporting import write_odds_asof_outputs
from odds_asof.selection import select_odds_asof
from odds_join import join_projections_to_odds
from odds_registry.registry import build_odds_registry

API_BASE = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_nfl"
REGION = "us"
ODDS_FORMAT = "american"
DATE_FORMAT = "iso"
SOURCE = "odds_api"
LOCAL_TZ = ZoneInfo("America/New_York")

MARKETS = [
    "player_pass_yds",
    "player_rush_yds",
    "player_reception_yds",
    "player_receptions",
    "player_pass_yds_alternate",
    "player_rush_yds_alternate",
    "player_reception_yds_alternate",
    "player_receptions_alternate",
]

MAIN_MARKETS = {
    "player_pass_yds",
    "player_rush_yds",
    "player_reception_yds",
    "player_receptions",
}

REGULAR_SEASON_START_DATES = {
    2023: "2023-09-07",
    2024: "2024-09-05",
    2025: "2025-09-04",
    2026: "2026-09-09",
}


@dataclass(frozen=True)
class ApiCallResult:
    payload: Any
    raw_file: Path
    status_code: int
    x_requests_last: int | None
    x_requests_used: int | None
    x_requests_remaining: int | None


def parse_api_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def week_window(season: int, week: int) -> tuple[datetime, datetime]:
    if season not in REGULAR_SEASON_START_DATES:
        raise ValueError(f"No regular-season start date configured for season={season}")
    if week < 1 or week > 18:
        raise ValueError("Only regular-season weeks 1-18 are supported")
    start_date = datetime.fromisoformat(REGULAR_SEASON_START_DATES[season]).replace(tzinfo=LOCAL_TZ)
    start = start_date + timedelta(days=(week - 1) * 7)
    end = start + timedelta(days=7)
    return start, end


def filter_events_for_week(events: list[dict], *, season: int, week: int) -> list[dict]:
    start, end = week_window(season, week)
    selected: list[dict] = []
    for event in events:
        commence_time = event.get("commence_time")
        if not commence_time:
            continue
        try:
            local_commence = parse_api_datetime(commence_time).astimezone(LOCAL_TZ)
        except ValueError:
            continue
        if start <= local_commence < end:
            selected.append(event)
    return selected


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_api_key(project_root: Path = PROJECT_ROOT) -> str:
    load_env_file(project_root / ".env")
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ODDS_API_KEY is not set in the environment or .env")
    return key


def _header_int(headers: Any, name: str) -> int | None:
    value = headers.get(name) or headers.get(name.upper()) or headers.get(name.lower())
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _write_bytes_before_parse(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _safe_slug(value: str) -> str:
    return (
        value.replace(":", "")
        .replace("-", "")
        .replace("+", "")
        .replace(".", "")
        .replace("T", "T")
    )


def call_odds_api(session: Any, url: str, *, params: dict[str, str], raw_file: Path) -> ApiCallResult:
    response = session.get(url, params=params, timeout=30)
    _write_bytes_before_parse(raw_file, response.content)
    x_last = _header_int(response.headers, "x-requests-last")
    x_used = _header_int(response.headers, "x-requests-used")
    x_remaining = _header_int(response.headers, "x-requests-remaining")
    if response.status_code >= 400:
        message = response.text[:500] if response.text else f"HTTP {response.status_code}"
        raise RuntimeError(f"Odds API request failed with status {response.status_code}: {message}")
    return ApiCallResult(
        payload=json.loads(response.content.decode("utf-8")),
        raw_file=raw_file,
        status_code=response.status_code,
        x_requests_last=x_last,
        x_requests_used=x_used,
        x_requests_remaining=x_remaining,
    )


def raw_snapshot_dir(project_root: Path, season: int, week: int) -> Path:
    return project_root / "data" / "raw" / "odds" / SOURCE / str(season) / f"week_{week:02d}" / "snapshots"


def write_bundle(raw_files: list[Path], *, bundle_file: Path) -> list[dict]:
    payloads = [load_json_payload(path) for path in raw_files]
    bundle_file.write_text(json.dumps(payloads, indent=2, sort_keys=False), encoding="utf-8")
    return payloads


def write_manifest(
    *,
    manifest_file: Path,
    captured_at: datetime,
    season: int,
    week: int,
    events_file: Path,
    event_odds_files: list[Path],
    events_returned: int,
    events_selected: int,
    markets: list[str],
    event_calls: int,
    credit_total: int,
    request_headers: list[dict[str, Any]],
) -> None:
    manifest = {
        "source": SOURCE,
        "sport": SPORT,
        "season": season,
        "week": week,
        "captured_at": captured_at.isoformat(),
        "timezone": str(LOCAL_TZ),
        "events_file": str(events_file.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "event_odds_files": [str(path.relative_to(PROJECT_ROOT)).replace("\\", "/") for path in event_odds_files],
        "markets": markets,
        "region": REGION,
        "odds_format": ODDS_FORMAT,
        "date_format": DATE_FORMAT,
        "bookmaker_policy": "regions=us; no bookmaker filter",
        "events_returned": events_returned,
        "events_selected": events_selected,
        "event_odds_calls": event_calls,
        "x_requests_last_total": credit_total,
        "request_headers": request_headers,
    }
    manifest_file.write_text(json.dumps(manifest, indent=2, sort_keys=False), encoding="utf-8")


def market_return_counts(bundle_payload: list[dict]) -> dict[str, int]:
    counts = {market: 0 for market in MARKETS}
    for event in bundle_payload:
        for book in event.get("bookmakers", []) or []:
            for market in book.get("markets", []) or []:
                key = str(market.get("key", ""))
                if key in counts:
                    counts[key] += len(market.get("outcomes", []) or [])
    return counts


def latest_projection_rows_path(project_root: Path, season: int, week: int) -> Path | None:
    base = project_root / "data" / "processed" / "projection_consensus" / str(season) / f"week_{week}"
    if not base.exists():
        return None
    candidates = sorted(base.glob("asof_*/selected_source_projections.csv"))
    return candidates[-1] if candidates else None


def write_join_smoke(project_root: Path, season: int, week: int, odds_asof_dir: Path) -> dict[str, Any]:
    projection_path = latest_projection_rows_path(project_root, season, week)
    selected_odds_path = odds_asof_dir / "selected_odds.csv"
    if projection_path is None or not selected_odds_path.exists():
        return {"warning": "projection or selected odds file unavailable"}
    projections = pd.read_csv(projection_path)
    odds = pd.read_csv(selected_odds_path)
    result = join_projections_to_odds(projections, odds)
    joined = result["joined"]
    unmatched_projection = result["unmatched_projection"]
    unmatched_odds = result["unmatched_odds"]
    coverage_rows: list[dict[str, Any]] = []
    for market in sorted(set(projections.get("market", pd.Series(dtype=str)).dropna().astype(str)) | set(odds.get("market", pd.Series(dtype=str)).dropna().astype(str))):
        market_proj = projections.loc[projections["market"].astype(str) == market] if "market" in projections else pd.DataFrame()
        market_odds = odds.loc[odds["market"].astype(str) == market] if "market" in odds else pd.DataFrame()
        market_joined = joined.loc[joined["market"].astype(str) == market] if "market" in joined else pd.DataFrame()
        coverage_rows.append({
            "market": market,
            "projection_rows": len(market_proj),
            "odds_rows": len(market_odds),
            "joined_rows": len(market_joined),
            "unique_projected_players": market_proj["player_normalized"].nunique() if "player_normalized" in market_proj else 0,
            "unique_odds_players": market_odds["player_normalized"].nunique() if "player_normalized" in market_odds else 0,
            "unique_joined_players": market_joined["player_normalized"].nunique() if "player_normalized" in market_joined else 0,
        })
    coverage = pd.DataFrame(coverage_rows)
    coverage_path = odds_asof_dir / "projection_odds_join_smoke_coverage.csv"
    joined_sample_path = odds_asof_dir / "projection_odds_join_smoke_sample.csv"
    unmatched_projection_path = odds_asof_dir / "projection_odds_join_smoke_unmatched_projection.csv"
    unmatched_odds_path = odds_asof_dir / "projection_odds_join_smoke_unmatched_odds.csv"
    coverage.to_csv(coverage_path, index=False)
    joined.head(250).to_csv(joined_sample_path, index=False)
    unmatched_projection.head(250).to_csv(unmatched_projection_path, index=False)
    unmatched_odds.head(250).to_csv(unmatched_odds_path, index=False)
    return {
        "projection_path": str(projection_path),
        "coverage_path": str(coverage_path),
        "joined_sample_path": str(joined_sample_path),
        "unmatched_projection_path": str(unmatched_projection_path),
        "unmatched_odds_path": str(unmatched_odds_path),
        "projection_rows": len(projections),
        "odds_rows": len(odds),
        "joined_rows": len(joined),
        "unmatched_projection_rows": len(unmatched_projection),
        "unmatched_odds_rows": len(unmatched_odds),
        "coverage": coverage.to_dict(orient="records"),
    }


def run_live_download(args: argparse.Namespace) -> dict[str, Any]:
    import requests

    captured_at = datetime.now(LOCAL_TZ)
    slug = _safe_slug(captured_at.isoformat())
    snapshot_dir = raw_snapshot_dir(PROJECT_ROOT, args.season, args.week)
    api_key = load_api_key(PROJECT_ROOT)
    session = requests.Session()

    events_file = snapshot_dir / f"{slug}_events.json"
    events_result = call_odds_api(
        session,
        f"{API_BASE}/sports/{SPORT}/events",
        params={"apiKey": api_key, "dateFormat": DATE_FORMAT},
        raw_file=events_file,
    )
    events = [event for event in events_result.payload if isinstance(event, dict)]
    selected_events = filter_events_for_week(events, season=args.season, week=args.week)
    skipped = len(events) - len(selected_events)
    print(f"[events_returned] {len(events)}")
    print(f"[events_inside_week_{args.week}] {len(selected_events)}")
    print(f"[events_skipped_outside_week_window] {skipped}")
    if not selected_events:
        print("[no_events] No regular-season events were inside the requested week window; no event-odds calls made.")
        return {
            "events_returned": len(events),
            "events_scanned": 0,
            "events_skipped": skipped,
            "event_odds_calls": 0,
            "credit_total": 0,
            "events_file": str(events_file),
        }

    event_odds_files: list[Path] = []
    request_headers: list[dict[str, Any]] = []
    credit_total = 0
    unsupported_errors: list[str] = []
    market_param = ",".join(MARKETS)
    for index, event in enumerate(selected_events, start=1):
        event_id = str(event["id"])
        odds_file = snapshot_dir / f"{slug}_event_{index:02d}_{event_id}_odds.json"
        try:
            result = call_odds_api(
                session,
                f"{API_BASE}/sports/{SPORT}/events/{event_id}/odds",
                params={
                    "apiKey": api_key,
                    "regions": REGION,
                    "markets": market_param,
                    "oddsFormat": ODDS_FORMAT,
                    "dateFormat": DATE_FORMAT,
                },
                raw_file=odds_file,
            )
        except RuntimeError as exc:
            message = str(exc)
            if "market" in message.lower() and "support" in message.lower():
                unsupported_errors.append(message)
            raise
        event_odds_files.append(odds_file)
        if result.x_requests_last is not None:
            credit_total += result.x_requests_last
        request_headers.append({
            "event_id": event_id,
            "x_requests_last": result.x_requests_last,
            "x_requests_used": result.x_requests_used,
            "x_requests_remaining": result.x_requests_remaining,
        })
        print(
            f"[event_odds] {index}/{len(selected_events)} {event.get('away_team', '')} @ {event.get('home_team', '')} "
            f"x-requests-last={result.x_requests_last}"
        )
        time.sleep(args.request_sleep_seconds)

    bundle_file = snapshot_dir / f"{slug}_odds_bundle.json"
    bundle_payload = write_bundle(event_odds_files, bundle_file=bundle_file)
    manifest_file = snapshot_dir / f"{slug}_manifest.json"
    write_manifest(
        manifest_file=manifest_file,
        captured_at=captured_at,
        season=args.season,
        week=args.week,
        events_file=events_file,
        event_odds_files=event_odds_files,
        events_returned=len(events),
        events_selected=len(selected_events),
        markets=MARKETS,
        event_calls=len(event_odds_files),
        credit_total=credit_total,
        request_headers=request_headers,
    )

    ingest_result = ingest_snapshot_file(
        bundle_file,
        source=SOURCE,
        season=args.season,
        week=args.week,
        output_root=PROJECT_ROOT,
        captured_at=captured_at.isoformat(),
        skip_registry_update=True,
        overwrite=args.overwrite,
    )
    registry_result = build_odds_registry(project_root=PROJECT_ROOT, output_root=PROJECT_ROOT, source=SOURCE, season=args.season, week=args.week, rebuild=True)
    registry = load_odds_registry(PROJECT_ROOT / "data" / "processed" / "odds" / "snapshot_registry.csv", project_root=PROJECT_ROOT)
    asof_result = select_odds_asof(
        registry=registry,
        project_root=PROJECT_ROOT,
        season=args.season,
        week=args.week,
        as_of=captured_at.isoformat(),
        sportsbooks=None,
        market=None,
    )
    odds_asof_dir = PROJECT_ROOT / "data" / "processed" / "odds_asof" / str(args.season) / f"week_{args.week:02d}" / f"asof_{_safe_slug(captured_at.isoformat())}"
    asof_outputs = write_odds_asof_outputs(asof_result, output_dir=odds_asof_dir, overwrite=args.overwrite)
    join_smoke = write_join_smoke(PROJECT_ROOT, args.season, args.week, odds_asof_dir)
    returned_market_counts = market_return_counts(bundle_payload)
    zero_markets = [market for market, count in returned_market_counts.items() if count == 0]
    selected_odds = asof_result["selected_odds"]
    rows_by_market = selected_odds.groupby("market").size().to_dict() if not selected_odds.empty else {}
    rows_by_raw_market = selected_odds.groupby("market_source_key").size().to_dict() if not selected_odds.empty else {}
    books_returned = sorted(selected_odds["sportsbook"].dropna().astype(str).unique().tolist()) if not selected_odds.empty else []
    return {
        "events_returned": len(events),
        "events_scanned": len(selected_events),
        "events_skipped": skipped,
        "event_odds_calls": len(event_odds_files),
        "credit_total": credit_total,
        "events_file": str(events_file),
        "event_odds_files": [str(path) for path in event_odds_files],
        "bundle_file": str(bundle_file),
        "manifest_file": str(manifest_file),
        "ingest_result": ingest_result,
        "registry_path": registry_result["registry_path"],
        "registry_conflicts": registry_result["conflicts"],
        "asof_outputs": asof_outputs,
        "join_smoke": join_smoke,
        "requested_markets": MARKETS,
        "requested_books": "regions=us (all available US books)",
        "books_returned": books_returned,
        "canonical_rows": ingest_result.get("rows_written", 0),
        "main_line_rows": ingest_result.get("main_line_rows", 0),
        "alternate_line_rows": ingest_result.get("alternate_line_rows", 0),
        "rejected_rows": ingest_result.get("rejected_rows", 0),
        "rows_by_market": rows_by_market,
        "rows_by_raw_market": rows_by_raw_market,
        "zero_returned_requested_markets": zero_markets,
        "unsupported_market_errors": unsupported_errors,
    }


def print_summary(result: dict[str, Any]) -> None:
    print("[event_odds_calls]", result.get("event_odds_calls", 0))
    print("[x_requests_last_total]", result.get("credit_total", 0))
    if "bundle_file" not in result:
        return
    print("[requested_markets]", result["requested_markets"])
    print("[requested_books]", result["requested_books"])
    print("[books_returned]", result["books_returned"])
    print("[raw_events_file]", result["events_file"])
    print("[raw_event_odds_files]", result["event_odds_files"])
    print("[raw_bundle_file]", result["bundle_file"])
    print("[manifest_file]", result["manifest_file"])
    print("[canonical_rows]", result["canonical_rows"])
    print("[main_line_rows]", result["main_line_rows"])
    print("[alternate_line_rows]", result["alternate_line_rows"])
    print("[rejected_rows]", result["rejected_rows"])
    print("[rows_by_market]", result["rows_by_market"])
    print("[rows_by_raw_market]", result["rows_by_raw_market"])
    print("[zero_returned_requested_markets]", result["zero_returned_requested_markets"])
    print("[unsupported_market_errors]", result["unsupported_market_errors"])
    print("[registry_path]", result["registry_path"])
    print("[registry_conflicts]", result["registry_conflicts"])
    print("[asof_outputs]", result["asof_outputs"])
    print("[join_smoke]", {key: value for key, value in result["join_smoke"].items() if key != "coverage"})
    if result["join_smoke"].get("coverage"):
        print("[join_smoke_coverage]")
        print(pd.DataFrame(result["join_smoke"]["coverage"]).to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Download live Odds API NFL player props into the existing odds pipeline")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--execute-live-request", action="store_true", help="Required before any HTTP request is made")
    parser.add_argument("--request-sleep-seconds", type=float, default=0.35)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if not args.execute_live_request:
        print("[dry_run] No HTTP requests made. Re-run with --execute-live-request to download live Odds API data.")
        print(f"[sport] {SPORT}")
        print(f"[event_endpoint] /sports/{SPORT}/events")
        print(f"[event_odds_endpoint] /sports/{SPORT}/events/{{event_id}}/odds")
        print(f"[markets] {MARKETS}")
        print(f"[books] regions={REGION}; no bookmaker filter")
        print(f"[week_window] {week_window(args.season, args.week)[0].isoformat()} to {week_window(args.season, args.week)[1].isoformat()}")
        discovered = discover_snapshot_files(PROJECT_ROOT, source=SOURCE, season=args.season, week=args.week)
        print(f"[existing_ingestable_snapshots] {[str(path) for path in discovered]}")
        return

    result = run_live_download(args)
    print_summary(result)


if __name__ == "__main__":
    main()
