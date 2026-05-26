import os
import csv
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests


API_BASE = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_nfl"
REGIONS = "us"
ODDS_FORMAT = "american"
DATE_FORMAT = "iso"

OUT_DIR = Path("data/historical_props")
RAW_DIR = OUT_DIR / "raw"
OUT_CSV = OUT_DIR / "historical_closing_props.csv"

DEFAULT_MARKETS = ["player_pass_yds"]
DEFAULT_BOOKMAKER = "fanduel"
SNAPSHOT_MINUTES_BEFORE_KICKOFF = 30
SLEEP_SECONDS = 0.35


def load_dotenv_value(name):
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return None

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")

    return None


def get_api_key():
    key = os.getenv("ODDS_API_KEY") or load_dotenv_value("ODDS_API_KEY")
    if not key:
        raise RuntimeError("Missing ODDS_API_KEY environment variable or .env entry.")
    return key.strip().strip('"').strip("'")


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


def parse_iso_z(dt_str):
    return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))


def iso_z(dt):
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def date_to_midday_utc(date_str):
    # Historical slate endpoint needs a snapshot timestamp.
    # Noon UTC is enough to discover the day’s events.
    return f"{date_str}T12:00:00Z"


def fetch_historical_slate(api_key, date_str, bookmaker):
    url = f"{API_BASE}/historical/sports/{SPORT}/odds"
    params = {
        "apiKey": api_key,
        "regions": REGIONS,
        "bookmakers": bookmaker,
        "markets": "h2h",
        "oddsFormat": ODDS_FORMAT,
        "dateFormat": DATE_FORMAT,
        "date": date_to_midday_utc(date_str),
    }
    return request_json(url, params)


def fetch_historical_event_props(api_key, event_id, snapshot_time, bookmaker, markets):
    url = f"{API_BASE}/historical/sports/{SPORT}/events/{event_id}/odds"
    params = {
        "apiKey": api_key,
        "regions": REGIONS,
        "bookmakers": bookmaker,
        "markets": ",".join(markets),
        "oddsFormat": ODDS_FORMAT,
        "dateFormat": DATE_FORMAT,
        "date": snapshot_time,
    }
    return request_json(url, params)


def save_raw_json(date_str, event_id, snapshot_time, payload):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    safe_ts = snapshot_time.replace(":", "").replace("-", "")
    path = RAW_DIR / f"{date_str}_{safe_ts}_{event_id}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path


def normalize_event_props(payload, requested_snapshot_time):
    data = payload.get("data") or {}

    event_id = data.get("id")
    sport_key = data.get("sport_key")
    commence_time = data.get("commence_time")
    home_team = data.get("home_team")
    away_team = data.get("away_team")

    actual_snapshot_time = payload.get("timestamp")
    previous_timestamp = payload.get("previous_timestamp")
    next_timestamp = payload.get("next_timestamp")

    # Collect outcomes keyed by player/market/line so Over and Under become one row.
    grouped = {}

    for book in data.get("bookmakers", []):
        bookmaker_key = book.get("key")
        bookmaker_title = book.get("title")
        bookmaker_last_update = book.get("last_update")

        for market in book.get("markets", []):
            market_key = market.get("key")
            market_last_update = market.get("last_update")

            for outcome in market.get("outcomes", []):
                player = outcome.get("description")
                side = outcome.get("name")
                line = outcome.get("point")
                price = outcome.get("price")

                if not player or side not in {"Over", "Under"}:
                    continue

                key = (
                    event_id,
                    bookmaker_key,
                    market_key,
                    player,
                    line,
                )

                if key not in grouped:
                    grouped[key] = {
                        "requested_snapshot_time": requested_snapshot_time,
                        "actual_snapshot_time": actual_snapshot_time,
                        "previous_timestamp": previous_timestamp,
                        "next_timestamp": next_timestamp,
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
                        "player": player,
                        "line": line,
                        "over_price": None,
                        "under_price": None,
                    }

                if side == "Over":
                    grouped[key]["over_price"] = price
                elif side == "Under":
                    grouped[key]["under_price"] = price

    return list(grouped.values())


