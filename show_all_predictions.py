#!/usr/bin/env python
"""Visualizador final de pronósticos - formato limpio y directo"""

import json
from datetime import datetime

def main():
    # Cargar predicciones generadas
    with open('predictions/2026-02-19.json') as f:
        predictions = json.load(f)
    
    print('\n' + '='*110)
    print(' '*30 + 'PRONÓSTICOS FINALES DEL AGENTE DE ANÁLISIS')
    print('='*110)
    
    # Agrupar por competencia
    by_comp = {}
    for p in predictions:
        comp = p.get('competition', 'UNKNOWN')
        if comp not in by_comp:
            by_comp[comp] = []
        by_comp[comp].append(p)
    
    total_generated = 0
    total_with_odds = 0
    total_without_odds = 0
    
    for comp in sorted(by_comp.keys()):
        comp_preds = by_comp[comp]
        print(f'\n{"-"*110}')
        print(f'  [{comp}] - {len(comp_preds)} pronósticos generados')
        print(f'{"-"*110}')
        
        for idx, pred in enumerate(sorted(comp_preds, key=lambda x: x.get('match_date', '')), 1):
            home = pred.get('home_team', 'N/A')
            away = pred.get('away_team', 'N/A')
            prediction = pred.get('prediction', '?')
            confidence = pred.get('confidence', '?')
            score = pred.get('score_prediction', '?')
            rationale = pred.get('rationale', 'N/A')
            has_odds = pred.get('has_odds', True)
            
            outcome_map = {'1': '🏠 GANA LOCAL', 'X': '🤝 EMPATE', '2': '✈️ GANA VISITANTE'}
            outcome_display = outcome_map.get(prediction, f'? ({prediction})')
            
            # Indicador de cuotas
            odds_indicator = "✓" if has_odds else "🔴 SIN CUOTAS"
            
            print(f'\n  {idx:2d}. {odds_indicator:20s} {home:30s} (LOCAL) vs {away:30s} (VISITANTE)')
            print(f'      {'─'*90}')
            print(f'      📊 PREDICCIÓN:  {outcome_display}')
            print(f'      🎯 CONFIANZA:   {confidence}%')
            print(f'      ⚽ SCORE EST:   {score}')
            print(f'      💡 ANÁLISIS:    {rationale}')
            
            # Mostrar factores
            key_factors = pred.get('key_factors', [])
            if key_factors:
                print(f'      ✅ FACTORES:')
                for factor in key_factors[:2]:
                    print(f'         • {factor}')
            
            total_generated += 1
            if has_odds:
                total_with_odds += 1
            else:
                total_without_odds += 1
        
        print(f'\n  Subtotal {comp}: {len(comp_preds)} pronósticos')
    
    print(f'\n{"="*110}')
    print(f'  TOTAL PRONÓSTICOS GENERADOS: {total_generated}')
    print(f'  ✓ CON CUOTAS DISPONIBLES: {total_with_odds}')
    print(f'  🔴 SIN CUOTAS DISPONIBLES: {total_without_odds}')
    print(f'  FUENTE: Algoritmo heurístico multi-factor (posición + forma + análisis)')
    print(f'  FECHA: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'{"="*110}\n')

if __name__ == '__main__':
    main()
