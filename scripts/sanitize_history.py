import json
import os
import re
from datetime import datetime, timedelta

TEAM_HISTORY_FILE = os.path.join("data", "knowledge", "team_history.json")

def sanitize():
    if not os.path.exists(TEAM_HISTORY_FILE):
        print(f"File not found: {TEAM_HISTORY_FILE}")
        return

    with open(TEAM_HISTORY_FILE, "r", encoding="utf-8") as f:
        history = json.load(f)

    cleaned_count = 0
    total_removed = 0
    today = datetime.now()
    six_months_ago = today - timedelta(days=180)

    # 1. Muslera de Liverpool
    # 2. Aubameyang/Emery de Arsenal (muy antiguos)
    # 3. Datos demasiado viejos (> 6 meses)
    
    new_history = {}
    for team, entries in history.items():
        new_entries = []
        for entry in entries:
            insight = entry.get("insight", "").lower()
            date_str = entry.get("date", "")
            
            # Criterio de eliminación: Muslera fuera de Galatasaray
            if "muslera" in insight and team != "galatasaray":
                total_removed += 1
                continue
                
            # Criterio de eliminación: Aubameyang/Emery en Arsenal
            if team == "arsenal" and ("aubameyang" in insight or "emery" in insight):
                total_removed += 1
                continue

            # Criterio de eliminación: Alucinación Rangers/Magallanes 2026 (Liderato falso)
            if "16 pts" in insight or "16 puntos" in insight or "15 puntos" in insight or "15 pts" in insight:
                if team in ["rangers", "magallanes"]:
                    total_removed += 1
                    continue
            
            if "puntaje ideal" in insight and team == "rangers":
                total_removed += 1
                continue
            
            # Criterio de fecha
            if date_str:
                try:
                    entry_date = datetime.strptime(date_str[:10], "%Y-%m-%d")
                    if entry_date < six_months_ago:
                        total_removed += 1
                        continue
                except:
                    pass
            
            new_entries.append(entry)
        
        if new_entries:
            new_history[team] = new_entries
            cleaned_count += 1

    with open(TEAM_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(new_history, f, indent=2, ensure_ascii=False)

    print(f"Sanitization complete.")
    print(f"Teams processed: {len(history)}")
    print(f"Total entries removed: {total_removed}")
    print(f"Teams remaining in history: {len(new_history)}")

if __name__ == "__main__":
    sanitize()
