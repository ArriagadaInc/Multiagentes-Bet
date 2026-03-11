
import os
import json
from dotenv import load_dotenv
load_dotenv()
from agents.insights_agent import insights_agent_node, TEAM_HISTORY_FILE
from agents.normalizer_agent import TeamNormalizer

def test_persistence():
    # 1. Mock web_agent_output.json
    web_output = {
        "generated_at": "2026-03-05T15:00:00",
        "data": {
            "competitions": [
                {
                    "competition": "CHI1",
                    "teams": [
                        {
                            "team": "Universidad de Chile",
                            "last_result": "Palestino 1-0 Universidad de Chile (Copa Libertadores, 04/03/2026)",
                            "context_signals": [
                                {"type": "motivation", "signal": "Baja anímica tras eliminación de Libertadores", "confidence": 0.9}
                            ],
                            "raw_context": "La U quedó fuera de la Libertadores ante Palestino. Golpe duro para el equipo de Álvarez."
                        }
                    ]
                }
            ]
        }
    }
    with open("web_agent_output.json", "w", encoding="utf-8") as f:
        json.dump(web_output, f, indent=2, ensure_ascii=False)

    # 2. Prepare mock state
    state = {
        "competitions": [{"competition": "CHI1"}],
        "insights_sources": {"CHI1": ["https://www.youtube.com/watch?v=NKIaZh20wXU"]}, # Example URL
        "odds_canonical": [
            {"competition": "CHI1", "home_team": "Everton", "away_team": "Universidad de Chile", "commence_time": "2026-03-08T20:00:00Z"}
        ],
        "insights": [],
        "meta": {"errors": {}}
    }

    # 3. Run insights_agent_node
    print("--- RUNNING INSIGHTS AGENT NODE ---")
    new_state = insights_agent_node(state)

    # 4. Check team_history.json
    print("\n--- CHECKING PERSISTENCE ---")
    if os.path.exists(TEAM_HISTORY_FILE):
        with open(TEAM_HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        
        u_history = history.get("Universidad de Chile", [])
        found_elimination = False
        for entry in u_history:
            if "Palestino 1-0" in entry.get("insight", "") or "Baja anímica" in entry.get("insight", ""):
                found_elimination = True
                print(f"✓ Found persisted insight: {entry['insight']}")
        
        if not found_elimination:
            print("✗ Elimination news not found in history")
    else:
        print("✗ team_history.json not found")

if __name__ == "__main__":
    test_persistence()
