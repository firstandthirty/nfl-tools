import requests

API_KEY = "e0fcd42624227ac3aa5b45b7f4a74a77"

BASE_URL = "https://api.the-odds-api.com/v4/sports/baseball_mlb"

def test_events():
    print("\n=== TEST 1: Fetch MLB Events ===")
    url = f"{BASE_URL}/events"
    params = {"apiKey": API_KEY}

    r = requests.get(url, params=params)

    print("Status:", r.status_code)
    print("Remaining:", r.headers.get("x-requests-remaining"))
    print("Used:", r.headers.get("x-requests-used"))

    if r.status_code != 200:
        print("Error response:", r.text)
        return None

    data = r.json()
    print(f"Events returned: {len(data)}")

    if not data:
        print("No events found (could be off day)")
        return None

    first_event = data[0]
    print("Sample event:")
    print(f"  {first_event['away_team']} @ {first_event['home_team']}")
    print(f"  ID: {first_event['id']}")

    return first_event["id"]


def test_event_props(event_id):
    print("\n=== TEST 2: Fetch Props for ONE Game ===")

    url = f"{BASE_URL}/events/{event_id}/odds"

    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": "batter_hits",
        "bookmakers": "fanduel",  # keep it light
    }

    r = requests.get(url, params=params)

    print("Status:", r.status_code)
    print("Remaining:", r.headers.get("x-requests-remaining"))
    print("Used:", r.headers.get("x-requests-used"))

    if r.status_code != 200:
        print("Error response:", r.text)
        return

    data = r.json()

    bookmakers = data.get("bookmakers", [])
    print(f"Bookmakers returned: {len(bookmakers)}")

    if not bookmakers:
        print("⚠️ No bookmakers / no props returned")
        return

    markets = bookmakers[0].get("markets", [])
    print(f"Markets in first book: {len(markets)}")

    if markets:
        print("Sample market key:", markets[0]["key"])


def main():
    event_id = test_events()

    if event_id:
        test_event_props(event_id)


if __name__ == "__main__":
    main()