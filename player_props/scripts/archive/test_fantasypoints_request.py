from dotenv import load_dotenv
import os
import requests


load_dotenv()

API_KEY = os.getenv("FANTASYPROS_API_KEY")

headers = {
    "x-api-key": API_KEY
}

url = "https://api.fantasypros.com/v2/json/nfl/2025/consensus-rankings/qb"

print(f"[request] {url}")

response = requests.get(
    url,
    headers=headers,
    timeout=30
)

print("\nSTATUS:")
print(response.status_code)

print("\nTEXT:")
print(response.text[:3000])