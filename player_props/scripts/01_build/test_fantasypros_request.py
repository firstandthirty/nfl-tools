from dotenv import load_dotenv
import os
import requests

load_dotenv()

API_KEY = os.getenv("FANTASYPROS_API_KEY")

headers = {"x-api-key": API_KEY}

urls = [
    "https://api.fantasypros.com/v2/json/nfl/news",
    "https://api.fantasypros.com/v2/json/nfl/players",
    "https://api.fantasypros.com/v2/json/nfl/2025/projections",
]

for url in urls:
    print("\n" + "=" * 80)
    print(url)
    r = requests.get(url, headers=headers, timeout=30)
    print(r.status_code)
    print(r.text[:1000])