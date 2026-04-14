#!/usr/bin/env python3
import json

with open('web_agent_output.json') as f:
    data = json.load(f)

for comp in data.get('data', {}).get('competitions', []):
    print(f"\nCompetition: {comp.get('competition')}")
    print(f"Teams found: {len(comp.get('teams', []))}")
    for team in comp.get('teams', []):
        name = team.get('team', '?')
        pos = team.get('position_in_table', 'N/A')
        pts = team.get('points', 'N/A')
        sig_count = len(team.get('context_signals', []))
        print(f"  - {name}: pos={pos}, pts={pts}, signals={sig_count}")
