import json
import os
import re

def clean_file(filepath, pattern):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return

    print(f"Cleaning {filepath}...")
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    original_count = 0
    cleaned_count = 0

    if isinstance(data, dict) and "data" in data and "competitions" in data["data"]:
        # Case for web_agent_output.json
        for comp in data["data"]["competitions"]:
            if "teams" in comp:
                new_teams = []
                for team in comp["teams"]:
                    if pattern.search(str(team)):
                        print(f"  Removing team entry with '{pattern.pattern}' from {comp.get('competition')}")
                        cleaned_count += 1
                    else:
                        new_teams.append(team)
                comp["teams"] = new_teams
    
    elif isinstance(data, dict):
        # Case for team_history.json
        for team, entries in data.items():
            if isinstance(entries, list):
                new_entries = []
                for entry in entries:
                    if pattern.search(str(entry)):
                        print(f"  Removing history entry for {team}: {entry.get('insight', '')[:50]}...")
                        cleaned_count += 1
                    else:
                        new_entries.append(entry)
                data[team] = new_entries

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Done. Removed {cleaned_count} entries.")

if __name__ == "__main__":
    fortaleza_pattern = re.compile(r"Fortaleza", re.IGNORECASE)
    
    # Clean team_history.json
    clean_file("c:/desarrollos/apuestas/Futbol/data/knowledge/team_history.json", fortaleza_pattern)
    
    # Clean web_agent_output.json
    clean_file("c:/desarrollos/apuestas/Futbol/web_agent_output.json", fortaleza_pattern)
    
    # Clean pipeline_match_contexts.json if exists
    clean_file("c:/desarrollos/apuestas/Futbol/pipeline_match_contexts.json", fortaleza_pattern)
