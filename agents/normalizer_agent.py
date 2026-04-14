"""
Agente Normalizador de Partidos

Corre ANTES del analyst_agent. Su función es:
1. Tomar todos los fixtures y cruzarlos con Odds, Stats, e Insights.
2. Normalizar nombres de equipos (un solo nombre canónico por equipo).
3. Asignar un match_id único a cada partido.
4. Emitir state["match_contexts"] — lista de MatchContext completos.

Los agentes posteriores NO hacen búsquedas propias: reciben todo encapsulado.

Salidas en el estado:
    - match_contexts: lista de MatchContext (ver función _build_match_context)
"""

import logging
import re
import json
import os
from datetime import datetime
from typing import Any, Optional

from state import AgentState
from utils.normalizer import slugify, TeamNormalizer
from utils.signal_partitioner import partition_match_signals

logger = logging.getLogger(__name__)

# Instancia global para normalización con alias
normalizer_tool = TeamNormalizer()
TEAM_HISTORY_FILE = os.path.join("data", "knowledge", "team_history.json")


# ============================================================================
# NORMALIZACIÓN DE NOMBRES
# ============================================================================

# Usando slugify importado


# Palabras "ruido" comunes en nombres de equipos de fútbol
_NOISE_WORDS = {
    # Prefijos/sufijos genéricos de club
    "fc", "cf", "sc", "ac", "as", "cd", "rc", "rcd", "sk", "bk",
    "ca", "club", "kv", "gk", "fk", "bv", "vfb", "vfl", "tsv",
    "sv", "ssv", "rsv", "ssc", "afc", "cfc", "ufc", "utd",
    "united", "city", "town",
    # Prefijos griegos/turcos/europeos
    "pae", "paok", "sfp", "rsb", "csc", "hsc", "bsc",
    # Adjetivos / preposiciones
    "athletic", "deportivo", "sporting", "deportes",
    "de", "del", "la", "los", "las", "el",
    "the", "of", "and", "y", "e", "le", "du",
}

# Números de año/fundación típicos en nombres de equipos (ej: "04", "1904")
_NOISE_RE = re.compile(r"\b(\d{2,4})\b")

# Tokens ambiguos (ciudades o genéricos) que no deben igualarse solos
_AMBIGUOUS_TOKENS = {
    "madrid",
    "concepcion",
    "deportes",
    "deportivo",
    "universidad",
}

def _is_blacklisted_match(name_a: str, name_b: str) -> bool:
    """
    Evita matches mecanicos erroneos entre equipos muy similares pero distintos.
    REGLA DURA: se debe llamar ANTES de cualquier matching (substring / Jaccard / etc.)
    
    Opera sobre AMBOS el slug original y el slug canónico (post-Golden Mapping)
    para capturar aliases cortos como 'u concepcion' que resuelven a 
    'universidad de concepcion' via Golden Mapping.
    """
    slug_a = slugify(name_a)
    slug_b = slugify(name_b)

    # Resolver canónicos para capturar aliases ('u concepcion' → 'universidad de concepcion')
    clean_a = normalizer_tool.clean(name_a)
    clean_b = normalizer_tool.clean(name_b)
    canon_slug_a = slugify(clean_a)
    canon_slug_b = slugify(clean_b)

    def _check_concepcion_rules(sa: str, sb: str) -> bool:
        """Aplica las 4 reglas sobre un par de slugs dado."""
        
        # --- Regla 1: U. de Concepción vs Deportes Concepción ---
        if "concepcion" in sa and "concepcion" in sb:
            is_u_a = "universidad" in sa or sa.startswith("u-de") or "univ" in sa
            is_d_a = "deportes" in sa or sa.startswith("d-con") or sa.startswith("dep-con")
            is_u_b = "universidad" in sb or sb.startswith("u-de") or "univ" in sb
            is_d_b = "deportes" in sb or sb.startswith("d-con") or sb.startswith("dep-con")
            if (is_u_a and is_d_b) or (is_d_a and is_u_b):
                return True

        # --- Regla 2: Alias bare 'concepcion'/'conce' vs cualquier equipo universidad ---
        _bare_conce = {"concepcion", "conce", "el-conce"}
        if (sa in _bare_conce and "universidad" in sb) or \
           (sb in _bare_conce and "universidad" in sa):
            return True

        # --- Regla 3: Universidad vs Universidad (entidades distintas) ---
        # Solo bloquear si tras limpiar sufijos comunes (como -chi) siguen siendo diferentes.
        is_univ_a = "universidad" in sa or sa.startswith("u-")
        is_univ_b = "universidad" in sb or sb.startswith("u-")
        if is_univ_a and is_univ_b:
            # Normalización rápida interna para la regla: quitar -chi y otros ruidos
            norm_a = sa.replace("-chi", "").replace("-de-", "-").replace("univ-", "u-")
            norm_b = sb.replace("-chi", "").replace("-de-", "-").replace("univ-", "u-")
            if norm_a != norm_b and not (norm_a in norm_b or norm_b in norm_a):
                return True

        # --- Regla 4: Deportes Limache vs Deportes Concepción ---
        if "limache" in sa and "concepcion" in sb:
            return True
        if "concepcion" in sa and "limache" in sb:
            return True

        return False

    # Comprobar con slugs originales
    if _check_concepcion_rules(slug_a, slug_b):
        return True
    # Comprobar con slugs canónicos (captura aliases como 'u concepcion')
    if canon_slug_a != slug_a or canon_slug_b != slug_b:
        if _check_concepcion_rules(canon_slug_a, canon_slug_b):
            return True

    return False


