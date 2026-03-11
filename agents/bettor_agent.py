"""
Agente #6: Apostador — Optimizador de Jugadas

Especialista en apuestas deportivas. Recibe predicciones del Analista y odds 
del mercado para detectar value bets y sugerir jugadas optimizadas (simples y combinadas).

Entradas esperadas en el estado:
- predictions: lista de predicciones del Analista 
- odds_canonical: cuotas del mercado

Salidas en el estado:
- betting_tips: lista de tips de apuesta (simples y combinadas)
"""

import logging
from typing import Any, Optional
from itertools import combinations
from datetime import datetime, timezone
import os
import json

from state import AgentState

from utils.normalizer import TeamNormalizer

logger = logging.getLogger(__name__)

# Configuración de Estrategia
MIN_EDGE_PCT   = 1.0   # Bajado para visualizar más opciones (antes 5.0)
MIN_CONFIDENCE = 50    # Bajado a 50% por pedido de Álvaro para ver más opciones
MIN_ODDS       = 1.30  
MAX_COMBOS     = 5     
COMBO_SIZE     = 3     

# Rangos de Estrategia
BANK_MAX_ODDS  = 2.10  # Techo para 'Construir Banca'
PASADA_MIN_ODDS = 2.20  # Suelo para singles de 'La Pasada'


# Instancia global del normalizador
normalizer = TeamNormalizer()

# ============================================================================
# LÓGICA DE APUESTAS
# ============================================================================

def _calculate_implied_prob(odds: float) -> float:
    """Calcula probabilidad implícita (0-100) desde cuota decimal."""
    if odds <= 1.0:
        return 100.0
    return (1 / odds) * 100.0

def _find_market_odds(prediction: dict, odds_canonical: list[dict]) -> Optional[dict]:
    """
    Encuentra la cuota del mercado correspondiente a la predicción usando fuzzy matching.
    Retorna dict con {odd, bookmaker, market}
    """
    pred_home = prediction.get("home_team", "")
    pred_away = prediction.get("away_team", "")
    pred_pick = prediction.get("prediction") # "1", "X", "2"
    
    match_ev = None
    
    # 1. Buscar evento de odds coincidente (ambos equipos deben matchear)
    for ev in odds_canonical:
        ev_home = ev.get("home_team", "")
        ev_away = ev.get("away_team", "")
        
        # Verificar Home
        # Usamos threshold alto (0.6) porque deberían ser muy parecidos
        if not normalizer.find_match(pred_home, [ev_home], threshold=0.6):
            continue
            
        # Verificar Away
        if not normalizer.find_match(pred_away, [ev_away], threshold=0.6):
            continue
            
        # Si ambos coinciden, encontramos el evento
        match_ev = ev
        logger.info(f"Match encontrado: '{pred_home}' vs '{pred_away}' -> Odds Event: '{ev_home}' vs '{ev_away}'")
        break
            
    if not match_ev:
        logger.warning(f"No se encontraron odds para: {pred_home} vs {pred_away}")
        return None
        
    if not match_ev:
        logger.warning(f"No se encontraron odds para: {pred_home} vs {pred_away}")
        return None
        
    # 2. Extraer cuota para el pick
    best_price = -1.0
    best_bookie = None
    
    # Mapeo de predicción a clave en el dict de odds normalizado
    # '1' -> 'home_odds', 'X' -> 'draw_odds', '2' -> 'away_odds'
    odds_key = None
    if pred_pick == "1":
        odds_key = "home_odds"
    elif pred_pick == "X":
        odds_key = "draw_odds"
    elif pred_pick == "2":
        odds_key = "away_odds"
        
    if not odds_key:
        return None
        
    # Buscar el mejor precio en todos los bookmakers disponibles para este evento
    for bk in match_ev.get("bookmakers", []):
        price = bk.get(odds_key)
        
        if price and isinstance(price, (int, float)) and price > best_price:
            best_price = price
            best_bookie = bk.get("title")
                            
    if best_price > 0:
        return {
            "odds": best_price,
            "bookmaker": best_bookie,
            "market": "1X2"
        }
    return None

