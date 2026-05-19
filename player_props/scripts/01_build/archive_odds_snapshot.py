import os
import csv
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone

import requests


API_BASE = "https://api.the-odds-api.com/v4"

SPORT = "americanfootball_nfl"
BOOKMAKERS = "fanduel"
REGIONS = "us"
ODDS_FORMAT = "american"
DATE_FORMAT = "iso"

# Start small. Add more once we confirm clean output.
DEFAULT_MARKETS = [
    "player_pass_yds",
    "player_rush_yds",
    "player_reception_yds",
    "player_receptions",
    "player_anytime_td",
]

OUT_DIR = Path("data/odds_snapshots")
RAW_DIR = OUT_DIR / "raw"
NORMALIZED_PATH = OUT_DIR / "odds_snapshots.csv"

SLEEP_SECONDS = 0.35  # stay comfortably under rate limits


def utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_api_key():
    key = os.getenv("ODDS_API_KEY")
    if not key:
        raise RuntimeError("Missing ODDS_API_KEY environment variable.")
    return key


def request_json(url, params):
    resp = requests.get(url, params=params, timeout=30)

    usage = {
        "remaining": resp.headers.get("x-requests-remaining"),
        "used": resp.headers.get("x-requests-used"),
        "last": resp.headers.get("x-requests-last"),
    }

    if resp.status_code != 200:
        raise RuntimeError(
            f"API error {resp.status_code}: {resp.text}\n"
            f"Usage: {usage}\n"
            f"URL: {resp.url}"
        )

    return resp.json(), usage, resp.url


def fetch_events(api_key):
    url = f"{API_BASE}/sports/{SPORT}/events"
    params = {
        "apiKey": api_key,
        "dateFormat": DATE_FORMAT,
    }
    return request_json(url, params)


def fetch_event_odds(api_key, event_id, markets):
    url = f"{API_BASE}/sports/{SPORT}/events/{event_id}/odds"
    params = {
        "apiKey": api_key,
        "regions": REGIONS,
        "bookmakers": BOOKMAKERS,
        "markets": ",".join(markets),
        "oddsFormat": ODDS_FORMAT,
        "dateFormat": DATE_FORMAT,
    }
    return request_json(url, params)


def ensure_dirs():
    RAW_DIR.mkdir(parents=True, exist_ok=True)


def save_raw_json(snapshot_ts, event_id, payload):
    safe_ts = snapshot_ts.replace(":", "").replace("-", "")
    path = RAW_DIR / f"{safe_ts}_{event_id}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path


def normalize_event_odds(snapshot_ts, event_payload):
    rows = []

    event_id = event_payload.get("id")
    sport_key = event_payload.get("sport_key")
    commence_time = event_payload.get("commence_time")
    home_team = event_payload.get("home_team")
    away_team = event_payload.get("away_team")

    for book in event_payload.get("bookmakers", []):
        bookmaker_key = book.get("key")
        bookmaker_title = book.get("title")
        bookmaker_last_update = book.get("last_update")

        for market in book.get("markets", []):
            market_key = market.get("key")
            market_last_update = market.get("last_update")

            for outcome in market.get("outcomes", []):
                rows.append({
                    "snapshot_time": snapshot_ts,
                    "event_id": event_id,
                    "sport_key": sport_key,
                    "commence_time": commence_time,
                    "home_team": home_team,
                    "away_team": away_team,
                    "bookmaker_key": bookmaker_key,
                    "bookmaker_title": bookmaker_title,
                    "bookmaker_last_update": bookmaker_last_update,
                    "market_key": market_key,
                    "market_last_update": market_last_update,
                    "player": outcome.get("description") or outcome.get("name"),
                    "side": outcome.get("name"),
                    "line": outcome.get("point"),
                    "price": outcome.get("price"),
                })

    return rows


def append_rows(rows):
    if not rows:
        return

    NORMALIZED_PATH.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "snapshot_time",
        "event_id",
        "sport_key",
        "commence_time",
        "home_team",
        "away_team",
        "bookmaker_key",
        "bookmaker_title",
        "bookmaker_last_update",
        "market_key",
        "market_last_update",
        "player",
        "side",
        "line",
        "price",
    ]

    file_exists = NORMALIZED_PATH.exists()

    with NORMALIZED_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)

        if not file_exists:
            writer.writeheader()

        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--markets",
        default=",".join(DEFAULT_MARKETS),
        help="Comma-separated market keys. Default: player_pass_yds",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=None,
        help="Optional cap for testing, e.g. --max-events 2",
    )
    parser.add_argument(
        "--no-raw",
        action="store_true",
        help="Do not save raw JSON responses.",
    )
    args = parser.parse_args()

    ensure_dirs()

    api_key = get_api_key()
    markets = [m.strip() for m in args.markets.split(",") if m.strip()]
    snapshot_ts = utc_now_iso()

    print(f"[start] snapshot_time={snapshot_ts}")
    print(f"[config] sport={SPORT} bookmaker={BOOKMAKERS} markets={markets}")

    events, usage, events_url = fetch_events(api_key)
    print(
        f"[events] returned={len(events)} "
        f"credits_last={usage['last']} used={usage['used']} remaining={usage['remaining']}"
    )

    if args.max_events:
        events = events[:args.max_events]
        print(f"[test mode] max_events={args.max_events}")

    total_rows = 0
    events_with_rows = 0

    for i, event in enumerate(events, start=1):
        event_id = event["id"]
        matchup = f"{event.get('away_team')} @ {event.get('home_team')}"
        print(f"[event {i}/{len(events)}] {matchup} | {event_id}")

        try:
            payload, usage, url = fetch_event_odds(api_key, event_id, markets)
        except Exception as e:
            print(f"[warn] failed event_id={event_id}: {e}")
            continue

        if not args.no_raw:
            save_raw_json(snapshot_ts, event_id, payload)

        rows = normalize_event_odds(snapshot_ts, payload)

        if rows:
            append_rows(rows)
        else:
            print("  no rows returned — market likely unavailable for this event/book yet")

        if rows:
            events_with_rows += 1
            total_rows += len(rows)

        if rows:
            events_with_rows += 1
            total_rows += len(rows)

        print(
            f"  rows={len(rows)} "
            f"credits_last={usage['last']} used={usage['used']} remaining={usage['remaining']}"
        )

        time.sleep(SLEEP_SECONDS)

    print(f"[done] events_checked={len(events)} events_with_rows={events_with_rows} rows_appended={total_rows}")
    print(f"[output] {NORMALIZED_PATH}")


if __name__ == "__main__":
    main()