def _normalize_tokens(text: str) -> set[str]:
    """
    Convierte un nombre de equipo en un conjunto de tokens limpios.
    Usa el normalizer_tool para limpiar alias antes de tokenizar.
    """
    cleaned = normalizer_tool.clean(text)
    slug = slugify(cleaned)
    tokens = set(slug.split("-"))
    # Eliminar ruido
    tokens = {t for t in tokens if t not in _NOISE_WORDS and not _NOISE_RE.fullmatch(t) and len(t) > 1}
    return tokens


def _token_matches(t_a: str, t_b: str, min_prefix: int = 4) -> bool:
    """
    Dos tokens 'coinciden' si:
      - Son idénticos, O
      - Uno es prefijo del otro (mín min_prefix chars).
    Esto cubre 'inter' ↔ 'internazionale', 'milan' ↔ 'milano'.
    """
    if t_a == t_b:
        return True
    if len(t_a) >= min_prefix and t_b.startswith(t_a):
        return True
    if len(t_b) >= min_prefix and t_a.startswith(t_b):
        return True
    return False


def _soft_jaccard(tokens_a: set, tokens_b: set) -> float:
    """
    Jaccard 'suave': cuenta cuántos tokens de A tienen pareja en B
    (usando _token_matches, no igualdad exacta).

    Ejemplos:
      {'inter','milan'} ↔ {'internazionale','milano'} → 2/2 = 1.0 ✅
      {'bayer','leverkusen'} ↔ {'bayer','leverkusen'} → 2/2 = 1.0 ✅
      {'madrid'} ↔ {'madrid'} → 1/1 = 1.0 ✅
    """
    if not tokens_a or not tokens_b:
        return 0.0

    matched_a = sum(
        1 for ta in tokens_a if any(_token_matches(ta, tb) for tb in tokens_b)
    )
    matched_b = sum(
        1 for tb in tokens_b if any(_token_matches(tb, ta) for ta in tokens_a)
    )
    # Intersection = promedio de ambos lados (simétrico)
    pseudo_intersection = (matched_a + matched_b) / 2
    pseudo_union = len(tokens_a) + len(tokens_b) - pseudo_intersection
    return pseudo_intersection / pseudo_union if pseudo_union else 0.0


