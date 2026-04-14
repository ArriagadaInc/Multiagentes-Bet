import json
import os

PREDICTIONS_FILE = r"c:\desarrollos\apuestas\Futbol\predictions\predictions_history.json"

def analyze_temuco():
    if not os.path.exists(PREDICTIONS_FILE):
        print("File not found")
        return

    with open(PREDICTIONS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    temuco_matches = [p for p in data if "Temuco" in str(p.values())]
    
    print(f"Total Temuco matches in history: {len(temuco_matches)}")
    print("-" * 50)
    for p in temuco_matches[:10]:
        print(f"Match: {p.get('home_team')} vs {p.get('away_team')}")
        print(f"  Competition: {p.get('competition')}")
        print(f"  Date: {p.get('match_date')} | Generated: {p.get('generated_at')}")
        print(f"  Status: {p.get('evaluation_status')}")
        print(f"  ID: {p.get('prediction_id')}")
        print("-" * 30)

if __name__ == "__main__":
    analyze_temuco()
