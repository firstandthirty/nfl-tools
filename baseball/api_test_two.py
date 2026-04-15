import requests
import json
from pprint import pprint

API_KEY = "e0fcd42624227ac3aa5b45b7f4a74a77"
SPORT = "baseball_mlb"
BASE = f"https://api.the-odds-api.com/v4/sports/{SPORT}"

def show_headers(r):
    print("Status:", r.status_code)
    print("x-requests-remaining:", r.headers.get("x-requests-remaining"))
    print("x-requests-used:", r.headers.get("x-requests-used"))
    print("x-requests-last:", r.headers.get("x-requests-last"))
    print()

def get_events():
    print("=== EVENTS ===")
    r = requests.get(f"{BASE}/events", params={"apiKey": API_KEY})
    show_headers(r)

    if r.status_code != 200:
        print(r.text)
        return []

    events = r.json()
    print(f"Events returned: {len(events)}")
    for e in events[:3]:
        print(f"- {e['away_team']} @ {e['home_team']} | {e['id']}")
    print()
    return events

def test_event_market(event_id, markets, bookmakers=None):
    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": markets,
    }
    if bookmakers:
        params["bookmakers"] = bookmakers

    print(f"=== EVENT ODDS TEST | markets={markets} | bookmakers={bookmakers or 'default'} ===")
    url = f"{BASE}/events/{event_id}/odds"
    r = requests.get(url, params=params)
    show_headers(r)

    if r.status_code != 200:
        print(r.text)
        print()
        return

    data = r.json()
    books = data.get("bookmakers", [])
    print("Bookmakers returned:", len(books))

    if not books:
        print("No bookmakers returned.")
        print()
        return

    for book in books[:3]:
        print(f"Book: {book.get('title')} ({book.get('key')})")
        markets_list = book.get("markets", [])
        print("  markets count:", len(markets_list))
        for m in markets_list[:3]:
            print("  -", m.get("key"), "| outcomes:", len(m.get("outcomes", [])))
    print()

def main():
    events = get_events()
    if not events:
        return

    event_id = events[0]["id"]

    # Cheap sanity check: does a common market still return data?
    test_event_market(event_id, markets="h2h", bookmakers="fanduel")

    # Your target market, same book
    test_event_market(event_id, markets="batter_hits", bookmakers="fanduel")

    # Same target market, alternate books
    test_event_market(event_id, markets="batter_hits", bookmakers="draftkings")
    test_event_market(event_id, markets="batter_hits", bookmakers="betmgm")

    # Optional: test multiple books at once
    test_event_market(event_id, markets="batter_hits", bookmakers="fanduel,draftkings,betmgm")

if __name__ == "__main__":
    main()