def _fuzzy_match(name_a: str, name_b: str, threshold: float = 0.6) -> bool:
    """
    Coincidencia difusa entre dos nombres de equipo.

    Estrategia (A → B → C → D):
      A) Substring exacto en slugs (rápido y determinista).
      B) Soft-Jaccard de tokens limpios con prefix matching >= threshold.
      C) El set de tokens más pequeño es subconjunto del más grande
         (con prefix match). Cubre casos donde un nombre tiene tokens
         extra de ciudad/apodo: 'Everton CD' ⊂ 'Everton de Viña del Mar'.
      D) Comparten al menos un token largo (≥7 chars) con prefix match.
         Cubre 'Olympiakos Piraeus' ↔ 'Olympiakos SFP' (tras quitar PAE/SFP).
    """
    if not name_a or not name_b:
        return False

    # 1. Priorizar Golden Mapping (manual_map)
    clean_a = normalizer_tool.clean(name_a)
    clean_b = normalizer_tool.clean(name_b)
    
    # Si ambos mapean a lo mismo y no es el nombre original después de limpiar (indicando un mapeo manual exitoso)
    # O si simplemente son idénticos después de limpiar.
    if clean_a == clean_b:
        return True

    # REGLA DURA: evaluar blacklist ANTES de cualquier matching.
    # Debe ser la primera comprobacion tras el match exacto por Golden Mapping.
    if _is_blacklisted_match(name_a, name_b):
        return False

    a_slug = slugify(name_a)
    b_slug = slugify(name_b)

    # A) Substring rapido
    if a_slug and b_slug and (a_slug in b_slug or b_slug in a_slug):
        return True

    # Calcular tokens solo si el substring check no fue suficiente
    tokens_a = _normalize_tokens(name_a)
    tokens_b = _normalize_tokens(name_b)

    if not tokens_a or not tokens_b:
        return False

    # Evitar falsos positivos cuando solo comparten un token ambiguo
    if len(tokens_a) == 1 and len(tokens_b) == 1:
        only = next(iter(tokens_a))
        if only in _AMBIGUOUS_TOKENS and only in tokens_b:
            return False

    # B) Soft-Jaccard con prefix matching
    if _soft_jaccard(tokens_a, tokens_b) >= threshold:
        return True

    # C) El set más pequeño está completamente contenido en el más grande
    #    (usando prefix matching en cada token)
    smaller, larger = (tokens_a, tokens_b) if len(tokens_a) <= len(tokens_b) else (tokens_b, tokens_a)
    if all(any(_token_matches(ts, tl) for tl in larger) for ts in smaller):
        return True

    # D) Comparten al menos UN token largo y distintivo (≥7 chars)
    #    IMPORTANTE: El token no debe ser ambiguo (ej: 'concepcion' es largo pero ambiguo aquí)
    for ta in tokens_a:
        if len(ta) >= 7 and ta not in _AMBIGUOUS_TOKENS:
            if any(_token_matches(ta, tb) for tb in tokens_b):
                return True

    return False


def _find_odds(home: str, away: str, odds_data: list[dict]) -> Optional[dict]:
    """Busca el evento de odds que corresponde a un partido fixture."""
    if not odds_data:
        return None

    target_home_slug = slugify(home)
    target_away_slug = slugify(away)

    for ev in odds_data:
        ev_home_slug = slugify(ev.get("home_team", ""))
        ev_away_slug = slugify(ev.get("away_team", ""))

        # Exact slug match
        if ev_home_slug == target_home_slug and ev_away_slug == target_away_slug:
            return ev

        # Fuzzy: uno contiene al otro
        if _fuzzy_match(home, ev.get("home_team", "")) and _fuzzy_match(away, ev.get("away_team", "")):
            return ev

    return None


def _find_stats(team: str, stats_data: list[dict]) -> Optional[dict]:
    """Busca estadísticas para un equipo por nombre (con fuzzy)."""
    if not stats_data:
        return None
    for s in stats_data:
        if _fuzzy_match(team, s.get("team", "")):
            return s
    return None


def _find_insights(team: str, insights_data: list[dict]) -> Optional[dict]:
    """Busca insights de YouTube para un equipo (con fuzzy)."""
    if not insights_data:
        return None
    for i in insights_data:
        if _fuzzy_match(team, i.get("team", "")):
            return i
    return None


def _load_team_history() -> dict[str, list[dict]]:
    """Carga historial persistente de insights/contexto por equipo."""
    if not os.path.exists(TEAM_HISTORY_FILE):
        return {}
    try:
        with open(TEAM_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"No se pudo leer {TEAM_HISTORY_FILE}: {e}")
        return {}


def _find_team_history_entries(team: str, team_history: dict[str, list[dict]]) -> list[dict]:
    """Busca entradas de historial para un equipo usando matching conservador."""
    if not team_history:
        return []
    # 1) exacto/canónico
    for hist_team, entries in team_history.items():
        if hist_team == team or normalizer_tool.clean(hist_team) == normalizer_tool.clean(team):
            return entries if isinstance(entries, list) else []
    # 2) fuzzy conservador (mismo helper usado en el normalizador)
    for hist_team, entries in team_history.items():
        if _is_blacklisted_match(team, hist_team):
            continue
        if _fuzzy_match(team, hist_team):
            return entries if isinstance(entries, list) else []
    return []


