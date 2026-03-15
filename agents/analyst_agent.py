"""
Agente #5: Analista — Predictor de resultados

El mejor analista deportivo del mundo. Consume todos los insumos del pipeline
(stats, insights YouTube, fixtures, odds) y genera predicciones 1X2 para cada
partido próximo con confianza, score estimado, factores clave y de riesgo.

OPTIMIZACIÓN: 1 sola llamada LLM por competencia (batch).

Entradas esperadas en el estado:
- fixtures: lista de partidos próximos
- stats_by_team: estadísticas ESPN normalizadas (capa 1 + 2)
- insights: insights YouTube + LLM por equipo
- odds_canonical: cuotas 1X2 del mercado
- competitions: lista de competencias

Salidas en el estado:
- predictions: lista de predicciones por partido
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

from state import AgentState
from agents.analyst_web_check import run_analyst_web_check
from utils.normalizer import TeamNormalizer
from utils.token_tracker import TokenTrackingCallbackHandler

logger = logging.getLogger(__name__)
team_normalizer = TeamNormalizer()


def _team_ref_tokens(team_name: str) -> set[str]:
    """
    Tokens distintivos para detectar si una señal parece referirse al equipo correcto.
    Evita sobrepeso de palabras genéricas como 'club', 'fc', etc.
    """
    cleaned = team_normalizer.clean(team_name or "")
    if not cleaned:
        return set()
    stop = {
        "fc", "cf", "sc", "club", "de", "del", "la", "el", "ud", "ac", "bc",
        "universidad", "deportes", "saint",
    }
    return {tok for tok in cleaned.split() if tok and tok not in stop and len(tok) > 2}


def _signal_team_match_scores(team_name: str, text: str) -> tuple[int, set[str]]:
    """Puntúa coincidencia de una señal con un equipo según tokens distintivos."""
    tokens = _team_ref_tokens(team_name)
    if not tokens:
        return 0, set()
    t = str(text or "").lower()
    matched = {tok for tok in tokens if tok in t}
    return len(matched), matched


def _looks_like_opponent_context(text: str, target_team: str, opponent_team: str) -> bool:
    """
    Heurística para detectar señales que mencionan al equipo target solo como contexto del rival
    (ej: "X volvió ... contra Atalanta"), pero la señal realmente trata del rival.
    """
    t = str(text or "").lower()
    target_tokens = _team_ref_tokens(target_team)
    opp_tokens = _team_ref_tokens(opponent_team)
    if not t or not target_tokens or not opp_tokens:
        return False

    target_mentions = sum(1 for tok in target_tokens if tok in t)
    opp_mentions = sum(1 for tok in opp_tokens if tok in t)
    versus_markers = [" vs ", "contra ", "frente a ", "ante "]
    has_versus = any(m in t for m in versus_markers)

    # Si el rival aparece más que el target y además hay marcadores de cruce,
    # es muy probable que el target esté mencionado solo como contexto del partido.
    return has_versus and opp_mentions > target_mentions


def _analyst_web_check_enabled() -> bool:
    """Flag para habilitar web-check puntual del analista (off por defecto)."""
    return str(os.getenv("ENABLE_ANALYST_WEB_CHECK", "")).strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def _analyst_web_check_force_test() -> bool:
    """
    Modo de prueba para forzar 1 web-check aunque el trigger normal no lo requiera.
    Útil para validar UI + pipeline sin degradar la lógica de producción.
    """
    return str(os.getenv("ANALYST_WEB_CHECK_FORCE_TEST", "")).strip().lower() in {"1", "true", "yes", "on"}


def _analyst_web_check_disable_normal_trigger() -> bool:
    """Permite desactivar trigger normal para pruebas controladas del FORCE TEST."""
    return str(os.getenv("ANALYST_WEB_CHECK_DISABLE_NORMAL_TRIGGER", "")).strip().lower() in {"1", "true", "yes", "on"}


def _analyst_web_check_force_all() -> bool:
    """Flag para forzar búsqueda web en TODOS los partidos del ciclo."""
    return str(os.getenv("ANALYST_WEB_CHECK_FORCE_ALL", "")).strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def _select_web_check_candidate(
    home_team: str,
    away_team: str,
    home_insights: Optional[dict],
    away_insights: Optional[dict],
) -> Optional[dict]:
    """
    Trigger simple (v1): confirma solo señales acotadas de bajas/sanciones/castigos.
    Prioriza rumores y luego señales críticas sin corroboración web.
    """
    candidate_types = {"injury_news", "disciplinary_issue", "home_venue_issue", "coach_change"}

    def _scan(team_name: str, opponent_name: str, team_ins: Optional[dict]) -> list[dict]:
        out = []
        for sig in (team_ins or {}).get("context_signals") or []:
            if not isinstance(sig, dict):
                continue
            sig_type = str(sig.get("type") or "other").strip().lower()
            if sig_type not in candidate_types:
                continue
            prov = sig.get("provenance") or sig.get("source") or []
            if isinstance(prov, str):
                prov = [prov]
            prov_set = {str(p).strip().lower() for p in prov if str(p).strip()}
            is_rumor = bool(sig.get("is_rumor", False))
            has_web = "web" in prov_set or "analyst_web_check" in prov_set
            evidence_text = str(sig.get("evidence") or "").lower()
            signal_text = str(sig.get("signal") or "").lower()
            joined_text = f"{signal_text} {evidence_text}".strip()
            own_score, _ = _signal_team_match_scores(team_name, joined_text)
            opp_score, _ = _signal_team_match_scores(opponent_name, joined_text)
            # Si la señal menciona más claramente al rival que al equipo dueño del payload, no usarla como seed.
            if opp_score > own_score and opp_score > 0:
                continue
            if _looks_like_opponent_context(joined_text, team_name, opponent_name):
                continue
            try:
                conf = float(sig.get("confidence", 0.4))
            except Exception:
                conf = 0.4

            # Trigger quirúrgico (v2):
            # - rumores
            # - señales críticas sin soporte web
            # - o dudas/no confirmado con confianza media-baja
            text_has_uncertainty = any(tok in (evidence_text + " " + signal_text) for tok in [
                "duda", "no confirmado", "rumor", "podria", "podría", "en duda", "pendiente"
            ])
            should_check = (
                is_rumor
                or (not has_web and sig_type in {"injury_news", "disciplinary_issue", "home_venue_issue"})
                or (text_has_uncertainty and conf < 0.8 and sig_type in candidate_types)
            )
            if not should_check:
                continue

            score = 0
            if is_rumor:
                score += 100
            if not has_web:
                score += 50
            if text_has_uncertainty:
                score += 25
            if sig_type == "injury_news":
                score += 20
            elif sig_type == "disciplinary_issue":
                score += 15
            if conf < 0.7:
                score += 10
            out.append({
                "team": team_name,
                "signal": sig,
                "score": score,
            })
        return out

    candidates = _scan(home_team, away_team, home_insights) + _scan(away_team, home_team, away_insights)
    if not candidates:
        return None
    candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
    top = candidates[0]
    sig = top["signal"]
    team = top["team"]
    s_type = str(sig.get("type") or "other")
    s_text = str(sig.get("signal") or "").strip()
    question = f"Confirmar estado actual de {team}: {s_type} - {s_text}"
    if s_type == "injury_news":
        question = f"Confirmar lesión/duda médica y tiempo estimado de baja en {team}: {s_text}"
    elif s_type == "disciplinary_issue":
        question = f"Confirmar suspensión/expulsión/castigo vigente en {team}: {s_text}"
    elif s_type == "home_venue_issue":
        question = f"Confirmar castigo de localía/estadio o restricción vigente en {team}: {s_text}"
    return {"team": team, "question": question, "seed_signal": sig}


def _select_web_check_candidate_force_test(
    home_team: str,
    away_team: str,
    home_insights: Optional[dict],
    away_insights: Optional[dict],
) -> Optional[dict]:
    """
    Selector laxo para pruebas: toma la primera señal de contexto disponible que sea
    razonablemente verificable (prioriza bajas/sanciones, pero permite otras).
    """
    preferred_types = {"injury_news", "disciplinary_issue", "home_venue_issue", "coach_change", "other"}
    for team_name, opponent_name, team_ins in ((home_team, away_team, home_insights), (away_team, home_team, away_insights)):
        for sig in (team_ins or {}).get("context_signals") or []:
            if not isinstance(sig, dict):
                continue
            sig_type = str(sig.get("type") or "other").strip().lower()
            sig_text = str(sig.get("signal") or "").strip()
            if not sig_text or sig_type not in preferred_types:
                continue
            joined_text = f"{sig_text} {str(sig.get('evidence') or '')}"
            own_score, _ = _signal_team_match_scores(team_name, joined_text)
            opp_score, _ = _signal_team_match_scores(opponent_name, joined_text)
            if opp_score > own_score and opp_score > 0:
                continue
            if _looks_like_opponent_context(joined_text, team_name, opponent_name):
                continue
            # En FORCE TEST, exigir algo de anclaje real al equipo para señales de bajas/sanciones.
            if sig_type in {"injury_news", "disciplinary_issue"} and own_score <= 0:
                continue
            question = f"Verificar si sigue vigente/confirmada esta señal para {team_name}: {sig_text}"
            return {"team": team_name, "question": question, "seed_signal": sig}
    return None


def _extract_person_names_from_signal(seed_signal: dict) -> list[str]:
    """
    Extrae nombres propios simples desde signal/evidence para pedir contexto de jugador/persona.
    Heurística conservadora: secuencias de 2+ palabras con mayúscula inicial.
    """
    text = f"{seed_signal.get('signal') or ''} | {seed_signal.get('evidence') or ''}"
    if not text.strip():
        return []
    # Nombres tipo "Lucas Assadi", "Arturo Vidal", "Emre Can"
    matches = re.findall(r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,2})\b", text)
    # Filtrar palabras/frases comunes que no son personas
    blacklist = {
        "Champions League", "Copa Libertadores", "Superclásico", "Liga De", "Universidad De",
        "Borussia Dortmund", "Real Madrid", "Atalanta BC", "Benfica", "U De", "Ucl",
    }
    out = []
    seen = set()
    for m in matches:
        name = m.strip()
        if name in blacklist:
            continue
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append(name)
    return out[:2]


def _build_analyst_web_check_questions(team: str, candidate: dict) -> list[str]:
    """
    Construye 1-2 preguntas para el web-check:
    - confirmación de señal
    - (opcional) referencia de jugador/persona para contexto del analista
    """
    q = [str(candidate.get("question") or "").strip()]
    seed_signal = candidate.get("seed_signal") or {}
    sig_type = str(seed_signal.get("type") or "other").strip().lower()
    if sig_type in {"injury_news", "disciplinary_issue", "other"}:
        for person in _extract_person_names_from_signal(seed_signal):
            q.append(
                f"¿Quién es {person} en {team} y qué rol/importancia tiene para el equipo (titular, figura, goleador, capitán, etc.)?"
            )
            break
    return [x for x in q if x][:2]


def _merge_analyst_web_check_signals(team_insights: Optional[dict], check_result: Optional[dict]) -> Optional[dict]:
    """Inyecta señales del analyst_web_check en insights del equipo sin duplicar."""
    if not isinstance(team_insights, dict) or not isinstance(check_result, dict):
        return team_insights
    checks = ((check_result.get("data") or {}).get("checks") or [])
    if not checks:
        return team_insights

    merged = dict(team_insights)
    ctx = list(merged.get("context_signals") or [])
    existing_keys = set()
    for sig in ctx:
        if not isinstance(sig, dict):
            continue
        key = (
            str(sig.get("type") or "other").strip().lower(),
            str(sig.get("signal") or "").strip().lower(),
            str(sig.get("date") or "").strip()[:10],
        )
        existing_keys.add(key)

    added = 0
    for chk in checks:
        if not isinstance(chk, dict):
            continue
        for sig in (chk.get("context_signals") or []):
            if not isinstance(sig, dict):
                continue
            key = (
                str(sig.get("type") or "other").strip().lower(),
                str(sig.get("signal") or "").strip().lower(),
                str(sig.get("date") or "").strip()[:10],
            )
            if key in existing_keys:
                continue
            ctx.append(sig)
            existing_keys.add(key)
            added += 1
    if added:
        merged["context_signals"] = ctx
        merged["source"] = str(merged.get("source") or "insights") + "+analyst_web_check"
    return merged


# ============================================================================
# LLM
# ============================================================================

def _make_llm() -> Optional[Any]:
    """Crea instancia del LLM según el factory."""
    try:
        from utils.llm_factory import get_llm
        return get_llm(
            temperature=0.3,
            callbacks=[TokenTrackingCallbackHandler()]
        )
    except Exception as e:
        logger.error(f"Fallo al inicializar el modelo en get_llm: {e}")
        return None


# ============================================================================
# CONSTRUCCIÓN DE CONTEXTO POR PARTIDO
# ============================================================================

def _find_team_stats(team_name: str, stats: list[dict]) -> Optional[dict]:
    """Busca stats de un equipo por nombre (fuzzy match)."""
    name_lower = team_name.lower().strip()
    for s in stats:
        if s.get("team", "").lower().strip() == name_lower:
            return s
    # Fuzzy: buscar contenido parcial
    for s in stats:
        s_name = s.get("team", "").lower().strip()
        if name_lower in s_name or s_name in name_lower:
            return s
    return None


def _find_team_insights(team_name: str, insights: list[dict]) -> Optional[dict]:
    """Busca insights de un equipo por nombre."""
    name_lower = team_name.lower().strip()
    for ins in insights:
        if not isinstance(ins, dict): continue
        if ins.get("team", "").lower().strip() == name_lower:
            return ins
    for ins in insights:
        if not isinstance(ins, dict): continue
        i_name = ins.get("team", "").lower().strip()
        if name_lower in i_name or i_name in name_lower:
            return ins
    return None


def _find_match_odds(home: str, away: str, odds: list[dict]) -> Optional[dict]:
    """
    Busca odds coincidente usando lógica difusa.
    """
    if not odds:
        return None
        
    # 1. Match Exacto de nombres normalizados
    target_slug = f"{home} vs {away}".lower().strip()
    
    for game in odds:
        # Check normal
        g_home = game.get('home_team', '')
        g_away = game.get('away_team', '')
        g_slug = f"{g_home} vs {g_away}".lower().strip()
        
        if g_slug == target_slug:
            return game
            
        # 2. Match Parcial (si ambos equipos están contenidos)
        # Soportar casos como "Club Atlético de Madrid" vs "Atlético Madrid"
        # Estrategia: Tokenizar y ver intersección
        
        # Simpler check: is sub-phrase?
        # Check home
        match_home = (g_home.lower() in home.lower()) or (home.lower() in g_home.lower())
        # Check away
        match_away = (g_away.lower() in away.lower()) or (away.lower() in g_away.lower())
        
        if match_home and match_away:
            return game
            
    return None


def _format_stats_context(stats: Optional[dict]) -> str:
    """Formatea stats de un equipo para el prompt."""
    if not stats:
        return "  Sin datos estadísticos disponibles."

    s = stats.get("stats", {})
    lines = []
    lines.append(f"  Posición: {s.get('position', '?')} | "
                 f"PJ={s.get('played', 0)} G={s.get('won', 0)} "
                 f"E={s.get('draw', 0)} P={s.get('lost', 0)} | "
                 f"GF={s.get('goals_for', 0)} GC={s.get('goals_against', 0)} "
                 f"DG={s.get('goal_difference', 0)} | Pts={s.get('points', 0)}")

    form = s.get("form", "")
    if form:
        lines.append(f"  Racha últimos partidos: {form}")

    ms = s.get("match_stats", {})
    if ms:
        lines.append(f"  Último partido — posesión: {ms.get('possession_pct', '?')}%, "
                     f"tiros: {ms.get('shots', '?')} ({ms.get('shots_on_target', '?')} al arco), "
                     f"corners: {ms.get('corners', '?')}, faltas: {ms.get('fouls', '?')}")

    rm = stats.get("recent_match", {})
    if rm and rm.get("opponent"):
        lines.append(f"  Último resultado: vs {rm['opponent']} {rm.get('score', '?')} "
                     f"({rm.get('home_away', '?')}) en {rm.get('venue', '?')}")

        for g in rm.get("goals", []):
            lines.append(f"    ⚽ {g.get('minute', '?')} {g.get('player', '?')} ({g.get('type', '')})")
        for g in rm.get("goals_against", []):
            lines.append(f"    ❌ {g.get('minute', '?')} {g.get('player', '?')} ({g.get('type', '')})")
        for c in rm.get("cards", []):
            emoji = "🔴" if c.get("card") == "red" else "🟡"
            lines.append(f"    {emoji} {c.get('minute', '?')} {c.get('player', '?')}")

        hl = rm.get("headline", "")
        if hl:
            lines.append(f"  📰 Recap: {hl[:200]}")

    scorers = stats.get("top_scorers", [])
    if scorers:
        sc_str = ", ".join([f"{sc['player']} ({sc['goals']}g)" for sc in scorers[:3]])
        lines.append(f"  Goleadores: {sc_str}")

    return "\n".join(lines)


def _format_insights_context(insights: Optional[dict]) -> str:
    """Formatea insights de un equipo para el prompt."""
    if not insights or not isinstance(insights, dict):
        return "  Sin análisis táctico disponible."

    lines = []
    if insights.get("as_of_date"):
        lines.append(f"  Fecha del insight (as_of): {insights.get('as_of_date')}")
    if insights.get("source"):
        lines.append(f"  Fuentes del insight (resumen): {insights.get('source')}")

    insight_text = insights.get("insight", "")
    if insight_text:
        # Aumentamos el límite para no perder señales contextuales relevantes.
        lines.append(f"  Análisis: {insight_text[:2000]}")

    # Nuevo: Información de confianza y citas
    meta = insights.get("insight_meta")
    if meta:
        conf = meta.get("confidence", 0.5)
        lines.append(f"  Confianza del Análisis: {conf*100:.0f}%")
        if meta.get("confidence_rationale"):
            lines.append(f"  Justificación Confianza: {meta.get('confidence_rationale')}")
        
        citations = meta.get("citations", [])
        if citations:
            lines.append("  Hechos citados:")
            for c in citations[:2]: # Top 2 citas
                if not isinstance(c, dict):
                    lines.append(f"    - \"{str(c)}\"")
                    continue
                ts = f" (min {c.get('timestamp')})" if c.get('timestamp') else ""
                lines.append(f"    - \"{c.get('text')}\"{ts}")

    forecast = insights.get("forecast")
    if forecast and isinstance(forecast, dict):
        lines.append(f"  Pronóstico YouTube: {forecast.get('outcome', '?')} "
                     f"(confianza: {forecast.get('confidence', '?')}) — "
                     f"{forecast.get('rationale', '')}")

    entities = insights.get("entities") or {}
    injuries = entities.get("injuries", [])
    suspensions = entities.get("suspensions", [])
    absences = entities.get("absences", [])
    if injuries or suspensions or absences:
        parts = []
        if injuries:
            parts.append(f"Lesionados: {', '.join(injuries)}")
        if suspensions:
            parts.append(f"Sancionados: {', '.join(suspensions)}")
        if absences:
            parts.append(f"Ausencias: {', '.join(absences)}")
        lines.append(f"  Bajas mencionadas: {' | '.join(parts)}")

    # NOTA: Las señales en `context_signals` ahora se renderizan a nivel de partido 
    # mediante _format_match_signals() separadas en limpias y sospechosas.

    return "\n".join(lines) if lines else "  Sin análisis táctico disponible."


def _format_match_signals(mc: dict) -> str:
    """
    Formatea las señales del partido dividiéndolas explícitamente en Limpias y Sospechosas.
    Aplica fallback si es una ejecución antigua que no particionó las señales.
    """
    clean = mc.get("signals_clean")
    suspicious = mc.get("signals_suspicious")
    summary = mc.get("signals_summary")
    
    # Fallback compatibilidad hacia atrás
    if clean is None and suspicious is None:
        home_sigs = mc.get("home", {}).get("insights", {}).get("context_signals", [])
        away_sigs = mc.get("away", {}).get("insights", {}).get("context_signals", [])
        clean = list(home_sigs) + list(away_sigs)
        suspicious = []
        summary = {
            "total": len(clean),
            "clean_count": len(clean),
            "suspicious_count": 0,
            "suspicious_ratio": 0.0,
            "top_suspicion_reasons": []
        }
    else:
        clean = clean or []
        suspicious = suspicious or []
        summary = summary or {
            "total": len(clean) + len(suspicious),
            "clean_count": len(clean),
            "suspicious_count": len(suspicious),
            "suspicious_ratio": 0.0,
            "top_suspicion_reasons": []
        }

    lines = []
    
    # 1. Limpias
    lines.append("SEÑALES LIMPIAS (Base de alta confianza)")
    lines.append("-" * 40)
    if clean:
        for s in clean[:15]: # Limitar para no saturar context window
            tm = s.get("team", "?")
            t_type = s.get("type", "other")
            text = s.get("signal", "")
            src = s.get("source_type", "unknown")
            lines.append(f"- [{tm}] {t_type} | {text} | src={src}")
    else:
        lines.append("- (Ninguna señal limpia reportada)")
        
    lines.append("")
        
    # 2. Sospechosas
    lines.append("SEÑALES SOSPECHOSAS (Información de precaución o dudosa)")
    lines.append("-" * 40)
    if suspicious:
        for s in suspicious[:10]:
            tm = s.get("team", "?")
            t_type = s.get("type", "other")
            text = s.get("signal", "")
            src = s.get("source_type", "unknown")
            reasons = ", ".join(s.get("suspicion_reasons", []))
            lines.append(f"- [{tm}] {t_type} | {text} | src={src} | reasons={reasons}")
    else:
        lines.append("- (Ninguna señal sospechosa detectada)")
        
    lines.append("")
        
    # 3. Resumen
    lines.append("RESUMEN DE SEÑALES (SUMMARY)")
    lines.append("-" * 40)
    lines.append(f"- total: {summary.get('total', 0)}")
    lines.append(f"- clean_count: {summary.get('clean_count', 0)}")
    lines.append(f"- suspicious_count: {summary.get('suspicious_count', 0)}")
    lines.append(f"- suspicious_ratio: {summary.get('suspicious_ratio', 0.0)}")
    
    top_reasons = summary.get('top_suspicion_reasons', [])
    if top_reasons:
        lines.append(f"- top_suspicion_reasons: {', '.join(top_reasons)}")
        
    return "\n".join(lines)


def _format_odds_context(odds_event: Optional[dict]) -> str:
    """
    Formatea las odds de un partido para el prompt del analista.
    Incluye probabilidades implícitas ya calculadas y el favorito del mercado,
    para que el modelo pueda usarlas como ancla bayesiana directamente.
    """
    if not odds_event:
        return "  Sin cuotas disponibles. ATENCIÓN: sin cuotas, usa la distribución histórica como base."

    lines = []
    bookmakers = odds_event.get("bookmakers", [])

    home_odds_vals, draw_odds_vals, away_odds_vals = [], [], []

    for bk in bookmakers:
        h = bk.get("home_odds")
        d = bk.get("draw_odds")
        a = bk.get("away_odds")
        if isinstance(h, (int, float)) and h > 1: home_odds_vals.append(h)
        if isinstance(d, (int, float)) and d > 1: draw_odds_vals.append(d)
        if isinstance(a, (int, float)) and a > 1: away_odds_vals.append(a)

    if not home_odds_vals:
        # Fallback: leer del primer bookmaker con estructura markets
        for bk in bookmakers:
            for mkt in bk.get("markets", []):
                if mkt.get("key") == "h2h":
                    for o in mkt.get("outcomes", []):
                        name = (o.get("name") or "").lower()
                        price = o.get("price")
                        if not isinstance(price, (int, float)) or price <= 1:
                            continue
                        if "draw" in name or "empate" in name:
                            draw_odds_vals.append(price)
                        elif name == (odds_event.get("home_team") or "").lower():
                            home_odds_vals.append(price)
                        else:
                            away_odds_vals.append(price)

    if not home_odds_vals:
        return "  Sin cuotas disponibles."

    # Usar mejor cuota promedio disponible entre casas
    best_home = min(home_odds_vals) if home_odds_vals else None
    best_draw = min(draw_odds_vals) if draw_odds_vals else None
    best_away = min(away_odds_vals) if away_odds_vals else None

    def impl_prob(o):
        return round((1 / o) * 100, 1) if o and o > 1 else None

    p_home = impl_prob(best_home)
    p_draw = impl_prob(best_draw)
    p_away = impl_prob(best_away)

    # Calcular suma para normalizar (margen del bookmaker)
    raw_sum = sum(p for p in [p_home, p_draw, p_away] if p is not None)
    def norm(p):
        return round(p / raw_sum * 100, 1) if p and raw_sum > 0 else None

    np_home = norm(p_home)
    np_draw = norm(p_draw)
    np_away = norm(p_away)

    bk_name = bookmakers[0].get("title", "Mercado") if bookmakers else "Mercado"
    n_bk = len(bookmakers)

    lines.append(f"  Fuente cuotas: {bk_name} ({n_bk} casas disponibles)")
    cuota_str = []
    if best_home: cuota_str.append(f"Local={best_home:.2f}")
    if best_draw: cuota_str.append(f"Empate={best_draw:.2f}")
    if best_away: cuota_str.append(f"Visitante={best_away:.2f}")
    lines.append(f"  Cuotas: {' | '.join(cuota_str)}")

    prob_str = []
    if np_home: prob_str.append(f"Local={np_home}%")
    if np_draw: prob_str.append(f"Empate={np_draw}%")
    if np_away: prob_str.append(f"Visitante={np_away}%")
    lines.append(f"  Probabilidades implícitas (normalizadas): {' | '.join(prob_str)}")

    # Favorito del mercado
    candidates = []
    if np_home: candidates.append(("LOCAL (1)", np_home))
    if np_draw: candidates.append(("EMPATE (X)", np_draw))
    if np_away: candidates.append(("VISITANTE (2)", np_away))
    if candidates:
        fav_name, fav_pct = max(candidates, key=lambda x: x[1])
        lines.append(f"  ⭐ FAVORITO DEL MERCADO: {fav_name} con {fav_pct}% de probabilidad implícita")

    return "\n".join(lines)


def _build_match_context(
    fixture: dict,
    stats: list[dict],
    insights: list[dict],
    odds: list[dict],
) -> Optional[dict]:
    """
    Construye el contexto completo de un partido para el prompt del analista.

    Returns:
        dict con home, away, context_text, o None si no se puede construir.
    """
    home = (fixture.get("home_team") or "").strip()
    away = (fixture.get("away_team") or "").strip()
    if not home or not away:
        return None

    match_date = fixture.get("match_date", fixture.get("commence_time", "?"))
    competition = fixture.get("competition", "?")

    home_stats = _find_team_stats(home, stats)
    away_stats = _find_team_stats(away, stats)
    home_insights = _find_team_insights(home, insights)
    away_insights = _find_team_insights(away, insights)
    match_odds = _find_match_odds(home, away, odds)

    # Reconstrucción dummy de match context para _format_match_signals con legacy format
    dummy_mc = {
        "home": {"insights": home_insights},
        "away": {"insights": away_insights}
    }

    ctx = f"""
