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
    home_slug = slugify(home)
    away_slug = slugify(away)
    return f"{competition}_{date_part}_{home_slug}_{away_slug}"


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
    match_date  = str(odds_event.get("commence_time") or "")[:10]
    match_key   = odds_event.get("match_key") # Fuente de verdad del Odds Fetcher

    # Ignorar eventos incompletos
    if not home or not away:
        return None

    match_id = _build_match_id(competition, match_date, home, away)

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
    return ctx


# ============================================================================
# NODO PRINCIPAL
# ============================================================================

def normalizer_agent_node(state: AgentState) -> AgentState:
    """
    Nodo LangGraph del Agente Normalizador.

    Lee:
        state["odds_canonical"] - partidos + cuotas (fuente de verdad)
        state["stats_by_team"]  - estadísticas del stats_agent
        state["insights"]       - insights del insights_agent

    Escribe:
        state["match_contexts"] - lista de MatchContext completos
    """
    logger.info("=" * 60)
    logger.info("NORMALIZER AGENT: consolidando datos (odds como fixture source)")
    logger.info("=" * 60)

    odds_data     = state.get("odds_canonical") or []
    stats_data    = state.get("stats_by_team")  or []
    insights_data = state.get("insights")       or []
    team_history  = _load_team_history()

    logger.info(f"  Partidos (odds): {len(odds_data)}")
    logger.info(f"  Stats:           {len(stats_data)}")
    logger.info(f"  Insights:        {len(insights_data)}")

    match_contexts = []

    for odds_ev in odds_data:
        ctx = _build_match_context(odds_ev, stats_data, insights_data, team_history=team_history)
        if ctx is None:
            continue
        match_contexts.append(ctx)

        status = "✅" if not ctx["missing_data"] else "⚠️ "
        missing_str = ", ".join(ctx["missing_data"]) if ctx["missing_data"] else "ninguno"
        logger.info(f"  {status} {ctx['match_id']} | Faltantes: {missing_str}")

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