def _merge_persistent_context_into_insights(
    team: str,
    competition: str,
    insights: Optional[dict],
    team_history: dict[str, list[dict]],
) -> Optional[dict]:
    """
    Fusiona señales/contexto persistido en el payload de insights que verá el analista.
    Prioriza datos del run actual y agrega contexto histórico faltante.
    """
    history_entries = _find_team_history_entries(team, team_history)
    if not history_entries:
        return insights

    # Tomar entradas recientes de la misma competencia (o generales sin competencia).
    relevant = []
    for h in history_entries[-25:]:
        if not isinstance(h, dict):
            continue
        h_comp = (h.get("competition") or "").strip()
        if h_comp and competition and h_comp != competition:
            continue
        relevant.append(h)
    if not relevant:
        return insights

    merged = dict(insights or {})
    merged.setdefault("team", team)
    merged.setdefault("competition", competition)
    try:
        max_history_bullets_in_insight = max(0, int(os.getenv("NORMALIZER_MAX_HISTORY_BULLETS_IN_INSIGHT", "0")))
    except Exception:
        max_history_bullets_in_insight = 0

    # Normalizar/asegurar listas
    context_signals = list(merged.get("context_signals") or [])
    existing_ctx_keys = {
        f"{(c.get('type') or 'other').strip().lower()}|{(c.get('signal') or '').strip().lower()}"
        for c in context_signals if isinstance(c, dict)
    }

    historical_bullets = []
    existing_insight_text = (merged.get("insight") or "")

    for h in relevant:
        kind = (h.get("kind") or "insight").strip()
        text = (h.get("insight") or "").strip()
        if not text:
            continue

        if kind == "context_signal":
            sig_type = (h.get("signal_type") or "other").strip()
            # El texto persistido suele venir como "[CONTEXTO:tipo] ... | Evidencia: ..."
            signal_text = text
            evidence = ""
            if "| Evidencia:" in text:
                signal_text, evidence = text.split("| Evidencia:", 1)
                signal_text = signal_text.strip()
                evidence = evidence.strip()
            # Limpiar prefijo persistido para el campo signal
            signal_text = re.sub(r"^\[CONTEXTO:[^\]]+\]\s*", "", signal_text, flags=re.IGNORECASE).strip()

            combined_text = f"{signal_text} {evidence}".strip().lower()
            from_manual_user = "noticia manual del usuario" in combined_text
            looks_like_pseudo_json = (
                '"home_team"' in signal_text
                or '"away_team"' in signal_text
                or '"match_id"' in signal_text
                or '"availability_comparison"' in signal_text
                or signal_text.startswith("{")
                or signal_text.startswith("[")
            )
            looks_like_cross_schedule = bool(
                re.search(r"\b\d{1,2}\s+de\s+[a-záéíóúñ]+\s*\d{1,2}:\d{2}\b", combined_text)
            ) or any(
                marker in combined_text
                for marker in [
                    "calendario de la semana critica",
                    "los horarios han sido ajustados",
                    "promedio goleador",
                    "arquitectura del torneo",
                    "partidos de vuelta de los cuartos de final",
                ]
            )
            is_negative_absence_non_signal = any(
                marker in combined_text
                for marker in [
                    "sin parte medico nuevo",
                    "sin parte médico nuevo",
                    "no han emergido reportes",
                    "enfermeria practicamente vacia",
                    "enfermería prácticamente vacía",
                    "sin bajas estructurales nuevas",
                    "sin lesiones nuevas",
                ]
            )
            is_stale_cup_context = any(
                marker in combined_text
                for marker in [
                    "efl cup",
                    "carabao cup",
                    "final de efl cup",
                ]
            )
            is_low_value_other = sig_type.lower() == "other" and (
                combined_text.startswith("no se registran en las ultimas")
                or combined_text.startswith("no se registran en las últimas")
            )

            if (
                looks_like_pseudo_json
                or looks_like_cross_schedule
                or (from_manual_user and len(combined_text) > 220)
                or ((sig_type.lower() in {"injury_news", "availability"}) and is_negative_absence_non_signal)
                or is_stale_cup_context
                or is_low_value_other
            ):
                continue

            ctx_key = f"{sig_type.lower()}|{signal_text.lower()}"
            if signal_text and ctx_key not in existing_ctx_keys:
                context_signals.append({
                    "type": sig_type or "other",
                    "signal": signal_text,
                    "evidence": evidence,
                    "confidence": h.get("confidence", 0.5),
                    "date": h.get("date"),
                    "source": "team_history",
                    "provenance": ["history"],
                    "subject_type": h.get("subject_type"),
                    "epistemic_status": h.get("epistemic_status"),
                    "impact_axis": h.get("impact_axis"),
                    "impact_level": h.get("impact_level"),
                    "source_type": h.get("source_type"),
                    "source_quality": h.get("source_quality"),
                    "time_horizon": h.get("time_horizon"),
                    "relevance_to_match": h.get("relevance_to_match"),
                    "relevance_to_1x2": h.get("relevance_to_1x2"),
                    "freshness_score": h.get("freshness_score"),
                    "trust_score": h.get("trust_score"),
                    "conflict_score": h.get("conflict_score"),
                    "final_signal_score": h.get("final_signal_score"),
                    "resolution_status": h.get("resolution_status"),
                    "raw_excerpt": h.get("raw_excerpt"),
                    "reasoning_note": h.get("reasoning_note"),
                    "impact_note": h.get("impact_note"),
                })
                existing_ctx_keys.add(ctx_key)
            # También preparar bullet visible (si no está ya en insight textual)
            if signal_text and signal_text.lower() not in existing_insight_text.lower():
                h_date = (h.get("date") or "").strip()
                date_prefix = f"[{h_date}] " if h_date else ""
                historical_bullets.append(f"{date_prefix}Contexto histórico ({sig_type}): {signal_text}")
        else:
            if text.lower() not in existing_insight_text.lower():
                h_date = (h.get("date") or "").strip()
                date_prefix = f"[{h_date}] " if h_date else ""
                historical_bullets.append(f"{date_prefix}Histórico: {text}")

    if context_signals:
        merged["context_signals"] = context_signals

    if historical_bullets and max_history_bullets_in_insight > 0:
        base = existing_insight_text.strip()
        addon = "\n".join(f"- {b}" for b in historical_bullets[:max_history_bullets_in_insight])
        merged["insight"] = f"{base}\n{addon}".strip() if base else addon

    # Marcar fecha del merge para trazabilidad del payload consumido por analista.
    merged.setdefault("as_of_date", datetime.now().strftime("%Y-%m-%d"))

    return merged