PARTIDO: {home} vs {away}
Fecha: {match_date} | Competencia: {competition}

{home} (LOCAL):
{_format_stats_context(home_stats)}
{_format_insights_context(home_insights)}

{away} (VISITANTE):
{_format_stats_context(away_stats)}
{_format_insights_context(away_insights)}

CUOTAS DEL MERCADO:
{_format_odds_context(match_odds)}

{_format_match_signals(dummy_mc)}
"""

    return {
        "home": home,
        "away": away,
        "match_date": match_date,
        "competition": competition,
        "context": ctx,
    }


# ============================================================================
# MEMORIA DEL ANALISTA (lecciones aprendidas)
# ============================================================================

def _load_analyst_memory(competition: str) -> Optional[dict]:
    """
    Carga las lecciones aprendidas del archivo analyst_memory.json para la liga dada.
    Retorna el bloque de la liga, o None si no existe.
    """
    memory_file = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "predictions", "analyst_memory.json"
    )
    if not os.path.exists(memory_file):
        return None
    try:
        with open(memory_file, "r", encoding="utf-8") as f:
            memory = json.load(f)
        return memory.get("by_league", {}).get(competition)
    except Exception as e:
        logger.warning(f"No se pudo cargar analyst_memory.json: {e}")
        return None


def _format_memory_section(competition: str) -> str:
    """
    Formatea las lecciones de analyst_memory.json para incluirlas en el prompt.
    Retorna string vacío si no hay memoria disponible.
    """
    league_memory = _load_analyst_memory(competition)
    if not league_memory:
        return ""

    stats  = league_memory.get("stats", {})
    lessons= league_memory.get("lessons", [])
    top    = league_memory.get("top_lesson", "")
    cal    = league_memory.get("calibration_note", "")

    if not lessons and not top:
        return ""

    lines = [
        "",
        "═" * 60,
        f"LECCIONES APRENDIDAS DE PARTIDOS {competition} PASADOS (PRIORIDAD MUY ALTA)",
        "═" * 60,
        f"Basado en {stats.get('total', '?')} partidos evaluados "
        f"(precisión actual {competition}: {stats.get('accuracy', '?')}%)",
        "",
    ]

    if top:
        lines.append(f"★ LECCIÓN MAESTRA: {top}")
        lines.append("")

    if cal:
        lines.append(f"CALIBRACIÓN: {cal}")
        lines.append("")

    if lessons:
        lines.append("PATRONES DE ERROR HISTÓRICOS (aplícalos directamente):")
        for les in sorted(lessons, key=lambda x: {"alta": 0, "media": 1, "baja": 2}.get(x.get("severity", "baja"), 2)):
            sev = les.get("severity", "").upper()
            pat = les.get("pattern", "")
            desc= les.get("description", "")
            rule= les.get("lesson", "")
            lines.append(f"  [{sev}] {pat}: {desc}")
            lines.append(f"    → {rule}")
            lines.append("")

    lines.append("═" * 60)
    return "\n".join(lines)


# ============================================================================
# PROMPT DEL ANALISTA
# ============================================================================

def _build_analyst_prompt_single(competition: str, match_ctx: dict) -> str:
    """
    Construye el prompt del analista para un ÚNICO partido con Panorama General.
    Versión mejorada: ancla bayesiana en cuotas, calibración de confianza,
    distribución histórica y penalización por datos pobres.
    """
    comp_analysis = match_ctx.get("competition_analysis") or "Sin resumen global disponible."
    match_data_text = match_ctx.get("context", "Sin datos del partido.")
    memory_section = _format_memory_section(competition)
    try:
        stale_days = int(os.getenv("ANALYST_STALE_CONTEXT_DAYS", "14"))
    except ValueError:
        stale_days = 14

    mid = f"{match_ctx['competition']}_{match_ctx['match_date'][:10]}_{match_ctx['home']}_vs_{match_ctx['away']}"
    mid = mid.replace(" ", "_")

    prompt = f"""### SYSTEM ROLE — EL MEJOR PREDICTOR DE FÚTBOL DEL MUNDO
