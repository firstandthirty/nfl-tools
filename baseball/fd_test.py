import os
import json
import requests

API_KEY = "e0fcd42624227ac3aa5b45b7f4a74a77"

SPORT = "baseball_mlb"
BOOKMAKER = "fanduel"
MARKET = "batter_hits_alternate"
REGIONS = "us"
ODDS_FORMAT = "american"


def get_events():
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/events"
    params = {"apiKey": API_KEY}

    r = requests.get(url, params=params, timeout=30)

    print("\n=== EVENTS REQUEST ===")
    print("Status:", r.status_code)
    print("x-requests-remaining:", r.headers.get("x-requests-remaining"))
    print("x-requests-used:", r.headers.get("x-requests-used"))
    print("x-requests-last:", r.headers.get("x-requests-last"))

    if r.status_code != 200:
        print(r.text[:2000])
        return []

    return r.json()


def get_event_alt_hits(event_id):
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/events/{event_id}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": REGIONS,
        "bookmakers": BOOKMAKER,
        "markets": MARKET,
        "oddsFormat": ODDS_FORMAT,
    }

    r = requests.get(url, params=params, timeout=30)

    print("\n=== EVENT ODDS REQUEST ===")
    print("Event ID:", event_id)
    print("Status:", r.status_code)
    print("x-requests-remaining:", r.headers.get("x-requests-remaining"))
    print("x-requests-used:", r.headers.get("x-requests-used"))
    print("x-requests-last:", r.headers.get("x-requests-last"))

    if r.status_code != 200:
        print(r.text[:2000])
        return None

    return r.json()


def summarize_event(data):
    if not data:
        return

    print("\n=== EVENT SUMMARY ===")
    print("Home:", data.get("home_team"))
    print("Away:", data.get("away_team"))
    print("Commence:", data.get("commence_time"))

    bookmakers = data.get("bookmakers", [])
    print("Bookmakers returned:", len(bookmakers))

    for book in bookmakers:
        print("\nBook:", book.get("title"), f"({book.get('key')})")

        markets = book.get("markets", [])
        print("Markets returned:", len(markets))

        for market in markets:
            print("Market key:", market.get("key"))
            outcomes = market.get("outcomes", [])
            print("Outcomes returned:", len(outcomes))

            points = {}
            sample = []

            for o in outcomes:
                point = o.get("point")
                points[point] = points.get(point, 0) + 1

                if len(sample) < 25:
                    sample.append({
                        "name": o.get("name"),
                        "description": o.get("description"),
                        "point": o.get("point"),
                        "price": o.get("price"),
                    })

            print("Point distribution:")
            for point, count in sorted(points.items(), key=lambda x: str(x[0])):
                print(f"  {point}: {count}")

            print("\nSample outcomes:")
            for o in sample:
                print(
                    f"  name={o['name']!r}, "
                    f"description={o['description']!r}, "
                    f"point={o['point']!r}, "
                    f"price={o['price']!r}"
                )


def main():
    events = get_events()
    print(f"\nEvents returned: {len(events)}")

    if not events:
        return

    # Try the first few events in case FD has props for some games but not others.
    for i, event in enumerate(events[:5], start=1):
        print("\n" + "=" * 80)
        print(
            f"Checking event {i}: "
            f"{event.get('away_team')} at {event.get('home_team')} "
            f"| {event.get('commence_time')}"
        )

        data = get_event_alt_hits(event["id"])
        summarize_event(data)


if __name__ == "__main__":
    main()