# ============================================================================
# CONSTRUCCIÓN DEL MATCH CONTEXT
# ============================================================================

def _build_match_id(competition: str, date_str: str, home: str, away: str) -> str:
    """
    Genera un match_id canónico y estable.
    """
    date_part = date_str[:10] if date_str else "nodate"
    home_slug = slugify(normalizer_tool.clean(home) or home)
    away_slug = slugify(normalizer_tool.clean(away) or away)
    return f"{competition}_{date_part}_{home_slug}_{away_slug}"


def _build_match_key(competition: str, date_str: str, home: str, away: str) -> str:
    """
    Genera un match_key canónico y estable usando nombres normalizados.
    Se usa como clave primaria de matching entre normalizer, gate y analyst.
    """
    date_part = date_str[:10] if date_str else "nodate"
    home_slug = slugify(normalizer_tool.clean(home) or home)
    away_slug = slugify(normalizer_tool.clean(away) or away)
    return f"{competition}:{date_part}:{home_slug}:{away_slug}"


def _extract_best_odds(odds_event: Optional[dict]) -> Optional[dict]:
    """Extrae las cuotas del primer bookmaker disponible."""
    if not odds_event:
        return None
    bookmakers = odds_event.get("bookmakers", [])
    if not bookmakers:
        return None
    bm = bookmakers[0]
    return {
        "home_odds": bm.get("home_odds"),
        "draw_odds": bm.get("draw_odds"),
        "away_odds": bm.get("away_odds"),
        "bookmaker": bm.get("title", bm.get("key", "unknown")),
        "bookmakers_count": odds_event.get("bookmakers_count", len(bookmakers)),
    }