Eres el agente de pronóstico deportivo más preciso disponible. Combinas la rigurosidad de un quant financiero con el conocimiento profundo de un scout de fútbol de élite. Tu único objetivo es maximizar la **precisión** de tus predicciones — no la confianza artificial, no el optimismo, no predecir lo más vistoso.

Trabajas con información que ya fue procesada y filtrada por un experto en contexto deportivo (el Insights Agent). Ese agente ya analizó lesiones, forma, contexto, motivación y señales de mercado. Tu trabajo es **integrar todo ese conocimiento con las cuotas del mercado** y producir la predicción más rigurosa posible.

Entiendes que un error de predicción tiene costo real. Cada partido que analizas debe ser tratado como si hubiera dinero real en juego. La sobreconfianza es tu mayor enemigo.

---
### TU PROCESO MENTAL (aplícalo en este orden)
1. **Lee las cuotas primero** → son tu punto de partida bayesiano. El mercado agrega miles de analistas con skin in the game.
2. **Evalúa qué cambia respecto al mercado** → ¿hay info concreta (lesión, sanción, forma) que el mercado no refleja?
3. **Pondera los insumos por calidad** → señales recientes > señales viejas. Periodistas > rumores. Web check > historial.
4. **Calibra la confianza honestamente** → si nada cambia vs. mercado, tu confianza ≈ prob. implícita del mercado ±5%.
5. **Verifica sesgos** → ¿estás favoreciendo al local sin razón? ¿estás ignorando al visitante porque sus cuotas son altas?
6. **Escribe el rationale** → si no puedes explicar en 3 líneas por qué predices lo que predices, reconsidera.