def _analyze_value(prediction: dict, market_odds: dict) -> Optional[dict]:
    """
    Genera datos de value bet si existe edge real.
    Incluye protección contra predicciones que van contra el mercado con baja confianza.
    """
    if not market_odds:
        return None

    odds = market_odds["odds"]
    if odds < MIN_ODDS:
        return None

    conf = prediction.get("confidence", 0)
    if conf < MIN_CONFIDENCE:
        return None

    implied = _calculate_implied_prob(odds)

    # Edge = Probabilidad Modelo - Probabilidad Implícita del mercado
    edge = conf - implied

    if edge < MIN_EDGE_PCT:
        return None

    # ── Protección contra-mercado ────────────────────────────────────────
    # Si la predicción del analista va contra el favorito del mercado
    # (la cuota del pick es > 2.2, es decir prob implícita < 45%) y la
    # confianza es < 72%, marcamos el tip con un warning.
    going_against_market = odds > 2.20
    low_conf_against_market = going_against_market and conf < 72
    warning = None
    if low_conf_against_market:
        warning = "contra_mercado_baja_conf"
        logger.warning(
            f"Tip CONTRA MERCADO con confianza baja: {prediction.get('home_team')} vs "
            f"{prediction.get('away_team')} pick={prediction.get('prediction')} "
            f"conf={conf}% implied={implied:.1f}%"
        )

    # Determinar Estrategia
    strategy = "other"
    if odds <= BANK_MAX_ODDS and conf >= 50:
        strategy = "bank"
    elif odds >= PASADA_MIN_ODDS:
        strategy = "parlay" # En singles, "parlay" se asocia a "La Pasada" visualmente

    # Calcular stake (Kelly simplificado)
    # Banca: Más estable (máx 3u)
    # Pasada: Más pequeño (máx 1.5u)
    if strategy == "bank":
        stake_unit = 1.0 + (edge - 5.0) * 0.2
        stake_unit = min(stake_unit, 3.0)
    else:
        stake_unit = 0.5 + (edge - 5.0) * 0.1
        stake_unit = min(stake_unit, 1.5)

    # Reducir stake si hay warning
    if warning:
        stake_unit = max(0.5, round(stake_unit * 0.5, 1))

    tip = {
        "tip_id": f"TIP_{prediction.get('prediction_id', 'UNK')}",
        "type": "value_bet",
        "strategy": strategy,
        "match": f"{prediction['home_team']} vs {prediction['away_team']}",
        "pick": prediction["prediction"],
        "odds": odds,
        "bookmaker": market_odds["bookmaker"],
        "confidence": conf,
        "implied_prob": round(implied, 1),
        "edge_pct": round(edge, 1),
        "stake_units": round(stake_unit, 1),
        "rationale": (
            f"Value detectado: Modelo ({conf}%) vs Mercado ({implied:.1f}% @ {odds}). "
            f"Edge: {edge:.1f}%"
        ),
    }
    if warning:
        tip["warning"] = warning

    return tip


def _generate_combos(singles: list[dict]) -> list[dict]:
    """Genera apuestas combinadas (dobles y triples) con las mejores singles."""
    # Filtrar singles de alta confianza para combos
    candidates = [
        s for s in singles 
        if s["confidence"] >= (MIN_CONFIDENCE + 5) and s["edge_pct"] >= MIN_EDGE_PCT
    ]
    
    if len(candidates) < 2:
        return []
        
    combos = []
    
    # Generar Dobles y Triples
    for r in range(2, min(len(candidates), COMBO_SIZE) + 1):
        for subset in combinations(candidates, r):
            # Calcular cuota combinada
            total_odds = 1.0
            for leg in subset:
                total_odds *= leg["odds"]
            
            # Stake conservador para combinadas
            stake = 0.5 + (0.5 / len(subset))
            
            # Validar que no haya selecciones del mismo partido (correlación)
            # En este modelo 1X2 ya es único por partido, así que ok.
            
            combo_id = f"COMBO_{len(combos)+1}"
            combos.append({
                "tip_id": combo_id,
                "type": f"combo_{r}",
                "strategy": "parlay", # Las combinadas siempre son de 'La Pasada'
                "total_odds": round(total_odds, 2),
                "stake_units": round(stake, 2),
                "legs": [
                    {
                        "match": leg["match"], 
                        "pick": leg["pick"], 
                        "odds": leg["odds"]
                    } 
                    for leg in subset
                ],
                "rationale": f"Combinada de {r} selecciones para alta rentabilidad. Cuota total: {total_odds:.2f}"
            })
            
            if len(combos) >= MAX_COMBOS:
                return combos
                
    return combos

# ============================================================================
# PERSISTENCIA
# ============================================================================

def _save_bets(bets: list[dict]):
    """Guarda los tips generados en archivo JSON."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    bets_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "bets"
    )
    os.makedirs(bets_dir, exist_ok=True)
    
    filepath = os.path.join(bets_dir, f"{today}_bets.json")
    
    # Cargar existentes del día para no sobrescribir sin querer (o append)
    # Por simplicidad en este paso, sobrescribimos el día con la última ejecución completa
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(bets, f, indent=2, ensure_ascii=False)
        
    logger.info(f"Apuestas guardadas en {filepath}")

# ============================================================================
# NODO PRINCIPAL
# ============================================================================

def bettor_agent_node(state: AgentState) -> AgentState:
    """Node del Agente Apostador."""
    logger.info("=" * 60)
    logger.info("BETTOR AGENT: optimizing betting strategy")
    logger.info("=" * 60)
    
    predictions = state.get("predictions") or []
    odds_canonical = state.get("odds_canonical") or []
    
    betting_tips = []
    singles = []
    
    # 1. Analizar Singles (Value Bets)
    for pred in predictions:
        market = _find_market_odds(pred, odds_canonical)
        if market:
            value_bet = _analyze_value(pred, market)
            if value_bet:
                betting_tips.append(value_bet)
                singles.append(value_bet)
    
    logger.info(f"Encontradas {len(singles)} value bets simples.")
    
    # 2. Generar Combinadas
    combos = _generate_combos(singles)
    betting_tips.extend(combos)
    logger.info(f"Generadas {len(combos)} apuestas combinadas.")
    
    # 3. Persistir
    if betting_tips:
        _save_bets(betting_tips)
        
    state["betting_tips"] = betting_tips
    
    return state
