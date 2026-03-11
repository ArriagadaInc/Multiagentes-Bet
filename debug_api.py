"""Debug - Inspeccionar respuesta bruta de The Odds API"""

import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("ODDS_API_KEY")
url = "https://api.the-odds-api.com/v4/sports/soccer_uefa_champs_league/odds"
params = {
    "apiKey": api_key,
    "markets": "h2h",
    "regions": "eu",
    "oddsFormat": "decimal"
}

print("Llamando API...")
response = requests.get(url, params=params, timeout=20)

print(f"Status: {response.status_code}")
print(f"\nRaw response (primeros 2000 caracteres):")
print(response.text[:2000])

print(f"\n\nJSON parsed:")
data = response.json()
print(f"Tipo: {type(data)}")
print(f"Keys: {data.keys() if isinstance(data, dict) else 'N/A (es lista)'}")

if isinstance(data, dict):
    print(f"\nDatos en 'results':")
    results = data.get("results", [])
    print(f"  Tipo: {type(results)}")
    print(f"  Len: {len(results)}")
    if results:
        print(f"  Primer evento: {json.dumps(results[0], indent=2)[:500]}")