def _evaluate_signal_quality(ctx: dict, stats_quality_score: float) -> None:
    """
    Evalúa la higiene epistemológica de las señales en el partido y
    enriquece el diccionario data_quality in-place.
    """
    summary = ctx.get("signals_summary", {})
    signals_total = summary.get("total", 0)
    clean_count = summary.get("clean_count", 0)
    suspicious_count = summary.get("suspicious_count", 0)
    suspicious_ratio = summary.get("suspicious_ratio", 0.0)
    
    # Extraer razones presentes en CUALQUIER señal sospechosa
    sus_list = ctx.get("signals_suspicious", [])
    all_reasons = set()
    for s in sus_list:
        for r in s.get("suspicion_reasons", []):
            all_reasons.add(r)
            
    has_foreign_entity_issue = "foreign_entity_in_team_signal" in all_reasons
    has_subject_type_mismatch = "subject_type_type_mismatch" in all_reasons
    has_manual_low_clarity = "manual_signal_low_clarity" in all_reasons
    has_stale_history_issue = "stale_or_implausible_history_signal" in all_reasons

    has_severe = any([has_foreign_entity_issue, has_subject_type_mismatch, has_manual_low_clarity, has_stale_history_issue])
    
    signal_quality_score = 1.0
    risk_level = "low"
    explanation = "Contexto sano: pocas señales sospechosas y sin razones graves."

    if signals_total == 0:
        signal_quality_score = 0.5
        risk_level = "medium"
        explanation = "Sin señales contextuales suficientes; riesgo epistemológico neutro-conservador."
    else:
        # Castigo por ratio general
        if suspicious_ratio >= 0.35:
            signal_quality_score -= 0.3
            risk_level = "high"
            explanation = "Riesgo alto: gran proporción de señales dudosas frente a limpias."
        elif suspicious_ratio >= 0.15:
            signal_quality_score -= 0.15
            risk_level = "medium"
            if risk_level != "high":  # Solo si no fue seteado antes
                explanation = "Riesgo medio: proporción moderada de señales dudosas."
        
        # Castigo por anomalías severas presentes independientemente del ratio
        if has_severe:
            risk_level = "high"
            explanation = "Riesgo alto: detectadas señales sospechosas críticas (ej. entidad foránea o mismatch semántico) que comprometen el análisis."
            if has_foreign_entity_issue:
                signal_quality_score -= 0.25
            else:
                signal_quality_score -= 0.15
                
        # Castigo leve por volumen de ruidos menores
        if "scope_unknown_for_actionable_signal" in all_reasons or "possible_duplicate_signal" in all_reasons:
             signal_quality_score -= 0.05
             if risk_level == "low":
                 risk_level = "medium"
                 explanation = "Riesgo medio: contexto con ruido leve (duplicidades o scopes inciertos)."

    # --- 3. Integración de Calidad de Mercado (v12.0) ---
    odds_obj = ctx.get("odds", {})
    odds_source = (ctx.get("odds") or {}).get("odds_source_type", "official")
    market_quality_score = 1.0
    
    if odds_source == "web_scraped":
        # Penalización por incertidumbre de captura/latencia
        market_quality_score = 0.65
        if risk_level == "low":
            risk_level = "medium"
            explanation += " | Nota: Cuotas obtenidas vía Web Scraping (Riesgo de latencia)."

    # Clamp al suelo
    signal_quality_score = max(0.0, min(1.0, round(signal_quality_score, 2)))
    
    # Pesos v12.0: 60% Stats, 30% Señales, 10% Mercado
    STATS_QUALITY_WEIGHT = 0.60
    SIGNAL_QUALITY_WEIGHT = 0.30
    MARKET_QUALITY_WEIGHT = 0.10
    
    overall_score = round(
        (stats_quality_score * STATS_QUALITY_WEIGHT) + 
        (signal_quality_score * SIGNAL_QUALITY_WEIGHT) +
        (market_quality_score * MARKET_QUALITY_WEIGHT), 
        2
    )
    
    dq = ctx.get("data_quality", {})
    dq["stats_quality_score"] = round(stats_quality_score, 2)
    dq["signal_quality_score"] = signal_quality_score
    dq["market_quality_score"] = market_quality_score
    dq["score"] = overall_score
    dq["overall_quality_score"] = overall_score
    
    dq["signals_total"] = signals_total
    dq["signals_clean_count"] = clean_count
    dq["signals_suspicious_count"] = suspicious_count
    dq["signals_suspicious_ratio"] = suspicious_ratio
    dq["top_suspicion_reasons"] = summary.get("top_suspicion_reasons", [])
    
    dq["signal_risk_level"] = risk_level
    dq["has_severe_signal_issues"] = has_severe
    dq["signal_explanation"] = explanation
    ctx["data_quality"] = dq

