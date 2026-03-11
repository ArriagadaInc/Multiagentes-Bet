#!/usr/bin/env python
"""
Generador directo de predicciones - Bypass del pipeline completo
Usa los datos ya generados (fixtures, odds, stats, insights) para generar pronósticos.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# LOAD DATA
# ============================================================================

def load_data():
    """Carga datos de los archivos JSON"""
    fixtures = json.load(open('pipeline_fixtures.json'))
    odds = json.load(open('pipeline_odds.json'))
    stats = json.load(open('pipeline_stats.json'))
    insights = json.load(open('pipeline_insights.json'))
    return fixtures, odds, stats, insights

def has_odds_for_match(home, away, odds):
    """Verifica si existe cuota para un partido específico"""
    home_norm = normalize_team(home)
    away_norm = normalize_team(away)
    
    for odd in odds:
        odd_home = normalize_team(odd.get('home_team', ''))
        odd_away = normalize_team(odd.get('away_team', ''))
        
        if (odd_home == home_norm and odd_away == away_norm) or \
           (odd_home == away_norm and odd_away == home_norm):
            return True
    return False

# ============================================================================
# HELPERS
# ============================================================================

def normalize_team(name):
    """Normaliza nombre de equipo"""
    if not name:
        return ""
    return name.lower().strip()

def find_stats(team_name, stats_list):
    """Busca stats de un equipo"""
    name_norm = normalize_team(team_name)
    for s in stats_list:
        if normalize_team(s.get('team', '')) == name_norm:
            return s
        if name_norm in normalize_team(s.get('team', '')):
            return s
    return None

def find_insights(team_name, insights_list):
    """Busca insights de un equipo"""
    name_norm = normalize_team(team_name)
    for i in insights_list:
        if normalize_team(i.get('team', '')) == name_norm:
            return i
        if name_norm in normalize_team(i.get('team', '')):
            return i
    return None

# ============================================================================
# PREDICTION LOGIC
# ============================================================================

def generate_heuristic_prediction(fixture, stats, insights):
    """Genera predicción heurística mejorada"""
    home = fixture.get('home_team', '')
    away = fixture.get('away_team', '')
    
    if not home or not away:
        return None
    
    # Buscar datos
    home_stats = find_stats(home, stats)
    away_stats = find_stats(away, stats)
    home_insights = find_insights(home, insights)
    away_insights = find_insights(away, insights)
    
    # Extraer métricas
    home_pos = home_stats.get('stats', {}).get('position', 99) if home_stats else 99
    away_pos = away_stats.get('stats', {}).get('position', 99) if away_stats else 99
    home_form = home_stats.get('stats', {}).get('form', '') or '' if home_stats else ''
    away_form = away_stats.get('stats', {}).get('form', '') or '' if away_stats else ''
    
    # Contar wins en racha
    home_wins = home_form.count('W')
    away_wins = away_form.count('W')
    
    # Score combinado
    pos_diff = away_pos - home_pos  # positivo = home ventaja
    form_diff = home_wins - away_wins
    
    combined = pos_diff + (form_diff * 1.5)
    
    # Predicción
    if combined > 4:
        prediction, confidence = "1", min(75, 55 + abs(combined))
    elif combined < -4:
        prediction, confidence = "2", min(75, 55 + abs(combined))
    else:
        prediction, confidence = "X", 52
    
    # Score estimado
    if prediction == "1":
        score = "2-0"
    elif prediction == "2":
        score = "0-2"
    else:
        score = "1-1"
    
    # Rationale
    factors = []
    if home_pos < away_pos:
        factors.append(f"local mejor posicionado (pos {home_pos})")
    if home_wins > away_wins:
        factors.append(f"forma local: {home_form}")
    if home_insights and home_insights.get('forecast'):
        factors.append("análisis YouTube favorable local")
    
    rationale = f"{home} (pos {home_pos}, {home_form}) vs {away} (pos {away_pos}, {away_form}): {' | '.join(factors) if factors else 'predicción equilibrada'}"
    
    return {
        "home": home,
        "away": away,
        "prediction": prediction,
        "confidence": confidence,
        "score": score,
        "rationale": rationale,
        "position_diff": pos_diff,
        "form_diff": form_diff,
    }

# ============================================================================
# MAIN
# ============================================================================

def main():
    print('\n' + '='*100)
    print('GENERADOR DE PREDICCIONES - ALGORITMO HEURÍSTICO')
    print('='*100)
    
    fixtures, odds, stats, insights = load_data()
    
    # Agrupar fixtures por competencia
    by_comp = {}
    for fix in fixtures:
        comp = fix.get('competition', 'UNKNOWN')
        if comp not in by_comp:
            by_comp[comp] = []
        by_comp[comp].append(fix)
    
    now = datetime.now(timezone.utc).isoformat()
    all_predictions = []
    
    for comp in sorted(by_comp.keys()):
        comp_fixtures = by_comp[comp]
        comp_stats = [s for s in stats if s.get('competition') == comp]
        comp_insights = [i for i in insights if i.get('competition') == comp]
        comp_odds = [o for o in odds if o.get('competition') == comp]
        
        print(f'\n{"-"*100}')
        print(f'[{comp}] Generando {len(comp_fixtures)} pronósticos...')
        print(f'{"-"*100}')
        
        comp_predictions = []
        matches_without_odds = 0
        
        for idx, fixture in enumerate(sorted(comp_fixtures, key=lambda x: x.get('commence_time', '')), 1):
            pred = generate_heuristic_prediction(fixture, comp_stats, comp_insights)
            
            if not pred:
                continue
            
            # Verificar si hay cuotas disponibles
            has_odds = has_odds_for_match(pred['home'], pred['away'], comp_odds)
            
            if not has_odds:
                matches_without_odds += 1
            
            # Mapear a output format
            outcome_map = {
                '1': '🏠 GANA LOCAL',
                'X': '🤝 EMPATE',
                '2': '✈️ GANA VISITANTE'
            }
            
            prediction_record = {
                "prediction_id": f"{comp}_{fixture.get('commence_time', '')[:10]:.9}_{pred['home']}_vs_{pred['away']}".replace(" ", "_"),
                "competition": comp,
                "generated_at": now,
                "match_date": fixture.get('commence_time', '')[:10],
                "home_team": pred["home"],
                "away_team": pred["away"],
                "prediction": pred["prediction"],
                "confidence": int(pred["confidence"]),
                "score_prediction": pred["score"],
                "rationale": pred["rationale"],
                "key_factors": [f"Diferencia posición: {pred['position_diff']}", f"Diferencia forma: {pred['form_diff']}"],
                "risk_factors": ["Márgenes ajustados", "Datos agregados limitados"],
                "entities_impact": [],
                "has_odds": has_odds,
            }
            
            comp_predictions.append(prediction_record)
            all_predictions.append(prediction_record)
            
            outcome_text = outcome_map.get(pred['prediction'], '?')
            odds_indicator = "✓" if has_odds else "🔴"
            print(f'{idx:2d}. {odds_indicator} {pred["home"]:25s} vs {pred["away"]:25s} => {outcome_text:20s} {int(pred["confidence"]):3d}% ({pred["score"]})')
        
        print(f'\n✓ {comp}: {len(comp_predictions)} predicciones generadas')
        if matches_without_odds > 0:
            print(f'  ⚠️  {matches_without_odds} partidos SIN cuotas disponibles 🔴')
    
    # Guardar
    os.makedirs("predictions", exist_ok=True)
    
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_file = f"predictions/{today}.json"
    with open(daily_file, "w", encoding="utf-8") as f:
        json.dump(all_predictions, f, indent=2, ensure_ascii=False)
    
    history_file = "predictions/predictions_history.json"
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(all_predictions, f, indent=2, ensure_ascii=False)
    
    print(f'\n' + '='*100)
    print(f'TOTAL PREDICCIONES GENERADAS: {len(all_predictions)}')
    print(f'Guardadas en: {daily_file}')
    print('='*100 + '\n')

if __name__ == '__main__':
    main()
