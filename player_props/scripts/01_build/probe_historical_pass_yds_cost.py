from dotenv import load_dotenv
import os
import requests
import json
from pathlib import Path


load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY")
if not API_KEY:
    raise RuntimeError("ODDS_API_KEY not found in .env")


EVENT_ID = "7a5e353202d40a844491fa5753bc3097"

url = (
    f"https://api.the-odds-api.com/v4/historical/"
    f"sports/americanfootball_nfl/events/{EVENT_ID}/odds"
)

params = {
    "apiKey": API_KEY,
    "regions": "us",
    "markets": "player_pass_yds",
    "bookmakers": "fanduel",
    "date": "2024-09-08T16:00:00Z",
}

r = requests.get(url, params=params, timeout=30)

print("STATUS:", r.status_code)
print("remaining:", r.headers.get("x-requests-remaining"))
print("used:", r.headers.get("x-requests-used"))
print("last cost:", r.headers.get("x-requests-last"))

print("\nTEXT:")
print(r.text[:3000])

out = Path("data/raw/odds_api/probe_pass_yds_event.json")
out.parent.mkdir(parents=True, exist_ok=True)

if r.status_code == 200:
    out.write_text(json.dumps(r.json(), indent=2), encoding="utf-8")
    print(f"\n[save] {out}")