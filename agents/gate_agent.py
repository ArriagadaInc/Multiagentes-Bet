import logging
import json
from typing import Any, List, Dict
from state import AgentState

logger = logging.getLogger(__name__)

def gate_agent_node(state: AgentState) -> AgentState:
    """
    Data Completeness Gate.
    Verifica que los MatchContext tengan suficiente calidad antes de pasar al Analista.
    Emite 'gate_summary' en el estado para observabilidad operativa (Tarea 5).
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

    # Registro estructurado para observabilidad
    gate_events: List[Dict] = []

    # Threshold de calidad (configurable o dinámico)
    QUALITY_THRESHOLD = 0.4

    for ctx in match_contexts:
        quality = ctx.get("data_quality", {})
        score = quality.get("score", 0.0)
        match_id = ctx.get("match_id", "unknown")
        home = ctx.get("home", {}).get("canonical_name", "?")
        away = ctx.get("away", {}).get("canonical_name", "?")

        # ============================================================================
        # CRUCIAL: Validación de Cuotas de Mercado (PRIMERA regla, NO tiene excepciones)
        # ============================================================================
        # SIN CUOTAS DE MERCADO = PARTIDO ELIMINADO DEL FLUJO
        # No se puede llegar al Analista sin odds disponibles
        # ============================================================================
        has_odds = ctx.get("odds") is not None
        
        if not has_odds:
            msg = f"  ❌ ELIMINADO: {match_id} ({home} vs {away}) | SIN CUOTAS DE MERCADO - Partido bloqueado antes del Analista"
            logger.warning(msg)
            dropped_count += 1
            gate_events.append({
                "match_id": match_id,
                "home": home,
                "away": away,
                "gate_status": "dropped",
                "drop_reason": "no_market_odds",
                "critical_validation": True,
                "message": "Sin cuotas de mercado disponibles"
            })
            continue

        # Criterios de filtrado base
        # 1. Score de calidad extremadamente bajo
        overall_score = quality.get("overall_quality_score", score)
        if overall_score < QUALITY_THRESHOLD:
            msg = (
                f"  ⚠️ OBSERVATION (Low Quality): {match_id} | Overall {overall_score:.2f} < {QUALITY_THRESHOLD} "
                f"(Stats={quality.get('stats_quality_score', score):.2f}, "
                f"Signal={quality.get('signal_quality_score', 0):.2f}) | "
                f"Risk: {quality.get('signal_risk_level', 'unknown')} | "
                f"{quality.get('signal_explanation', '')}"
            )
            logger.warning(msg)
            # v14.12: No se descarta. Se pasa al analista para que decida, pero sin permitir apuesta.
            quality["gate_status"] = "observation"
            quality["is_bet_allowed"] = False
            gate_events.append({
                "match_id": match_id, "home": home, "away": away,
                "gate_status": "observation",
                "drop_reason": "low_overall_quality",
                "overall_score": overall_score,
                "risk_level": quality.get("signal_risk_level", "unknown"),
            })
            ctx["data_quality"] = quality
            valid_contexts.append(ctx)
            continue

        # 2. Ausencia de ambos stats (Home & Away)
        home_has_stats = ctx["home"].get("stats") is not None
        away_has_stats = ctx["away"].get("stats") is not None

        if not home_has_stats and not away_has_stats:
            # FLEXIBILIZACIÓN v14.12: Pasamos a 'observation' en lugar de bloquear
            logger.warning(f"  ⚠️ OBSERVATION (No Stats): {match_id} | No stats available for either team")
            quality["gate_status"] = "observation"
            quality["is_bet_allowed"] = False
            gate_events.append({
                "match_id": match_id, "home": home, "away": away,
                "gate_status": "observation",
                "drop_reason": "no_stats_both_teams",
                "overall_score": overall_score,
                "risk_level": quality.get("signal_risk_level", "unknown"),
            })
            ctx["data_quality"] = quality
            valid_contexts.append(ctx)
            continue
        # 3. Bloqueo Operativo: risk=high y severe=true
        # (Defino risk_level e is_severe aquí para usarlas en las reglas siguientes)
        risk_level = quality.get("signal_risk_level", "unknown")
        is_severe = quality.get("has_severe_signal_issues", False)

        if risk_level == "high" and is_severe:
            # FLEXIBILIZACIÓN v14.12: Pasamos al analista para que decida con la info de calidad
            msg = (
                f"  ⚠️ OBSERVATION (High Risk/Severe): {match_id} | "
                f"Risk=High, Severe=True | {quality.get('signal_explanation', '')}"
            )
            logger.warning(msg)
            quality["gate_status"] = "observation"
            quality["is_bet_allowed"] = False
            gate_events.append({
                "match_id": match_id, "home": home, "away": away,
                "gate_status": "observation",
                "drop_reason": "high_risk_severe",
                "overall_score": overall_score,
                "risk_level": risk_level,
                "signal_explanation": quality.get("signal_explanation", ""),
            })
            ctx["data_quality"] = quality
            valid_contexts.append(ctx)
            continue
        # 4. Observación: risk=high y severe=false -> NO APUESTABLE
        if risk_level == "high" and not is_severe:
            msg = f"  ⚠️ OBSERVATION: {match_id} | Risk=High, Severe=False | Marcado como no apuestable."
            logger.warning(msg)
            quality["gate_status"] = "observation"
            quality["is_bet_allowed"] = False
            gate_events.append({
                "match_id": match_id, "home": home, "away": away,
                "gate_status": "observation",
                "drop_reason": None,
                "overall_score": overall_score,
                "risk_level": risk_level,
                "is_bet_allowed": False,
            })
        # 5. Degradado: risk=medium y severe=false -> Entra con penalizaciones de Edge/Stake
        elif risk_level == "medium" and not is_severe:
            msg = f"  🟡 DEGRADED: {match_id} | Risk=Medium, Severe=False | Entra con penalizaciones."
            logger.info(msg)
            quality["gate_status"] = "degraded"
            quality["is_bet_allowed"] = True
            gate_events.append({
                "match_id": match_id, "home": home, "away": away,
                "gate_status": "degraded",
                "drop_reason": None,
                "overall_score": overall_score,
                "risk_level": risk_level,
                "is_bet_allowed": True,
            })
        else:
            # Limpio
            quality["gate_status"] = "clean"
            quality["is_bet_allowed"] = True
            gate_events.append({
                "match_id": match_id, "home": home, "away": away,
                "gate_status": "clean",
                "drop_reason": None,
                "overall_score": overall_score,
                "risk_level": risk_level,
                "is_bet_allowed": True,
            })

        ctx["data_quality"] = quality

        # El partido pasa el gate
        valid_contexts.append(ctx)
        logger.info(
            f"  ✅ PASSED: {match_id} | Overall Score: {overall_score:.2f} "
            f"(Stats={quality.get('stats_quality_score', score):.2f}, "
            f"Signal={quality.get('signal_quality_score', 0):.2f}) | "
            f"Risk: {quality.get('signal_risk_level', 'unknown')} | "
            f"{quality.get('signal_explanation', '')}"
        )

    state["match_contexts"] = valid_contexts

    # ════════════════════════════════════════════════════════════════════════════════
    # v13.7: REESCRIBIR pipeline_match_contexts.json CON CONTEXTOS VALIDADOS
    # (El normalizer guardó ANTES del Gate; ahora reescribimos SOLO con los aprobados)
    # ════════════════════════════════════════════════════════════════════════════════
    try:
        with open("pipeline_match_contexts.json", "w", encoding="utf-8") as f:
            json.dump(valid_contexts, f, indent=2, ensure_ascii=False)
        logger.info(f"  ✅ pipeline_match_contexts.json reescrito con {len(valid_contexts)} matches validados")
    except Exception as e:
        logger.warning(f"  ⚠️  No se pudo reescribir pipeline_match_contexts.json: {e}")

    # Persistir resumen estructurado para observabilidad downstream
    state["gate_summary"] = {
        "total_input": len(match_contexts),
        "total_passed": len(valid_contexts),
        "total_dropped": dropped_count,
        "count_clean": sum(1 for e in gate_events if e["gate_status"] == "clean"),
        "count_degraded": sum(1 for e in gate_events if e["gate_status"] == "degraded"),
        "count_observation": sum(1 for e in gate_events if e["gate_status"] == "observation"),
        "events": gate_events,
    }

    logger.info(
        f"GATE COMPLETE: {len(valid_contexts)} passed ({dropped_count} dropped) | "
        f"clean={state['gate_summary']['count_clean']} "
        f"degraded={state['gate_summary']['count_degraded']} "
        f"observation={state['gate_summary']['count_observation']}"
    )

    return state