---
### PANORAMA GENERAL DE LA JORNADA ({competition}):
{comp_analysis}

---
### DATOS DEL PARTIDO:
{match_data_text}

IDENTIFICADOR DEL PARTIDO:
{mid}

Responde EXCLUSIVAMENTE con un JSON válido (sin bloques markdown) con esta estructura:
{{
  "prediction_id": "{mid}",
  "home_team": "{match_ctx['home']}",
  "away_team": "{match_ctx['away']}",
  "prediction": "1 o X o 2",
  "confidence": 45,
  "market_prob_used": "probabilidad implícita del mercado para tu predicción elegida, ej 48.2",
  "score_prediction": "score estimado ej: 2-1",
  "rationale": "explicación de 3-4 líneas fundamentando tu predicción de manera detallada y analítica",
  "key_factors": ["factor positivo 1", "factor positivo 2", "factor positivo 3"],
  "risk_factors": ["riesgo 1", "riesgo 2"],
  "entities_impact": [
    {{"player": "nombre", "team": "equipo", "status": "lesionado/duda/sancionado", "impact": "alto/medio/bajo"}}
  ],
  "analyst_wishlist": [
    {{
      "need": "Descripción concisa de qué información te habría ayudado a decidir con más confianza",
      "category": "stats|injuries|form|tactical|context|h2h|market|other",
      "priority": "alta|media|baja",
      "teams_affected": ["nombre del equipo afectado"]
    }}
  ]
}}

Campo 'analyst_wishlist' OBLIGATORIO: Lista breve (1-4 ítems max) de lo que te faltó o mejoraría este pronóstico.
Ejemplos de wishlist válidos:
- "No tenía la alineación confirmada de Colo-Colo. Un reporte de equipo del último entrenamiento ayudaría."
- "Sin datos de los últimos 3 H2H en cancha de local. Los números históricos no estaban disponibles."
- "El parte médico de Mbappé es confúso. Necesito confirmación de si juega o no esta semana."
- "Sin estadísticas reales de ESPN para Everton de Viña Mar. Solo tuve la posición=99."
Si tenías todo lo que necesitabas y la predicción es sólida, puedes escribir: [{{'need': 'Datos suficientes', 'category': 'other', 'priority': 'baja', 'teams_affected': []}}]

════════════════════════════════════════════════════════════
REGLAS FUNDAMENTALES (LEER COMPLETO ANTES DE RESPONDER)
════════════════════════════════════════════════════════════

1. DISCERNIMIENTO DE SEÑALES (LIMPIAS vs SOSPECHOSAS):
   - Usa SEÑALES LIMPIAS como base prioritaria de tu análisis táctico y narrativo. Son verdades confirmadas.
   - Trata SEÑALES SOSPECHOSAS con extrema precaución. Son contexto de advertencia, rumor, o información contaminada/desactualizada.
   - NUNCA conviertas una señal sospechosa en hecho duro (Ej: no digas "Mbappé está lesionado" si la señal es sospechosa; di "Existe incertidumbre sobre Mbappé").
   - Si una señal sospechosa aborda un tema crítico (lesiones, castigos, fatiga), repórtala como INCERTIDUMBRE CRÍTICA en key_factors o risk_factors, no como hecho comprobado.
   - Si el 'suspicious_ratio' del resumen de señales es alto (ej > 0.3), o existen demasiados conflictos (ej duplicate_signals, mismatch), DEBES BAJAR TU CONVICCIÓN (confidence), porque estás prediciendo a ciegas bajo niebla. El reasoning debe reflejar cautela explícita frente a datos confusos.

2. ANCLA BAYESIANA — CUOTAS DEL MERCADO (PRIORIDAD MÁXIMA):
   - Las probabilidades implícitas que aparecen en las CUOTAS DEL MERCADO al final del contexto
     son el MEJOR PREDICTOR DISPONIBLE. Representan el consenso de miles de analistas con dinero real.
   - TU PUNTO DE PARTIDA OBLIGATORIO es el favorito del mercado (⭐ FAVORITO DEL MERCADO).
   - SOLO debes apartarte del favorito del mercado si tienes evidencia CONCRETA, RECIENTE y LIMPIA:
       * Lesión confirmada (SEÑAL LIMPIA) de un titular clave no reflejada en las cuotas
       * Sanción o suspensión confirmada (SEÑAL LIMPIA) que el mercado no ha descontado
       * Ventaja táctica o de localía extrema demostrable
   - Si no tienes evidencia limpia como las anteriores, TU PREDICCIÓN DEBE COINCIDIR con el mercado.

3. CALIBRACIÓN DE CONFIANZA (CRÍTICO):
   - `confidence` es tu estimación de probabilidad real del resultado (escala 0-100).
   - Si no tienes evidencia limpia que contradiga al mercado: confidence ≈ prob. implícita ± 5%.
   - Para superar confidence >= 70% necesitas justificación EXPLÍCITA en key_factors apoyada 100% en SEÑALES LIMPIAS.
   - PENALIZACIONES OBLIGATORIAS en confidence:
       * 'suspicious_ratio' > 0.35: -10 puntos (niebla informativa).
       * Datos de stats con posición=99 (sin datos reales de ESPN): -12 puntos
       * Forma vacía o desconocida de algún equipo: -8 puntos
       * Sin insights de YouTube/Web para esta jornada: -5 puntos

4. DISTRIBUCIÓN HISTÓRICA (BASE):
   - En CHI1: ~40% victorias local | ~27% empates | ~33% victorias visitante
   - En UCL fase eliminatoria: ~45% local | ~24% empates | ~31% visitante
   - Si las cuotas muestran empate con probabilidad implícita >= 28%, el empate es plausible. NO lo descartes sin evidencia limpia.

5. PONDERACIÓN TEMPORAL Y DE FUENTES:
   - Usa fechas (as_of_date, date) para ponderar relevancia. Contexto > {stale_days} días vale menos, salvo cambios estructurales (cambio DT).
   - Prioridad de Fuentes LIMPIAS: youtube/web > history.
   - Señales [RUMOR] / SOSPECHOSAS: peso enormemente reducido. NUNCA pueden gatillar una decisión contra-mercado por sí solas.

