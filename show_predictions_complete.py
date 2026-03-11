#!/usr/bin/env python
"""
Visualizador mejorado de predicciones con deduplicación.
- Deduplica partidos (mismo matchup)
- Muestra claramente HOME vs AWAY
- Agrupa por competencia
"""

import json
from collections import defaultdict
from datetime import datetime

def normalize_team_name(name):
    """Normaliza nombre de equipo para comparación"""
    if not name:
        return ""
    return name.lower().strip()

def deduplicate_matches(fixtures):
    """Deduplica fixtures, mantiene un solo (home, away)"""
    seen = set()
    unique = []
    
    for fix in fixtures:
        home = fix.get('home_team', '')
        away = fix.get('away_team', '')
        
        # Saltar si no hay home o away
        if not home or not away:
            continue
        
        # Crear tupla ordenada para detectar duplicados
        match_key = tuple(sorted([normalize_team_name(home), normalize_team_name(away)]))
        
        if match_key not in seen:
            seen.add(match_key)
            unique.append(fix)
    
    return unique

def load_data():
    """Carga datos de outputs"""
    with open('pipeline_fixtures.json') as f:
        fixtures = json.load(f)
    
    with open('pipeline_insights.json') as f:
        insights = json.load(f)
    
    with open('pipeline_odds.json') as f:
        odds = json.load(f)
    
    try:
        with open('predictions/predictions_history.json') as f:
            predictions = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        predictions = []
    
    return fixtures, insights, odds, predictions

def find_prediction(home, away, competition, predictions):
    """Busca predicción para un partido específico"""
    home_l = normalize_team_name(home)
    away_l = normalize_team_name(away)
    
    for pred in predictions:
        if pred.get('competition') != competition:
            continue
        
        pred_home = normalize_team_name(pred.get('home_team', ''))
        pred_away = normalize_team_name(pred.get('away_team', ''))
        
        if pred_home == home_l and pred_away == away_l:
            return pred
    
    return None

def main():
    fixtures, insights, odds, predictions = load_data()
    
    # Agrupar por competencia
    by_comp = defaultdict(list)
    for fix in fixtures:
        comp = fix.get('competition', 'UNKNOWN')
        by_comp[comp].append(fix)
    
    # Deduplicar por competencia
    for comp in by_comp:
        by_comp[comp] = deduplicate_matches(by_comp[comp])
    
    print('\n' + '='*80)
    print('PRONÓSTICOS COMPLETOS - TODAS LAS COMPETENCIAS')
    print('='*80)
    
    total_fixtures = 0
    total_with_pred = 0
    
    for comp in sorted(by_comp.keys()):
        comp_fixtures = by_comp[comp]
        
        print(f'\n{"="*80}')
        print(f'[{comp}] - {len(comp_fixtures)} partidos')
        print(f'{"="*80}')
        
        matches_with_pred = 0
        
        for idx, fixture in enumerate(sorted(comp_fixtures, key=lambda x: x.get('commence_time', '')), 1):
            home = fixture.get('home_team', 'N/A')
            away = fixture.get('away_team', 'N/A')
            date = fixture.get('commence_time', fixture.get('match_date', 'N/A'))[:10]
            time = fixture.get('commence_time', '')[-8:] if len(fixture.get('commence_time', '')) > 10 else ''
            
            # Buscar predicción
            pred = find_prediction(home, away, comp, predictions)
            
            print(f'\n{idx}. 🏟️ {home} (LOCAL) vs {away} (VISITANTE)')
            print(f'   📅 {date} {time}')
            
            if pred:
                matches_with_pred += 1
                outcome_map = {'1': '🏠 GANA LOCAL', 'X': '🤝 EMPATE', '2': '✈️ GANA VISITANTE'}
                outcome_text = outcome_map.get(str(pred.get('prediction')), f"? ({pred.get('prediction')})")
                conf = pred.get('confidence', '?')
                score = pred.get('score_prediction', '?')
                
                print(f'   ═══════════════════════════════════════════')
                print(f'   📊 PREDICCIÓN: {outcome_text}')
                print(f'   🎯 Confianza: {conf}%')
                print(f'   ⚽ Score estimado: {score}')
                print(f'   💡 Razón: {pred.get("rationale", "N/A")}')
                
                if pred.get('key_factors'):
                    print(f'   ✅ Factores a favor:')
                    for factor in pred['key_factors'][:3]:
                        print(f'      - {factor}')
                
                if pred.get('risk_factors'):
                    print(f'   ⚠️ Riesgos:')
                    for risk in pred['risk_factors'][:2]:
                        print(f'      - {risk}')
            else:
                print(f'   ❌ SIN PREDICCIÓN (datos insuficientes)')
            
            total_fixtures += 1
        
        total_with_pred += matches_with_pred
        print(f'\n   Resumen: {matches_with_pred}/{len(comp_fixtures)} partidos con predicción')
    
    print('\n' + '='*80)
    print(f'RESUMEN TOTAL: {total_with_pred}/{total_fixtures} partidos con predicción')
    print(f'Cobertura: {100*total_with_pred/total_fixtures:.1f}%' if total_fixtures else 'N/A')
    print('='*80 + '\n')

if __name__ == '__main__':
    main()
