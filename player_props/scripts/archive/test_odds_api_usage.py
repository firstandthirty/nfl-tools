from dotenv import load_dotenv
import os
import requests

load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY")

if not API_KEY:
    raise RuntimeError("ODDS_API_KEY not found in .env")

url = "https://api.the-odds-api.com/v4/sports"

params = {
    "apiKey": API_KEY,
}

r = requests.get(url, params=params, timeout=30)

print("status:", r.status_code)
print("remaining:", r.headers.get("x-requests-remaining"))
print("used:", r.headers.get("x-requests-used"))
print("last cost:", r.headers.get("x-requests-last"))
print("text:", r.text[:500])