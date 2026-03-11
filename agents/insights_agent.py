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
import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Union

from state import AgentState
from utils.token_tracker import TokenTrackingCallbackHandler
from utils.normalizer import TeamNormalizer

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURACIÓN Y CONSTANTES
# ============================================================================
INSIGHTS_CACHE_FILE = "youtube_insights_cache.json"
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
        return data if isinstance(data, dict) else {}
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


def _manual_news_signals_for_team(team: str, competition: str, manual_news_payload: Optional[dict]) -> list[dict]:
    """
    Genera señales sintéticas desde noticia manual del usuario para poder deduplicar/fusionar
    con YouTube/Web en el payload final del insight.
    """
    if not isinstance(manual_news_payload, dict):
        return []
    raw_text = str(manual_news_payload.get("text") or "").strip()
    if not raw_text:
        return []
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
    chunks = [c.strip() for c in re.split(r"[\n\r]+|(?<=[\.\!\?])\s+", raw_text) if c.strip()]
    rel_chunks = []
    for ch in chunks:
        ch_norm = _normalize_signal_text(ch)
        if any(a in ch_norm for a in matched_aliases):
            rel_chunks.append(ch)
    if not rel_chunks:
        rel_chunks = [raw_text[:400]]

    signal_text = " ".join(rel_chunks[:2]).strip()
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

    return {
        "type": signal_type,
        "signal": signal_text,
        "evidence": evidence,
        "confidence": entry.get("confidence", 0.55),
        "date": str(entry.get("date") or "").strip()[:10] or None,
        "provenance": ["history"],
    }