def _build_match_context(
    odds_event: dict,
    stats_data: list[dict],
    insights_data: list[dict],
    team_history: Optional[dict[str, list[dict]]] = None,
) -> Optional[dict]:
    """
    Construye el MatchContext completo para un evento de odds.
    """
    home        = odds_event.get("home_team") or ""
    away        = odds_event.get("away_team") or ""
    competition = odds_event.get("competition") or ""
    match_date  = str(odds_event.get("commence_time") or odds_event.get("utc_date") or "")[:10]

    # Ignorar eventos incompletos
    if not home or not away:
        return None

    # Enrichment: buscar stats e insights
    home_stats    = _find_stats(home, stats_data)
    away_stats    = _find_stats(away, stats_data)
    home_insights = _find_insights(home, insights_data)
    away_insights = _find_insights(away, insights_data)
    team_history = team_history or {}
    home_insights = _merge_persistent_context_into_insights(home, competition, home_insights, team_history)
    away_insights = _merge_persistent_context_into_insights(away, competition, away_insights, team_history)

    # Calcular Data Quality Score consolidado
    h_quality = (home_stats or {}).get("data_quality_score", 0.0)
    a_quality = (away_stats or {}).get("data_quality_score", 0.0)
    avg_quality = (h_quality + a_quality) / 2 if home_stats and away_stats else 0.5
    
    quality_notes = []
    if not home_stats: quality_notes.append("home_stats_missing")
    if not away_stats: quality_notes.append("away_stats_missing")
    
    # Flag de datos faltantes (Legacy)
    missing = []
    if not home_stats: missing.append("stats_home_not_found")
    if not away_stats: missing.append("stats_away_not_found")

    # Usar canonical_name de stats si está disponible; si no, normalizar el nombre de odds
    normalizer = TeamNormalizer()
    home_canonical = (home_stats or {}).get("canonical_name") or normalizer.clean(home)
    away_canonical = (away_stats or {}).get("canonical_name") or normalizer.clean(away)
    match_id = odds_event.get("match_id") or odds_event.get("fixture_id") or _build_match_id(competition, match_date, home_canonical, away_canonical)
    match_key = odds_event.get("match_key") or _build_match_key(competition, match_date, home_canonical, away_canonical)

    ctx = {
        "match_id":    match_id,
        "match_key":   match_key,
        "competition": competition,
        "match_date":  match_date,
        "data_quality": {
            "score": avg_quality,
            "notes": quality_notes + (home_stats or {}).get("quality_notes", []) + (away_stats or {}).get("quality_notes", [])
        },
        "home": {
            "canonical_name": home_canonical,
            "stats":          home_stats,
            "insights":       home_insights,
        },
        "away": {
            "canonical_name": away_canonical,
            "stats":          away_stats,
            "insights":       away_insights,
        },
        "odds": _extract_best_odds(odds_event),
        "missing_data": missing,
    }

    # Enriquecer ctx separando y dictaminando senales limpias de sospechosas epistemologicas
    ctx = partition_match_signals(ctx, force_recompute=True)
    
    # 2. Agregar puntuaciones híbridas de metadata al objeto
    _evaluate_signal_quality(ctx, avg_quality)
    
    return ctx


# ============================================================================
# NODO PRINCIPAL
# ============================================================================

