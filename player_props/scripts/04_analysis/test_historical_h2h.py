import os
import json
import requests
from datetime import datetime, timezone

API_BASE = "https://api.the-odds-api.com/v4"

SPORT = "americanfootball_nfl"
BOOKMAKERS = "fanduel"
REGIONS = "us"
MARKETS = "h2h"
ODDS_FORMAT = "american"
DATE_FORMAT = "iso"

# CIN @ NE, Sunday 11/23/2025, 1:00 PM ET
# 1:00 PM ET = 18:00 UTC in November
# Use 30 minutes before kickoff as the first test.
SNAPSHOT_DATE = "2025-11-23T17:30:00Z"

TARGET_TEAMS = {"Cincinnati Bengals", "New England Patriots"}


def get_api_key():
    key = os.getenv("ODDS_API_KEY")
    if not key:
        raise RuntimeError("Missing ODDS_API_KEY environment variable.")
    return key.strip().strip('"').strip("'")


def request_json(url, params):
    resp = requests.get(url, params=params, timeout=30)

    usage = {
        "remaining": resp.headers.get("x-requests-remaining"),
        "used": resp.headers.get("x-requests-used"),
        "last": resp.headers.get("x-requests-last"),
    }

    print(f"[status] {resp.status_code}")
    print(f"[usage] last={usage['last']} used={usage['used']} remaining={usage['remaining']}")
    print(f"[url] {resp.url}")

    if resp.status_code != 200:
        raise RuntimeError(f"API error {resp.status_code}: {resp.text}")

    return resp.json(), usage


def main():
    api_key = get_api_key()

    url = f"{API_BASE}/historical/sports/{SPORT}/odds"
    params = {
        "apiKey": api_key,
        "regions": REGIONS,
        "bookmakers": BOOKMAKERS,
        "markets": MARKETS,
        "oddsFormat": ODDS_FORMAT,
        "dateFormat": DATE_FORMAT,
        "date": SNAPSHOT_DATE,
    }

    payload, usage = request_json(url, params)

    print("\n[snapshot metadata]")
    print(f"timestamp: {payload.get('timestamp')}")
    print(f"previous_timestamp: {payload.get('previous_timestamp')}")
    print(f"next_timestamp: {payload.get('next_timestamp')}")

    events = payload.get("data", [])
    print(f"\n[events returned] {len(events)}")

    matches = []
    for event in events:
        teams = {event.get("home_team"), event.get("away_team")}
        if teams == TARGET_TEAMS:
            matches.append(event)

    print(f"[target matches] {len(matches)}")

    if not matches:
        print("\nNo CIN/NE match found in this snapshot.")
        print("Closest useful debug sample:")
        for event in events[:10]:
            print(f"- {event.get('away_team')} @ {event.get('home_team')} | {event.get('commence_time')} | {event.get('id')}")
        return

    event = matches[0]
    print("\n[target event]")
    print(f"{event.get('away_team')} @ {event.get('home_team')}")
    print(f"commence_time: {event.get('commence_time')}")
    print(f"event_id: {event.get('id')}")

    print("\n[bookmakers/markets]")
    print(json.dumps(event.get("bookmakers", []), indent=2))


if __name__ == "__main__":
    main()