from pathlib import Path
import os
import json
import time
from datetime import datetime, timedelta, timezone

import requests
import pandas as pd
from dotenv import load_dotenv


load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY")
if not API_KEY:
    raise RuntimeError("ODDS_API_KEY not found in .env")

SPORT = "americanfootball_nfl"
BOOKMAKER = "fanduel"
MARKET = "player_pass_yds"

SEASONS = [2023, 2024, 2025]

RAW_DIR = Path("data/raw/odds_api/fanduel_pass_yds")
OUT_FILE = Path("data/processed/fanduel_pass_yds_history.csv")

REQUEST_SLEEP = 1.05


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def season_date_range(season):
    # Broad NFL regular season windows
    return {
        2023: ("2023-09-07", "2024-01-08"),
        2024: ("2024-09-05", "2025-01-06"),
        2025: ("2025-09-04", "2026-01-05"),
    }[season]


def daterange(start_date, end_date):
    start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def get_json(url, params, raw_file):
    if raw_file.exists():
        return json.loads(raw_file.read_text(encoding="utf-8")), True

    r = requests.get(url, params=params, timeout=30)

    print(
        f"[status] {r.status_code} "
        f"remaining={r.headers.get('x-requests-remaining')} "
        f"used={r.headers.get('x-requests-used')} "
        f"cost={r.headers.get('x-requests-last')}"
    )

    if r.status_code != 200:
        print(r.text[:1000])
        r.raise_for_status()

    data = r.json()
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    time.sleep(REQUEST_SLEEP)
    return data, False


def fetch_events_for_date(day):
    date_str = iso(day + timedelta(hours=12))

    url = f"https://api.the-odds-api.com/v4/historical/sports/{SPORT}/events"
    params = {
        "apiKey": API_KEY,
        "date": date_str,
    }

    raw_file = RAW_DIR / "events" / f"events_{day.date()}.json"

    print(f"[events] {day.date()}")

    data, cached = get_json(url, params, raw_file)

    events = data.get("data", data)
    if not isinstance(events, list):
        return []

    # Keep events commencing on this UTC date or nearby.
    return events


def fetch_event_odds(event):
    event_id = event["id"]
    commence_time = datetime.fromisoformat(
        event["commence_time"].replace("Z", "+00:00")
    )

    snapshot_time = commence_time - timedelta(minutes=90)

    url = (
        f"https://api.the-odds-api.com/v4/historical/"
        f"sports/{SPORT}/events/{event_id}/odds"
    )

    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": MARKET,
        "bookmakers": BOOKMAKER,
        "date": iso(snapshot_time),
    }

    raw_file = RAW_DIR / "event_odds" / f"{event_id}_{iso(snapshot_time).replace(':', '')}.json"

    print(
        f"[odds] {event.get('away_team')} @ {event.get('home_team')} "
        f"kickoff={event['commence_time']} snapshot={iso(snapshot_time)}"
    )

    data, cached = get_json(url, params, raw_file)
    return data


def flatten_event_odds(payload):
    rows = []

    timestamp = payload.get("timestamp")
    previous_timestamp = payload.get("previous_timestamp")
    next_timestamp = payload.get("next_timestamp")

    event = payload.get("data", {})

    base = {
        "requested_snapshot_time": timestamp,
        "previous_timestamp": previous_timestamp,
        "next_timestamp": next_timestamp,
        "event_id": event.get("id"),
        "sport_key": event.get("sport_key"),
        "commence_time": event.get("commence_time"),
        "home_team": event.get("home_team"),
        "away_team": event.get("away_team"),
    }

    for book in event.get("bookmakers", []):
        for market in book.get("markets", []):
            if market.get("key") != MARKET:
                continue

            grouped = {}

            for outcome in market.get("outcomes", []):
                player = outcome.get("description")
                side = outcome.get("name")
                point = outcome.get("point")
                price = outcome.get("price")

                if not player or side not in {"Over", "Under"}:
                    continue

                key = (player, point)
                grouped.setdefault(key, {
                    **base,
                    "bookmaker_key": book.get("key"),
                    "bookmaker_title": book.get("title"),
                    "bookmaker_last_update": book.get("last_update"),
                    "market_key": market.get("key"),
                    "market_last_update": market.get("last_update"),
                    "player": player,
                    "line": point,
                    "over_price": None,
                    "under_price": None,
                })

                if side == "Over":
                    grouped[key]["over_price"] = price
                elif side == "Under":
                    grouped[key]["under_price"] = price

            rows.extend(grouped.values())

    return rows


def main():
    all_events = []
    seen_event_ids = set()

    for season in SEASONS:
        start, end = season_date_range(season)

        print(f"\n===== FETCH EVENTS season={season} =====")

        for day in daterange(start, end):
            events = fetch_events_for_date(day)

            for event in events:
                if event.get("id") in seen_event_ids:
                    continue

                seen_event_ids.add(event.get("id"))
                event["season"] = season
                all_events.append(event)

    print(f"\n[event count] {len(all_events):,}")

    all_rows = []

    print("\n===== FETCH ODDS =====")

    for i, event in enumerate(all_events, start=1):
        print(f"\n[{i}/{len(all_events)}]")

        try:
            payload = fetch_event_odds(event)
            rows = flatten_event_odds(payload)

            for row in rows:
                row["season_guess"] = event.get("season")

            print(f"[flatten] rows={len(rows)}")
            all_rows.extend(rows)

        except Exception as e:
            print(f"[error] event_id={event.get('id')} error={e}")

    if not all_rows:
        raise RuntimeError("No rows collected.")

    df = pd.DataFrame(all_rows)

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_FILE, index=False)

    print("\n===== BACKFILL COMPLETE =====")
    print(f"events: {len(all_events):,}")
    print(f"rows: {len(df):,}")
    print(f"output: {OUT_FILE}")

    print("\nRows by season_guess:")
    print(df.groupby("season_guess").size())

    print("\nSample:")
    print(df.head(20).to_string(index=False))


if __name__ == "__main__":
    main()