def _history_context_signals_for_team(team: str, competition: str, history: Optional[dict], max_items: int = 6) -> list[dict]:
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

    # TTL (Time-to-Live) en dias por tipo de señal (Caducidad Inteligente)
    ttl_days = {
        'international_fatigue': 5,
        'heavy_rotation': 4,
        'extreme_venue': 3,
        'must_win_scenario': 3,
        'aggregate_score': 8,
        'injury_news': 30,
        'disciplinary_issue': 30,
        'coach_change': 45,
    }
    today = datetime.now()

    out: list[dict] = []
    for e in reversed(entries or []):  # más recientes primero (asumiendo append cronológico)
        if not isinstance(e, dict):
            continue
        if competition and (e.get("competition") or "").strip() not in ("", competition):
            continue
            
        parsed = _parse_history_context_signal_entry(e)
        if parsed:
            # Validacion de Caducidad (TTL)
            sig_type = parsed.get("type", "other")
            sig_date_str = parsed.get("date")
            
            is_expired = False
            if sig_date_str:
                try:
                    sig_date = datetime.strptime(sig_date_str[:10], '%Y-%m-%d')
                    days_elapsed = (today - sig_date).days
                    max_ttl = ttl_days.get(sig_type, 14) # 14 dias por defecto para otros tipos
                    if days_elapsed > max_ttl:
                        is_expired = True
                except Exception:
                    pass
            
            if not is_expired:
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
        date_str = str(sig.get("date") or "").strip()[:10]
        rank = (
            type_priority.get(sig_type, 50),
            1 if date_str else 0,
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
        return (
            type_priority.get(sig_type, 50),
            1 if date_str else 0,
            date_str,  # ISO ascending; se usa reverse=True abajo
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

    return list(merged_by_key.values()), extra_bullets

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
                }

        meta = {"url": url, "title": title, "channel": channel, "language": used_lang}
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
    """Crea instancia de ChatOpenAI si OPENAI_API_KEY está configurada."""
    try:
        from langchain_openai import ChatOpenAI

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        return ChatOpenAI(
            model="gpt-5", 
            temperature=0.2,
            callbacks=[TokenTrackingCallbackHandler()]
        )
    except Exception:
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


def _llm_batch_insights(
    llm,
    transcript: str,
    teams_matches: list[dict],
    competition: str,
    manual_news_payload: Optional[dict] = None,
    competition_summary: str = "",
) -> dict:
    """
    Genera insights para TODOS los equipos de una competencia en UNA sola
    llamada al LLM.

    Args:
        llm: Instancia de ChatOpenAI
        transcript: Transcripción concatenada de los videos
        teams_matches: Lista de dicts [{"team": ..., "next_match": ...}, ...]
        competition: Etiqueta de competencia (UCL, CHI1)
        competition_summary: Resumen macro del torneo (de Agente Web)

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

    # Construir contexto histórico para cada equipo
    history = _load_team_history()
    historical_ctx_list = []
    for team in team_names:
        ctx = _get_team_context(team, history)
        historical_ctx_list.append(f"### {team} PREVIOUS KNOWLEDGE:\n{ctx}")
    
    historical_ctx = "\n\n".join(historical_ctx_list)
    alias_ctx = _build_alias_context(team_names)
    manual_news_payload = manual_news_payload or {}
    manual_news_text = str(manual_news_payload.get("text") or "").strip()
    manual_news_updated_at = str(manual_news_payload.get("updated_at") or "").strip()
    manual_news_section = "Sin noticias manuales del usuario."
    if manual_news_text:
        manual_news_section = (
            f"Actualizado: {manual_news_updated_at or 'sin fecha'}\n"
            f"{manual_news_text[:3000]}"
        )

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
#### JERARQUÍA DE CONFIANZA DE TUS FUENTES
1. Periodistas especializados en el club (rueda de prensa, fuente directa)
2. Agencias y medios oficiales (ESPN, AS, Marca)
3. Agente Web (PANORAMA WEB ACTUAL abajo indicado) → Confianza alta para estado de tabla
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
        content = response.content if hasattr(response, "content") else str(response)

        # Limpiar posibles bloques markdown
        content = content.strip()
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
    manual_news_salt = ""
    if manual_news_text:
        manual_news_salt = hashlib.md5(
            (str(manual_news_payload.get("updated_at") or "") + "||" + manual_news_text).encode("utf-8")
        ).hexdigest()[:12]
    if (manual_news_payload.get("text") or "").strip():
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

        if not urls:
            logger.info(f"No YouTube sources for {label}, skipping insights")
            continue

        logger.info(f"Processing {len(urls)} videos for {label}")

        # Descargar transcripciones
        texts = []
        metas = []
        for u in urls:
            t, m = _load_youtube_transcript(u)
            if t:
                video_title = m.get("title", "Unknown")
                video_channel = m.get("channel", "Unknown")
                logger.info(f"  ✓ YouTube: '{video_title}' (Canal: {video_channel})")
                texts.append(t)
                metas.append(m)
            else:
                error = m.get("error", "unknown error")
                logger.warning(f"  ✗ Failed to get transcript from {u}: {error}")

        if not texts:
            meta["errors"]["insights"][label] = "no transcript from any source"
            logger.warning(f"No transcripts available for {label}")
            continue

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

        # Equipos candidatos: de odds en ventana configurable
        teams: set[str] = set()
        for ev in odds:
            if ev.get("competition") != label:
                continue
            teams.add(ev.get("home_team", "").strip())
            teams.add(ev.get("away_team", "").strip())
        teams.discard("")

        if not teams:
            logger.warning(f"No teams found in odds for {label}")
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
                competition_summary=web_summaries_by_comp.get(label, "")
            )
            batch_results = batch_payload.get("teams", [])
            comp_analysis = batch_payload.get("competition_analysis", "")
            cache_misses += 1

            # Guardar en cache
            cache[key] = {
                "saved_at":     datetime.now(timezone.utc).isoformat(),
                "label":        label,
                "video_ids":    video_ids,
                "teams":        sorted(teams),
                "batch_results": batch_payload,
            }
            _save_cache(cache)

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
                insight_text = f"Sin datos disponibles en la transcripción para {team}."
                forecast = None
                entities = None
                insight_meta = {"confidence": 0, "confidence_rationale": "No info", "citations": []}
                context_signals = []

            # Fusión/deduplicación incremental: YouTube + Web + Manual + History
            web_team_payload = (web_team_map_by_comp.get(label) or {}).get(normalizer_tool.clean(team))
            manual_signals = _manual_news_signals_for_team(team, label, manual_news_payload)
            history_signals = _history_context_signals_for_team(team, label, team_history_snapshot)
            history_signals = _prune_history_signals_for_analyst(
                history_signals,
                existing_signals=(context_signals or []) + ((web_team_payload or {}).get("context_signals") or []) + manual_signals,
                max_items=int(os.getenv("INSIGHTS_MAX_HISTORY_SIGNALS_TO_ANALYST", "20")),
            )
            pre_merge_count = len(context_signals or [])
            context_signals, web_extra_bullets = _merge_context_signals_multisource(
                context_signals or [],
                web_team_payload,
                manual_signals=manual_signals,
                history_signals=history_signals,
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
            clean_bullets = [b.lstrip("- ").strip() for b in text_bullets if b.strip()]
            for bullet in clean_bullets:
                # Evitar duplicados exactos muy recientes
                exists = any(h["insight"] == bullet for h in history[canonical_key][-3:])
                if not exists:
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
            exists = any(h.get("insight") == stored_text for h in history[canonical_key][-5:])
            if not exists:
                history[canonical_key].append({
                    "date": now_str,
                    "insight": stored_text,
                    "competition": ins["competition"],
                    "kind": "context_signal",
                    "signal_type": signal_type,
                    "confidence": sig.get("confidence", 0.4),
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
    return state
