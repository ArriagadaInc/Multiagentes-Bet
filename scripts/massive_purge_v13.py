import json
import os
import re
from datetime import datetime, timedelta

def massive_purge():
    history_file = "c:/desarrollos/apuestas/Futbol/data/knowledge/team_history.json"
    if not os.path.exists(history_file):
        print("History file not found.")
        return

    with open(history_file, 'r', encoding='utf-8') as f:
        history = json.load(f)

    # Keywords that indicate hallucinations or old data
    BLACK_LIST_KEYWORDS = [
        "Fortaleza", "San Lorenzo", "Gremio", "The Strongest", "São Paulo", # Old international rivals
        "Arrué", "Francisco Meneghini", "Pellegrino", "Paiva", # Old coaches
        "Holgado", "Zampedri (récord histórico)", # If mentioned as 'almost reached' in 2023 context
        "Concepción", "Arturo Fernández Vial", # Teams from other divisions/years
        "Huachipato 3-0", "femenino", "femenina", # Content mismatch
    ]
    
    # Compile regex for efficiency
    pattern = re.compile("|".join(BLACK_LIST_KEYWORDS), re.IGNORECASE)
    
    # TTL: 21 days
    today = datetime.now()
    ttl_limit = today - timedelta(days=21)
    
    purged_count = 0
    expired_count = 0
    
    new_history = {}
    for team, entries in history.items():
        if not isinstance(entries, list):
            new_history[team] = entries
            continue
            
        clean_entries = []
        for entry in entries:
            text = str(entry.get("insight", "")) + " " + str(entry.get("signal", ""))
            entry_date_str = entry.get("date", "2026-01-01")
            
            try:
                entry_date = datetime.strptime(entry_date_str, "%Y-%m-%d")
            except:
                entry_date = datetime(2026, 1, 1)

            # Rule 1: Keyword Purge
            if pattern.search(text):
                print(f"  [PURGE] {team}: {text[:60]}...")
                purged_count += 1
                continue
            
            # Rule 2: TTL Expiration (only for insights/signals, keep stable info if needed)
            # Actually, for this system, most insights should expire.
            if entry_date < ttl_limit:
                # Keep only if it's a very recent result? No, 21 days is enough for 'form'.
                # print(f"  [EXPIRE] {team}: {entry_date_str}")
                expired_count += 1
                continue
                
            clean_entries.append(entry)
        
        if clean_entries:
            new_history[team] = clean_entries

    with open(history_file, 'w', encoding='utf-8') as f:
        json.dump(new_history, f, indent=2, ensure_ascii=False)
    
    print(f"Cleanup complete.")
    print(f"Purged (Keywords): {purged_count}")
    print(f"Expired (TTL): {expired_count}")

if __name__ == "__main__":
    massive_purge()
