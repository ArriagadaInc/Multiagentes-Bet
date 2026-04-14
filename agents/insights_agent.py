"""
Agente #3: Insights desde YouTube + LLM

Toma videos de YouTube por competencia, obtiene la transcripción y genera
insights por equipo y para su próximo partido (deducido al cruzar con odds).

OPTIMIZACIÓN: En lugar de hacer 1 llamada LLM por equipo (~32 llamadas),
se hace 1 sola llamada por competencia (~2 llamadas totales) enviando
todos los partidos en un batch.

Entradas esperadas en el estado:
- insights_sources: dict con URLs de YouTube por competencia (del youtube_selector)
- competitions: lista de competencias
- odds_canonical: lista de eventos de odds normalizados
- OPENAI_API_KEY opcional (si no está, genera insights heurísticos)

Salidas en el estado:
- insights: lista de dicts con insight por equipo
"""

import hashlib
import difflib
import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Union

from agents.schemas import CanonicalSignal
from state import AgentState
from utils.token_tracker import TokenTrackingCallbackHandler
from utils.normalizer import TeamNormalizer

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURACIÓN Y CONSTANTES
# ============================================================================
INSIGHTS_CACHE_FILE = "youtube_insights_cache.json"
YOUTUBE_FAILURE_CACHE_FILE = "youtube_source_failures_cache.json"
TEAM_HISTORY_FILE = os.path.join("data", "knowledge", "team_history.json")
MANUAL_NEWS_FILE = os.path.join("data", "inputs", "manual_news_input.json")
WEB_AGENT_OUTPUT_FILE = "web_agent_output.json"

# Instancia global de normalización con Golden Mapping
normalizer_tool = TeamNormalizer()

# Alias/apodos extendidos para ayudar al LLM. 
# NOTA: Los de CHI1 ya vienen en chi1_golden_mapping.json cargados en normalizer_tool.
TEAM_ALIASES = {
    "FC Barcelona": ["barca", "barça", "cule", "culé", "blaugrana", "azulgrana"],
    "Barcelona": ["barca", "barça", "cule", "culé", "blaugrana", "azulgrana"],
    "Real Madrid": ["madrid", "merengue", "merengues", "blanco", "blancos"],
    "Atlético Madrid": ["atleti", "colchonero", "colchoneros", "atleti"],
    "Club Atlético de Madrid": ["atleti", "colchonero", "colchoneros", "atletico"],
    "Inter Milan": ["inter", "neroazzurri", "nerazzurri"],
    "Internazionale": ["inter", "neroazzurri", "nerazzurri"],
    "Juventus": ["juve", "bianconeri"],
    "Borussia Dortmund": ["dortmund", "bvb", "die borussen"],
    "Bayern München": ["bayern", "fcb", "bavarians"],
    "FC Bayern München": ["bayern", "fcb", "bavarians"],
    "Paris Saint Germain": ["psg", "paris", "paris sg"],
    "AS Monaco": ["monaco", "mónaco"],
    "Benfica": ["sl benfica", "aguias", "águias", "encarnados"],
    "Club Brugge": ["brugge", "brujas", "club brugge kv"],
    "Club Brugge KV": ["brugge", "brujas", "club brugge"],
}


