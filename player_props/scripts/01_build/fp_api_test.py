from dotenv import load_dotenv
import os
import requests
import json

load_dotenv()

API_KEY = os.getenv("FANTASYPROS_API_KEY")
headers = {"x-api-key": API_KEY}

base = "https://api.fantasypros.com/public/v2/json/nfl/2025/projections"

tests = [
    {"week": 1, "position": "WR"},
    {"week": 1, "positions": "WR"},
    {"week": 1, "position": "TE"},
    {"week": 1, "positions": "TE"},
]

for params in tests:
    print("\n" + "=" * 100)
    print("PARAMS:", params)
    r = requests.get(base, headers=headers, params=params, timeout=30)
    print("URL:", r.url)
    print("STATUS:", r.status_code)
    print(r.text[:1500])

    try:
        data = r.json()
        print("keys:", data.keys() if isinstance(data, dict) else type(data))
        if isinstance(data, dict):
            print("season:", data.get("season"), "week:", data.get("week"), "count:", data.get("count"), "positions:", data.get("positions"), "scoring:", data.get("scoring"))
            players = data.get("players") or []
            if players:
                p = players[0]
                print("sample player keys:", p.keys())
                print("sample player:", json.dumps(p, indent=2)[:1500])
    except Exception as e:
        print("JSON parse error:", e)