def normalizer_agent_node(state: AgentState) -> AgentState:
    """
    Nodo LangGraph del Agente Normalizador.

    Lee:
        state["fixtures"]       - todos los partidos programados (fuente de verdad)
        state["odds_canonical"] - cuotas encontradas
        state["stats_by_team"]  - estadísticas del stats_agent
        state["insights"]       - insights del insights_agent

    Escribe:
        state["match_contexts"] - lista de MatchContext completos
    """
    logger.info("=" * 60)
    logger.info("NORMALIZER AGENT: consolidando datos (odds como fixture source)")
    logger.info("=" * 60)

    odds_data     = state.get("odds_canonical") or []
    fixtures_data = state.get("fixtures") or []
    stats_data    = state.get("stats_by_team")  or []
    insights_data = state.get("insights")       or []
    team_history  = _load_team_history()

    logger.info(f"  Fixtures (match source): {len(fixtures_data)}")
    logger.info(f"  Odds disponibles:       {len(odds_data)}")
    logger.info(f"  Stats:                  {len(stats_data)}")
    logger.info(f"  Insights:               {len(insights_data)}")

    match_contexts = []
    matched_odds_keys = set()

    # Mapear odds por match_key para búsqueda rápida
    odds_map = {}
    for o in odds_data:
        # Usar slug de equipos para linkear
        h_slug = slugify(normalizer_tool.clean(o.get("home_team", "")) or o.get("home_team", ""))
        a_slug = slugify(normalizer_tool.clean(o.get("away_team", "")) or o.get("away_team", ""))
        key = f"{h_slug}_{a_slug}"
        odds_map[key] = o

    # 1. Prioridad: Procesar Fixtures Oficiales
    for fix in fixtures_data:
        # Encontrar odds para este fixture
        h_slug = slugify(normalizer_tool.clean(fix.get("home_team", "")) or fix.get("home_team", ""))
        a_slug = slugify(normalizer_tool.clean(fix.get("away_team", "")) or fix.get("away_team", ""))
        key = f"{h_slug}_{a_slug}"
        odds_ev = odds_map.get(key)
        
        if odds_ev:
            matched_odds_keys.add(key)
            base_event = odds_ev
        else:
            # Si no hay odds_ev, pasamos el fixture con campos mínimos para el builder
            base_event = {
                "competition": fix.get("competition"),
                "home_team": fix.get("home_team"),
                "away_team": fix.get("away_team"),
                "utc_date": fix.get("utc_date"),
                "match_id": fix.get("fixture_id"),
                "match_key": _build_match_key(
                    fix.get("competition", ""),
                    str(fix.get("utc_date") or "")[:10],
                    fix.get("home_team", ""),
                    fix.get("away_team", ""),
                ),
                "no_odds": True
            }
        
        ctx = _build_match_context(base_event, stats_data, insights_data, team_history=team_history)
        if ctx is None:
            continue
        match_contexts.append(ctx)

        status = "✅" if not ctx["missing_data"] else "⚠️ "
        logger.info(f"  {status} {ctx['match_id']} | Fuente: Fixture{' + Odds' if odds_ev else ''}")

    # 2. Resiliencia: Procesar Odds huérfanos (sin fixture oficial)
    orphans = []
    for key, o in odds_map.items():
        if key not in matched_odds_keys:
            # Verificar que pertenezca a una competencia activa en el estado
            active_comps = {c.get("competition") for c in state.get("competitions", [])}
            if o.get("competition") in active_comps:
                orphans.append(o)
    
    if orphans:
        logger.info(f"  RESILIENCIA: Procesando {len(orphans)} eventos de cuotas sin fixture oficial asociado.")
        for o in orphans:
            ctx = _build_match_context(o, stats_data, insights_data, team_history=team_history)
            if ctx:
                match_contexts.append(ctx)
                logger.info(f"  ✨ {ctx['match_id']} | Fuente: Mercado (Odds-based)")

    logger.info(f"NORMALIZER AGENT: {len(match_contexts)} MatchContext generados")
    state["match_contexts"] = match_contexts

    # ── Persistir a disco para la UI ─────────────────────────────────────────
    try:
        # Guardamos la lista completa de match_contexts (incluye stats e insights)
        with open("pipeline_match_contexts.json", "w", encoding="utf-8") as f:
            json.dump(match_contexts, f, indent=2, ensure_ascii=False)
        # Odds unmatched: ya no aplica — todos los odds SON los fixtures
        with open("pipeline_odds_unmatched.json", "w", encoding="utf-8") as f:
            json.dump([], f)
        logger.info(f"pipeline_match_contexts.json guardado ({len(match_contexts)} partidos)")
    except Exception as e:
        logger.warning(f"No se pudo guardar match_contexts: {e}")

    return state
