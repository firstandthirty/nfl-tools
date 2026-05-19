from dotenv import load_dotenv
import os

load_dotenv()

api_key = os.getenv("FANTASYPROS_API_KEY")

print("API KEY FOUND:")
print(api_key[:6] + "...")