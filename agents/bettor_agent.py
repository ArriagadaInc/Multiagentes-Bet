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
from utils.bet_math import (
    combo_odds,
    combo_probability,
    expected_value,
    fractional_kelly,
    implied_probability,
)
from utils.bet_slip_normalizer import normalize_betano_bets
from utils.probability_calibration import calibrate_prediction_probability

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

# --- Guardrails de Riesgo Epistemológico ---
# Penalidades al edge mínimo exigido (unidades de %: 1.0 = 1%)
MEDIUM_RISK_EDGE_PENALTY = 1.0
HIGH_RISK_EDGE_PENALTY   = 3.0
WEB_SCRAPED_EDGE_PENALTY = 2.0 # Penalidad adicional por ser fuente web

# Topes máximos para el stake (en unidades)
MEDIUM_RISK_MAX_STAKE = 2.0
HIGH_RISK_MAX_STAKE   = 1.0
WEB_SCRAPED_MAX_STAKE = 1.0 # Tope estricto para cuotas web (max 1u)

# Umbral crítico para hacer un Skip forzoso ante anomalías severas
HIGH_RISK_SKIP_SIGNAL_SCORE_THRESHOLD = 0.45
# ---------------------------------------------


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
    Encuentra la cuota del mercado correspondiente a la predicción.
    Orden de prioridad:
    1) match_id/event_id/prediction_id
    2) nombres canónicos exactos
    3) fuzzy matching conservador
    Retorna dict con {odd, bookmaker, market}
    """
    pred_home = prediction.get("home_team", "")
    pred_away = prediction.get("away_team", "")
    pred_pick = prediction.get("prediction") # "1", "X", "2"
    pred_match_id = prediction.get("event_id") or prediction.get("match_id") or prediction.get("prediction_id")
    
    match_ev = None

    # 1. Prioridad absoluta: match_id canónico/determinista
    if pred_match_id:
        for ev in odds_canonical:
            ev_match_id = ev.get("match_id") or ev.get("event_id")
            if ev_match_id and ev_match_id == pred_match_id:
                match_ev = ev
                logger.info(
                    f"Match encontrado por match_id: '{pred_home}' vs '{pred_away}' -> Odds Event: "
                    f"'{ev.get('home_team', '')}' vs '{ev.get('away_team', '')}'"
                )
                break
    
    # 2. Nombres canónicos exactos
    if not match_ev:
        pred_home_clean = normalizer.clean(pred_home or "")
        pred_away_clean = normalizer.clean(pred_away or "")
        for ev in odds_canonical:
            ev_home = ev.get("home_team", "")
            ev_away = ev.get("away_team", "")
            ev_home_clean = normalizer.clean(ev_home or "")
            ev_away_clean = normalizer.clean(ev_away or "")
            if pred_home_clean == ev_home_clean and pred_away_clean == ev_away_clean:
                match_ev = ev
                logger.info(
                    f"Match encontrado por canónico: '{pred_home}' vs '{pred_away}' -> Odds Event: '{ev_home}' vs '{ev_away}'"
                )
                break

    # 3. Fuzzy matching conservador
    if not match_ev:
        for ev in odds_canonical:
            ev_home = ev.get("home_team", "")
            ev_away = ev.get("away_team", "")
            
            if not normalizer.find_match(pred_home, [ev_home], threshold=0.6):
                continue
            if not normalizer.find_match(pred_away, [ev_away], threshold=0.6):
                continue
                
            match_ev = ev
            logger.info(f"Match encontrado por fuzzy: '{pred_home}' vs '{pred_away}' -> Odds Event: '{ev_home}' vs '{ev_away}'")
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
            "market": "1X2",
            # Pasar metadatos de provenance si existen
            "odds_source_type": match_ev.get("odds_source_type", "api"),
            "odds_source_name": match_ev.get("provider", "the_odds_api"),
            "source_url": match_ev.get("source_url"),
            "captured_at": match_ev.get("captured_at"),
            "market_data_quality": match_ev.get("market_data_quality", "high" if match_ev.get("odds_source_type") != "web_scraped" else "medium")
        }
    return None

def _index_match_contexts(match_contexts: list[dict]) -> dict:
    """Indexa la lista global de contextos por ID y nombres para rápido acceso."""
    idx = {}
    for mc in match_contexts:
        if "match_id" in mc:
            idx[mc["match_id"]] = mc
        # Fallback de nombres
        home = normalizer.clean(mc.get("home", {}).get("canonical_name", "")).lower()
        away = normalizer.clean(mc.get("away", {}).get("canonical_name", "")).lower()
        if home and away:
            idx[f"{home}_{away}"] = mc
    return idx

def _analyze_value(prediction: dict, market_odds: dict, match_context: Optional[dict] = None) -> Optional[dict]:
    """
    Genera datos de value bet si existe edge real.
    Incluye protección contra predicciones que van contra el mercado con baja confianza,
    y ahora introduce guardrails suaves según el Riesgo Epistemológico del partido.
    """
    if not market_odds:
        return None

    odds = market_odds["odds"]
    if odds < MIN_ODDS:
        return None

    # GUARDRAIL P0.4: Usar SIEMPRE confidence_raw (valor crudo del LLM).
    # Nunca usar confidence_calibrated, aunque SHADOW_MODE se desactive en el futuro.
    # La calibración es solo para análisis retrospectivo, no para decisiones de apuesta.
    conf_raw = prediction.get("confidence_raw")
    conf = float(conf_raw) if conf_raw is not None else float(prediction.get("confidence", 0))
    if conf < MIN_CONFIDENCE:
        return None

    implied = _calculate_implied_prob(odds)

    # 1. Extraer Calidad del Contexto (Guardrails Epistemológicos)
    dq = {}
    if match_context and "data_quality" in match_context:
        dq = match_context["data_quality"]
    else:
        logger.warning(
            f"Falta 'data_quality' para {prediction.get('home_team')} vs {prediction.get('away_team')}. "
            "Usando fallback conservador."
        )

    # Fallbacks seguros por si la data no está estructurada o el match_context es None
    gate_status = dq.get("gate_status", "clean")
    is_bet_allowed = dq.get("is_bet_allowed", True)
    
    # Conservamos variables de monitoreo de riesgo heredadas
    signal_risk_level = dq.get("signal_risk_level", "unknown")
    signal_quality_score = dq.get("signal_quality_score", 0.5)

    # Regla Especial Letal: Skip forzoso por Gate (is_bet_allowed = False)
    # Esto cubre el estado "observation" y cualquier bloqueo preventivo.
    if not is_bet_allowed:
        logger.warning(
            f"BETTOR SKIP_OBSERVATION: {prediction.get('home_team')} vs {prediction.get('away_team')} "
            f"| gate_status={gate_status}"
        )
        return {
            "tip_id": f"TIP_{prediction.get('prediction_id', 'UNK')}",
            "type": "value_bet",
            "action": "Skip / No Apuestable",
            "match": f"{prediction['home_team']} vs {prediction['away_team']}",
            "pick": prediction["prediction"],
            "odds": odds,
            "bookmaker": market_odds["bookmaker"],
            "confidence": conf,
            "implied_prob": round(implied, 1),
            "edge_pct": round(conf - implied, 1),
            "skip_reason": f"gate_{gate_status}",
            "gate_status": gate_status,
            "rationale": f"Apuesta salteada (Skip) por restricción del Gate: estado {gate_status.upper()}."
        }

    bettor_risk_adjustment_applied = False
    bettor_risk_adjustment_reason = ""
    effective_min_edge_pct = MIN_EDGE_PCT

    # 2. Ajuste de Elegibilidad según status Degradado
    if gate_status == "degraded":
        effective_min_edge_pct += MEDIUM_RISK_EDGE_PENALTY
        bettor_risk_adjustment_applied = True
        bettor_risk_adjustment_reason = "degraded_edge_penalty"

    # Edge = Probabilidad Modelo - Probabilidad Implícita del mercado
    edge = conf - implied

    if edge < effective_min_edge_pct:
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

    # Calcular stake (Kelly simplificado - Base Bruta)
    # Banca: Más estable (máx 3u)
    # Pasada: Más pequeño (máx 1.5u)
    if strategy == "bank":
        stake_unit_raw = 1.0 + (edge - 5.0) * 0.2
        stake_unit_raw = min(stake_unit_raw, 3.0)
    else:
        stake_unit_raw = 0.5 + (edge - 5.0) * 0.1
        stake_unit_raw = min(stake_unit_raw, 1.5)

    stake_unit_final = stake_unit_raw

    # Reducir stake si hay warning (lógica legacy de contra-mercado)
    if warning:
        stake_unit_final = max(0.5, round(stake_unit_final * 0.5, 1))

    # 3. Aplicar Guardrails Geométricos (Stake Capping por Gate Degradado o Web Odds)
    stake_cap_applied = False
    
    # Detectar si la cuota viene de web scraping
    is_web_odds = market_odds.get("odds_source_type") == "web_scraped"
    
    if is_web_odds:
        effective_min_edge_pct += WEB_SCRAPED_EDGE_PENALTY
        bettor_risk_adjustment_applied = True
        bettor_risk_adjustment_reason += " | web_odds_penalty"
        
    # Re-evaluar edge después de la posible penalidad web
    if edge < effective_min_edge_pct:
        return None

    if gate_status == "degraded" and stake_unit_final > MEDIUM_RISK_MAX_STAKE:
        stake_unit_final = MEDIUM_RISK_MAX_STAKE
        stake_cap_applied = True
        bettor_risk_adjustment_applied = True
        bettor_risk_adjustment_reason += " | stake_capped_degraded"
        
    if is_web_odds and stake_unit_final > WEB_SCRAPED_MAX_STAKE:
        stake_unit_final = WEB_SCRAPED_MAX_STAKE
        stake_cap_applied = True
        bettor_risk_adjustment_applied = True
        bettor_risk_adjustment_reason += " | stake_capped_web"

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
        "stake_units_raw": round(stake_unit_raw, 1),
        "stake_units_final": round(stake_unit_final, 1),
        "stake_units": round(stake_unit_final, 1), # Mantener campo legacy por compatibilidad
        "gate_status": gate_status,
        "is_bet_allowed": is_bet_allowed,
        "signal_risk_level": signal_risk_level,
        "signal_quality_score": signal_quality_score,
        "effective_min_edge_pct": round(effective_min_edge_pct, 1),
        "stake_cap_applied": stake_cap_applied,
        "bettor_risk_adjustment_applied": bettor_risk_adjustment_applied,
        "bettor_risk_adjustment_reason": bettor_risk_adjustment_reason.strip(" |") if bettor_risk_adjustment_reason else "",
        "rationale": (
            f"Value detectado: Modelo ({conf}%) vs Mercado ({implied:.1f}% @ {odds}). "
            f"Edge: {edge:.1f}%."
            + (f" [FUENTE WEB]" if is_web_odds else "")
        ),
        "odds_source_type": market_odds.get("odds_source_type"),
        "source_url": market_odds.get("source_url")
    }

    # Logging explícito de la acción preventiva para trazabilidad
    if bettor_risk_adjustment_applied:
        logger.info(
            f"BETTOR RISK ADJ: match_id={prediction.get('event_id', 'UNK')} | gate_status={gate_status} "
            f"| signal_score={signal_quality_score} "
            f"| edge_min_effective={effective_min_edge_pct} | stake_raw={stake_unit_raw:.1f} "
            f"| stake_final={stake_unit_final:.1f} | action=Adjusted | reason={tip['bettor_risk_adjustment_reason']}"
        )
    if warning:
        tip["warning"] = warning

    return tip


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


def build_betano_eligible_bets(
    ocr_payload: dict[str, Any],
    predictions: list[dict],
    match_contexts: list[dict] | None = None,
    min_ocr_confidence: float = 0.80,
) -> dict[str, Any]:
    """
    Convierte una boleta/captura de Betano en apuestas elegibles usando el pick
    actual del analista como selección objetivo.
    """
    normalized = normalize_betano_bets(
        ocr_payload=ocr_payload,
        predictions=predictions or [],
        match_contexts=match_contexts or [],
        min_ocr_confidence=min_ocr_confidence,
    )

    eligible = []
    for item in normalized.get("eligible_bets", []):
        calibrated_probability = calibrate_prediction_probability(
            pick=item.get("selection"),
            confidence=float(item.get("analyst_confidence") or 0.0),
            gate_status=item.get("gate_status", "clean"),
            data_quality_flags=item.get("data_quality_flags") or [],
            had_youtube_insights=item.get("had_youtube_insights"),
            had_espn_stats=item.get("had_espn_stats"),
        )
        item = dict(item)
        item["estimated_probability"] = round(calibrated_probability, 4)
        item["implied_probability"] = round(implied_probability(float(item.get("odds_decimal") or 0.0)), 4)
        item["edge"] = round(item["estimated_probability"] - item["implied_probability"], 4)
        item["expected_value_per_unit"] = round(
            expected_value(item["estimated_probability"], float(item.get("odds_decimal") or 0.0)),
            4,
        )
        eligible.append(item)

    normalized["eligible_bets"] = eligible
    return normalized


def optimize_simple_bet_portfolio(
    eligible_bets: list[dict[str, Any]],
    bankroll_clp: int = 10000,
    mode: str = "balanced",
    include_combos: bool = True,
) -> dict[str, Any]:
    """
    Optimizador conservador de bankroll para boletas Betano.

    Fase 1:
    - Simples con Kelly fraccional
    - Combinadas 2-leg limitadas y opcionales
    - Permite dejar caja sin apostar
    """
    bankroll = max(0, int(bankroll_clp))
    mode_key = str(mode or "balanced").strip().lower()
    mode_cfg = {
        "conservative": {"kelly_fraction": 0.10, "max_exposure_pct": 0.45, "max_single_pct": 0.20, "max_combo_pct": 0.06},
        "balanced": {"kelly_fraction": 0.20, "max_exposure_pct": 0.60, "max_single_pct": 0.25, "max_combo_pct": 0.10},
        "aggressive": {"kelly_fraction": 0.33, "max_exposure_pct": 0.80, "max_single_pct": 0.30, "max_combo_pct": 0.15},
    }.get(mode_key, {"kelly_fraction": 0.20, "max_exposure_pct": 0.60, "max_single_pct": 0.25, "max_combo_pct": 0.10})

    min_stake = 100
    rounding = 100
    max_total_exposure = int(bankroll * mode_cfg["max_exposure_pct"])
    max_single_stake = int(bankroll * mode_cfg["max_single_pct"])
    max_combo_budget = int(bankroll * mode_cfg["max_combo_pct"])

    def _ticket_confidence_label(prob: float, edge: float, gate_status: str = "clean") -> str:
        gate = str(gate_status or "clean").lower()
        penalty = 0.05 if gate == "degraded" else 0.0
        score = float(prob) + float(edge) - penalty
        if score >= 0.58:
            return "alta"
        if score >= 0.42:
            return "media"
        return "baja"

    singles_candidates = []
    for bet in eligible_bets or []:
        ev = float(bet.get("expected_value_per_unit") or 0.0)
        if ev <= 0:
            continue
        if str(bet.get("gate_status") or "").lower() == "blocked":
            continue
        prob = float(bet.get("estimated_probability") or 0.0)
        odds = float(bet.get("odds_decimal") or 0.0)
        stake_fraction = fractional_kelly(prob, odds, fraction=mode_cfg["kelly_fraction"])
        proposed = int(round((bankroll * stake_fraction) / rounding) * rounding)
        proposed = min(proposed, max_single_stake)
        if proposed < min_stake:
            continue
        item = dict(bet)
        item["ticket_type"] = "single"
        item["stake_clp"] = proposed
        item["kelly_fraction_used"] = round(stake_fraction, 4)
        item["expected_profit_clp"] = round(proposed * ev, 0)
        item["recommendation_confidence"] = _ticket_confidence_label(
            prob=item["estimated_probability"],
            edge=item["edge"],
            gate_status=item.get("gate_status", "clean"),
        )
        singles_candidates.append(item)

    singles_candidates.sort(
        key=lambda x: (
            float(x.get("expected_profit_clp") or 0.0),
            float(x.get("edge") or 0.0),
            float(x.get("estimated_probability") or 0.0),
        ),
        reverse=True,
    )

    recommended_tickets: list[dict[str, Any]] = []
    allocated = 0
    for item in singles_candidates:
        if allocated >= max_total_exposure:
            break
        room = max_total_exposure - allocated
        stake = min(int(item["stake_clp"]), int(room))
        stake = int(round(stake / rounding) * rounding)
        if stake < min_stake:
            continue
        chosen = dict(item)
        chosen["stake_clp"] = stake
        chosen["expected_profit_clp"] = round(stake * float(chosen.get("expected_value_per_unit") or 0.0), 0)
        recommended_tickets.append(chosen)
        allocated += stake

    combo_candidates: list[dict[str, Any]] = []
    combo_allocated = 0
    combo_seed = [
        x for x in (recommended_tickets or singles_candidates)
        if str(x.get("gate_status") or "").lower() != "blocked"
    ][:5]
    if len(combo_seed) < 2:
        combo_seed = sorted(
            [
                x for x in (eligible_bets or [])
                if str(x.get("gate_status") or "").lower() != "blocked"
            ],
            key=lambda x: (
                float(x.get("estimated_probability") or 0.0),
                float(x.get("edge") or 0.0),
            ),
            reverse=True,
        )[:5]
    if include_combos and len(combo_seed) >= 2 and max_combo_budget >= min_stake:
        for a, b in combinations(combo_seed, 2):
            if a.get("match_id") == b.get("match_id"):
                continue
            probs = [float(a.get("estimated_probability") or 0.0), float(b.get("estimated_probability") or 0.0)]
            odds_vals = [float(a.get("odds_decimal") or 0.0), float(b.get("odds_decimal") or 0.0)]
            combo_prob = combo_probability(probs, correlation_penalty=0.90)
            combo_price = combo_odds(odds_vals)
            combo_ev = expected_value(combo_prob, combo_price)
            combo_kelly = fractional_kelly(combo_prob, combo_price, fraction=max(0.05, mode_cfg["kelly_fraction"] * 0.5))
            combo_stake = int(round((bankroll * combo_kelly) / rounding) * rounding)
            if combo_ev <= 0:
                combo_stake = min_stake
            combo_stake = min(combo_stake, max_combo_budget - combo_allocated)
            if combo_stake < min_stake:
                continue
            avg_edge = (float(a.get("edge") or 0.0) + float(b.get("edge") or 0.0)) / 2.0
            confidence_label = _ticket_confidence_label(combo_prob, avg_edge, gate_status="clean")
            combo_candidates.append({
                "ticket_type": "combo_2",
                "legs": [
                    {"match_id": a.get("match_id"), "match": f"{a.get('home_team')} vs {a.get('away_team')}", "selection": a.get("selection"), "odds_decimal": a.get("odds_decimal")},
                    {"match_id": b.get("match_id"), "match": f"{b.get('home_team')} vs {b.get('away_team')}", "selection": b.get("selection"), "odds_decimal": b.get("odds_decimal")},
                ],
                "combo_odds_decimal": round(combo_price, 2),
                "estimated_probability": round(combo_prob, 4),
                "expected_value_per_unit": round(combo_ev, 4),
                "stake_clp": combo_stake,
                "expected_profit_clp": round(combo_stake * combo_ev, 0),
                "risk_level": "high",
                "recommendation_confidence": confidence_label,
                "recommendation_basis": "positive_ev" if combo_ev > 0 else "forced_combo_exploratory",
            })
        combo_candidates.sort(
            key=lambda x: (
                float(x.get("expected_profit_clp") or 0.0),
                float(x.get("estimated_probability") or 0.0),
            ),
            reverse=True,
        )
        selected_combos = combo_candidates[:2]
        if not selected_combos and len(combo_candidates) > 0:
            selected_combos = [combo_candidates[0]]
        for combo in selected_combos:
            if combo_allocated + int(combo["stake_clp"]) > max_combo_budget:
                continue
            combo_allocated += int(combo["stake_clp"])
            recommended_tickets.append(combo)

    total_staked = sum(int(x.get("stake_clp") or 0) for x in recommended_tickets)
    expected_value_clp = round(sum(float(x.get("expected_profit_clp") or 0.0) for x in recommended_tickets), 0)
    hold_cash = max(0, bankroll - total_staked)

    return {
        "bankroll_clp": bankroll,
        "mode": mode_key,
        "recommended_tickets": recommended_tickets,
        "rejected_for_portfolio": [
            {
                "match_id": x.get("match_id"),
                "home_team": x.get("home_team"),
                "away_team": x.get("away_team"),
                "selection": x.get("selection"),
                "reason": "non_positive_ev_or_below_stake",
            }
            for x in eligible_bets or []
            if x.get("match_id") not in {y.get("match_id") for y in recommended_tickets if y.get("ticket_type") == "single"}
        ],
        "portfolio_summary": {
            "total_staked_clp": total_staked,
            "hold_cash_clp": hold_cash,
            "max_loss_clp": total_staked,
            "expected_value_clp": expected_value_clp,
            "expected_roi_pct_on_staked": round((expected_value_clp / total_staked) * 100.0, 2) if total_staked else 0.0,
            "risk_score": round(total_staked / bankroll, 3) if bankroll else 0.0,
        },
    }

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
    match_contexts = state.get("match_contexts") or []
    
    ctx_idx = _index_match_contexts(match_contexts)
    
    betting_tips = []
    singles = []
    bettor_trace = []
    
    # 1. Analizar Singles (Value Bets)
    for pred in predictions:
        # Encontrar Match Context para DQ (Data Quality)
        mc = None
        # Buscar por ID
        event_id = pred.get("event_id") or pred.get("match_id") or pred.get("prediction_id")
        if event_id and event_id in ctx_idx:
            mc = ctx_idx[event_id]
        else:
            # Fallback por nombres si no vino el event_id
            home = normalizer.clean(pred.get("home_team", "")).lower()
            away = normalizer.clean(pred.get("away_team", "")).lower()
            key = f"{home}_{away}"
            if key in ctx_idx:
                mc = ctx_idx[key]

        market = _find_market_odds(pred, odds_canonical)
        if market:
            value_bet = _analyze_value(pred, market, match_context=mc)
            if value_bet:
                betting_tips.append(value_bet)
                # Incluir a combinadas sólo si no fue skippeado
                if value_bet.get("action") != "Skip / No Value":
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
    state["bettor_trace"] = bettor_trace
    
    return state