6. REGLA DE ORO FINAL:
   - Es mejor predecir con 55% de confianza real que con 75% de confianza inventada sobre señales sospechosas.
   - Prefiere precisión a seguridad ficticia. Una predicción humilde y correcta vale más que una audaz e incorrecta.
   - Responde SOLO con el JSON, sin texto adicional.
{_format_memory_section(competition)}"""

    return prompt



# ============================================================================
# BITÁCORA DEL ANALISTA (wishlist persistente)
# ============================================================================

ANALYST_WISHLIST_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "predictions", "analyst_wishlist.json"
)


def _wishlist_dedup_key(item: dict) -> str:
    """Genera una clave única para una entrada de wishlist (evitar duplicados)."""
    need = str(item.get("need") or "").lower().strip()
    category = str(item.get("category") or "other").lower().strip()
    # Normalizar: quitar artículos y palabras comunes, tomar primeros 60 chars
    import re as _re
    normalized = _re.sub(r"\b(el|la|los|las|de|del|que|en|un|una|y|o|a|con|por|para|sin)\b", "", need)
    normalized = _re.sub(r"\s+", " ", normalized).strip()[:80]
    return f"{category}::{normalized}"


def _persist_analyst_wishlist(
    wishlist_items: list[dict],
    competition: str,
    home_team: str,
    away_team: str,
    match_date: str,
) -> None:
    """
    Persiste las entradas de wishlist del Analista en analyst_wishlist.json.
    Deduplica por clave semántica normalizada para no repetir ideas estructuralmente similares.
    """
    if not wishlist_items:
        return

    os.makedirs(os.path.dirname(ANALYST_WISHLIST_FILE), exist_ok=True)

    # Cargar wishlist existente
    existing: list[dict] = []
    existing_keys: set[str] = set()
    if os.path.exists(ANALYST_WISHLIST_FILE):
        try:
            with open(ANALYST_WISHLIST_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
            for entry in existing:
                for item in entry.get("items", []):
                    existing_keys.add(_wishlist_dedup_key(item))
        except Exception as e:
            logger.warning(f"No se pudo leer analyst_wishlist.json: {e}")
            existing = []

    # Filtrar items que aporten ideas nuevas
    new_items = []
    skip_phrases = {"datos suficientes", "información suficiente", "sin necesidades", "todo disponible"}
    for item in wishlist_items:
        need_text = str(item.get("need") or "").strip()
        if not need_text:
            continue
        # Omitir respuestas de "todo bien"
        if any(skip in need_text.lower() for skip in skip_phrases):
            continue
        key = _wishlist_dedup_key(item)
        if key not in existing_keys:
            new_items.append(item)
            existing_keys.add(key)

    if not new_items:
        logger.debug("analyst_wishlist: sin ideas nuevas para agregar (todas ya registradas o triviales)")
        return

    # Crear entrada del partido
    entry = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "competition": competition,
        "match": f"{home_team} vs {away_team}",
        "match_date": match_date[:10] if match_date else "",
        "items": new_items,
    }
    existing.insert(0, entry)  # Más reciente primero

    # Limitar a los últimos 200 entries para no crecer infinito
    existing = existing[:200]

    try:
        with open(ANALYST_WISHLIST_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        logger.info(f"  ✒ Bitácora Analista: {len(new_items)} nueva(s) necesidad(es) registrada(s) — {home_team} vs {away_team}")
    except Exception as e:
        logger.warning(f"No se pudo guardar analyst_wishlist.json: {e}")



def _parse_predictions(response_text: str) -> list[dict]:
    """Parsea la respuesta JSON del LLM con una ÚNICA predicción."""
    content = response_text.strip()

    # Limpiar posibles bloques markdown
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*\n?", "", content)
        content = re.sub(r"\n?```\s*$", "", content)

    try:
        data = json.loads(content)
        if isinstance(data, dict):
            if "predictions" in data:
                return data["predictions"]
            elif "prediction_id" in data:
                return [data] # Era un solo objeto, lo envolvemos en lista
        if isinstance(data, list):
            return data
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse error in analyst response: {e}")

    return []


# ============================================================================
# PERSISTENCIA HISTÓRICA
# ============================================================================

def _save_predictions_history(predictions: list[dict]):
    """
    Guarda predicciones en el historial acumulado (JSON y CSV).
    Append sin duplicados (por prediction_id).
    """
    history_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "predictions"
    )
    history_file_json = os.path.join(history_dir, "predictions_history.json")
    history_file_csv = os.path.join(history_dir, "predictions_history.csv")

    # Crear directorio si no existe
    os.makedirs(history_dir, exist_ok=True)

    # 1. Cargar historial existente (JSON)
    existing = []
    if os.path.exists(history_file_json):
        try:
            with open(history_file_json, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = []

    # IDs existentes
    existing_ids = {p.get("prediction_id") for p in existing}

    # 2. Agregar nuevas predicciones (con campos enriquecidos para retroalimentación)
    added = 0
    for pred in predictions:
        pid = pred.get("prediction_id")
        if pid and pid not in existing_ids:
            # Detectar flags de calidad de datos
            data_quality_flags = []
            home_pos = pred.get("home_pos")
            away_pos = pred.get("away_pos")
            if home_pos == 99 or home_pos is None:
                data_quality_flags.append("home_pos_99")
            if away_pos == 99 or away_pos is None:
                data_quality_flags.append("away_pos_99")
            if not pred.get("had_youtube_insights"):
                data_quality_flags.append("no_youtube_insights")
            if not pred.get("had_espn_stats"):
                data_quality_flags.append("no_espn_stats")

            pred_record = {
                # Identificación
                "prediction_id": pid,
                "competition": pred.get("competition"),
                "generated_at": pred.get("generated_at"),
                "match_date": pred.get("match_date"),
                "home_team": pred.get("home_team"),
                "away_team": pred.get("away_team"),
                # Predicción
                "prediction": pred.get("prediction"),
                "confidence": pred.get("confidence"),
                "market_prob_used": pred.get("market_prob_used"),
                "score_prediction": pred.get("score_prediction"),
                # Razonamiento completo (para retroalimentación)
                "rationale": pred.get("rationale"),
                "key_factors": pred.get("key_factors", []),
                "risk_factors": pred.get("risk_factors", []),
                # Contexto de calidad de datos en el momento de predecir
                "home_pos": home_pos,
                "away_pos": away_pos,
                "home_form": pred.get("home_form"),
                "away_form": pred.get("away_form"),
                "had_youtube_insights": bool(pred.get("had_youtube_insights")),
                "had_espn_stats": bool(pred.get("had_espn_stats")),
                "data_quality_flags": data_quality_flags,
                # Modelo usado
                "analyst_model_id": pred.get("analyst_model_id"),
                # Resultado (llenado por Post-Match Agent)
                "result": None,
                "actual_score": None,
                "correct": None,
                "evaluated_at": None,
                "event_id": pred.get("event_id"),
                "evaluation_status": pred.get("evaluation_status"),
                # Retroalimentación (llenado por Post-Match Agent)
                "post_match_observation": None,
            }
            existing.append(pred_record)
            existing_ids.add(pid)
            added += 1

    if added == 0 and os.path.exists(history_file_csv):
        # Si no hay nada nuevo y el CSV ya existe, no hacemos nada extra
        return

    # 3. Guardar JSON
    with open(history_file_json, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    # 4. Guardar CSV (Acumulativo)
    try:
        import pandas as pd
        df = pd.DataFrame(existing)
        # Reordenar columnas para legibilidad
        cols = ["match_date", "competition", "home_team", "away_team", "prediction", "confidence", "score_prediction", "result", "correct", "generated_at", "prediction_id"]
        # Filtrar solo las que existen
        final_cols = [c for c in cols if c in df.columns]
        df[final_cols].to_csv(history_file_csv, index=False, encoding="utf-8-sig")
        logger.info(f"✓ Historial CSV actualizado: {history_file_csv}")
    except Exception as e:
        logger.warning(f"No se pudo generar el CSV: {e}")

    logger.info(f"Historial JSON: {added} nuevas predicciones (total: {len(existing)})")

    # 5. También guardar archivo diario (JSON únicamente)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_file = os.path.join(history_dir, f"{today}.json")
    daily_preds = [p for p in predictions if p.get("prediction_id")]
    with open(daily_file, "w", encoding="utf-8") as f:
        json.dump(daily_preds, f, indent=2, ensure_ascii=False)


# ============================================================================
# EXPORTACIÓN DE AUDITORÍA DE SEÑALES
# ============================================================================

def _export_signals_audit(match_contexts: list[dict]):
    """
    Fase 2 - Diagnóstico:
    Genera una exportación plana y auditable de TODAS las señales que entran al 
    Analyst Agent, permitiendo ver de dónde viene cada pieza de información, su tipo y conflicto.
    No afecta la lógica de predicción.
    """
    audit_file = "pipeline_signals_audit.json"
    partitioned_file = "pipeline_signals_partitioned.json"
    rows = []
    partitioned_data = []
    seen_texts = {}
    
    for mc in match_contexts:
        match_id = mc.get("match_id", "unknown")
        competition = mc.get("competition", "unknown")
        
        home_dict = mc.get("home") or {}
        away_dict = mc.get("away") or {}
        home_team = home_dict.get("canonical_name", "unknown")
        away_team = away_dict.get("canonical_name", "unknown")
        
        # Pre-pass: Collect observed players for each team to catch cross-talk
        def collect_observed_players(t_dict):
            observed = set()
            signals = t_dict.get("insights", {}).get("context_signals", [])
            for sig in signals:
                if not isinstance(sig, dict): continue
                
                p_raw = sig.get("player")
                sig_type = str(sig.get("type", "unknown"))
                if not p_raw and sig_type in {"injury_news", "disciplinary_issue"}:
                    pts = _extract_person_names_from_signal(sig)
                    if pts: p_raw = pts[0]
                
                if isinstance(p_raw, str):
                    p_clean = p_raw.strip().lower()
                    if p_clean and p_clean not in {"null", "none", "", "n/a", "unknown"}:
                        observed.add(p_clean)
            return observed
            
        home_observed_players = collect_observed_players(home_dict)
        away_observed_players = collect_observed_players(away_dict)
        
        # Helper to process team signals
        def process_team_signals(team_dict, target_team):
            insights = team_dict.get("insights") or {}
            signals = insights.get("context_signals") or []
            
            other_team = away_team if target_team == home_team else home_team
            
            for sig in signals:
                if not isinstance(sig, dict):
                    continue
                
                # --- CALCULAR SIGNAL SCOPE ---
                t_type = str(sig.get("type", "")).lower()
                t_text = str(sig.get("signal", "")).lower()
                
                scope = "unknown"
                is_opponent_type = "opponent" in t_type or "rival" in t_type
                mentions_opponent = _signal_team_match_scores(other_team, t_text)[0] > 0
                mentions_self = _signal_team_match_scores(target_team, t_text)[0] > 0
                
                global_words = ["carga de calendario", "contexto macro", "agenda", "jornada", "contexto general"]
                is_global = any(w in t_text for w in global_words)
                
                if is_opponent_type or mentions_opponent:
                    scope = "opponent"
                elif is_global:
                    scope = "match_global"
                elif mentions_self:
                    scope = "self"
                else:
                    scope = "unknown"
                    
                # Inyectar el scope en la señal original (para futura estructura intermedia)
                sig["signal_scope"] = scope
                # -----------------------------
                
                # Resolve source_name and source_type
                prov_raw = sig.get("provenance", [])
                if isinstance(prov_raw, str):
                    prov_raw = [prov_raw]
                
                # Si hay varias procedencias, duplicar la fila para hacerla verdaderamente plana y auditable,
                # o joining it. Let's join the names, but pick a primary type
                prov_str = ",".join(str(p) for p in prov_raw) if prov_raw else "unknown"
                
                source_type = "unknown"
                prov_joined = prov_str.lower()
                if "web" in prov_joined or "analyst_web_check" in prov_joined:
                    source_type = "web"
                elif "youtube" in prov_joined:
                    source_type = "youtube"
                elif "history" in prov_joined:
                    source_type = "history"
                elif "manual" in prov_joined:
                    source_type = "manual"
                
                # Attempt to extract player name if applicable
                player = None
                sig_type = str(sig.get("type", "unknown"))
                if sig_type in {"injury_news", "disciplinary_issue"}:
                    players = _extract_person_names_from_signal(sig)
                    if players:
                        player = players[0]
                
                # Clean null representations
                def clean_null(val):
                    if not isinstance(val, str): return val
                    v = val.strip().lower()
                    if v in {"null", "none", "", "n/a", "unknown"}: return None
                    return val
                
                player_clean = clean_null(player)
                date_clean = clean_null(str(sig.get("date", "")))
                
                # Determine subject_type
                subject_type = "unknown"
                t_text_lower = t_text
                if player_clean:
                    coach_keywords = ["tecnico", "técnico", "dt", "entrenador", "mister", "manager", "dirige"]
                    if any(k in t_text_lower for k in coach_keywords):
                        subject_type = "coach"
                    else:
                        subject_type = "player"
                else:
                    team_keywords = ["equipo", "plantilla", "club", "dirigencia", "local", "visitante", "plantel"]
                    comp_keywords = ["liga", "champions", "copa", "torneo", "jornada", "fecha", "calendario"]
                    case_keywords = ["caso", "juicio", "demanda", "investigacion", "sancion original", "fifa", "tas", "tribunal", "directiva", "financier", "quiebra"]
                    
                    if any(k in t_text_lower for k in case_keywords):
                        subject_type = "case"
                    elif any(k in t_text_lower for k in comp_keywords):
                        subject_type = "competition"
                    elif any(k in t_text_lower for k in team_keywords):
                        subject_type = "team"
                
                # Inyectar campos también en la señal intermedia previa al Analista
                sig["player"] = player_clean
                sig["subject_type"] = subject_type
                sig["team"] = target_team
                sig["source_type"] = source_type
                
                # --- CALCULAR SUSPICIOUS FLAGS ---
                is_suspicious = False
                raw_reasons = []
                
                # 1. team_not_in_match
                if target_team not in (home_team, away_team):
                    raw_reasons.append("team_not_in_match")
                    
                # 2. subject_type_type_mismatch
                mismatch_triggered = False
                if subject_type == "player" and sig_type in {"case", "competition_context", "legal_context", "managerial_context"}:
                    mismatch_triggered = True
                elif subject_type == "player":
                    mismatch_coach = ["dt", "técnico", "tecnico", "mister", "entrenador", "evalúa rotaciones", "evalua rotaciones", "política de no arriesgar", "politica de no arriesgar"]
                    mismatch_case = ["caso", "procesamiento", "justicia", "demanda", "sanción", "sancion", "fifa"]
                    if any(w in t_text_lower for w in mismatch_coach + mismatch_case):
                        mismatch_triggered = True
                elif subject_type == "competition" and sig_type in {"injury_news", "disciplinary_issue", "availability", "rotation"}:
                    mismatch_triggered = True
                elif subject_type in {"coach", "case"} and sig_type in {"form", "recent_form"}:
                    mismatch_triggered = True
                elif subject_type == "unknown":
                    import re
                    # Heurística simple para "nombre propio" evidente
                    if re.search(r'\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\b', str(sig.get("signal", ""))):
                        mismatch_triggered = True
                        
                if mismatch_triggered:
                    opponent_types = {"opponent_form", "opponent_crisis", "opponent_strength", "opponent_availability", "opponent_schedule", "opponent_context"}
                    if scope == "opponent" and sig_type in opponent_types and subject_type in {"unknown", "team"}:
                        # Suprimir falso positivo de rival
                        pass
                    else:
                        raw_reasons.append("subject_type_type_mismatch")
                    
                # 3. foreign_entity_in_team_signal
                if player_clean and subject_type == "player" and scope != "opponent":
                    p_lower = player_clean.lower()
                    opponent_observed = away_observed_players if target_team == home_team else home_observed_players
                    self_observed = home_observed_players if target_team == home_team else away_observed_players
                    
                    # If player name explicitly matches the opponent's team name
                    if _signal_team_match_scores(other_team, player_clean)[0] > 0:
                        raw_reasons.append("foreign_entity_in_team_signal")
                    # Or if the player is exclusively observed in the opponent's raw signals
                    elif p_lower in opponent_observed and p_lower not in self_observed:
                        raw_reasons.append("foreign_entity_in_team_signal")
                    # Or if the signal mentions the opponent explicitly, and player is not confirmed as ours
                    elif _signal_team_match_scores(other_team, t_text_lower)[0] > 0 and p_lower not in self_observed:
                        raw_reasons.append("foreign_entity_in_team_signal")
                
                # 4. stale_or_implausible_history_signal
                if source_type == "history":
                    stale_words = ["cambio de dt", "histórico", "historico", "pasó de", "paso de", "era de", "mitad de temporada", "asume capitanía", "asume capitania"]
                    if any(w in t_text_lower for w in stale_words):
                        raw_reasons.append("stale_or_implausible_history_signal")
                        
                # 5. missing_date_for_time_sensitive_signal
                time_sensitive_types = {"injury_news", "availability", "fatigue", "disciplinary_issue", "rotation", "schedule_load", "opponent_missing_players", "medical_doubt"}
                if not date_clean and sig_type in time_sensitive_types:
                    raw_reasons.append("missing_date_for_time_sensitive_signal")
                    
                # 6. possible_duplicate_signal
                import unicodedata
                import re
                def normalize_for_dedup(s):
                    s = str(s).lower()
                    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
                    s = re.sub(r'[^\w\s]', '', s).strip()
                    s = re.sub(r'\s+', ' ', s)
                    s = s.replace("la champions", "champions")
                    return s
                
                norm_text = normalize_for_dedup(t_text)
                group_key = f"{match_id}_{target_team}_{sig_type}"
                
                is_dup = False
                if group_key not in seen_texts:
                    seen_texts[group_key] = []
                else:
                    for past_text in seen_texts[group_key]:
                        if norm_text == past_text or norm_text in past_text or past_text in norm_text:
                            is_dup = True
                            break
                if is_dup:
                    raw_reasons.append("possible_duplicate_signal")
                else:
                    seen_texts[group_key].append(norm_text)
                
                # 7. scope_unknown_for_actionable_signal
                actionable_types = {"injury_news", "disciplinary_issue", "squad_availability", "heavy_rotation", "medical_doubt", "medical_ok", "fatigue", "form", "schedule_load", "coach_change"}
                if scope == "unknown" and sig_type in actionable_types:
                    if sig_type in {"form", "schedule_load"}:
                        if not date_clean or subject_type == "unknown":
                            raw_reasons.append("scope_unknown_for_actionable_signal")
                    else:
                        raw_reasons.append("scope_unknown_for_actionable_signal")
                    
                # 8. manual_signal_low_clarity
                if source_type == "manual" and (scope == "unknown" or subject_type == "unknown" or not date_clean):
                    raw_reasons.append("manual_signal_low_clarity")
                    
                # 9. opponent_scope_attached_to_team
                if scope == "opponent" and not is_opponent_type:
                    raw_reasons.append("opponent_scope_attached_to_team")
                    
                # 10. low_information_signal
                valid_signal_text = str(sig.get("signal", ""))
                if not valid_signal_text or len(valid_signal_text.strip()) < 12:
                    raw_reasons.append("low_information_signal")
                else:
                    generic_phrases = ["mal momento", "complicado", "buen momento", "en duda", "lesionado", "partido dificil", "sin informacion"]
                    if valid_signal_text.strip().lower() in generic_phrases:
                        raw_reasons.append("low_information_signal")
                        
                # Ordenar razones
                priority_order = [
                    "foreign_entity_in_team_signal",
                    "subject_type_type_mismatch",
                    "stale_or_implausible_history_signal",
                    "possible_duplicate_signal",
                    "missing_date_for_time_sensitive_signal",
                    "scope_unknown_for_actionable_signal",
                    "team_not_in_match",
                    "manual_signal_low_clarity",
                    "opponent_scope_attached_to_team",
                    "low_information_signal"
                ]
                suspicion_reasons = sorted(raw_reasons, key=lambda x: priority_order.index(x) if x in priority_order else 99)
                
                if suspicion_reasons:
                    is_suspicious = True
                    
                sig["is_suspicious"] = is_suspicious
                sig["suspicion_reasons"] = suspicion_reasons
                
                row = {
                    "match_id": match_id,
                    "competition": competition,
                    "home_team": home_team,
                    "away_team": away_team,
                    "team": target_team,
                    "player": player_clean,
                    "subject_type": subject_type,
                    "source_type": source_type,
                    "source_name": prov_str,
                    "type": sig_type,
                    "signal": str(sig.get("signal", "unknown")),
                    "date": date_clean,
                    "is_rumor": bool(sig.get("is_rumor", False)),
                    "signal_scope": scope,
                    "is_suspicious": is_suspicious,
                    "suspicion_reasons": suspicion_reasons,
                    "origin_file": "match_contexts",
                }
                rows.append(row)
                
        # Procesar primero para inyectar los flags en los diccionarios originales
        process_team_signals(home_dict, home_team)
        process_team_signals(away_dict, away_team)
        
        # --- PARTICIÓN DE SEÑALES ---
        # Consolidamos todas las señales del partido (home + away)
        all_match_signals = []
        if home_dict and "insights" in home_dict and "context_signals" in home_dict["insights"]:
            all_match_signals.extend(home_dict["insights"]["context_signals"])
        if away_dict and "insights" in away_dict and "context_signals" in away_dict["insights"]:
            all_match_signals.extend(away_dict["insights"]["context_signals"])
            
        signals_clean = []
        signals_suspicious = []
        reasons_counter = {}
        
        for sig in all_match_signals:
            if not isinstance(sig, dict): continue
            
            if sig.get("is_suspicious", False):
                signals_suspicious.append(sig)
                for r in sig.get("suspicion_reasons", []):
                    reasons_counter[r] = reasons_counter.get(r, 0) + 1
            else:
                signals_clean.append(sig)
                
        # Top reasons sorting
        sorted_reasons = sorted(reasons_counter.items(), key=lambda x: x[1], reverse=True)
        top_reasons = [k for k, v in sorted_reasons[:5]]
        
        total_sigs = len(signals_clean) + len(signals_suspicious)
        ratio = round(len(signals_suspicious) / total_sigs, 2) if total_sigs > 0 else 0.0
        
        summary = {
            "total": total_sigs,
            "clean_count": len(signals_clean),
            "suspicious_count": len(signals_suspicious),
            "suspicious_ratio": ratio,
            "top_suspicion_reasons": top_reasons
        }
        
        # Inyectar estructura particionada en el context de este partido
        mc["signals_clean"] = signals_clean
        mc["signals_suspicious"] = signals_suspicious
        mc["signals_summary"] = summary
        
        partitioned_data.append({
            "match_id": match_id,
            "home_team": home_team,
            "away_team": away_team,
            "signals_clean": signals_clean,
            "signals_suspicious": signals_suspicious,
            "signals_summary": summary
        })
        
    try:
        with open(audit_file, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
            
        with open(partitioned_file, "w", encoding="utf-8") as f:
            json.dump(partitioned_data, f, indent=2, ensure_ascii=False)
            
        logger.info(f"✓ Auditoría de señales exportada: {len(rows)} señales guardadas en {audit_file}")
        logger.info(f"✓ Partición de señales guardada en {partitioned_file}")
    except Exception as e:
        logger.warning(f"No se pudo guardar la auditoría de señales y/o partición: {e}")

# ============================================================================
# NODO PRINCIPAL DE LANGGRAPH
# ============================================================================

def analyst_agent_node(state: AgentState) -> AgentState:
    """
    Nodo LangGraph que genera predicciones para cada partido próximo.

    Proceso por competencia:
    1. Filtra fixtures de la competencia
    2. Construye contexto por partido (stats + insights + odds)
    3. Envía mega-prompt al LLM con todos los partidos
    4. Parsea predicciones y las asigna
    5. Guarda en historial para tracking

    OPTIMIZACIÓN: 1 llamada LLM por competencia.
    """
    logger.info("=" * 60)
    logger.info("ANALYST AGENT: generating match predictions")
    logger.info("=" * 60)

    predictions: list[dict] = []
    analyst_web_checks: list[dict] = []
    fixtures = state.get("fixtures") or []
    stats = state.get("stats_by_team") or []
    insights = state.get("insights") or []
    odds = state.get("odds_canonical") or []
    match_contexts = state.get("match_contexts") or []
    meta = state.get("meta", {})
    meta.setdefault("errors", {}).setdefault("analyst", {})

    # FASE 2 DIAGNÓSTICO: Exportar auditoría cruda antes de fusionarla/analizarla
    if match_contexts:
        _export_signals_audit(match_contexts)

    # Intentar crear LLM
    comp_predictions = []
    llm = _make_llm()
    if llm:
        logger.info("LLM disponible (GPT-5) — modo batch: 1 llamada por competencia")
    else:
        logger.warning("LLM no disponible — se generarán predicciones heurísticas")
    web_check_enabled = _analyst_web_check_enabled()
    web_check_force_test = _analyst_web_check_force_test()
    web_check_force_all = _analyst_web_check_force_all()
    web_check_disable_normal = _analyst_web_check_disable_normal_trigger()
    if web_check_enabled:
        logger.info("Analyst Web Check habilitado (on-demand, trigger acotado)")
        if web_check_force_all:
            logger.info("Analyst Web Check FORCE ALL habilitado: se verificará cada partido.")
        elif web_check_force_test:
            logger.info("Analyst Web Check FORCE TEST habilitado (forzará 1 verificación para validar flujo/UI)")
        if web_check_disable_normal:
            logger.info("Analyst Web Check normal trigger desactivado (modo test)")
    forced_test_consumed = False

    for comp in state.get("competitions", []):
        label = comp.get("competition")
        # Extraer análisis macro (panorama) de la competencia desde los insights
        comp_analysis = ""
        if isinstance(insights, list):
            for ins in insights:
                if isinstance(ins, dict) and ins.get("competition") == label and ins.get("competition_analysis"):
                    comp_analysis = ins.get("competition_analysis")
                    break
        else:
            logger.warning(f"insights state is not a list, got {type(insights).__name__}")

        # Fixtures de esta competencia
        comp_fixtures = [f for f in fixtures if f.get("competition") == label]

        if not comp_fixtures:
            # Fallback: deducir partidos de odds
            comp_odds = [ev for ev in odds if ev.get("competition") == label]
            if comp_odds:
                logger.info(f"No fixtures for {label}, using {len(comp_odds)} odds events as fixtures")
                comp_fixtures = comp_odds
            else:
                logger.info(f"No fixtures or odds for {label}, skipping predictions")
                continue

        logger.info(f"Building context for {len(comp_fixtures)} matches in {label}")

        # Construir contexto por partido
        # PRIORIDAD: usar match_contexts del normalizer_agent si están disponibles
        match_contexts_map = {}
        match_contexts_by_key = {}
        for mc in (state.get("match_contexts") or []):
            if mc.get("competition") == label:
                home = mc["home"]["canonical_name"]
                away = mc["away"]["canonical_name"]
                match_contexts_map[f"{home}_{away}"] = mc
                if mc.get("match_key"):
                    match_contexts_by_key[mc["match_key"]] = mc

        matches_ctx = []
        for fix in comp_fixtures:
            home = (fix.get("home_team") or "").strip()
            away = (fix.get("away_team") or "").strip()
            
            # Intentar usar MatchContext del normalizador
            mc = None
            if fix.get("match_key") and fix.get("match_key") in match_contexts_by_key:
                mc = match_contexts_by_key[fix["match_key"]]
                logger.info(f"  🔗 MatchContext por match_key: {fix.get('match_key')}")
            if mc is None:
                mc = match_contexts_map.get(f"{home}_{away}")
                if mc:
                    logger.info(f"  🔗 MatchContext por nombres: {home} vs {away}")
            if mc:
                # Formatear desde MatchContext ya normalizado
                home_stats = mc["home"].get("stats")
                away_stats = mc["away"].get("stats")
                home_insights = mc["home"].get("insights")
                away_insights = mc["away"].get("insights")
                # Web-check puntual del analista (v1): confirmar rumores/bajas/sanciones acotadas.
                if web_check_enabled:
                    candidate = None if web_check_disable_normal else _select_web_check_candidate(home, away, home_insights, away_insights)
                    
                    # Lógica de forzado
                    if candidate is None:
                        if web_check_force_all:
                            # Candidato genérico para FORCE ALL
                            candidate = {
                                "team": home, 
                                "question": f"Verificar noticias de última hora, bajas de último minuto o cambios en la alineación titular de {home} para el partido contra {away} hoy.",
                                "seed_signal": {"type": "other", "signal": "Fuerza búsqueda global"}
                            }
                            logger.info("  🧪 Analyst Web Check FORCE ALL: generando consulta genérica para %s", home)
                        elif web_check_force_test and not forced_test_consumed:
                            candidate = _select_web_check_candidate_force_test(home, away, home_insights, away_insights)
                            if candidate:
                                logger.info("  🧪 Analyst Web Check FORCE TEST: se forzó candidato para %s", candidate["team"])
                                
                    if candidate:
                        try:
                            req = {
                                "match_id": mc.get("match_id"),
                                "competition": label,
                                "home_team": home,
                                "away_team": away,
                                "lookback_days": int(os.getenv("ANALYST_WEB_CHECK_LOOKBACK_DAYS", "7")),
                                "questions": _build_analyst_web_check_questions(candidate["team"], candidate),
                                "trigger_reason": "confirm_critical_signal",
                                "source_context": {
                                    "target_team": candidate["team"],
                                    "seed_signal": candidate.get("seed_signal"),
                                },
                            }
                            
                            # LOGGING EXPLÍCITO SOLICITADO POR ÁLVARO
                            logger.info("="*40)
                            logger.info(f"[WEB_QUERY] {candidate['team']}: {req['questions']}")
                            
                            web_check_result = run_analyst_web_check(req)
                            
                            if web_check_result and web_check_result.get("data"):
                                chks = web_check_result["data"].get("checks", [])
                                if chks:
                                    ans = chks[0].get("answer_summary", "Sin respuesta clara")
                                    logger.info(f"[WEB_RESPONSE] {ans}")
                            logger.info("="*40)
                            
                            analyst_web_checks.append({
                                "match_id": mc.get("match_id"),
                                "competition": label,
                                "home_team": home,
                                "away_team": away,
                                "target_team": candidate["team"],
                                "request": req,
                                "result": web_check_result,
                            })
                            if web_check_result.get("ok"):
                                if web_check_force_test and not forced_test_consumed:
                                    forced_test_consumed = True
                                if candidate["team"] == home:
                                    home_insights = _merge_analyst_web_check_signals(home_insights, web_check_result)
                                elif candidate["team"] == away:
                                    away_insights = _merge_analyst_web_check_signals(away_insights, web_check_result)
                                logger.info("  🔎 Analyst Web Check aplicado para %s (%s vs %s)", candidate["team"], home, away)
                            else:
                                if web_check_force_test and not forced_test_consumed:
                                    forced_test_consumed = True
                                logger.warning("  ⚠ Analyst Web Check sin resultado válido para %s", candidate["team"])
                        except Exception as e:
                            if web_check_force_test and not forced_test_consumed:
                                forced_test_consumed = True
                            logger.warning("  ⚠ Analyst Web Check falló para %s vs %s: %s", home, away, e)
                odds_info = mc.get("odds")
                
                odds_str = "  Sin cuotas disponibles."
                if odds_info:
                    odds_str = (
                        f"  Local: {odds_info.get('home_odds')} | "
                        f"Empate: {odds_info.get('draw_odds')} | "
                        f"Visita: {odds_info.get('away_odds')} "
                        f"({odds_info.get('bookmaker', '?')}, {odds_info.get('bookmakers_count', '?')} casas)"
                    )
                
                ctx_text = f"""
