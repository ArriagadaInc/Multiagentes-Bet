
import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY")
REGION = "eu"
MARKET = "h2h"
# URL = f"https://api.the-odds-api.com/v4/sports/soccer_uefa_champs_league/odds?apiKey={API_KEY}&regions={REGION}&markets={MARKET}"
# Usaremos la URL base definida en odds_agent.py o directo a la API oficial si la variable de entorno apunta allí.
# Asumimos que ODDS_BASE_URL es la oficial o un proxy transparente.

BASE_URL = os.getenv("ODDS_BASE_URL", "https://api.the-odds-api.com")
URL = f"{BASE_URL}/v4/sports/soccer_uefa_champs_league/odds"

params = {
    "apiKey": API_KEY,
    "regions": REGION,
    "markets": MARKET
}

print(f"Fetching from {URL}...")

try:
    resp = requests.get(URL, params=params)
    resp.raise_for_status()
    data = resp.json()
    
    print(f"✅ Response received. Events: {len(data)}")
    
    # Dump a file for inspection
    with open("raw_odds_response.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        
    # Print Inter match details
    targets = ["Inter", "Real Madrid", "Paris Saint-Germain"]
    
    for event in data:
        h = event.get("home_team", "")
        a = event.get("away_team", "")
        
        match_found = False
        for t in targets:
            if t in h or t in a:
                match_found = True
                break
        
        if match_found:
            print(f"\n⚽ EVENTO: {h} vs {a}")
            if event.get("bookmakers"):
                bk = event["bookmakers"][0]
                print(f"   Bookmaker: {bk.get('title')}")
                for mkt in bk.get("markets", []):
                    if mkt["key"] == "h2h":
                        print("   Outcomes (Orden Real):")
                        for i, out in enumerate(mkt.get("outcomes", [])):
                            print(f"     [{i}] Name: '{out.get('name')}' | Price: {out.get('price')}")
                            
except Exception as e:
    print(f"Error: {e}")
