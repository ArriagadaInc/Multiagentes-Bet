
import os
import json
from dotenv import load_dotenv
load_dotenv()
from agents.analyst_web_check import run_analyst_web_check

def test_u_de_chile_elimination():
    request = {
        "match_id": "TEST_U_EVERTON",
        "competition": "CHI1",
        "home_team": "Everton",
        "away_team": "Universidad de Chile",
        "trigger_reason": "check_recent_libertadores_result",
        "questions": [
            "¿Qué pasó ayer en el partido entre Universidad de Chile y Palestino por Copa Libertadores?",
            "¿Cómo afecta este resultado el ánimo o las bajas de la U de Chile para su próximo partido?"
        ],
        "lookback_days": 2
    }
    
    print("--- RUNNING ANALYST WEB CHECK ---")
    result = run_analyst_web_check(request)
    
    print("\n--- RESULT (check tmp/analyst_check_res.json) ---")
    with open("tmp/analyst_check_res.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    test_u_de_chile_elimination()