PARTIDO: {home} vs {away} [ID: {mc.get('match_id')}]
Fecha: {mc.get('match_date', '?')} | Competencia: {label}

{home} (LOCAL):
{_format_stats_context(home_stats)}
{_format_insights_context(home_insights)}

{away} (VISITANTE):
{_format_stats_context(away_stats)}
{_format_insights_context(away_insights)}

CUOTAS DEL MERCADO:
{odds_str}

{_format_match_signals(mc)}
"""
                matches_ctx.append({
                    "home": home,
                    "away": away,
                    "match_date": mc.get("match_date", "?"),
                    "competition": label,
                    "match_id": mc.get("match_id"),
                    "context": ctx_text,
                    "competition_analysis": comp_analysis,
                    "missing_data": mc.get("missing_data", []),
                })
                logger.info(f"  ✅ Usando MatchContext normalizado para: {home} vs {away}")
            else:
                # Fallback al método anterior si no hay MatchContext
                ctx = _build_match_context(fix, stats, insights, odds)
                if ctx:
                    matches_ctx.append(ctx)
                    logger.info(f"  ⚠️  Usando contexto legacy para: {home} vs {away}")


        if not matches_ctx:
            logger.warning(f"No valid match contexts for {label}")
            continue

        if llm:
            # === LLAMADA LLM INDIVIDUAL POR PARTIDO ===
            comp_predictions = []
            
            for match_ctx in matches_ctx:
                prompt = _build_analyst_prompt_single(label, match_ctx)
                try:
                    response = llm.invoke(prompt)
                    content = response.content if hasattr(response, "content") else str(response)
                    parsed_preds = _parse_predictions(content)

                    if parsed_preds:
                        comp_predictions.extend(parsed_preds)
                        # Persistir wishlist del analista
                        for pred in parsed_preds:
                            wishlist = pred.pop("analyst_wishlist", None) or []
                            if isinstance(wishlist, list) and wishlist:
                                _persist_analyst_wishlist(
                                    wishlist_items=wishlist,
                                    competition=label,
                                    home_team=match_ctx["home"],
                                    away_team=match_ctx["away"],
                                    match_date=match_ctx.get("match_date", ""),
                                )
                    else:
                        logger.warning(f"LLM returned no valid prediction for {match_ctx['home']} vs {match_ctx['away']}")
                except Exception as e:
                    logger.error(f"LLM error for {match_ctx['home']} vs {match_ctx['away']}: {e}")
                    # Continua con el siguiente partido si uno falla
                    
            if comp_predictions:
                # Enriquecer con metadata
                now = datetime.now(timezone.utc).isoformat()
                model_id = getattr(llm, "model", getattr(llm, "model_name", "unknown"))
                for pred in comp_predictions:
                    pred["competition"] = label
                    pred["generated_at"] = now
                    pred["analyst_model_id"] = model_id
                predictions.extend(comp_predictions)
                logger.info(
                    f"✓ {label}: {len(comp_predictions)} predicciones generadas individualmente"
                )
            else:
                meta["errors"]["analyst"][label] = "LLM returned no valid predictions for any match"
                logger.warning(f"LLM returned empty predictions for all matches in {label}")

        # Si no hay predicciones (por no tener LLM o por error), usar fallback heurístico
        if not comp_predictions and matches_ctx:
            # Fallback heurístico (sin LLM) - generar para TODOS los partidos
            logger.warning(f"Generating heuristic predictions for {label} (LLM not available)")
            now = datetime.now(timezone.utc).isoformat()
            for ctx in matches_ctx:
                home_stats = _find_team_stats(ctx["home"], stats)
                away_stats = _find_team_stats(ctx["away"], stats)
                home_insights = _find_team_insights(ctx["home"], insights)
                away_insights = _find_team_insights(ctx["away"], insights)

                # Heurística mejorada basada en posición + forma + insights
                home_pos = home_stats.get("stats", {}).get("position", 99) if home_stats else 99
                away_pos = away_stats.get("stats", {}).get("position", 99) if away_stats else 99
                home_form = home_stats.get("stats", {}).get("form", "") if home_stats else ""
                away_form = away_stats.get("stats", {}).get("form", "") if away_stats else ""

                # Contar wins en forma
                home_wins = home_form.count("W")
                away_wins = away_form.count("W")

                # Predicción basada en múltiples factores
                pos_diff = away_pos - home_pos  # positivo si away es peor (home ventaja)
                form_diff = home_wins - away_wins  # positivo si home tiene más wins

                combined_score = pos_diff + (form_diff * 1.5)

                if combined_score > 4:
                    pred, conf = "1", min(70, 55 + abs(combined_score))
                elif combined_score < -4:
                    pred, conf = "2", min(70, 55 + abs(combined_score))
                else:
                    pred, conf = "X", 52

                pid = f"{label}_{ctx['match_date'][:10]}_{ctx['home']}_vs_{ctx['away']}".replace(" ", "_")

                # Construir rationale y factores
                key_factors = []
                risk_factors = []

                if home_pos < away_pos:
                    key_factors.append(f"Local mejor posicionado (pos {home_pos} vs {away_pos})")
                if home_wins > away_wins:
                    key_factors.append(f"Mejor racha local ({home_form} vs {away_form})")
                if home_insights:
                    key_factors.append("Ventaja táctica local")

                if home_pos > away_pos:
                    risk_factors.append(f"Visitante mejor ubicado (pos {away_pos} vs {home_pos})")
                if away_wins > home_wins:
                    risk_factors.append(f"Visitante con mejor forma ({away_form})")
                if away_insights and away_insights.get("forecast"):
                    risk_factors.append("Visitante con buen análisis táctico")

                predictions.append({
                    "prediction_id": pid,
                    "competition": label,
                    "generated_at": now,
                    "match_date": ctx["match_date"],
                    "home_team": ctx["home"],
                    "away_team": ctx["away"],
                    "prediction": pred,
                    "confidence": conf,
                    "score_prediction": "2-0" if pred == "1" else "0-2" if pred == "2" else "1-1",
                    "rationale": f"{ctx['home']} (pos {home_pos}, forma {home_form}) vs {ctx['away']} (pos {away_pos}, forma {away_form})",
                    "key_factors": key_factors or [f"Análisis heurístico: {ctx['home']} local"],
                    "risk_factors": risk_factors or ["Márgenes ajustados"],
                    "entities_impact": [],
                })

            logger.info(f"✓ {label}: {len(matches_ctx)} predicciones heurísticas (sin LLM)")

    # Enriquecer predicciones con flags de 'missing_data'
    # Esto ocurre post-generación para asegurar que tanto LLM como heurística lo tengan
    for pred in predictions:
        missing = []
        
        # Verificar si hay insights para el equipo local/visita
        # Re-escaneamos insights para ver si tienen contenido real
        p_home = pred.get("home_team")
        p_away = pred.get("away_team")
        
        # Buscar insights
        i_home = _find_team_insights(p_home, insights)
        i_away = _find_team_insights(p_away, insights)
        
        # Criterio: Si no hay insight o es el mensaje de fallback
        if not i_home or "Sin datos disponibles" in i_home.get("insight", ""):
            missing.append("youtube_insights_home")
        if not i_away or "Sin datos disponibles" in i_away.get("insight", ""):
            missing.append("youtube_insights_away")
            
        # Verificar odds: buscar si hay cuotas para este partido
        odds_data = state.get("odds_canonical") or []
        odds_found = _find_match_odds(p_home, p_away, odds_data)
        if not odds_found:
            missing.append("odds_not_found")
        
        pred["missing_data"] = missing

    # Guardar en historial
    if predictions:
        try:
            _save_predictions_history(predictions)
        except Exception as e:
            logger.error(f"Error saving predictions history: {e}")

    state["predictions"] = predictions
    state["analyst_web_checks"] = analyst_web_checks
    logger.info(f"Predicciones totales: {len(predictions)}")
    return state
