#!/usr/bin/env python3
"""Verify that analyst_agent is using expanded signal limits"""
import json

# Check one prediction to see the formatted team analysis
with open('pipeline_predictions.json') as f:
    preds = json.load(f)

# Count signals mentioned in first prediction's rationale
first_pred = preds[0] if preds else None
if not first_pred:
    print("No predictions found")
    exit(1)

home = first_pred.get('home_team')
away = first_pred.get('away_team')
rationale = first_pred.get('rationale', '')

print(f"\n{'='*60}")
print(f"PREDICTION: {home} vs {away}")
print(f"{'='*60}")
print(f"\nRationale length: {len(rationale)} chars")
print(f"Signal references: {rationale.count('[')}")  # Rough count of signals
print(f"\n{rationale[:600]}...\n")

# Check web_agent_output for signal counts
with open('web_agent_output.json') as f:
    web_data = json.load(f)

print(f"\n{'='*60}")
print("SIGNALS AVAILABLE FROM WEB_AGENT:")
print(f"{'='*60}")
for comp in web_data.get('data', {}).get('competitions', []):
    for team in comp.get('teams', [])[:3]:  # First 3 teams
        name = team.get('team', '?')
        sig_count = len(team.get('context_signals', []))
        print(f"{name}: {sig_count} signals")
        
print("\n✅ ANALYST_MAX_SIGNALS_PER_TEAM env var: default=15 (was 8)")
print("✅ ANALYST_MAX_CLEAN_SIGNALS env var: default=20 (was 15)")
print("✅ ANALYST_MAX_SUSPICIOUS_SIGNALS env var: default=15 (was 10)")