def append_rows(rows):
    if not rows:
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "requested_snapshot_time",
        "actual_snapshot_time",
        "previous_timestamp",
        "next_timestamp",
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
        "line",
        "over_price",
        "under_price",
    ]

    new_rows_df = pd.DataFrame(rows)

    if OUT_CSV.exists():
        existing = pd.read_csv(OUT_CSV)
        combined = pd.concat([existing, new_rows_df], ignore_index=True)
    else:
        combined = new_rows_df

    combined = combined.drop_duplicates(
        subset=[
            "actual_snapshot_time",
            "event_id",
            "market_key",
            "player",
            "line",
            "over_price",
            "under_price",
        ],
        keep="last",
    )

    combined.to_csv(OUT_CSV, index=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Game date, YYYY-MM-DD")
    parser.add_argument("--bookmaker", default=DEFAULT_BOOKMAKER)
    parser.add_argument("--markets", default=",".join(DEFAULT_MARKETS))
    parser.add_argument("--max-events", type=int, default=None)
    parser.add_argument("--minutes-before", type=int, default=SNAPSHOT_MINUTES_BEFORE_KICKOFF)
    parser.add_argument("--no-raw", action="store_true")
    args = parser.parse_args()

    api_key = get_api_key()
    markets = [m.strip() for m in args.markets.split(",") if m.strip()]

    print(f"[start] date={args.date}")
    print(f"[config] bookmaker={args.bookmaker} markets={markets} minutes_before={args.minutes_before}")

    slate_payload, usage, slate_url = fetch_historical_slate(api_key, args.date, args.bookmaker)
    events = slate_payload.get("data", [])

    print(
        f"[slate] events_returned={len(events)} "
        f"snapshot={slate_payload.get('timestamp')} "
        f"credits_last={usage['last']} used={usage['used']} remaining={usage['remaining']}"
    )

    # Keep only events that start on the requested UTC date or nearby.
    # For NFL Sundays, this is fine. Later we can add season/week metadata.
    events = sorted(events, key=lambda e: e.get("commence_time") or "")

    if args.max_events:
        events = events[:args.max_events]
        print(f"[test mode] max_events={args.max_events}")

    total_rows = 0
    events_with_rows = 0

    for i, event in enumerate(events, start=1):
        event_id = event.get("id")
        commence_time = event.get("commence_time")
        away_team = event.get("away_team")
        home_team = event.get("home_team")

        if not event_id or not commence_time:
            continue

        kickoff_dt = parse_iso_z(commence_time)
        snapshot_dt = kickoff_dt - timedelta(minutes=args.minutes_before)
        snapshot_time = iso_z(snapshot_dt)

        print(f"[event {i}/{len(events)}] {away_team} @ {home_team}")
        print(f"  kickoff={commence_time} snapshot={snapshot_time} event_id={event_id}")

        try:
            props_payload, usage, url = fetch_historical_event_props(
                api_key=api_key,
                event_id=event_id,
                snapshot_time=snapshot_time,
                bookmaker=args.bookmaker,
                markets=markets,
            )
        except Exception as e:
            print(f"  [warn] failed: {e}")
            continue

        if not args.no_raw:
            save_raw_json(args.date, event_id, snapshot_time, props_payload)

        rows = normalize_event_props(props_payload, snapshot_time)

        if rows:
            append_rows(rows)
            events_with_rows += 1
            total_rows += len(rows)
            print(
                f"  rows={len(rows)} "
                f"actual_snapshot={props_payload.get('timestamp')} "
                f"credits_last={usage['last']} used={usage['used']} remaining={usage['remaining']}"
            )
        else:
            print(
                f"  no rows returned "
                f"actual_snapshot={props_payload.get('timestamp')} "
                f"credits_last={usage['last']} used={usage['used']} remaining={usage['remaining']}"
            )

        time.sleep(SLEEP_SECONDS)

    print(f"[done] events_checked={len(events)} events_with_rows={events_with_rows} rows_appended={total_rows}")
    print(f"[output] {OUT_CSV}")


if __name__ == "__main__":
    main()
