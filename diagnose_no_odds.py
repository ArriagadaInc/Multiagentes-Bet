#!/usr/bin/env python3
"""
Diagnosticar por qué partidos sin odds entraron a predicciones
"""

import json

# Revisar pipeline_result.json
with open('pipeline_result.json', 'r', encoding='utf-8') as f:
    result = json.load(f)

print("=" * 80)
print("DIAGNOSTICO: Partidos sin Odds en Predicciones")
print("=" * 80)

# Buscar eventos de gate
if 'gate_events' in result:
    events = result['gate_events']
    print(f'\n[1] Gate Agent Events: {len(events)} eventos registrados')
    dropped = [e for e in events if e.get('gate_status') == 'dropped']
    passed = [e for e in events if e.get('gate_status') != 'dropped']
    print(f'    - Passed: {len(passed)}')
    print(f'    - Dropped: {len(dropped)}')
    
    if dropped:
        print(f'\n[2] Partidos ELIMINADOS (sin odds):')
        for d in dropped[:5]:
            print(f'    ❌ {d.get("home")} vs {d.get("away")}: {d.get("drop_reason")}')
else:
    print('\n[ERROR] No gate_events en pipeline_result.json')
    print(f'  Keys: {list(result.keys())}')

# Revisar predicciones actuales
print(f'\n[3] Predicciones generadas:')
predictions = result.get('predictions', [])
print(f'    Total: {len(predictions)}')

# Buscar predicciones sin odds
no_odds_predictions = []
for pred in predictions:
    match_info = pred.get('match_info', {})
    odds_str = match_info.get('odds_str', '')
    if 'Sin cuotas' in odds_str or 'sin cuotas' in odds_str.lower():
        no_odds_predictions.append(pred)

print(f'    Sin cuotas: {len(no_odds_predictions)}')
if no_odds_predictions:
    print(f'\n[4] PREDICCIONES SIN CUOTAS (💥 ESTO NO DEBERIA PASAR):')
    for pred in no_odds_predictions[:3]:
        match = pred.get('match_info', {})
        print(f'    ❌ {match.get("home_team")} vs {match.get("away_team")}')
        print(f'       Odds: {match.get("odds_str")[:100]}')

print("\n" + "=" * 80)