def _load_youtube_failure_cache() -> dict:
    if os.path.exists(YOUTUBE_FAILURE_CACHE_FILE):
        try:
            with open(YOUTUBE_FAILURE_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _save_youtube_failure_cache(cache: dict) -> None:
    try:
        with open(YOUTUBE_FAILURE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _classify_youtube_source_error(error_text: str) -> str:
    t = (error_text or "").lower()
    anti_bot_markers = [
        "sign in to confirm you're not a bot",
        "not a bot",
        "cookies-from-browser",
        "cookies for the authentication",
        "exporting youtube cookies",
        "bot",
        "login required",
        "confirm you’re not a bot",
    ]
    if any(marker in t for marker in anti_bot_markers):
        return "youtube_antibot"
    return "other"


def _youtube_failure_cache_key(url: str) -> str:
    return hashlib.md5((url or "").strip().encode("utf-8")).hexdigest()


def _get_cached_youtube_failure(url: str, cache: dict, ttl_hours: int = 24) -> Optional[dict]:
    if not url or not isinstance(cache, dict):
        return None
    entry = cache.get(_youtube_failure_cache_key(url))
    if not isinstance(entry, dict):
        return None
    created_at = entry.get("created_at")
    if not created_at:
        return None
    try:
        created_dt = datetime.fromisoformat(created_at)
    except Exception:
        return None
    age = datetime.now(timezone.utc) - created_dt.astimezone(timezone.utc)
    if age > timedelta(hours=ttl_hours):
        return None
    return entry


def _remember_youtube_failure(url: str, error_text: str, cache: dict) -> None:
    reason = _classify_youtube_source_error(error_text)
    cache[_youtube_failure_cache_key(url)] = {
        "url": url,
        "reason": reason,
        "error": (error_text or "")[:500],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

def _get_team_aliases(team: str) -> list[str]:
    """Devuelve alias/apodos normalizados para un equipo usando Golden Mapping + TEAM_ALIASES."""
    # Buscar en TEAM_ALIASES manuales (UCL etc)
    aliases = TEAM_ALIASES.get(team, [])
    
    # Buscar si el normalizer_tool tiene mapeos para este equipo (Golden Mapping)
    # Reversamos el manual_map para encontrar todos los alias que apuntan a este canonical
    canonical = normalizer_tool.clean(team)
    for alias_clean, mapped_canonical in normalizer_tool.manual_map.items():
        if mapped_canonical == team or mapped_canonical == canonical:
            # Intentar encontrar el alias original (aunque aquí solo tenemos el clean)
            # Como fallback, agregamos el alias_clean si no es el mismo nombre
            if alias_clean != canonical:
                aliases.append(alias_clean)
                
    return list(set(aliases))

def _load_team_history() -> dict:
    """Carga el historial de insights de equipos desde disco."""
    if os.path.exists(TEAM_HISTORY_FILE):
        try:
            with open(TEAM_HISTORY_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error cargando historial de equipos: {e}")
    return {}

def _save_team_history(history: dict) -> None:
    """Guarda el historial de insights de equipos a disco."""
    try:
        os.makedirs(os.path.dirname(TEAM_HISTORY_FILE), exist_ok=True)
        with open(TEAM_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"No se pudo guardar el historial de equipos: {e}")

def _load_manual_news_payload() -> dict:
    """Carga noticias manuales ingresadas por el usuario desde Streamlit."""
    if not os.path.exists(MANUAL_NEWS_FILE):
        return {}
    try:
        with open(MANUAL_NEWS_FILE, encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            text = str(data.get("text") or "").strip()
            if text and text.lstrip().startswith("{") and any(tok in text for tok in ['"tournament"', '"teams"', '"match_briefs"']):
                candidate = text
                if "```json" in candidate:
                    candidate = candidate.split("```json", 1)[1].rsplit("```", 1)[0].strip()
                elif "```" in candidate:
                    candidate = candidate.split("```", 1)[1].rsplit("```", 1)[0].strip()
                try:
                    structured = json.loads(candidate)
                    if isinstance(structured, dict):
                        structured.setdefault("updated_at", data.get("updated_at"))
                        structured.setdefault("competition", data.get("competition"))
                        structured.setdefault("text", text)
                        return structured
                except Exception:
                    logger.warning("Noticia manual parece JSON estructurado pero no pudo parsearse; usando modo texto plano.")
            return data
        return {}
    except Exception as e:
        logger.warning(f"Error cargando noticias manuales: {e}")
        return {}


def _normalize_signal_text(text: str) -> str:
    """Normaliza texto de señal para deduplicación semántica básica."""
    t = (text or "").strip().lower()
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    
    # Remover ruidos y variaciones temporales comunes
    t = re.sub(r"\bsegun noticia manual del usuario\b", "", t)
    t = re.sub(r"\bactualmente\b|\brecientemente\b|\bal dia de hoy\b|\bhoy\b|\bayer\b", "", t)
    t = re.sub(r"\bse informa que\b|\bse comenta que\b|\btrascendio que\b", "", t)
    
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _calculate_similarity(a: str, b: str) -> float:
    """Calcula la similitud de Levenshtein (ratio) entre dos cadenas."""
    return difflib.SequenceMatcher(None, a, b).ratio()


def _signal_dedup_key(sig: dict) -> str:
    """Clave canónica para deduplicar señales (primer paso: YouTube + Web)."""
    sig_type = (sig.get("type") or "other").strip().lower()
    sig_text = _normalize_signal_text(sig.get("signal") or "")
    sig_date = (sig.get("date") or "").strip()[:10]
    # Incluimos fecha si existe para evitar colapsar eventos distintos muy similares.
    return f"{sig_type}|{sig_text}|{sig_date}"


def _load_web_agent_team_map() -> dict[str, Any]:
    """
    Carga `web_agent_output.json` y devuelve mapa por competencia + team canónico,
    además del resumen global de la competencia (panorama).
    Estructura: { 
        "teams": { "UCL": { "real madrid": {...} } },
        "summaries": { "UCL": "..." }
    }
    """
    if not os.path.exists(WEB_AGENT_OUTPUT_FILE):
        return {"teams": {}, "summaries": {}}
    try:
        with open(WEB_AGENT_OUTPUT_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        logger.warning(f"No se pudo leer {WEB_AGENT_OUTPUT_FILE}: {e}")
        return {"teams": {}, "summaries": {}}

    data = (payload or {}).get("data") or {}
    competitions = data.get("competitions") or []
    team_map: dict[str, dict[str, dict]] = {}
    summary_map: dict[str, str] = {}
    
    for comp in competitions:
        if not isinstance(comp, dict):
            continue
        label = (comp.get("competition") or "").strip()
        if not label:
            continue
        team_map.setdefault(label, {})
        summary_map[label] = comp.get("competition_summary") or ""
        
        for team_obj in (comp.get("teams") or []):
            if not isinstance(team_obj, dict):
                continue
            team_name = (team_obj.get("team") or "").strip()
            key = normalizer_tool.clean(team_name)
            if key and key not in team_map[label]:
                team_map[label][key] = team_obj
    return {"teams": team_map, "summaries": summary_map}


def _is_signal_toxic_v13(sig: dict) -> bool:
    """Detecta alucinaciones conocidas de 2023/2024 o mezclas de género."""
    text = (str(sig.get("signal", "")) + " " + str(sig.get("evidence", ""))).lower()
    
    toxic_keywords = [
        "fortaleza", "san lorenzo", "gremio", "the strongest", "sao paulo",
        "arrue", "arrué", "meneghini", "pellegrino", "paiva",
        "holgado", "vial", "femenino", "femenina"
    ]
    
    for kw in toxic_keywords:
        if kw in text:
            logger.warning(f"  🚨 SEÑAL TÓXICA DETECTADA Y DESCARTADA: '{kw}' en '{text[:50]}...'")
            return True
    return False


def _merge_context_signals_youtube_web(
    youtube_signals: list[dict],
    web_team_payload: Optional[dict],
) -> tuple[list[dict], list[str]]:
    """
    Primer paso de fusión/dedup: señales de contexto YouTube + Web.
    No integra manual/history aquí (eso queda para una etapa posterior).
    Returns: (signals_merged, extra_bullets_from_web)
    """
    merged_by_key: dict[str, dict] = {}
    extra_bullets: list[str] = []

    def _ingest(sig: dict, source_name: str):
        if not isinstance(sig, dict):
            return
        
        # --- VALIDACIÓN v13.0 ---
        if _is_signal_toxic_v13(sig):
            return

        signal_text = (sig.get("signal") or "").strip()
        if not signal_text:
            return
        norm_sig = {
            "type": (sig.get("type") or "other").strip(),
            "signal": signal_text,
            "evidence": (sig.get("evidence") or "").strip(),
            "confidence": sig.get("confidence", 0.4),
            "date": (sig.get("date") or None),
            "provenance": [source_name],
        }
        key = _signal_dedup_key(norm_sig)
        existing = merged_by_key.get(key)
        if not existing:
            merged_by_key[key] = norm_sig
            return
        # Merge suave: unir provenance, conservar mayor confidence y enriquecer evidencia/fecha
        prov = set(existing.get("provenance") or [])
        prov.add(source_name)
        existing["provenance"] = sorted(prov)
        try:
            existing["confidence"] = max(float(existing.get("confidence", 0.0)), float(norm_sig.get("confidence", 0.0)))
        except Exception:
            pass
        if not existing.get("date") and norm_sig.get("date"):
            existing["date"] = norm_sig.get("date")
        ev_existing = (existing.get("evidence") or "").strip()
        ev_new = (norm_sig.get("evidence") or "").strip()
        if ev_new and ev_new.lower() not in ev_existing.lower():
            existing["evidence"] = f"{ev_existing} | {ev_new}".strip(" |")

    for sig in (youtube_signals or []):
        _ingest(sig, "youtube")

    web_signals = []
    web_insights = []
    if isinstance(web_team_payload, dict):
        web_signals = web_team_payload.get("context_signals") or []
        # El Web Agent usa 'raw_context' y 'last_result', no 'web_insights'
        if web_team_payload.get("raw_context"):
            web_insights.append(web_team_payload["raw_context"])
        if web_team_payload.get("last_result"):
            web_insights.append(f"Último resultado (Web): {web_team_payload['last_result']}")
            
        web_as_of = (web_team_payload.get("as_of_date") or "").strip()
        for sig in web_signals:
            if isinstance(sig, dict) and web_as_of and not sig.get("date"):
                sig = dict(sig)
                sig["date"] = web_as_of
            _ingest(sig, "web")

    # Bullets web visibles (solo si no están ya reflejados por señal similar)
    existing_texts = { _normalize_signal_text((v.get("signal") or "")) for v in merged_by_key.values() }
    for wb in web_insights:
        wb_text = str(wb).strip()
        if not wb_text:
            continue
        norm = _normalize_signal_text(wb_text)
        if not norm or norm in existing_texts:
            continue
        extra_bullets.append(f"Contexto web: {wb_text}")

    merged = list(merged_by_key.values())
    return merged, extra_bullets


def _resolve_team_aliases(team: str) -> set[str]:
    """Devuelve alias/apodos normalizados para un equipo (incluye nombre base)."""
    out: set[str] = set()
    team_clean = normalizer_tool.clean(team or "")
    if not team_clean:
        return out
    out.add(team_clean)
    for alias_key, aliases in TEAM_ALIASES.items():
        if normalizer_tool.clean(alias_key) != team_clean:
            continue
        for a in aliases or []:
            aa = normalizer_tool.clean(str(a))
            if aa:
                out.add(aa)
    return out


def _alias_in_normalized_text(alias: str, text_norm: str) -> bool:
    """Busca un alias normalizado en texto normalizado sin depender de regex frágil."""
    alias = (alias or "").strip()
    text_norm = (text_norm or "").strip()
    if not alias or not text_norm:
        return False
    return f" {alias} " in f" {text_norm} "


def _looks_like_fixture_blob(text_norm: str) -> bool:
    """
    Detecta señales corruptas que arrastran tablas/listados de fixtures.
    Regla conservadora: solo dispara si hay mezcla de marcador/fixture + fecha/hora.
    """
    if not text_norm:
        return False
    has_vs = " vs " in text_norm or " vs. " in text_norm
    has_time = bool(re.search(r"\b\d{1,2}:\d{2}\b", text_norm))
    has_date = bool(re.search(r"\b\d{1,2}\s+de\s+[a-záéíóúñ]+\b", text_norm, flags=re.IGNORECASE))
    has_score = bool(re.search(r"\b\d+\s*-\s*\d+\b", text_norm))
    return (has_vs and has_time) or (has_vs and has_date) or (has_score and has_time)


def _looks_like_broken_json_fragment(raw_text: str) -> bool:
    """Detecta pseudo-JSON incrustado en señales manuales/históricas."""
    raw = (raw_text or "").strip()
    if not raw:
        return False
    json_markers = [
        '"home_team"',
        '"away_team"',
        '"match_id"',
        '"importance"',
        '"availability_comparison"',
        '"pressure_comparison"',
        '"schedule_congestion_note"',
    ]
    if any(marker in raw for marker in json_markers):
        return True
    if raw.startswith("{") or raw.startswith("["):
        return True
    if raw.count('"') >= 4 and ":" in raw:
        return True
    return False


def _looks_like_cross_match_schedule_blob(raw_text: str) -> bool:
    raw = (raw_text or "").strip()
    if not raw:
        return False
    raw_norm = _normalize_signal_text(raw)
    if re.search(r"\b\d{1,2}\s+de\s+[a-z??????]+\s*\d{1,2}:\d{2}\b", raw_norm):
        return True
    markers = [
        "calendario de la semana critica",
        "los horarios han sido ajustados",
        "promedio goleador",
        "partidos de vuelta de los cuartos de final",
        "el presente informe detalla",
        "arquitectura del torneo",
    ]
    return any(marker in raw_norm for marker in markers)


def _sanitize_context_signals_for_match(
    team: str,
    opponent: Optional[str],
    competition_teams: list[str],
    signals: list[dict],
) -> list[dict]:
    """
    Corta señales claramente contaminadas antes de que lleguen al normalizador/gate.

    Principio usado de bitácora:
    - mejor descartar una señal dudosa que contaminar el partido entero;
    - la señal debe ser coherente con el equipo/partido actual;
    - tablas/listados de fixtures no deben convertirse en context_signals.
    """
    if not signals:
        return []

    own_aliases = _resolve_team_aliases(team) or {normalizer_tool.clean(team)}
    opp_aliases = _resolve_team_aliases(opponent) if opponent else set()

    foreign_aliases: dict[str, set[str]] = {}
    target_canon = normalizer_tool.clean(team)
    opp_canon = normalizer_tool.clean(opponent or "")
    for comp_team in competition_teams or []:
        comp_canon = normalizer_tool.clean(comp_team)
        if not comp_canon or comp_canon in {target_canon, opp_canon}:
            continue
        foreign_aliases[comp_canon] = _resolve_team_aliases(comp_team) or {comp_canon}

    actionable_types = {
        "injury_news",
        "disciplinary_issue",
        "availability",
        "rotation",
        "medical_doubt",
        "fatigue",
        "squad_availability",
        "heavy_rotation",
        "coach_change",
        "coaching_change",
    }

    cleaned: list[dict] = []
    dropped = 0
    for sig in signals:
        if not isinstance(sig, dict):
            continue
        signal_text = (sig.get("signal") or "").strip()
        evidence_text = (sig.get("evidence") or "").strip()
        combined_norm = _normalize_signal_text(f"{signal_text} {evidence_text}")
        if not combined_norm:
            continue
        provenance = {str(p).strip().lower() for p in (sig.get("provenance") or []) if str(p).strip()}

        has_blob_shape = _looks_like_fixture_blob(combined_norm)
        mentions_own = any(_alias_in_normalized_text(alias, combined_norm) for alias in own_aliases)
        mentions_opp = any(_alias_in_normalized_text(alias, combined_norm) for alias in opp_aliases)

        foreign_hits = []
        for foreign_team, aliases in foreign_aliases.items():
            if any(_alias_in_normalized_text(alias, combined_norm) for alias in aliases):
                foreign_hits.append(foreign_team)

        sig_type = (sig.get("type") or "other").strip().lower()
        too_long = len(combined_norm) > 260

        drop_reason = ""
        if _looks_like_broken_json_fragment(signal_text):
            drop_reason = "fragmento pseudo-json incrustado en la se?al"
        elif provenance.intersection({"manual", "history", "manual_structured", "manual_clean_text"}) and _looks_like_cross_match_schedule_blob(signal_text):
            drop_reason = "texto manual/hist?rico parece calendario o contexto macro del torneo"
        elif provenance.intersection({"manual", "history", "manual_structured", "manual_clean_text"}) and has_blob_shape and too_long:
            drop_reason = "texto manual/hist?rico parece tabla o listado de fixtures"
        elif provenance.intersection({"manual", "history", "manual_structured", "manual_clean_text"}) and too_long and not (mentions_own and not foreign_hits):
            drop_reason = "texto manual/hist?rico demasiado largo o ambiguo para una se?al at?mica"
        elif provenance.intersection({"manual", "history", "manual_structured", "manual_clean_text"}) and sig_type == "other" and foreign_hits and not mentions_own:
            drop_reason = f"se?al gen?rica manual/hist?rica anclada a equipos ajenos ({', '.join(foreign_hits[:2])})"
        elif foreign_hits and (has_blob_shape or too_long):
            drop_reason = f"menciona equipos ajenos al match ({', '.join(foreign_hits[:2])}) en texto tipo fixture/blob"
        elif has_blob_shape and not (mentions_own or mentions_opp):
            drop_reason = "texto parece fila/listado de fixtures sin anclaje al partido"
        elif sig_type in actionable_types and foreign_hits:
            drop_reason = f"señal accionable contaminada por equipos ajenos ({', '.join(foreign_hits[:2])})"

        if drop_reason:
            dropped += 1
            logger.warning(
                "  🚫 %s: señal descartada por contaminación pre-gate (%s): %s",
                team,
                drop_reason,
                signal_text[:180],
            )
            continue

        cleaned.append(sig)

    if dropped:
        logger.info("  ↳ %s: saneamiento pre-gate de context_signals (%s -> %s)", team, len(signals), len(cleaned))
    return cleaned


def _sanitize_web_extra_bullets_for_match(
    team: str,
    opponent: Optional[str],
    competition_teams: list[str],
    bullets: list[str],
) -> list[str]:
    """Aplica el mismo filtro conservador a bullets web visibles."""
    if not bullets:
        return []
    pseudo_signals = [{"type": "other", "signal": b, "evidence": ""} for b in bullets if str(b).strip()]
    cleaned = _sanitize_context_signals_for_match(team, opponent, competition_teams, pseudo_signals)
    return [str(sig.get("signal") or "").strip() for sig in cleaned if str(sig.get("signal") or "").strip()]


def _infer_manual_signal_type(text: str) -> str:
    t = _normalize_signal_text(text)
    if any(k in t for k in ["tecnico", "dt ", "entrenador", "interino", "despid", "renunci"]):
        return "coaching_change"
    if any(k in t for k in ["lesion", "lesionado", "baja", "desgarro", "parte medico"]):
        return "injury_news"
    if any(k in t for k in ["sancion", "suspend", "castig", "expuls"]):
        return "disciplinary_issue"
    if any(k in t for k in ["quiebra", "deuda", "crisis econom", "financ"]):
        return "financial_crisis"
    if any(k in t for k in ["localia", "estadio", "sin publico", "puertas cerradas"]):
        return "home_venue_issue"
    if any(k in t for k in ["libertadores", "sudamericana", "champions", "doble competencia"]):
        return "multi_competition_load"
    return "other"


def _manual_news_heading_candidates(team: str) -> list[str]:
    """
    Devuelve candidatos razonables para detectar encabezados tipo 'Equipo:' en dossiers largos.
    Evita alias demasiado genéricos.
    """
    candidates = []
    seen = set()
    raw_candidates = [team]
    for alias_key, aliases in TEAM_ALIASES.items():
        if normalizer_tool.clean(alias_key) == normalizer_tool.clean(team):
            raw_candidates.append(alias_key)
            raw_candidates.extend(aliases or [])
    for cand in raw_candidates:
        cand = str(cand or "").strip()
        if len(cand) < 6:
            continue
        clean_cand = _normalize_signal_text(cand)
        if clean_cand and clean_cand not in seen:
            seen.add(clean_cand)
            candidates.append(cand)
    return candidates


def _find_structured_manual_team_entry(team: str, manual_news_payload: Optional[dict]) -> Optional[dict]:
    """Busca la ficha estructurada de un equipo dentro de la noticia manual JSON."""
    if not isinstance(manual_news_payload, dict):
        return None
    teams = manual_news_payload.get("teams")
    if not isinstance(teams, list):
        return None
    target = normalizer_tool.clean(team)
    for item in teams:
        if not isinstance(item, dict):
            continue
        candidates = [
            item.get("team"),
            item.get("canonical_name"),
        ]
        if any(normalizer_tool.clean(c or "") == target for c in candidates):
            return item
    return None


def _confidence_label_to_score(label: str, default: float = 0.7) -> float:
    t = _normalize_signal_text(label or "")
    if t == "high" or t == "alta":
        return 0.9
    if t == "medium" or t == "media":
        return 0.7
    if t == "low" or t == "baja":
        return 0.45
    return default


def _signal_source_type(provenance: list[str]) -> str:
    prov = {str(p).strip().lower() for p in (provenance or []) if str(p).strip()}
    if "manual_structured" in prov:
        return "manual_structured"
    if "manual_clean_text" in prov:
        return "manual_clean_text"
    if "manual" in prov:
        return "manual_text"
    if "history" in prov:
        return "history"
    if "web" in prov or "web_agent" in prov:
        return "web"
    if "youtube" in prov:
        return "youtube"
    return "unknown"


def _score_source_quality(source_type: str) -> float:
    return {
        "manual_structured": 0.92,
        "web": 0.84,
        "youtube": 0.8,
        "manual_clean_text": 0.78,
        "manual_text": 0.68,
        "history": 0.62,
        "unknown": 0.55,
    }.get(source_type, 0.55)


def _infer_subject_type_from_signal(sig_type: str, signal_text: str, evidence: str) -> str:
    sig_type = (sig_type or "").strip().lower()
    text = f"{signal_text} {evidence}".lower()
    if sig_type in {"injury_news", "disciplinary_issue", "lineup_doubt", "suspension", "availability", "medical_doubt"}:
        return "player"
    if sig_type in {"coach_change", "managerial_context"} or any(token in text for token in ["dt ", "entrenador", "arteta", "simeone", "ancelotti", "kompany", "luis enrique"]):
        return "coach"
    if sig_type in {"competition_context", "macro_context", "contexto_jornada"}:
        return "competition"
    if sig_type in {"institutional", "financial_crisis", "legal_context", "case"}:
        return "case"
    return "team"


def _infer_impact_axis(sig_type: str, signal_text: str) -> str:
    sig_type = (sig_type or "").strip().lower()
    text = (signal_text or "").lower()
    if sig_type in {"injury_news", "suspension", "lineup_doubt", "availability", "rotation", "medical_doubt", "disciplinary_issue"}:
        return "availability"
    if sig_type in {"schedule_load", "heavy_rotation", "international_fatigue"}:
        return "fatigue"
    if sig_type in {"tactical", "home_venue_issue", "competition_context", "macro_context", "contexto_jornada"}:
        return "tactical_shape"
    if sig_type in {"morale", "motivation", "media_pressure", "institutional"}:
        return "motivation"
    if sig_type in {"form", "recent_form", "momentum", "previous_result"}:
        return "form_cycle"
    if any(token in text for token in ["lesión", "injury", "baja", "suspensión", "duda"]):
        return "availability"
    return "general"


def _impact_level_from_signal(sig_type: str, signal_text: str, confidence: float, explicit_impact: Optional[str] = None) -> str:
    impact = str(explicit_impact or "").strip().lower()
    if impact in {"alto", "high"}:
        return "alto"
    if impact in {"bajo", "low"}:
        return "bajo"
    sig_type = (sig_type or "").strip().lower()
    text = (signal_text or "").lower()
    if sig_type in {"injury_news", "suspension", "schedule_load", "home_venue_issue", "disciplinary_issue"}:
        return "alto" if confidence >= 0.72 else "medio"
    if any(token in text for token in ["fuera", "out", "sanción", "suspensión", "no tuvo partido", "ventaja física"]):
        return "alto"
    return "medio" if confidence >= 0.6 else "bajo"


def _infer_epistemic_status(sig: dict) -> str:
    status = str(sig.get("epistemic_status") or "").strip().upper()
    if status in {"HECHO", "INFERENCIA", "RUMOR", "CONFLICTO"}:
        return status
    if sig.get("is_rumor"):
        return "RUMOR"
    evidence = str(sig.get("evidence") or "").lower()
    signal_text = str(sig.get("signal") or "").lower()
    if any(token in f"{signal_text} {evidence}" for token in ["podría", "podria", "probable", "50/50", "duda", "no confirmado"]):
        return "INFERENCIA"
    return "HECHO"


def _infer_time_horizon(sig_type: str) -> str:
    sig_type = (sig_type or "").strip().lower()
    if sig_type in {"injury_news", "suspension", "lineup_doubt", "availability", "schedule_load", "rotation", "medical_doubt"}:
        return "match_window"
    if sig_type in {"form", "momentum", "previous_result", "recent_form"}:
        return "short_term"
    if sig_type in {"coach_change", "institutional", "financial_crisis"}:
        return "medium_term"
    return "short_term"


def _score_freshness(signal_date: Optional[str], sig_type: str) -> float:
    if not signal_date:
        return 0.35
    try:
        parsed = datetime.strptime(str(signal_date)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return 0.35
    age_days = max(0, (datetime.now(timezone.utc) - parsed).days)
    sig_type = (sig_type or "").strip().lower()
    ttl_days = 5
    if sig_type in {"lineup_doubt", "availability", "rotation", "medical_doubt"}:
        ttl_days = 3
    elif sig_type in {"coach_change", "institutional", "financial_crisis"}:
        ttl_days = 10
    freshness = 1.0 - (age_days / max(ttl_days, 1))
    return round(max(0.0, min(1.0, freshness)), 2)


def _relevance_labels(sig_type: str, impact_axis: str, epistemic_status: str) -> tuple[str, str]:
    sig_type = (sig_type or "").strip().lower()
    if sig_type in {"injury_news", "suspension", "lineup_doubt", "availability", "schedule_load", "home_venue_issue", "medical_doubt"}:
        return "direct", "high"
    if impact_axis in {"fatigue", "availability", "tactical_shape"} and epistemic_status != "RUMOR":
        return "direct", "high"
    if sig_type in {"motivation", "morale", "institutional", "media_pressure"}:
        return "indirect", "medium"
    return "background", "low"


def _reasoning_note(sig_type: str, impact_axis: str, epistemic_status: str) -> str:
    return f"{sig_type} => eje {impact_axis}; estatus {epistemic_status}; señal preparada para gate/analista."


def _canonicalize_context_signal(team: str, competition: str, sig: dict, opponent: Optional[str] = None) -> dict:
    if not isinstance(sig, dict):
        return {}

    signal_text = (sig.get("signal") or "").strip()
    evidence = (sig.get("evidence") or "").strip()
    sig_type = (sig.get("type") or "other").strip() or "other"
    provenance = [str(p).strip() for p in (sig.get("provenance") or []) if str(p).strip()]
    confidence_raw = sig.get("confidence", 0.4)
    try:
        confidence = max(0.0, min(1.0, float(confidence_raw)))
    except Exception:
        confidence = 0.4

    epistemic_status = _infer_epistemic_status(sig)
    source_type = _signal_source_type(provenance)
    source_quality = _score_source_quality(source_type)
    subject_type = _infer_subject_type_from_signal(sig_type, signal_text, evidence)
    impact_axis = _infer_impact_axis(sig_type, signal_text)
    impact_level = _impact_level_from_signal(sig_type, signal_text, confidence, sig.get("impact"))
    time_horizon = _infer_time_horizon(sig_type)
    freshness_score = _score_freshness(sig.get("date"), sig_type)
    relevance_to_match, relevance_to_1x2 = _relevance_labels(sig_type, impact_axis, epistemic_status)
    trust_score = round(max(0.0, min(1.0, (confidence * 0.55) + (source_quality * 0.45))), 2)
    conflict_score = 0.7 if epistemic_status == "CONFLICTO" else (0.35 if epistemic_status == "RUMOR" else 0.0)
    final_signal_score = round(max(0.0, min(1.0, (trust_score * 0.5) + (freshness_score * 0.3) + ((1.0 - conflict_score) * 0.2))), 2)

    payload = {
        "team": team,
        "competition": competition,
        "type": sig_type,
        "signal": signal_text,
        "evidence": evidence,
        "date": (str(sig.get("date")).strip()[:10] if sig.get("date") else None),
        "confidence": confidence,
        "is_rumor": bool(sig.get("is_rumor", False)) or epistemic_status == "RUMOR",
        "provenance": provenance,
        "source_urls": sig.get("source_urls") or [],
        "subject_type": subject_type,
        "epistemic_status": epistemic_status,
        "impact_axis": impact_axis,
        "impact_level": impact_level,
        "source_type": source_type,
        "source_quality": source_quality,
        "time_horizon": time_horizon,
        "relevance_to_match": relevance_to_match,
        "relevance_to_1x2": relevance_to_1x2,
        "freshness_score": freshness_score,
        "trust_score": trust_score,
        "conflict_score": conflict_score,
        "final_signal_score": final_signal_score,
        "resolution_status": str(sig.get("resolution_status") or "active"),
        "raw_excerpt": (sig.get("raw_excerpt") or signal_text)[:280],
        "reasoning_note": _reasoning_note(sig_type, impact_axis, epistemic_status),
        "impact_note": f"axis={impact_axis}; level={impact_level}; opponent={opponent or 'N/A'}",
    }

    try:
        return CanonicalSignal(**payload).model_dump()
    except Exception:
        return payload


def _structured_manual_signals_for_team(team: str, competition: str, manual_news_payload: Optional[dict]) -> list[dict]:
    """Convierte dossier manual estructurado en señales atómicas utilizables por el pipeline."""
    team_entry = _find_structured_manual_team_entry(team, manual_news_payload)
    if not team_entry:
        return []

    updated_at = str(manual_news_payload.get("updated_at") or "").strip()
    fallback_date = updated_at[:10] if updated_at else None
    out: list[dict] = []

    recent_form = team_entry.get("recent_form") or {}
    if isinstance(recent_form, dict):
        trend = str(recent_form.get("trend") or "").strip()
        psych = str(recent_form.get("psychological_state") or "").strip()
        psych_ev = str(recent_form.get("psychological_state_evidence") or "").strip()
        if trend:
            out.append({
                "type": "form",
                "signal": f"Tendencia reciente: {trend}",
                "evidence": psych_ev or "Dossier manual estructurado",
                "confidence": 0.82,
                "date": fallback_date,
                "provenance": ["manual_structured"],
                "competition": competition,
            })
        if psych:
            out.append({
                "type": "morale",
                "signal": f"Estado anímico: {psych}",
                "evidence": psych_ev or "Dossier manual estructurado",
                "confidence": 0.74,
                "date": fallback_date,
                "provenance": ["manual_structured"],
                "competition": competition,
            })

    squad = team_entry.get("squad_availability") or {}
    if isinstance(squad, dict):
        for bucket_name, sig_type in [
            ("injuries", "injury_news"),
            ("suspensions", "disciplinary_issue"),
            ("doubts", "medical_doubt"),
            ("returns", "availability"),
        ]:
            bucket = squad.get(bucket_name) or []
            if not isinstance(bucket, list):
                continue
            for item in bucket:
                if isinstance(item, str):
                    out.append({
                        "type": sig_type,
                        "signal": item.strip(),
                        "evidence": "Dossier manual estructurado",
                        "confidence": 0.72,
                        "date": fallback_date,
                        "provenance": ["manual_structured"],
                        "competition": competition,
                    })
                    continue
                if not isinstance(item, dict):
                    continue
                player = str(item.get("player") or "").strip()
                issue = str(item.get("issue") or "").strip()
                status = str(item.get("status") or "").strip()
                source = str(item.get("source") or "").strip()
                source_date = str(item.get("source_date") or "").strip()[:10] or fallback_date
                desc = " - ".join(x for x in [player, issue or status] if x)
                if not desc:
                    continue
                out.append({
                    "type": sig_type,
                    "signal": desc,
                    "evidence": source or "Dossier manual estructurado",
                    "confidence": _confidence_label_to_score(item.get("confidence"), 0.78),
                    "date": source_date,
                    "provenance": ["manual_structured"],
                    "competition": competition,
                    "is_rumor": status in {"rumor", "doubtful", "contradicted"},
                })

    comp_ctx = team_entry.get("competitive_context") or {}
    if isinstance(comp_ctx, dict):
        fatigue = str(comp_ctx.get("fatigue_assessment") or "").strip()
        fatigue_ev = comp_ctx.get("fatigue_evidence") or {}
        if fatigue:
            ev_parts = []
            if isinstance(fatigue_ev, dict):
                if fatigue_ev.get("days_rest") is not None:
                    ev_parts.append(f"días descanso={fatigue_ev.get('days_rest')}")
                if fatigue_ev.get("last_match_date"):
                    ev_parts.append(f"último partido={fatigue_ev.get('last_match_date')}")
                if fatigue_ev.get("rotation_known"):
                    ev_parts.append(f"rotación={fatigue_ev.get('rotation_known')}")
            out.append({
                "type": "schedule_load",
                "signal": f"Evaluación de fatiga: {fatigue}",
                "evidence": " | ".join(ev_parts) or "Dossier manual estructurado",
                "confidence": 0.8,
                "date": str((fatigue_ev or {}).get("last_match_date") or fallback_date)[:10] if isinstance(fatigue_ev, dict) else fallback_date,
                "provenance": ["manual_structured"],
                "competition": competition,
            })
        for climate in comp_ctx.get("institutional_climate") or []:
            if str(climate).strip():
                out.append({
                    "type": "media_pressure",
                    "signal": str(climate).strip(),
                    "evidence": "Dossier manual estructurado",
                    "confidence": 0.72,
                    "date": fallback_date,
                    "provenance": ["manual_structured"],
                    "competition": competition,
                })

    for sig in team_entry.get("signals_for_prediction") or []:
        if not isinstance(sig, dict):
            continue
        desc = str(sig.get("description") or "").strip()
        if not desc:
            continue
        epistemic = str(sig.get("epistemic_status") or "").strip().upper()
        out.append({
            "type": str(sig.get("signal_type") or "other").strip() or "other",
            "signal": desc,
            "evidence": str(sig.get("evidence") or "").strip() or "Dossier manual estructurado",
            "confidence": _confidence_label_to_score(sig.get("confidence"), 0.78),
            "date": str(sig.get("event_date") or fallback_date)[:10] if (sig.get("event_date") or fallback_date) else None,
            "provenance": ["manual_structured"],
            "competition": competition,
            "is_rumor": epistemic == "RUMOR",
        })

    dedup: dict[str, dict] = {}
    for sig in out:
        key = _signal_dedup_key(sig)
        if key not in dedup:
            dedup[key] = sig
        else:
            dedup[key]["confidence"] = max(float(dedup[key].get("confidence", 0.0)), float(sig.get("confidence", 0.0)))
    return list(dedup.values())


def _extract_team_section_from_manual_news(raw_text: str, team: str, competition_teams: Optional[list[str]] = None) -> str:
    """
    Para dossiers grandes y multi-equipo, intenta recortar solo la sección del equipo objetivo.
    Busca encabezados 'Equipo:' y corta hasta el siguiente encabezado de otro equipo del mismo batch.
    """
    if not raw_text or len(raw_text) < 1200:
        return raw_text

    searchable_text = _normalize_signal_text(raw_text)
    heading_hits: list[tuple[int, str]] = []

    team_pool = competition_teams or []
    if team not in team_pool:
        team_pool = [team] + list(team_pool)

    for pool_team in team_pool:
        for cand in _manual_news_heading_candidates(pool_team):
            norm_cand = _normalize_signal_text(cand)
            if not norm_cand:
                continue
            pos = searchable_text.find(f"{norm_cand}:")
            if pos >= 0:
                heading_hits.append((pos, normalizer_tool.clean(pool_team)))

    if not heading_hits:
        return raw_text

    heading_hits.sort(key=lambda x: x[0])
    target_canon = normalizer_tool.clean(team)
    target_positions = [pos for pos, canon in heading_hits if canon == target_canon]
    if not target_positions:
        return raw_text

    start = target_positions[0]
    end = len(raw_text)
    for pos, canon in heading_hits:
        if pos > start and canon != target_canon:
            end = pos
            break

    section = raw_text[start:end].strip()
    return section or raw_text


def _extract_clean_manual_team_section(raw_text: str, team: str) -> str:
    """
    Extrae el bloque `### EQUIPO: <nombre>` de la plantilla textual limpia del
    investigador. Corta hasta el siguiente `### EQUIPO:` o `## 4.`.
    """
    if not raw_text:
        return ""

    lines = raw_text.splitlines()
    target = normalizer_tool.clean(team)
    start_idx = None
    end_idx = None

    for idx, line in enumerate(lines):
        line_clean = line.strip()
        line_norm = line_clean.lower()
        if not (line_norm.startswith("### equipo:") or line_norm.startswith("equipo:")):
            continue
        heading_name = line_clean.split(":", 1)[1].strip()
        if normalizer_tool.clean(heading_name) == target:
            start_idx = idx
            break

    if start_idx is None:
        return ""

    for idx in range(start_idx + 1, len(lines)):
        line_clean = lines[idx].strip().lower()
        if (
            line_clean.startswith("### equipo:")
            or line_clean.startswith("equipo:")
            or line_clean.startswith("## 4.")
            or line_clean.startswith("4. contexto por partido")
        ):
            end_idx = idx
            break

    section_lines = lines[start_idx:end_idx] if end_idx is not None else lines[start_idx:]
    return "\n".join(section_lines).strip()


def _parse_clean_manual_signal_line(line: str, competition: str) -> Optional[dict]:
    """
    Parsea la línea atómica pedida al investigador:
    - [TIPO=...] [ESTATUS=...] [IMPACTO=...] [CONFIANZA=...] [FECHA=...] [FUENTE=...] Descripción: ... Evidencia: ...
    """
    if not line or "[TIPO=" not in line or "Descripción:" not in line:
        return None

    pattern = re.compile(
        r"^\s*-\s*"
        r"\[TIPO=(?P<tipo>[^\]]+)\]\s*"
        r"\[ESTATUS=(?P<estatus>[^\]]+)\]\s*"
        r"\[IMPACTO=(?P<impacto>[^\]]+)\]\s*"
        r"\[CONFIANZA=(?P<conf>[^\]]+)\]\s*"
        r"\[FECHA=(?P<fecha>[^\]]+)\]\s*"
        r"\[FUENTE=(?P<fuente>[^\]]+)\]\s*"
        r"Descripci[oó]n:\s*(?P<descripcion>.*?)"
        r"(?:\.\s*Evidencia:\s*(?P<evidencia>.*?))?\s*$",
        flags=re.IGNORECASE,
    )
    match = pattern.match(line.strip())
    if not match:
        return None

    tipo = str(match.group("tipo") or "other").strip().lower()
    estatus = str(match.group("estatus") or "").strip().upper()
    impacto = str(match.group("impacto") or "").strip().lower()
    confianza = str(match.group("conf") or "").strip().lower()
    fecha = str(match.group("fecha") or "").strip()
    fuente = str(match.group("fuente") or "").strip()
    descripcion = str(match.group("descripcion") or "").strip().rstrip(".")
    evidencia = str(match.group("evidencia") or "").strip()

    if not descripcion:
        return None

    confidence_map = {"alta": 0.9, "media": 0.72, "baja": 0.55}
    date_str = None if fecha.lower() in {"", "desconocido", "null", "none", "no confirmado"} else fecha[:10]
    signal_text = descripcion
    if estatus and estatus not in {"HECHO", "INFERENCIA"}:
        signal_text = f"{descripcion} ({estatus.lower()})"

    return {
        "type": tipo or "other",
        "signal": signal_text,
        "evidence": evidencia or fuente or "Noticia manual estructurada (texto limpio)",
        "confidence": confidence_map.get(confianza, 0.72),
        "date": date_str,
        "impact": impacto,
        "epistemic_status": estatus or "HECHO",
        "provenance": ["manual_clean_text"],
        "competition": competition,
        "source_type": "manual_clean_text",
        "source": fuente or "manual_news",
    }


def _parse_loose_manual_signal_line(line: str, competition: str) -> Optional[dict]:
    """
    Parsea la variante más laxa que aún sigue siendo útil:
    -[CONFIANZA=alta][FECHA=2026-04-13] Descripción: ... Evidencia: ...
    """
    if not line or "Descripción:" not in line:
        return None

    pattern = re.compile(
        r"^\s*-\s*"
        r"(?:\[(?:TIPO=)?(?P<tipo>[^\]]+)\])?\s*"
        r"\[CONFIANZA=(?P<conf>[^\]]+)\]\s*"
        r"\[FECHA=(?P<fecha>[^\]]+)\]\s*"
        r"Descripci[oó]n:\s*(?P<descripcion>.*?)"
        r"(?:\.\s*Evidencia:\s*(?P<evidencia>.*?))?\s*$",
        flags=re.IGNORECASE,
    )
    match = pattern.match(line.strip())
    if not match:
        return None

    descripcion = str(match.group("descripcion") or "").strip().rstrip(".")
    evidencia = str(match.group("evidencia") or "").strip()
    confianza = str(match.group("conf") or "").strip().lower()
    fecha = str(match.group("fecha") or "").strip()
    tipo = str(match.group("tipo") or "").strip()
    if not descripcion:
        return None

    if not tipo or tipo.lower() == "tipo":
        tipo = _infer_manual_signal_type(f"{descripcion}. {evidencia}")

    impact = "alto" if confianza == "alta" else ("medio" if confianza == "media" else "bajo")
    confidence_map = {"alta": 0.88, "media": 0.72, "baja": 0.55}
    date_str = None if fecha.lower() in {"", "desconocido", "null", "none", "no confirmado"} else fecha[:10]

    return {
        "type": tipo or "other",
        "signal": descripcion,
        "evidence": evidencia or "Noticia manual del usuario",
        "confidence": confidence_map.get(confianza, 0.72),
        "date": date_str,
        "impact": impact,
        "epistemic_status": "HECHO",
        "provenance": ["manual_clean_text"],
        "competition": competition,
        "source_type": "manual_clean_text",
        "source": "manual_news",
    }


def _field_line_value(team_section: str, label: str) -> str:
    pattern = re.compile(rf"^\s*{re.escape(label)}\s*:\s*(.+?)\s*$", flags=re.IGNORECASE | re.MULTILINE)
    match = pattern.search(team_section)
    return (match.group(1).strip() if match else "")


def _extract_loose_manual_context_signals(team_section: str, competition: str) -> list[dict]:
    """
    Convierte líneas útiles del bloque de equipo en señales atómicas cuando el
    investigador no usa la línea canónica completa.
    """
    signals: list[dict] = []
    field_specs = [
        ("Lesionados confirmados", "injury_news", 0.84),
        ("Suspendidos confirmados", "disciplinary_issue", 0.9),
        ("Jugadores en duda", "availability", 0.72),
        ("Retornos", "availability", 0.74),
        ("Evaluación de fatiga", "fatigue", 0.82),
        ("Clima institucional", "other", 0.7),
        ("Eventos recientes de momentum", "other", 0.72),
        ("Impacto de ausencias relevantes", "injury_news", 0.76),
        ("Estado anímico", "other", 0.68),
        ("Tendencia reciente", "other", 0.66),
    ]

    for label, signal_type, conf in field_specs:
        value = _field_line_value(team_section, label)
        if not value:
            continue
        value_norm = _normalize_signal_text(value)
        if value_norm in {"ninguno", "ninguna", "no", "no confirmado", "desconocido", "null", "-"}:
            continue
        signals.append({
            "type": signal_type,
            "signal": value,
            "evidence": f"Noticia manual del usuario ({label})",
            "confidence": conf,
            "date": None,
            "provenance": ["manual_clean_text"],
            "competition": competition,
            "source_type": "manual_clean_text",
            "source": "manual_news",
        })

    return signals


def _parse_clean_manual_text_signals_for_team(team: str, competition: str, raw_text: str) -> list[dict]:
    """
    Aprovecha el formato limpio definido en `prompts/investigation_agent_prompt.md`.
    Prioriza las líneas atómicas de `#### SEÑALES PARA PRONÓSTICO`.
    """
    if not raw_text or ("EQUIPO:" not in raw_text and "### EQUIPO:" not in raw_text):
        return []

    team_section = _extract_clean_manual_team_section(raw_text, team)
    if not team_section:
        return []

    signals: list[dict] = []
    in_signal_block = False

    for raw_line in team_section.splitlines():
        line = raw_line.strip()
        line_lower = line.lower()

        if line_lower.startswith("#### señales para pronóstico") or line_lower.startswith("señales para pronóstico"):
            in_signal_block = True
            continue
        if in_signal_block and (line.startswith("#### ") or line.endswith(":") and not line.startswith("- ")):
            break
        if not in_signal_block or not line.startswith("- "):
            if not in_signal_block and raw_line.strip().startswith("-["):
                # tolerar ausencia de espacio después del guion
                pass
            else:
                continue
        if not line.startswith("- "):
            line = "- " + line.lstrip("-").strip()

        parsed = _parse_clean_manual_signal_line(line, competition)
        if parsed:
            signals.append(parsed)
            continue
        parsed = _parse_loose_manual_signal_line(line, competition)
        if parsed:
            signals.append(parsed)

    signals.extend(_extract_loose_manual_context_signals(team_section, competition))

    if signals:
        return _dedup_context_signals(signals)

    return []


def _manual_news_signals_for_team(
    team: str,
    competition: str,
    manual_news_payload: Optional[dict],
    competition_teams: Optional[list[str]] = None,
) -> list[dict]:
    """
    Genera señales sintéticas desde noticia manual del usuario para poder deduplicar/fusionar
    con YouTube/Web en el payload final del insight.
    """
    if not isinstance(manual_news_payload, dict):
        return []
    if isinstance(manual_news_payload.get("teams"), list):
        structured = _structured_manual_signals_for_team(team, competition, manual_news_payload)
        if structured:
            return structured
    raw_text = str(manual_news_payload.get("text") or "").strip()
    if not raw_text:
        return []
    clean_text_signals = _parse_clean_manual_text_signals_for_team(team, competition, raw_text)
    if clean_text_signals:
        return clean_text_signals
    raw_text = _extract_team_section_from_manual_news(raw_text, team, competition_teams)
    text_norm = _normalize_signal_text(raw_text)
    if not text_norm:
        return []

    aliases = _resolve_team_aliases(team)
    if not aliases:
        aliases = {normalizer_tool.clean(team)}
    matched_aliases = [a for a in aliases if a and a in text_norm]
    if not matched_aliases:
        return []

    # Extraer fragmentos relevantes por línea/oración para no meter todo el bloque.
    chunks = [
        c.strip()
        for c in re.split(r"[\n\r]+|(?<=[\.\!\?])\s*|(?<=:)(?=[A-ZÁÉÍÓÚÑ])", raw_text)
        if c.strip()
    ]
    rel_chunks = []
    for ch in chunks:
        ch_norm = _normalize_signal_text(ch)
        if any(a in ch_norm for a in matched_aliases):
            rel_chunks.append(ch)
    if not rel_chunks:
        rel_chunks = [raw_text[:400]]

    signal_text = " ".join(rel_chunks[:2]).strip()
    if _looks_like_fixture_blob(_normalize_signal_text(signal_text)):
        return []
    if len(signal_text) > 320:
        signal_text = signal_text[:317].rstrip() + "..."

    updated_at = str(manual_news_payload.get("updated_at") or "").strip()
    date_str = updated_at[:10] if updated_at else None
    signal_type = _infer_manual_signal_type(signal_text)

    return [{
        "type": signal_type,
        "signal": signal_text,
        "evidence": "Noticia manual del usuario",
        "confidence": 0.78,
        "date": date_str,
        "provenance": ["manual"],
        "competition": competition,
    }]


def _parse_history_context_signal_entry(entry: dict) -> Optional[dict]:
    if not isinstance(entry, dict):
        return None
    if entry.get("kind") != "context_signal":
        return None
    raw_text = str(entry.get("insight") or "").strip()
    if not raw_text:
        return None
    signal_type = str(entry.get("signal_type") or "other").strip() or "other"

    # Formato persistido: [CONTEXTO:tipo] señal | Evidencia: ...
    signal_text = raw_text
    evidence = ""
    m = re.match(r"^\[CONTEXTO:[^\]]+\]\s*(.*)$", raw_text, flags=re.IGNORECASE)
    if m:
        signal_text = m.group(1).strip()
    if " | Evidencia:" in signal_text:
        signal_text, evidence = signal_text.split(" | Evidencia:", 1)
        signal_text = signal_text.strip()
        evidence = evidence.strip()

    if not signal_text:
        return None

    combined_norm = _normalize_signal_text(f"{signal_text} {evidence}")
    provenance = {str(p).strip().lower() for p in (entry.get("provenance") or []) if str(p).strip()}
    from_manual_user = "noticia manual del usuario" in _normalize_signal_text(evidence) or "manual" in provenance

    if _looks_like_broken_json_fragment(signal_text):
        return None
    if _looks_like_cross_match_schedule_blob(signal_text):
        return None
    if _looks_like_fixture_blob(combined_norm) and len(combined_norm) > 180:
        return None
    if from_manual_user and len(combined_norm) > 220:
        return None

    return {
        "type": signal_type,
        "signal": signal_text,
        "evidence": evidence,
        "confidence": entry.get("confidence", 0.55),
        "date": str(entry.get("date") or "").strip()[:10] or None,
        "is_rumor": bool(entry.get("is_rumor", False)),
        "provenance": sorted({"history"} | {str(p).strip() for p in (entry.get("provenance") or []) if str(p).strip()}),
        "source_urls": entry.get("source_urls") or [],
        "subject_type": entry.get("subject_type"),
        "epistemic_status": entry.get("epistemic_status"),
        "impact_axis": entry.get("impact_axis"),
        "impact_level": entry.get("impact_level"),
        "source_type": entry.get("source_type"),
        "source_quality": entry.get("source_quality"),
        "time_horizon": entry.get("time_horizon"),
        "relevance_to_match": entry.get("relevance_to_match"),
        "relevance_to_1x2": entry.get("relevance_to_1x2"),
        "freshness_score": entry.get("freshness_score"),
        "trust_score": entry.get("trust_score"),
        "conflict_score": entry.get("conflict_score"),
        "final_signal_score": entry.get("final_signal_score"),
        "resolution_status": entry.get("resolution_status"),
        "raw_excerpt": entry.get("raw_excerpt"),
        "reasoning_note": entry.get("reasoning_note"),
        "impact_note": entry.get("impact_note"),
    }


def _history_context_signals_for_team(team: str, competition: str, history: Optional[dict], max_items: int = 6, current_opponent: Optional[str] = None) -> list[dict]:
    if not isinstance(history, dict) or not history:
        return []
    team_clean = normalizer_tool.clean(team)
    entries = history.get(team, [])
    if not entries:
        # Fallback por nombre canónico para claves históricas con variantes.
        for k, vals in history.items():
            if normalizer_tool.clean(k) == team_clean:
                entries = vals or []
                break

    # STALE SHIELD MATRIX (Alineada a decisión de arquitectura)
    ttl_days = {
        'form': 5,
        'previous_result': 5,
        'momentum': 5,
        'macrostats': 5,
        'injury_news': 5,
        'suspension': 5,
        'disciplinary_issue': 5,
        'lineup_doubt': 3,
        'table': 3,
        'position': 3,
        'macro_context': 3,
        'coach_change': 5,
        'coach_identity': 7,
        'player_membership': 5,
        'transfer': 5,
        'international_fatigue': 4,
        'heavy_rotation': 4,
        'extreme_venue': 3,
        'must_win_scenario': 3,
        'aggregate_score': 8,
    }
    today = datetime.now(timezone.utc)

    out: list[dict] = []
    for e in reversed(entries or []):  # más recientes primero (asumiendo append cronológico)
        if not isinstance(e, dict):
            continue
        if competition and (e.get("competition") or "").strip() not in ("", competition):
            continue
            
        parsed = _parse_history_context_signal_entry(e)
        if parsed:
            # Validacion de Caducidad (TTL Stale Shield)
            sig_type = parsed.get("type", "other")
            sig_date_str = parsed.get("date")
            
            is_expired = False
            if not sig_date_str:
                is_expired = True # Sin fecha exacta, penalizar fuerte / descartar
            else:
                try:
                    sig_date = datetime.strptime(sig_date_str[:10], '%Y-%m-%d').replace(tzinfo=timezone.utc)
                    days_elapsed = (today - sig_date).days
                    # Determinar TTL exacto
                    max_ttl = 3 # Base exigente para "other"
                    for k_type, k_ttl in ttl_days.items():
                        if k_type in sig_type.lower():
                            max_ttl = k_ttl
                            break
                            
                    if days_elapsed > max_ttl:
                        is_expired = True
                except Exception:
                    is_expired = True
            
            if not is_expired:
                # SANEAMIENTO SEMÁNTICO (Tarea 10): 
                # Si la señal es de disponibilidad del rival, validar contra el oponente actual.
                if sig_type == "opponent_availability" and current_opponent:
                    recorded_rival = e.get("rival") # Campo nuevo persistido
                    signal_text = parsed.get("signal", "").lower()
                    evidence_text = parsed.get("evidence", "").lower()
                    
                    # Si tenemos el rival grabado, debe coincidir.
                    if recorded_rival:
                        if normalizer_tool.clean(recorded_rival) != normalizer_tool.clean(current_opponent):
                            continue
                    else:
                        # Fallback heuristic: si el texto menciona un equipo que NO es el oponente actual
                        # (ej: menciona 'Galatasaray' y el oponente actual es 'PSG'), descartar.
                        opp_canon = normalizer_tool.clean(current_opponent)
                        # Buscar si hay mención de otros equipos conocidos en la señal.
                        # Esto es costoso, así que usamos un check simple.
                        if "muslera" in signal_text or "galatasaray" in signal_text:
                            if "galatasaray" not in opp_canon.lower():
                                continue

                out.append(parsed)
                
        if len(out) >= max_items:
            break
            
    return list(reversed(out))


def _prune_history_signals_for_analyst(
    history_signals: list[dict],
    existing_signals: Optional[list[dict]] = None,
    max_items: int = 20,
) -> list[dict]:
    """
    Reduce ruido de historial antes de fusionar en el payload del analista.
    Prioriza señales recientes/no duplicadas y evita repetir tipos/textos ya cubiertos
    por señales del run actual (YouTube/Web/Manual).
    Al usar predicción individual en el Analista, el límite sube a 20 (casi sin filtro)
    dejando solo la poda inteligente para descartar clones.
    """
    if not history_signals:
        return []

    try:
        max_items = max(1, int(max_items))
    except Exception:
        max_items = 20

    covered_keys = set()
    covered_type_text = set()
    for sig in (existing_signals or []):
        if not isinstance(sig, dict):
            continue
        covered_keys.add(_signal_dedup_key(sig))
        covered_type_text.add((
            str(sig.get("type") or "other").strip().lower(),
            _normalize_signal_text(str(sig.get("signal") or "")),
        ))

    # Tipos más valiosos/estructurales para predicción.
    type_priority = {
        "injury_news": 100,
        "disciplinary_issue": 95,
        "coach_change": 92,
        "racism_incident": 90,
        "financial_crisis": 88,
        "home_venue_issue": 85,
        "schedule_load": 80,
        "multi_competition_load": 80,
        "rotation": 72,
        "previous_match_context": 70,
        "media_pressure": 62,
        "morale": 58,
        "other": 40,
    }

    unique_by_type_text: dict[tuple[str, str], dict] = {}
    for sig in history_signals:
        if not isinstance(sig, dict):
            continue
        sig_text = str(sig.get("signal") or "").strip()
        if not sig_text:
            continue
        sig_type = str(sig.get("type") or "other").strip().lower() or "other"
        norm_text = _normalize_signal_text(sig_text)
        if not norm_text:
            continue

        # Saltar si ya está cubierto por señales del run actual
        if _signal_dedup_key(sig) in covered_keys or (sig_type, norm_text) in covered_type_text:
            continue

        key = (sig_type, norm_text)
        conf = sig.get("confidence", 0.4)
        try:
            conf_val = float(conf)
        except Exception:
            conf_val = 0.4
        final_score = sig.get("final_signal_score", conf_val)
        try:
            final_score_val = float(final_score)
        except Exception:
            final_score_val = conf_val
        date_str = str(sig.get("date") or "").strip()[:10]
        rank = (
            type_priority.get(sig_type, 50),
            1 if date_str else 0,
            final_score_val,
            conf_val,
        )

        current = unique_by_type_text.get(key)
        if not current:
            unique_by_type_text[key] = dict(sig, _rank=rank)
            continue
        if rank > current.get("_rank", (0, 0, 0)):
            unique_by_type_text[key] = dict(sig, _rank=rank)

    pruned_candidates = list(unique_by_type_text.values())

    # Orden: mayor prioridad -> con fecha -> más reciente -> confianza
    def _sort_key(s: dict):
        sig_type = str(s.get("type") or "other").strip().lower() or "other"
        date_str = str(s.get("date") or "").strip()[:10]
        conf = s.get("confidence", 0.4)
        try:
            conf_val = float(conf)
        except Exception:
            conf_val = 0.4
        final_score = s.get("final_signal_score", conf_val)
        try:
            final_score_val = float(final_score)
        except Exception:
            final_score_val = conf_val
        return (
            type_priority.get(sig_type, 50),
            1 if date_str else 0,
            date_str,  # ISO ascending; se usa reverse=True abajo
            final_score_val,
            conf_val,
        )

    pruned_candidates.sort(key=_sort_key, reverse=True)
    pruned = []
    used_types = {}
    for sig in pruned_candidates:
        sig_type = str(sig.get("type") or "other").strip().lower() or "other"
        # Evitar sobrecargar con demasiadas señales del mismo tipo débil
        used_types[sig_type] = used_types.get(sig_type, 0) + 1
        if sig_type in {"morale", "media_pressure", "other"} and used_types[sig_type] > 1:
            continue
        clean_sig = dict(sig)
        clean_sig.pop("_rank", None)
        pruned.append(clean_sig)
        if len(pruned) >= max_items:
            break

    return pruned


def _merge_context_signals_multisource(
    team: str,
    opponent: Optional[str],
    competition_teams: list[str],
    youtube_signals: list[dict],
    web_team_payload: Optional[dict],
    manual_signals: Optional[list[dict]] = None,
    history_signals: Optional[list[dict]] = None,
) -> tuple[list[dict], list[str]]:
    """
    Fusión/deduplicación incremental de señales de contexto.
    Paso actual: YouTube + Web + Manual + History.
    """
    merged, extra_bullets = _merge_context_signals_youtube_web(youtube_signals, web_team_payload)

    merged_by_key: dict[str, dict] = {}

    def _ingest(sig: dict, fallback_source: str):
        if not isinstance(sig, dict):
            return
        signal_text = (sig.get("signal") or "").strip()
        if not signal_text:
            return
        prov = sig.get("provenance") or [fallback_source]
        if not isinstance(prov, list):
            prov = [fallback_source]
        norm_sig = {
            "type": (sig.get("type") or "other").strip(),
            "signal": signal_text,
            "evidence": (sig.get("evidence") or "").strip(),
            "confidence": sig.get("confidence", 0.4),
            "date": (sig.get("date") or None),
            "provenance": sorted({str(p).strip() for p in prov if str(p).strip()} or {fallback_source}),
        }
        key = _signal_dedup_key(norm_sig)
        existing = merged_by_key.get(key)
        if not existing:
            merged_by_key[key] = norm_sig
            return
        existing["provenance"] = sorted(set(existing.get("provenance") or []) | set(norm_sig.get("provenance") or []))
        try:
            existing["confidence"] = max(float(existing.get("confidence", 0.0)), float(norm_sig.get("confidence", 0.0)))
        except Exception:
            pass
        if not existing.get("date") and norm_sig.get("date"):
            existing["date"] = norm_sig.get("date")
        ev_existing = (existing.get("evidence") or "").strip()
        ev_new = (norm_sig.get("evidence") or "").strip()
        if ev_new and ev_new.lower() not in ev_existing.lower():
            existing["evidence"] = f"{ev_existing} | {ev_new}".strip(" |")

    for sig in merged or []:
        _ingest(sig, "youtube")
    for sig in manual_signals or []:
        _ingest(sig, "manual")
    for sig in history_signals or []:
        _ingest(sig, "history")

    sanitized = _sanitize_context_signals_for_match(
        team=team,
        opponent=opponent,
        competition_teams=competition_teams,
        signals=list(merged_by_key.values()),
    )
    return sanitized, extra_bullets

def _get_team_context(team: str, history: dict, max_entries: int = 5) -> str:
    """Obtiene un resumen del historial para un equipo específico."""
    entries = history.get(team, [])
    if not entries:
        return "Sin historial previo."
    
    # Tomar las últimas N entradas
    recent = entries[-max_entries:]
    lines = []
    for entry in recent:
        lines.append(f"- [{entry.get('date', 'N/A')}] {entry.get('insight', '')}")
    return "\n".join(lines)


def _build_alias_context(team_names: list[str]) -> str:
    """Construye una guía corta de alias para los equipos presentes en el batch."""
    lines = []
    seen = set()
    for team in team_names:
        canon = normalizer_tool.clean(team or "")
        if not canon or canon in seen:
            continue
        seen.add(canon)
        aliases = []
        for key, vals in TEAM_ALIASES.items():
            if normalizer_tool.clean(key) == canon:
                aliases.extend(vals)
        if aliases:
            uniq = []
            for a in aliases:
                if a not in uniq:
                    uniq.append(a)
            lines.append(f"- {team}: aliases/apodos = {', '.join(uniq)}")
    return "\n".join(lines) if lines else "Sin alias explícitos cargados para este batch."


def _cache_key(video_ids: list[str], teams: list[str], extra_salt: str = "") -> str:
    """Genera una clave de cache única para un conjunto de videos + equipos (+ salt opcional)."""
    canonical = "|".join(sorted(video_ids)) + "##" + "|".join(sorted(teams))
    if extra_salt:
        canonical += "##" + extra_salt
    return hashlib.md5(canonical.encode()).hexdigest()


def _extract_video_id(url: str) -> str:
    """Extrae el video_id de una URL de YouTube."""
    patterns = [
        r"(?:v=|youtu\.be/|/embed/)([\w-]{11})",
        r"(?:shorts/)([\w-]{11})",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return url  # fallback: URL completa como ID


def _load_cache() -> dict:
    """Carga el cache de insights desde disco."""
    if os.path.exists(INSIGHTS_CACHE_FILE):
        try:
            with open(INSIGHTS_CACHE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cache(cache: dict) -> None:
    """Guarda el cache de insights a disco."""
    try:
        with open(INSIGHTS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"No se pudo guardar el cache de insights: {e}")


def _cache_is_valid(entry: dict, ttl_days: int) -> bool:
    """Verifica que la entrada del cache no haya expirado."""
    saved_at = entry.get("saved_at")
    if not saved_at:
        return False
    try:
        dt = datetime.fromisoformat(saved_at)
        return datetime.now(timezone.utc) - dt < timedelta(days=ttl_days)
    except Exception:
        return False



# ============================================================================
# TRANSCRIPCIÓN DE YOUTUBE
# ============================================================================

def _is_youtube_url(url: str) -> bool:
    """Detecta si una URL corresponde a un video de YouTube."""
    youtube_regex = (
        r'(https?://)?(www\.)?'
        r'(youtube|youtu|youtube-nocookie)\.(com|be)/'
        r'(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
    )
    return bool(re.match(youtube_regex, url))


def _load_web_article(url: str) -> tuple[Optional[str], dict]:
    """
    Carga el contenido de un artículo web (Scraper genérico).
    Optimizado inicialmente para primerabchile.cl.
    """
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return None, {"error": "missing dependencies (requests/beautifulsoup4)", "url": url}

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept-Language": "es-CL,es;q=0.9",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Intentar extraer título
        title = ""
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)
        else:
            title = soup.title.string if soup.title else "Untitled Article"

        # Intentar extraer contenido (párrafos de la noticia)
        # En WordPress (como primerabchile.cl), el contenido suele estar en .entry-content o article
        content_div = soup.find(class_=re.compile(r"content|entry|article|post"))
        if content_div:
            paragraphs = content_div.find_all("p")
        else:
            paragraphs = soup.find_all("p")

        text_content = "\n".join([p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20])
        
        meta = {
            "url": url,
            "title": title,
            "channel": "Web Source",
            "language": "es",
            "upload_date": datetime.now(timezone.utc).isoformat()[:10]
        }

        if not text_content.strip():
            return None, {"error": "empty content extracted", "url": url}

        return text_content.strip(), meta

    except Exception as e:
        return None, {"error": str(e), "url": url}


def _load_youtube_transcript(url: str) -> tuple[Optional[str], dict]:
    """
    Carga la transcripción de un video de YouTube usando múltiples estrategias.

    Intento 1: youtube-transcript-api con idiomas preferidos (es, en, pt)
    Intento 2: listar transcripts disponibles y traducir si es necesario
    Intento 3: captions automáticos desde yt_dlp
    Intento 4: usar descripción del video como insumo mínimo

    Returns:
        Tuple (text, meta):
        - text: transcripción concatenada o None si no se pudo obtener
        - meta: dict con url, title, channel, language (o error)
    """
    title = ""
    channel = ""
    used_lang = None
    preferred_languages = ["es", "en", "pt"]

    try:
        import yt_dlp

        # Extraer metadata del video
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        title = info.get("title", "")
        channel = info.get("channel", "") or info.get("uploader", "")
        video_id = info.get("id", "")
        upload_date = info.get("upload_date", "")  # Formato YYYYMMDD de yt-dlp
        
        # Normalizar upload_date a YYYY-MM-DD
        if upload_date and len(upload_date) == 8:
            upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"

        if not video_id:
            match = re.search(r"(?:v=|/)([a-zA-Z0-9_-]{11})", url)
            video_id = match.group(1) if match else ""

        text = None

        # Intento 1: youtube-transcript-api directa
        if video_id:
            try:
                from youtube_transcript_api import YouTubeTranscriptApi

                for lang in preferred_languages:
                    try:
                        data = YouTubeTranscriptApi.get_transcript(video_id, languages=[lang])
                        text = " ".join([x["text"] for x in data])
                        used_lang = lang
                        break
                    except Exception:
                        continue
            except Exception:
                pass

        # Intento 2: listar transcripts y traducir si es posible
        if text is None:
            try:
                from youtube_transcript_api import YouTubeTranscriptApi

                transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
                for lang in preferred_languages:
                    try:
                        t = transcripts.find_transcript([lang])
                        data = t.fetch()
                        text = " ".join([x["text"] for x in data])
                        used_lang = lang
                        break
                    except Exception:
                        continue
                if text is None:
                    for t in transcripts:
                        try:
                            t_es = t.translate("es")
                            data = t_es.fetch()
                            text = " ".join([x["text"] for x in data])
                            used_lang = "es"
                            break
                        except Exception:
                            continue
            except Exception:
                pass

        # Si tenemos transcript pero no en español, intentar traducir a español
        if text is not None and used_lang and used_lang != "es":
            try:
                from youtube_transcript_api import YouTubeTranscriptApi
                transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
                t = transcripts.find_transcript([used_lang])
                t_es = t.translate("es")
                data = t_es.fetch()
                text = " ".join([x["text"] for x in data])
                used_lang = "es"
            except Exception:
                pass

        # Intento 3: captions automáticos desde yt_dlp
        if text is None:
            import requests as req

            caps = info.get("automatic_captions") or info.get("subtitles") or {}
            chosen = None
            for lang in preferred_languages + list(caps.keys()):
                if lang in caps and caps[lang]:
                    cand = None
                    for fmt in caps[lang]:
                        if fmt.get("ext") in ("vtt", "ttml", "srv1", "srv3"):
                            cand = fmt
                            break
                    if not cand:
                        cand = caps[lang][0]
                    chosen = (lang, cand.get("url"))
                    break
            if chosen and chosen[1]:
                try:
                    r = req.get(chosen[1], timeout=20)
                    r.raise_for_status()
                    raw = r.text
                    lines = []
                    for ln in raw.splitlines():
                        l = ln.strip()
                        if not l or "WEBVTT" in l or "-->" in l or l.isdigit():
                            continue
                        l = l.replace("<c>", "").replace("</c>", "")
                        lines.append(l)
                    if lines:
                        text = " ".join(lines)
                        used_lang = chosen[0]
                except Exception:
                    pass

        # Intento 4: usar descripción del video como insumo mínimo
        if text is None:
            desc = info.get("description") or ""
            if desc.strip():
                text = desc.strip()
                used_lang = used_lang or "unknown"
            else:
                return None, {
                    "error": "no transcript available",
                    "url": url,
                    "title": title,
                    "channel": channel,
                    "upload_date": upload_date,
                }

        meta = {
            "url": url, 
            "title": title, 
            "channel": channel, 
            "language": used_lang,
            "upload_date": upload_date
        }
        return text, meta

    except Exception as e:
        return None, {"error": str(e), "url": url}


# ============================================================================
# UTILIDADES DE MATCHING
# ============================================================================

def _find_next_match(
    team: str, odds: list[dict], days_ahead: int = 14
) -> Optional[dict]:
    """
    Encuentra el próximo partido de un equipo a partir de los odds canónicos.
    """
    now = datetime.now(timezone.utc)
    limit = now + timedelta(days=days_ahead)
    best = None
    best_dt = None

    for ev in odds:
        home = ev.get("home_team", "").strip()
        away = ev.get("away_team", "").strip()

        if team.lower() not in (home.lower(), away.lower()):
            continue

        dt_str = ev.get("commence_time", "")
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except Exception:
            continue

        if dt < now or dt > limit:
            continue

        if best_dt is None or dt < best_dt:
            opponent = away if home.lower() == team.lower() else home
            best = {
                "opponent": opponent,
                "date": dt_str,
                "competition": ev.get("competition", ""),
                "source": "odds",
            }
            best_dt = dt

    return best


# ============================================================================
# LLM BATCH: 1 LLAMADA POR COMPETENCIA
# ============================================================================

def _make_llm() -> Optional[Any]:
    """Crea instancia de LLM según factory."""
    try:
        from utils.llm_factory import get_llm
        # No pasar callbacks directamente a get_llm - algunas implementaciones (Gemini) no los soportan bien
        return get_llm(temperature=0.2, profile="insights_core")
    except Exception as e:
        logger.warning(f"Error al inicializar LLM: {e}")
        logger.warning("Using fallback web agent insights (no LLM available)")
        return None


def _build_matches_context(teams_matches: list[dict]) -> str:
    """
    Construye la sección de partidos para el prompt batch.

    Args:
        teams_matches: Lista de dicts con team, opponent, date, competition
    Returns:
        Texto formateado con la lista de partidos próximos
    """
    lines = []
    for i, tm in enumerate(teams_matches, 1):
        team = tm["team"]
        nm = tm.get("next_match")
        if nm:
            lines.append(
                f"{i}. {team} vs {nm['opponent']} — {nm['date']}"
            )
        else:
            lines.append(f"{i}. {team} — sin partido próximo definido")
    return "\n".join(lines)


def _sanitize_transcript(text: str) -> str:
    """
    Sanitiza la transcripción para mitigar ataques de prompt injection
    y ruidos irrelevantes.
    """
    if not text:
        return ""
    # Eliminar secuencias que parezcan comandos o instrucciones del sistema
    text = re.sub(r"(?i)(system prompt|ignore previous instructions|you are now|forget everything)", "[REDACTED]", text)
    # Limpiar caracteres de control y exceso de espacios
    text = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _generate_insights_from_web_agent(
    web_agent_payload: Optional[dict],
    teams_matches: list[dict],
    competition: str
) -> dict:
    """
    Genera insights usando SOLO el output del web_agent.
    Se usa cuando YouTube y LLM fallan completamente.
    
    Args:
        web_agent_payload: dict con {"teams": {comp: {team: {...}}}, "summaries": {...}}
        teams_matches: Lista de equipos con partidos próximos
        competition: Code de competencia
    
    Returns:
        Dict {"teams": [...], "competition_analysis": "..."}
    """
    if not web_agent_payload:
        return {"teams": [], "competition_analysis": ""}
    
    web_team_map = web_agent_payload.get("teams", {}).get(competition, {})
    web_summary = web_agent_payload.get("summaries", {}).get(competition, "")
    
    results = []
    
    for tm in teams_matches:
        team = tm["team"]
        team_clean = normalizer_tool.clean(team)
        
        # Buscar web agent data para este equipo
        web_data = web_team_map.get(team_clean)
        if not web_data:
            # Fallback: raw insight vacío
            results.append({
                "team": team,
                "insight": "Datos limitados (web agent indisponible)",
                "forecast": None,
                "entities": {"injuries": [], "suspensions": [], "absences": []},
                "context_signals": [],
            })
            continue
        
        # Construir insight desde web agent data
        context_signals = web_data.get("context_signals", []) or []
        raw_context = web_data.get("raw_context", "")
        last_result = web_data.get("last_result", "")
        form = web_data.get("form", "")
        position = web_data.get("position_in_table")
        points = web_data.get("points")
        
        # Texto de insight: combinar última acción + contexto + forma
        insight_parts = []
        if last_result:
            insight_parts.append(f"Último: {last_result}")
        if position and points is not None:
            insight_parts.append(f"Tabla: pos {position}, {points} pts")
        if form:
            insight_parts.append(f"Forma: {form}")
        if raw_context:
            insight_parts.append(f"{raw_context[:200]}")
        
        insight_text = " | ".join(insight_parts) or "Datos web agent disponibles"
        
        # Entities desde web agent
        entities = {
            "injuries": web_data.get("injuries", []) or [],
            "suspensions": [],
            "absences": [],
        }
        
        results.append({
            "team": team,
            "insight": insight_text,
            "forecast": None,
            "entities": entities,
            "context_signals": context_signals,
        })
    
    return {
        "teams": results,
        "competition_analysis": web_summary or f"Análisis desde web agent para {competition}",
    }


def _llm_batch_insights(
    llm,
    transcript: str,
    teams_matches: list[dict],
    competition: str,
    manual_news_payload: Optional[dict] = None,
    web_agent_payload: Optional[dict] = None,
) -> dict:
    """
    Genera insights para TODOS los equipos de una competencia en UNA sola
    llamada al LLM.

    Args:
        llm: Instancia de ChatOpenAI
        transcript: Transcripción concatenada de los videos
        teams_matches: Lista de dicts [{"team": ..., "next_match": ...}, ...]
        competition: Etiqueta de competencia (UCL, CHI1)
        web_agent_payload: Datos estructurados del Agente Web

    Returns:
        Dict {"teams": [...], "competition_analysis": "..."}
    """
    if llm is None:
        # Fallback heurístico (sin LLM)
        results = []
        for tm in teams_matches:
            results.append({
                "team": tm["team"],
                "insights": [f"No LLM available. Transcript: {len(transcript)} chars."],
                "forecast": None,
                "entities": {"injuries": [], "suspensions": [], "absences": []},
            })
        return {"teams": results, "competition_analysis": f"Panorama heurístico: {competition_summary}"}

    matches_ctx = _build_matches_context(teams_matches)
    team_names = [tm["team"] for tm in teams_matches]
    clean_transcript = _sanitize_transcript(transcript)

    # Preparar Contexto de Equipos desde Web Agent
    web_team_data = (web_agent_payload or {}).get("teams", {}).get(competition, {})
    competition_summary = (web_agent_payload or {}).get("summaries", {}).get(competition, "")

    # Construir contexto histórico para cada equipo enriquecido con Web Data
    history = _load_team_history()
    historical_ctx_list = []
    for team in team_names:
        team_clean = normalizer_tool.clean(team)
        h_ctx = _get_team_context(team, history)
        
        # Enriquecer con datos frescos del Web Agent
        web_info = web_team_data.get(team_clean)
        if web_info:
            w_res = web_info.get("last_result", "No disponible")
            w_pos = web_info.get("position_in_table", "?")
            w_pts = web_info.get("points", "?")
            w_form = web_info.get("form", "N/A")
            h_ctx += f"\n[FRESH WEB DATA] Último Resultado: {w_res} | Posición: {w_pos} ({w_pts} pts) | Forma: {w_form}"
        
        historical_ctx_list.append(f"### {team} PREVIOUS KNOWLEDGE:\n{h_ctx}")
    
    historical_ctx = "\n\n".join(historical_ctx_list)
    alias_ctx = _build_alias_context(team_names)
    # Preparar SECCIÓN DE NOTICIAS MANUALES (Dual: Texto o JSON)
    manual_news_payload = manual_news_payload or {}
    manual_news_text = str(manual_news_payload.get("text") or "").strip()
    manual_news_updated_at = str(manual_news_payload.get("updated_at") or "").strip()
    
    # v14: Si el payload es un JSON estructurado (tiene 'tournament' o 'teams'), lo volcamos para el LLM.
    if any(k in manual_news_payload for k in ["tournament", "teams", "match_briefs"]):
        # Prioridad Absoluta: Formateamos el JSON estructurado como Verdad Absoluta
        structured_manual = json.dumps(manual_news_payload, indent=2, ensure_ascii=False)
        manual_news_section = (
            f"!!! VERDAD ABSOLUTA (Prioridad 1) !!!\n"
            f"El usuario ha ingresado esta información estructurada que DEBE prevalecer sobre YouTube:\n"
            f"{structured_manual[:8000]}" # Límite razonable para no saturar el prompt
        )
    elif manual_news_text:
        # Formato antiguo: Texto plano
        manual_news_section = (
            f"Actualizado: {manual_news_updated_at or 'sin fecha'}\n"
            f"{manual_news_text[:4000]}"
        )
    else:
        manual_news_section = "Sin noticias manuales del usuario."

    # Bloque de Panorama del Torneo (Web Context)
    web_panorama_section = "Sin datos recientes de panorama web."
    if competition_summary:
        web_panorama_section = f"PANORAMA WEB ACTUAL:\n{competition_summary}"

    prompt = f"""### SYSTEM ROLE — EXPERTO EN PRONÓSTICO DEPORTIVO
Eres un **analista de élite en pronóstico deportivo**, con 20+ años de experiencia en modelado predictivo de resultados de fútbol profesional. Trabajas para un equipo de analistas cuantitativos y tu output alimentará directamente a otro agente (el Analista) que tomará decisiones de pronóstico y apuesta con valor esperado positivo.

Tu especialidad es entender **qué variables realmente mueven el resultado** de un partido y extraer señales accionables de múltiples fuentes. No eres un comentarista deportivo — eres un científico del pronóstico que sabe que los datos incorrectos o superficiales dañan el modelo.

---
#### SEÑALES QUE DEBES BUSCAR (orientativo — no limitante)
... (omitido por brevedad en el prompt real interno si aplica, pero aquí lo mantenemos para el LLM) ...
**DISPONIBILIDAD DE PLANTILLA** (impacto típicamente ALTO)
   - Lesiones confirmadas y dudosas, especialmente titulares y figuras
   - Suspensiones y sanciones disciplinarias
   - Ausencias por acumulación de tarjetas, selección nacional o compromisos paralelos
   - Dudas de último minuto (parte médico previo al partido)

**FORMA RECIENTE Y MOMENTUM** (impacto típicamente ALTO)
   - Últimos resultados (W/D/L) con contexto del rival enfrentado
   - Racha de goles a favor y en contra
   - Rendimiento como local vs visitante en la temporada actual
   - Tendencia: ¿el equipo está en ascenso, estancado o en caída?

**CONTEXTO TÁCTICO Y ROTACIONES**
   - Cambios de sistema o alineación confirmados o anticipados
   - Rotación por fatiga o calendarios comprimidos
   - Doble competencia (liga + copa + internacional) → desgaste físico real
   - Matchup táctico específico contra el rival

**MOTIVACIÓN Y CONTEXTO COMPETITIVO**
   - Importancia del partido: definición de título, lucha por no descender, acceso a copa, clásico
   - Presión diferencial entre equipos (uno tiene más que perder)
   - Estado emocional: euforia post-victoria gran o trauma post-derrota
   - Historial reciente H2H (últimos 3 enfrentamientos directos)

**FACTORES INSTITUCIONALES Y OFF-FIELD** (puede ser decisivo, a veces más que táctico)
   - Crisis económica o impago de sueldos
   - Conflicto interno: camarín vs cuerpo técnico, directivos
   - Cambio reciente de entrenador (efecto "DT nuevo" — tendencia positiva inicial)
   - Problemas de localía: estadio sancionado, partido sin público
   - Presión mediática extrema
   - Incidentes raciales o disciplinarios que dividen al grupo

**CONTEXTO DE JORNADA**
   - Posición en la tabla y urgencia de los puntos
   - Qué queda de temporada y qué está en juego en este partido específico

**NARRATIVA Y SEÑALES PSICOLÓGICAS**
   - ¿El equipo viene de una derrota traumática o una victoria clave?
   - ¿Hay presión mediática o narrativa de "deuda" pendiente?
   - ¿Se enfrenta a un rival con historial de dominio sobre ellos?

**SEÑALES DE MERCADO**
   - Las cuotas actuales reflejan el consenso profesional; úsalas como referencia
   - Si tus señales contradicen al mercado, señálalo explícitamente y justifica

---
#### REGLAS CRÍTICAS DE VERACIDAD (SKEPTICISM FIRST):
1. **PROTECCIÓN CONTRA ANACRONISMOS**: Si una señal o noticia menciona partidos internacionales (ej: Libertadores/Sudamericana) contra rivales como 'Fortaleza', 'San Lorenzo' o 'Gremio', pero el **PANORAMA WEB ACTUAL** no confirma que el equipo está jugando dicha competencia EN MARZO 2026, ignóralo por completo.
2. **FILTRO DE CUERPO TÉCNICO**: Verifica que el DT mencionado coincida con la realidad de 2026 (ej: Gustavo Lema en Audax, Lucas Bovaglio en O'Higgins). Si la transcripción menciona nombres antiguos (Arrué, Meneghini, etc.), descártalo como ruido de años pasados.
3. **FILTRO DE GÉNERO**: NO mezcles resultados del Campeonato Femenino con el Masculino. Si ves un 3-0 a Huachipato que no figura en la tabla masculina, es probable que sea femenino o una alucinación.
4. **LA DUDA ES TU AMIGA**: Si algo suena a noticia de hace años o no tiene sustento en el Panorama Web Actual, NO lo incluyas en los insights. Es preferible tener menos información que información contaminada.

---
#### JERARQUÍA DE CONFIANZA DE TUS FUENTES
1. Periodistas especializados en el club (rueda de prensa, fuente directa)
2. Agencias y medios oficiales (ESPN, AS, Marca)
3. Agente Web (PANORAMA WEB ACTUAL) → Máxima prioridad para hechos factuables 2026
4. Canales de análisis táctico (ThonyBet)
...

---
### PANORAMA WEB ACTUAL (Contexto macro del torneo):
{web_panorama_section}

### HISTORICAL CONTEXT (Lo que ya sabemos de los equipos):
{historical_ctx}

### ALIASES DE EQUIPOS (usar para mapear menciones indirectas)
{alias_ctx}

### NOTICIAS MANUALES DEL USUARIO (opcional, usar SOLO si aplica)
{manual_news_section}

### TAREA
1. Genera un **ANÁLISIS GLOBAL DE LA JORNADA** basándote en la transcripción y el panorama web. Resalta equipos obligados, duelos directos y tendencias generales.
2. Analiza la transcripción sobre {competition} y genera un análisis detallado para cada uno de los siguientes equipos.
3. **REGLA DE COBERTURA**: Si un equipo NO es mencionado en la transcripción pero existe información sobre él en el **PANORAMA WEB ACTUAL** o **HISTORICAL CONTEXT**, DEBES generar un análisis basado en esa información. Indica en `confidence_rationale` que la fuente es el panorama web/historial. No dejes equipos con "Sin información" si hay contexto web disponible.

PARTIDOS PRÓXIMOS:
{matches_ctx}

TRANSCRIPCIÓN (Fragmento):
{clean_transcript[:14000]}

### REGLAS DE RESPUESTA
Responde EXCLUSIVAMENTE con un JSON válido:
{{
  "competition_analysis": "Análisis macro de la fecha/jornada. Quién lidera, quién está en crisis, qué equipos se juegan la vida hoy. Máx 3-4 líneas.",
  "teams": [
    {{
      "team": "Nombre exacto del equipo",
      "insights": ["Hechos clave tácticos/contexto/off-field"],
      "insight_confidence": 0.0,
      "confidence_rationale": "...",
      "citations": [],
      "context_signals": [
        {{
          "type": "...",
          "signal": "...",
          "evidence": "...",
          "date": "YYYY-MM-DD",
          "is_rumor": false,
          "confidence": 0.0
        }}
      ],
      "forecast": {{ "outcome": "...", "confidence": 0.0 }},
      "entities": {{ "injuries": [], "suspensions": [] }}
    }}
  ]
}}
Responde SOLO con el JSON."""

    try:
        response = llm.invoke(prompt)
        
        raw_content = response.content if hasattr(response, "content") else str(response)
        if isinstance(raw_content, list):
            content = " ".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in raw_content
            ).strip()
            if not content:
                raise ValueError("llm batch response: lista vacía")
        else:
            content = str(raw_content).strip()

        # Limpiar posibles bloques markdown
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*\n?", "", content)
            content = re.sub(r"\n?```\s*$", "", content)

        data = json.loads(content)
        # Asegurar formato dict con teams y competition_analysis
        if isinstance(data, dict):
            if "teams" not in data:
                data["teams"] = []
            if "competition_analysis" not in data:
                data["competition_analysis"] = ""
            return data

        if isinstance(data, list):
            return {"teams": data, "competition_analysis": ""}

        logger.warning(f"LLM batch response unexpected format for {competition}")
    except json.JSONDecodeError as e:
        logger.warning(f"LLM batch JSON parse error for {competition}: {e}")
    except Exception as e:
        logger.error(f"LLM batch error for {competition}: {e}")

    # Fallback: retornar dict vacío estructurado
    return {"teams": [], "competition_analysis": ""}


def _parse_team_result(raw: dict) -> tuple[str, Optional[dict], Optional[dict], dict, list[dict]]:
    """
    Parsea el resultado de un equipo del batch LLM.

    Returns:
        Tuple (insight_text, forecast, entities, insight_meta, context_signals)
    """
    bullets = [str(b).strip() for b in (raw.get("insights") or []) if str(b).strip()]

    # Añadir confianza y citas a la metadata del insight si existen
    insight_meta = {
        "confidence": raw.get("insight_confidence", 0.5),
        "confidence_rationale": raw.get("confidence_rationale", ""),
        "citations": raw.get("citations") or []
    }

    forecast = raw.get("forecast")
    if isinstance(forecast, dict) and "outcome" not in forecast:
        forecast = None

    ents = raw.get("entities") or {}
    entities = None
    if isinstance(ents, dict):
        entities = {
            "injuries": ents.get("injuries") or [],
            "suspensions": ents.get("suspensions") or [],
            "absences": ents.get("absences") or [],
        }

    context_signals = []
    raw_signals = raw.get("context_signals") or []
    if isinstance(raw_signals, list):
        for sig in raw_signals:
            if not isinstance(sig, dict):
                continue
            signal_text = (sig.get("signal") or "").strip()
            if not signal_text:
                continue
            context_signals.append(
                {
                    "type": (sig.get("type") or "other").strip(),
                    "signal": signal_text,
                    "evidence": (sig.get("evidence") or "").strip(),
                    "date": (str(sig.get("date")).strip()[:10] if sig.get("date") else None),
                    "is_rumor": bool(sig.get("is_rumor", False)),
                    "confidence": sig.get("confidence", 0.4),
                }
            )

    # Solo añadir señales de contexto como bullets si NO están ya presentes de forma similar.
    # NOTA: En la UI (app.py) también se filtrará para evitar duplicidad visual entre el bloque de texto
    # y el bloque de señales estructuradas.
    if context_signals:
        existing_norm = { _normalize_signal_text(b) for b in bullets }
        for sig in context_signals:
            sig_text = (sig.get("signal") or "").strip()
            if not sig_text:
                continue
            
            norm_sig = _normalize_signal_text(sig_text)
            if any(norm_sig in b_norm or b_norm in norm_sig for b_norm in existing_norm):
                continue
                
            prefix = "Contexto"
            sig_type = (sig.get("type") or "").strip()
            if sig_type:
                prefix = f"Contexto ({sig_type})"
            if sig.get("is_rumor"):
                prefix = f"{prefix} [RUMOR]"
            conf = sig.get("confidence")
            sig_date = sig.get("date")
            date_txt = f" [{sig_date}]" if sig_date else ""
            
            new_bullet = f"{prefix}{date_txt}: {sig_text}"
            if isinstance(conf, (int, float)):
                new_bullet += f" [conf. {conf:.2f}]"
            
            bullets.append(new_bullet)
            existing_norm.add(norm_sig)

    insight_text = "\n".join([f"- {b}" for b in bullets]) if bullets else ""

    return insight_text, forecast, entities, insight_meta, context_signals


# ============================================================================
# NODO PRINCIPAL DE LANGGRAPH
# ============================================================================

def _semantic_dedup_supervisor(llm, team: str, new_text: str, history: list[dict]) -> dict:
    """
    Usa el LLM para supervisar si una nueva señal es semánticamente duplicada de alguna en el historial.
    Solo se debe llamar cuando el comparador estadístico detecta duda (>0.6 similitud).
    
    Retorna: {"is_duplicate": bool, "action": "keep_existing"|"keep_new"|"merge", "merged_text": str|None}
    """
    if not llm or not history:
        return {"is_duplicate": False, "action": "keep_new"}

    # Tomar solo los últimos 10 del historial para contexto del supervisor (eficiencia)
    history_str = "\n".join([f"- {h.get('insight')}" for h in history[-10:]])
    
    prompt = f"""Eres un supervisor de integridad de datos deportivos (Árbitro de Verdad).
Analiza si la SIGUIENTE SEÑAL NUEVA es redundante o CONTRADICTORIA con lo que ya está en el HISTORIAL para el equipo {team}.

HISTORIAL RECIENTE:
{history_str}

SIGUIENTE SEÑAL NUEVA:
{new_text}

REGLAS DE ARBITRAJE:
1. DUPLICADO: Si informan el mismo hecho con palabras distintas.
2. CONTRADICCIÓN: Si los hechos son mutuamente excluyentes (ej: "Titular" vs "Banco", "Gana 1-0" vs "Pierde 2-0").
3. RESOLUCIÓN: 
   - Si hay contradicción, elige la más reciente (fresca) o la más específica (con más detalle/fuente).
   - Si la nueva es mejor, usa "replace_conflict". 
   - Si la vieja es mejor/más veraz, usa "keep_existing".
4. MERGE: Si la nueva aporta un detalle crítico que la vieja no tenía.

Responde SOLO en JSON:
{{
  "is_duplicate": true/false,
  "is_contradictory": true/false,
  "explanation": "breve razon del arbitraje",
  "action": "keep_existing" (vieja gana), "keep_new" (nueva gana), "merge" (unir), "replace_conflict" (nueva aplasta la contradicción vieja),
  "merged_text": "Texto si la acción es merge o replace_conflict, de lo contrario null"
}}
"""
    try:
        response = llm.invoke(prompt)
        raw_content = response.content if hasattr(response, "content") else str(response)
        
        # Normalizar si es lista (patrón canónico Gemini/LangGraph)
        if isinstance(raw_content, list):
            content = "".join([part.get("text", "") if isinstance(part, dict) else str(part) for part in raw_content])
        else:
            content = str(raw_content)

        # Saneamiento de respuesta Gemini (Markdown block)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
            
        data = json.loads(content)
        return data
    except Exception as e:
        logger.warning(f"Error en Supervisor Semántico: {e}")
        return {"is_duplicate": False, "action": "keep_new"}


def insights_agent_node(state: AgentState) -> AgentState:
    """
    Nodo LangGraph que genera insights por equipo usando YouTube + LLM.

    OPTIMIZACIÓN: Hace 1 sola llamada LLM por competencia (batch)
    en lugar de 1 por equipo. Con 2 competencias → 2 llamadas LLM en total.

    Proceso:
    1. Lee insights_sources del estado (URLs de YouTube por competencia)
    2. Para cada competencia con URLs:
       a. Descarga transcripciones de los videos
       b. Concatena textos priorizando los más recientes
       c. Extrae equipos candidatos de odds_canonical con sus próximos partidos
       d. Hace 1 sola llamada LLM con todos los equipos de la competencia
       e. Parsea resultados y los asigna a cada equipo
    3. Guarda resultados en state["insights"]
    """
    logger.info("=" * 60)
    logger.info("INSIGHTS AGENT: generating team insights from YouTube + LLM")
    logger.info("=" * 60)

    insights: list[dict] = []
    sources = state.get("insights_sources") or {}
    odds = state.get("odds_canonical") or []
    meta = state.get("meta", {})
    meta.setdefault("errors", {}).setdefault("insights", {})

    # Ventana de días para próximo partido (configurable)
    try:
        next_days = int(os.getenv("INSIGHTS_NEXT_DAYS", "14"))
    except ValueError:
        next_days = 14

    # TTL del cache en días (default: 3)
    try:
        cache_ttl = int(os.getenv("INSIGHTS_CACHE_TTL_DAYS", "3"))
    except ValueError:
        cache_ttl = 3

    # Máximo historial persistente por equipo (insights + context_signals)
    try:
        team_history_max_items = int(os.getenv("INSIGHTS_TEAM_HISTORY_MAX_ITEMS", "25"))
    except ValueError:
        team_history_max_items = 25

    # Cargar cache persistente
    cache = _load_cache()
    youtube_failure_cache = _load_youtube_failure_cache()
    cache_hits = 0
    cache_misses = 0

    # Intentar crear LLM
    llm = _make_llm()
    manual_news_payload = _load_manual_news_payload()
    web_agent_payload = _load_web_agent_team_map()
    web_team_map_by_comp = web_agent_payload.get("teams", {})
    web_summaries_by_comp = web_agent_payload.get("summaries", {})
    team_history_snapshot = _load_team_history()
    manual_news_text = str(manual_news_payload.get("text") or "").strip()
    manual_news_comp = str(manual_news_payload.get("competition") or "").strip()
    manual_news_salt = ""
    if manual_news_text:
        manual_news_salt = hashlib.md5(
            (str(manual_news_payload.get("updated_at") or "") + "||" + manual_news_text).encode("utf-8")
        ).hexdigest()[:12]
    if (manual_news_payload.get("text") or "").strip():
        if manual_news_comp:
            logger.info(f"Noticias manuales del usuario disponibles para {manual_news_comp}")
        else:
            logger.info("Noticias manuales del usuario disponibles para ponderar en Insights")
    if web_team_map_by_comp:
        logger.info("Web Agent output disponible para fusión de context_signals en Insights")
    if llm:
        logger.info("LLM disponible (GPT-5) — modo batch: 1 llamada por competencia")
    else:
        logger.warning("LLM no disponible — se generarán insights heurísticos")

    for comp in state.get("competitions", []):
        label = comp.get("competition")
        urls = sources.get(label, [])

        # Fallback: si no hay YouTube URLs pero sí hay web_agent data, usar web_agent
        if not urls:
            if web_team_map_by_comp.get(label):
                logger.info(f"No YouTube sources for {label}, usando Web Agent output para insights")
                # Equipos candidatos: de odds en ventana configurable
                teams: set[str] = set()
                for ev in odds:
                    if ev.get("competition") != label:
                        continue
                    teams.add(ev.get("home_team", "").strip())
                    teams.add(ev.get("away_team", "").strip())
                
                # Si no hay odds, usar fixtures
                if not teams:
                    fixtures = state.get("fixtures") or []
                    for f in fixtures:
                        if f.get("competition") == label:
                            teams.add(f.get("home_team", "").strip())
                            teams.add(f.get("away_team", "").strip())
                
                teams.discard("")
                
                if teams:
                    teams_matches = [
                        {"team": team, "next_match": _find_next_match(team, odds, days_ahead=next_days)}
                        for team in sorted(teams)
                    ]
                    
                    batch_payload = _generate_insights_from_web_agent(
                        web_agent_payload, teams_matches, label
                    )
                    batch_results = batch_payload.get("teams", [])
                    comp_analysis = batch_payload.get("competition_analysis", "")
                    
                    logger.info(f"✓ Generados {len(batch_results)} insights desde Web Agent para {label}")
                else:
                    logger.warning(f"No teams found for {label}, skipping insights")
                    continue
            else:
                logger.warning(
                    f"No YouTube sources nor Web Agent data for {label}. "
                    "Continuando en modo manual/history-only si existen insumos."
                )


        logger.info(f"Processing {len(urls)} videos for {label}")

        # Descargar transcripciones
        texts = []
        metas = []
        for u in urls:
            cached_failure = _get_cached_youtube_failure(u, youtube_failure_cache)
            if cached_failure and cached_failure.get("reason") == "youtube_antibot":
                logger.info(f"  ↷ Saltando YouTube por caché anti-bot vigente: {u}")
                continue

            if _is_youtube_url(u):
                t, m = _load_youtube_transcript(u)
                source_type = "YouTube"
            elif "primerabchile.cl" in u:
                t, m = _load_web_article(u)
                source_type = "Web (PrimeraBChile)"
            else:
                logger.info(f"  ⚠ URL no soportada, intentando como web genérica: {u}")
                t, m = _load_web_article(u)
                source_type = "Web"

            if t:
                video_title = m.get("title", "Unknown")
                video_channel = m.get("channel", "Unknown")
                logger.info(f"  ✓ {source_type}: '{video_title}' (Canal/Site: {video_channel})")
                texts.append(t)
                metas.append(m)
            else:
                error = m.get("error", "unknown error")
                if _is_youtube_url(u) and _classify_youtube_source_error(error) == "youtube_antibot":
                    _remember_youtube_failure(u, error, youtube_failure_cache)
                    logger.warning(f"  ✗ Failed to load source from {u}: bloqueo anti-bot de YouTube (cacheado)")
                else:
                    logger.warning(f"  ✗ Failed to load source from {u}: {error}")

        if not texts:
            meta["errors"]["insights"][label] = "no transcript from any source"
            logger.warning(f"No transcripts available for {label}")
            
            # Fallback: usar Web Agent si está disponible
            batch_results = []
            if web_team_map_by_comp.get(label):
                logger.info(f"→ Fallback: usando Web Agent output para {label}")
                
                # Equipos candidatos: de odds en ventana configurable
                teams: set[str] = set()
                for ev in odds:
                    if ev.get("competition") != label:
                        continue
                    teams.add(ev.get("home_team", "").strip())
                    teams.add(ev.get("away_team", "").strip())
                
                # Si no hay odds, usar fixtures
                if not teams:
                    fixtures = state.get("fixtures") or []
                    for f in fixtures:
                        if f.get("competition") == label:
                            teams.add(f.get("home_team", "").strip())
                            teams.add(f.get("away_team", "").strip())
                
                teams.discard("")
                
                if teams:
                    teams_matches = [
                        {"team": team, "next_match": _find_next_match(team, odds, days_ahead=next_days)}
                        for team in sorted(teams)
                    ]
                    
                    batch_payload = _generate_insights_from_web_agent(
                        web_agent_payload, teams_matches, label
                    )
                    batch_results = batch_payload.get("teams", [])
                    comp_analysis = batch_payload.get("competition_analysis", "")
                    
                    logger.info(f"✓ Generados {len(batch_results)} insights desde Web Agent (fallback)")
                    
                    # Continuar con el mapeo de resultados en lugar de hacer continue
                else:
                    logger.warning(f"No teams found for {label}, skipping insights")
                    continue
            else:
                logger.warning(
                    f"No web_agent data para {label}. "
                    "Continuando en modo manual/history-only."
                )

        if not texts and not batch_results:
            has_manual_news = bool((manual_news_payload.get("text") or "").strip()) if isinstance(manual_news_payload, dict) else False
            has_team_history = bool(team_history_snapshot)
            if not has_manual_news and not has_team_history:
                continue
            logger.info(
                "→ %s: sin YouTube/Web, pero hay %s%s. "
                "Se generarán insights desde insumos manuales/históricos.",
                label,
                "noticia manual" if has_manual_news else "historial",
                " + historial" if has_manual_news and has_team_history else "",
            )


        # Ordenar por fecha de subida (más reciente primero)
        def _keym(mm):
            return mm.get("upload_date") or ""

        metas_sorted = sorted(metas, key=_keym, reverse=True)

        # Concatenar textos en orden de metas_sorted
        url_to_text = {m.get("url"): t for m, t in zip(metas, texts)}
        texts_sorted = [
            url_to_text.get(m.get("url"))
            for m in metas_sorted
            if url_to_text.get(m.get("url"))
        ]
        text = "\n\n".join(texts_sorted)[:16000]
        video_meta = {"videos": metas_sorted}

        # Equipos candidatos: de odds en ventana configurable, o fixtures como fallback
        teams: set[str] = set()
        for ev in odds:
            if ev.get("competition") != label:
                continue
            teams.add(ev.get("home_team", "").strip())
            teams.add(ev.get("away_team", "").strip())
        
        # --- TAREA 9: Soporte Fixtures-First ---
        # Si no hay odds (caso común en CHI2), usamos los equipos de los fixtures
        if not teams:
            fixtures = state.get("fixtures") or []
            for f in fixtures:
                if f.get("competition") == label:
                    teams.add(f.get("home_team", "").strip())
                    teams.add(f.get("away_team", "").strip())
            if teams:
                logger.info(f"Usando {len(teams)} equipos desde fixtures para {label} (sin odds)")

        teams.discard("")

        if not teams:
            logger.warning(f"No teams found in odds or fixtures for {label}")
            continue

        # Construir lista de equipos con sus próximos partidos
        teams_matches = [
            {"team": team, "next_match": _find_next_match(team, odds, days_ahead=next_days)}
            for team in sorted(teams)
        ]

        # ── Verificar cache ─────────────────────────────────────────────────
        video_ids = [_extract_video_id(m.get("url", m.get("source", str(i))))
                     for i, m in enumerate(metas_sorted)]
        key = _cache_key(video_ids, list(teams), extra_salt=manual_news_salt)
        cached = cache.get(key)

        if cached and _cache_is_valid(cached, cache_ttl):
            # ✔ Cache HIT
            cache_data = cached["batch_results"]
            if isinstance(cache_data, dict):
                batch_results = cache_data.get("teams", [])
                comp_analysis = cache_data.get("competition_analysis", "")
            else:
                # Legacy cache (list)
                batch_results = cache_data
                comp_analysis = ""
            cache_hits += 1
            logger.info(f"★ CACHE HIT [{label}]: skipping LLM call")
        else:
            # ✖ Cache MISS
            logger.info(f"Generating insights for {label}")
            batch_payload = _llm_batch_insights(
                llm, text, teams_matches, label, 
                manual_news_payload=manual_news_payload,
                web_agent_payload=web_agent_payload
            )
            batch_results = batch_payload.get("teams", [])
            comp_analysis = batch_payload.get("competition_analysis", "")
            cache_misses += 1

            # Fallback a Web Agent si batch_results está vacío
            if not batch_results and web_team_map_by_comp.get(label):
                logger.info(f"⚠ LLM produced no insights for {label}, falling back to Web Agent")
                web_payload = _generate_insights_from_web_agent(
                    web_agent_payload, teams_matches, label
                )
                batch_results = web_payload.get("teams", [])
                comp_analysis = web_payload.get("competition_analysis", "")

            # Guardar en cache
            cache[key] = {
                "saved_at":     datetime.now(timezone.utc).isoformat(),
                "label":        label,
                "video_ids":    video_ids,
                "teams":        sorted(teams),
                "batch_results": {"teams": batch_results, "competition_analysis": comp_analysis},
            }
            _save_cache(cache)
            _save_youtube_failure_cache(youtube_failure_cache)


        # Mapear resultados
        result_by_team = {
            r.get("team", "").strip().lower(): r
            for r in batch_results if isinstance(r, dict)
        }
        result_by_team_canon = {}
        for r in batch_results:
            if isinstance(r, dict):
                k = normalizer_tool.clean(r.get("team", "") or "")
                if k and k not in result_by_team_canon:
                    result_by_team_canon[k] = r

        # Construir insights finales para cada equipo
        for tm in teams_matches:
            team = tm["team"]
            next_match = tm["next_match"]

            raw = result_by_team.get(team.lower(), {})
            if not raw:
                raw = result_by_team_canon.get(normalizer_tool.clean(team), {})
            if not raw:
                target_canon = normalizer_tool.clean(team)
                for r in batch_results:
                    if not isinstance(r, dict):
                        continue
                    r_team = r.get("team", "") or ""
                    r_canon = normalizer_tool.clean(r_team)
                    if not r_canon or not target_canon:
                        continue
                    # Fallback conservador para variantes largas/cortas del mismo equipo.
                    # Evita falsos positivos tipo "universidad de concepcion" vs "deportes concepcion".
                    if r_canon == target_canon:
                        raw = r
                        logger.info(f"Insights mapping fallback por nombre canónico: {team} <- {r_team}")
                        break
                    r_first = r_canon.split()[0] if r_canon.split() else ""
                    t_first = target_canon.split()[0] if target_canon.split() else ""
                    if r_first and t_first and r_first == t_first and (r_canon in target_canon or target_canon in r_canon):
                        # Guardia adicional: no cruzar equipos que el blacklist considera distintos.
                        from agents.normalizer_agent import _is_blacklisted_match
                        if _is_blacklisted_match(team, r_team):
                            logger.debug(f"Insights mapping bloqueado por blacklist: {team} vs {r_team}")
                            continue
                        raw = r
                        logger.info(f"Insights mapping fallback por nombre canónico: {team} <- {r_team}")
                        break

            if raw:
                insight_text, forecast, entities, insight_meta, context_signals = _parse_team_result(raw)
            else:
                insight_text = f"Sin datos tácticos en YouTube para {team}."
                forecast = None
                entities = None
                insight_meta = {"confidence": 0.0, "confidence_rationale": "No info in YT", "citations": []}
                context_signals = []

            # --- CORRECCIÓN DE CONFIANZA v12.9 (Fallback Web/Manual) ---
            # Si no hay data de YouTube (conf=0), pero hay otras fuentes, restauramos confianza base.
            web_team_payload = (web_team_map_by_comp.get(label) or {}).get(normalizer_tool.clean(team))
            
            if insight_meta["confidence"] < 0.3:
                has_structured_manual_team = _find_structured_manual_team_entry(team, manual_news_payload) is not None
                if has_structured_manual_team or ((manual_news_payload.get("text") or "").strip() and team.lower() in (manual_news_payload.get("text") or "").lower()):
                    insight_meta["confidence"] = 0.85
                    insight_meta["confidence_rationale"] = "Basado en noticias manuales del usuario."
                    if has_structured_manual_team:
                        insight_text = f"Información prioritaria (Usuario estructurado): contexto validado para {team}."
                    else:
                        insight_text = f"Información prioritaria (Usuario): {manual_news_text[:200]}..."
                elif web_team_payload:
                    insight_meta["confidence"] = 0.65
                    insight_meta["confidence_rationale"] = "Basado en panorama web y tabla de posiciones (sin YouTube)."
                    if not raw:
                         insight_text = web_team_payload.get("raw_context") or "Contexto web disponible (sin detalles tácticos de video)."
                elif team_history_snapshot.get(team):
                    insight_meta["confidence"] = 0.40
                    insight_meta["confidence_rationale"] = "Basado únicamente en historial persistente (sin datos frescos)."

            # Fusión/deduplicación incremental: YouTube + Web + Manual + History
            # v13.6: Verificar que la competencia del JSON coincida con la actual (si está especificada)
            manual_news_comp = str(manual_news_payload.get("competition") or "").strip()
            should_process_manual = True
            if manual_news_comp and manual_news_comp.upper() != label.upper():
                should_process_manual = False
                logger.debug(f"Omitiendo noticias manuales para {team}: esperado {manual_news_comp}, actual {label}")
            
            manual_signals = _manual_news_signals_for_team(
                team,
                label,
                manual_news_payload,
                competition_teams=[tm.get("team") for tm in teams_matches],
            ) if should_process_manual else []
            
            # SANEAMIENTO (Tarea 10): Pasar el oponente actual para filtrar señales de rival obsoletas.
            curr_opp = None
            if isinstance(next_match, dict):
                curr_opp = next_match.get("opponent")
                
            history_signals = _history_context_signals_for_team(team, label, team_history_snapshot, current_opponent=curr_opp)
            history_signals = _prune_history_signals_for_analyst(
                history_signals,
                existing_signals=(context_signals or []) + ((web_team_payload or {}).get("context_signals") or []) + manual_signals,
                max_items=int(os.getenv("INSIGHTS_MAX_HISTORY_SIGNALS_TO_ANALYST", "20")),
            )
            pre_merge_count = len(context_signals or [])
            context_signals, web_extra_bullets = _merge_context_signals_multisource(
                team,
                curr_opp,
                [tm.get("team") for tm in teams_matches],
                context_signals or [],
                web_team_payload,
                manual_signals=manual_signals,
                history_signals=history_signals,
            )
            context_signals = [
                _canonicalize_context_signal(team, label, sig, opponent=curr_opp)
                for sig in (context_signals or [])
                if isinstance(sig, dict) and (sig.get("signal") or "").strip()
            ]
            if web_extra_bullets:
                web_extra_bullets = _sanitize_web_extra_bullets_for_match(
                    team,
                    curr_opp,
                    [tm.get("team") for tm in teams_matches],
                    web_extra_bullets,
                )
            if web_extra_bullets:
                base_lines = [ln for ln in (insight_text or "").splitlines() if ln.strip()]
                for b in web_extra_bullets[:3]:
                    line = f"- {b}"
                    if line not in base_lines:
                        base_lines.append(line)
                insight_text = "\n".join(base_lines).strip()
            if (web_team_payload or manual_signals or history_signals) and len(context_signals) != pre_merge_count:
                logger.info(
                    "  ↳ %s: fusión context_signals YT/Web/Manual/History (%s -> %s)%s%s%s",
                    team,
                    pre_merge_count,
                    len(context_signals),
                    f" | web={len((web_team_payload or {}).get('context_signals') or [])}" if web_team_payload else "",
                    f" | manual={len(manual_signals)}" if manual_signals else "",
                    f" | history={len(history_signals)}" if history_signals else "",
                )

            signal_sources = {"youtube"}
            if web_team_payload:
                signal_sources.add("web")
            if manual_signals:
                signal_sources.add("manual")
            if history_signals:
                signal_sources.add("history")
            insights.append(
                {
                    "competition": label,
                    "team": team,
                    "next_match": next_match,
                    "as_of_date": datetime.now().strftime("%Y-%m-%d"),
                    "insight": insight_text,
                    "forecast": forecast,
                    "entities": entities,
                    "context_signals": context_signals,
                    "web_last_result": web_team_payload.get("last_result") if web_team_payload else None,
                    "competition_analysis": comp_analysis, # Panorama General
                    "insight_meta": insight_meta,
                    "source": "+".join(sorted(signal_sources)),
                    "video": video_meta,
                }
            )
            if context_signals:
                logger.info(f"  ↳ {team}: {len(context_signals)} señales de contexto detectadas")

        logger.info(f"✓ {label}: {len(teams_matches)} team insights generados")

    # 6. Persistir nuevos insights en el historial de equipos
    history = _load_team_history()
    now_str = datetime.now().strftime("%Y-%m-%d")
    
    for ins in insights:
        team = ins["team"]
        # FIX TERCIARIO: Canonizar la clave antes de guardar en team_history.
        # Evita que alias o nombres parciales generados por el LLM (ej: 'Concepción')
        # contaminen futuros lookups. El Golden Mapping resuelve el nombre correcto.
        canonical_key = normalizer_tool.clean(team) or team
        text_bullets = ins["insight"].split("\n")
        # Solo guardar si hay algo relevante (más de un simple "Sin datos")
        if "Sin datos disponibles" not in ins["insight"] and text_bullets:
            if canonical_key not in history:
                history[canonical_key] = []
            
            # Limpiar el texto para guardarlo (quitar los guiones del inicio si existen)
            # v14.7: Filtro Anti-JSON Leaks (ignorar líneas que parecen código crudo)
            clean_bullets = []
            for b in text_bullets:
                b_clean = b.lstrip("- ").strip()
                if b_clean and not b_clean.startswith(('{', '}', '"', ']', '[')):
                    clean_bullets.append(b_clean)
                    
            for bullet in clean_bullets:
                # Evitar duplicados (Fiel a Tarea 14.4: Hardening Global + 80% Similitud)
                norm_bullet = _normalize_signal_text(bullet)
                is_duplicate = False
                for h in history[canonical_key]:
                    h_text = h.get("insight", "")
                    # Exact match o Similitud semántica > 80%
                    if norm_bullet == _normalize_signal_text(h_text) or _calculate_similarity(norm_bullet, _normalize_signal_text(h_text)) >= 0.8:
                        is_duplicate = True
                        break
                
                if not is_duplicate:
                    # Supervisor Semántico (v14.5) - Solo si hay sospecha fundada (0.65 < sim < 0.8)
                    # Si sim >= 0.8 ya es duplicate por el filtro anterior.
                    # Aquí buscamos falsos negativos del filtro difuso (semántica pura).
                    # Nota: bajamos el threshold de sospecha para el LLM.
                    suspicious_match = False
                    for h in history[canonical_key]:
                        h_text = h.get("insight", "")
                        if _calculate_similarity(norm_bullet, _normalize_signal_text(h_text)) > 0.65:
                            suspicious_match = True
                            break
                    
                    if suspicious_match and llm:
                        supervision = _semantic_dedup_supervisor(llm, team, bullet, history[canonical_key])
                        if supervision.get("is_duplicate") or supervision.get("is_contradictory"):
                            is_duplicate = True
                            action = supervision.get("action")
                            if action in ["merge", "replace_conflict"] and supervision.get("merged_text"):
                                if history[canonical_key]:
                                    history[canonical_key][-1]["insight"] = supervision.get("merged_text")
                                    msg = "Merged" if action == "merge" else "Resolved Contradiction (Replaced)"
                                    logger.info(f"  ⚡ Árbitro de Verdad: {msg} for {team}")
                            elif action == "keep_new":
                                if history[canonical_key]:
                                    history[canonical_key][-1]["insight"] = bullet
                                    logger.info(f"  ⚡ Árbitro de Verdad: Replaced existing with newer for {team}")
                            else:
                                logger.info(f"  ⚡ Árbitro de Verdad: Ignored duplicate/conflict (old wins) for {team}")

                    if not is_duplicate:
                        history[canonical_key].append({
                            "date": now_str,
                            "insight": bullet,
                            "competition": ins["competition"],
                            "kind": "insight"
                        })

        for sig in (ins.get("context_signals") or []):
            if canonical_key not in history:
                history[canonical_key] = []
            signal_text = (sig.get("signal") or "").strip()
            if not signal_text:
                continue
            signal_type = (sig.get("type") or "other").strip()
            evidence = (sig.get("evidence") or "").strip()
            stored_text = f"[CONTEXTO:{signal_type}] {signal_text}"
            if evidence:
                stored_text += f" | Evidencia: {evidence}"
            
            # Evitar duplicados globales en señales (Hardening v14.4)
            norm_sig = _normalize_signal_text(stored_text)
            is_sig_duplicate = False
            for h in history[canonical_key]:
                h_text = h.get("insight", "")
                if norm_sig == _normalize_signal_text(h_text) or _calculate_similarity(norm_sig, _normalize_signal_text(h_text)) >= 0.8:
                    is_sig_duplicate = True
                    break

            if not is_sig_duplicate:
                # Supervisor Semántico para señales (v14.5)
                suspicious_sig = False
                for h in history[canonical_key]:
                    h_text = h.get("insight", "")
                    if _calculate_similarity(norm_sig, _normalize_signal_text(h_text)) > 0.65:
                        suspicious_sig = True
                        break
                
                if suspicious_sig and llm:
                    supervision = _semantic_dedup_supervisor(llm, team, stored_text, history[canonical_key])
                    if supervision.get("is_duplicate") or supervision.get("is_contradictory"):
                        is_sig_duplicate = True
                        action = supervision.get("action")
                        if action in ["merge", "replace_conflict"] and supervision.get("merged_text"):
                            if history[canonical_key]:
                                history[canonical_key][-1]["insight"] = supervision.get("merged_text")
                                msg = "Merged" if action == "merge" else "Resolved Contradiction (Replaced)"
                                logger.info(f"  ⚡ Árbitro de Verdad: {msg} for {team}")
                        elif action == "keep_new":
                            if history[canonical_key]:
                                history[canonical_key][-1]["insight"] = stored_text
                                logger.info(f"  ⚡ Árbitro de Verdad: Replaced existing signal with newer for {team}")

                if not is_sig_duplicate:
                    history[canonical_key].append({
                        "date": str(sig.get("date"))[:10] if sig.get("date") else now_str,
                        "insight": stored_text,
                        "competition": ins["competition"],
                        "kind": "context_signal",
                        "signal_type": signal_type,
                        "rival": ins.get("next_match", {}).get("opponent") if isinstance(ins.get("next_match"), dict) else None,
                        "confidence": sig.get("confidence", 0.4),
                        "is_rumor": bool(sig.get("is_rumor", False)),
                        "provenance": sig.get("provenance") or [],
                        "source_urls": sig.get("source_urls") or [],
                        "subject_type": sig.get("subject_type"),
                        "epistemic_status": sig.get("epistemic_status"),
                        "impact_axis": sig.get("impact_axis"),
                        "impact_level": sig.get("impact_level"),
                        "source_type": sig.get("source_type"),
                        "source_quality": sig.get("source_quality"),
                        "time_horizon": sig.get("time_horizon"),
                        "relevance_to_match": sig.get("relevance_to_match"),
                        "relevance_to_1x2": sig.get("relevance_to_1x2"),
                        "freshness_score": sig.get("freshness_score"),
                        "trust_score": sig.get("trust_score"),
                        "conflict_score": sig.get("conflict_score"),
                        "final_signal_score": sig.get("final_signal_score"),
                        "resolution_status": sig.get("resolution_status"),
                        "raw_excerpt": sig.get("raw_excerpt"),
                        "reasoning_note": sig.get("reasoning_note"),
                        "impact_note": sig.get("impact_note"),
                    })

        if canonical_key in history:
            history[canonical_key] = history[canonical_key][-team_history_max_items:]
    
    _save_team_history(history)
    logger.info(f"Historial de equipos actualizado en {TEAM_HISTORY_FILE}")

    state["insights"] = insights
    logger.info(
        f"Insights totales: {len(insights)} | "
        f"Cache hits: {cache_hits} | Cache misses: {cache_misses} | "
        f"Tokens LLM ahorrados: {'Sí' if cache_hits > 0 else 'No'}"
    )
    _save_youtube_failure_cache(youtube_failure_cache)
    return state
