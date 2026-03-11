
import os
import json
from dotenv import load_dotenv
load_dotenv()
from agents.web_agent import _build_tournament_prompt, _make_client, _call_web_search

def test_u_de_chile():
    client = _make_client()
    if not client:
        print("No OpenAI client")
        return

    teams = ["Universidad de Chile"]
    fixtures = [
        {"home_team": "Everton", "away_team": "Universidad de Chile", "commence_time": "2026-03-08T20:00:00Z"}
    ]
    
    prompt = _build_tournament_prompt("CHI1", teams, fixtures)
    print("--- PROMPT ---")
    print(prompt)
    
    result = _call_web_search(client, prompt, "CHI1")
    
    print("\n--- RESULT (check tmp/diag_res.json) ---")
    with open("tmp/diag_res.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    test_u_de_chile()
