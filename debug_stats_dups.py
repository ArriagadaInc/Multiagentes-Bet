import json
from collections import Counter

try:
    with open('pipeline_stats.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
except Exception as e:
    print(f"Error loading file: {e}")
    exit(1)

ucl = [s for s in data if s.get('competition') == 'UCL']
print(f"Total UCL items: {len(ucl)}")

names = [s.get('team') for s in ucl]
counts = Counter(names)
dups = {n: c for n, c in counts.items() if c > 1}

print("\n--- DETALLE DE EQUIPOS ---")
for s in ucl:
    name = s.get('team')
    id_data = f" (Data: {'YES' if (s.get('advanced_stats') or s.get('lineup') or s.get('match_facts')) else 'NO'})"
    print(f"- {name}{id_data}")

if dups:
    print(f"\nDUPLICATES FOUND: {dups}")
else:
    print("\nNo duplicates found by exact name.")

# Check for near matches
clean_names = {}
for s in ucl:
    import re
    clean = re.sub(r'[^a-zA-Z0-9]', '', s.get('team').lower())
    if clean in clean_names:
        print(f"COLLISION (Cleaned): '{clean}' | Names: '{clean_names[clean]}' vs '{s.get('team')}'")
    clean_names[clean] = s.get('team')
