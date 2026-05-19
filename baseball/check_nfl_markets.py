import os
import requests

API_KEY = "e0fcd42624227ac3aa5b45b7f4a74a77"

url = "https://api.the-odds-api.com/v4/sports/"
params = {
    "apiKey": API_KEY,
    "all": "true",
}

r = requests.get(url, params=params, timeout=20)

print("Status:", r.status_code)
print("Remaining:", r.headers.get("x-requests-remaining"))
print("Used:", r.headers.get("x-requests-used"))

sports = r.json()

print("\n=== ALL AMERICAN FOOTBALL / NFL SPORT KEYS ===")
for s in sports:
    blob = f"{s.get('key','')} {s.get('title','')} {s.get('description','')}".lower()

    if "nfl" in blob or "americanfootball" in blob:
        print(
            f"{s.get('key')} | "
            f"title={s.get('title')} | "
            f"active={s.get('active')} | "
            f"has_outrights={s.get('has_outrights')} | "
            f"description={s.get('description')}"
        )