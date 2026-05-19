import os
import json
import requests

API_BASE = "https://api.the-odds-api.com/v4"

SPORT = "americanfootball_nfl"

EVENT_ID = "1a8f3d70399a5cad83c95196795ed77b"

SNAPSHOT_DATE = "2025-11-23T17:30:00Z"

BOOKMAKERS = "fanduel"
MARKETS = "player_pass_yds"

ODDS_FORMAT = "american"
DATE_FORMAT = "iso"


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

    return resp.json()


def main():
    api_key = get_api_key()

    url = (
        f"{API_BASE}/historical/sports/"
        f"{SPORT}/events/{EVENT_ID}/odds"
    )

    params = {
        "apiKey": api_key,
        "regions": "us",
        "bookmakers": BOOKMAKERS,
        "markets": MARKETS,
        "oddsFormat": ODDS_FORMAT,
        "dateFormat": DATE_FORMAT,
        "date": SNAPSHOT_DATE,
    }

    payload = request_json(url, params)

    print("\n===== FULL PAYLOAD =====\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()