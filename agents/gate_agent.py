import logging
from typing import Any, List
from state import AgentState

logger = logging.getLogger(__name__)

def gate_agent_node(state: AgentState) -> AgentState:
    """
    Data Completeness Gate.
    Verifica que los MatchContext tengan suficiente calidad antes de pasar al Analista.
    """
    logger.info("=" * 60)
    logger.info("DATA COMPLETENESS GATE: Validando calidad de datos")
    logger.info("=" * 60)

    match_contexts = state.get("match_contexts") or []
    if not match_contexts:
        logger.warning("No match contexts found to validate")
        return state

    valid_contexts = []
    dropped_count = 0
    
    # Threshold de calidad (configurable o dinámico)
    QUALITY_THRESHOLD = 0.4 
    
    for ctx in match_contexts:
        quality = ctx.get("data_quality", {})
        score = quality.get("score", 0.0)
        match_id = ctx.get("match_id", "unknown")
        
        # Criterios de filtrado
        # 1. Score de calidad extremadamente bajo
        if score < QUALITY_THRESHOLD:
            logger.warning(f"  ❌ DROPPED: {match_id} | Score {score:.2f} < {QUALITY_THRESHOLD}")
            dropped_count += 1
            continue
            
        # 2. Ausencia de ambos stats (Home & Away)
        home_has_stats = ctx["home"].get("stats") is not None
        away_has_stats = ctx["away"].get("stats") is not None
        
        if not home_has_stats and not away_has_stats:
            logger.warning(f"  ❌ DROPPED: {match_id} | No stats available for either team")
            dropped_count += 1
            continue

        # El partido pasa el gate
        valid_contexts.append(ctx)
        logger.info(f"  ✅ PASSED: {match_id} | Quality Score: {score:.2f}")

    state["match_contexts"] = valid_contexts
    logger.info(f"GATE COMPLETE: {len(valid_contexts)} matches passed, {dropped_count} dropped")
    
    return state
