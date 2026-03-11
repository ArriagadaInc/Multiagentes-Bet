#!/usr/bin/env python
"""Mostrar los pronósticos sugeridos por el agente de insights"""

import json

with open('pipeline_insights.json') as f:
    insights = json.load(f)

print('\n' + '='*80)
print('PRONÓSTICOS SUGERIDOS POR EL AGENTE DE INSIGHTS')
print('='*80)

# Mostrar solo los que tienen forecast
with_forecast = [i for i in insights if i.get('forecast')]
print(f'\nTotal insights: {len(insights)}, Con pronóstico: {len(with_forecast)}\n')

for idx, insight in enumerate(with_forecast[:15], 1):
    team = insight['team']
    competition = insight['competition']
    opponent = insight['next_match']['opponent']
    date = insight['next_match']['date']
    
    forecast = insight['forecast']
    outcome_map = {'1': 'GANA LOCAL', 'X': 'EMPATE', '2': 'GANA VISITANTE'}
    outcome = outcome_map.get(str(forecast['outcome']), str(forecast['outcome']))
    confidence = forecast['confidence']
    rationale = forecast['rationale']
    
    entities = insight['entities']
    absent_count = sum(len(v) for v in entities.values()) if entities else 0
    
    print(f'\n{idx}. [{competition}] {team} vs {opponent}')
    print(f'   📅 {date}')
    print(f'   📊 PRONÓSTICO: {outcome}')
    print(f'   🎯 Confianza: {confidence:.0%}')
    print(f'   💡 Razón: {rationale}')
    if absent_count > 0:
        print(f'   ⚠️  Ausencias: {absent_count} jugador(es)')

print('\n' + '='*80)
print(f'TOTAL PRONÓSTICOS CON PREDICCIÓN: {len(with_forecast)} de {len(insights)}')
print('='*80 + '\n')
