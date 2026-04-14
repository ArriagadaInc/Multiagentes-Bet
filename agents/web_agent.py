"""
Web Agent — contexto de torneo por jornada

Integrado en el pipeline principal (entre Journalist y Insights Agent).

Estrategia: 1 llamada por torneo (CHI1 + UCL = 2 llamadas máximo).
El LLM recibe los partidos de la jornada y el estado de la tabla, y devuelve
un contexto enriquecido por equipo que el Insights Agent filtra y consume.

Persiste el resultado en web_agent_output.json para:
- No repetir la búsqueda si ya está fresca (TTL configurable)
- Que la UI standalone también pueda usar el resultado

Formato de salida esperado por el Insights Agent (ya implementado):
{
    "data": {
        "competitions": [
            {
                "competition": "CHI1",
                "teams": [
                    {
                        "team": "Colo-Colo",
                        "last_result": "Colo-Colo 2-0 Huachipato (Fecha 8)",
                        "figures": ["Solari (2 goles)", "Falcón"],
                        "injuries": ["Pavez (suspendido)"],
                        "context_signals": [
                            {"type": "injury", "signal": "...", "confidence": 0.8},
                            {"type": "form", "signal": "...", "confidence": 0.7}
                        ],
                        "raw_context": "..."
                    }
                ]
            }
        ]
    }
}
"""

import json
import logging
import os
import unicodedata
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

from utils.token_tracker import track_tokens
from utils.llm_factory import get_llm
from utils.wishlist import get_wishlist_for_teams
from agents.manual_odds_agent import get_recent_manual_match_keys

logger = logging.getLogger(__name__)

WEB_AGENT_OUTPUT_FILE = "web_agent_output.json"
WEB_AGENT_MODEL = "gpt-5.1"  # Default (legacy compatibility)
WEB_AGENT_CACHE_TTL_HOURS = int(os.getenv("WEB_AGENT_CACHE_TTL_HOURS", "6"))

# ── Selección dinámica de modelo por torneo ────────────────────────────────
TOURNAMENT_MODELS = {
    "UCL": "gpt-5.1",           # Análisis profundo europeo
    "CHI1": "gpt-4o",           # Balance: análisis + web_search con datos locales inyectados
    "CHI2": "gpt-4o",           # Balance: análisis + web_search con datos locales inyectados
}

def get_model_for_tournament(competition: str) -> str:
    """Retorna el modelo apropiado para una competencia."""
    comp_upper = (competition or "").upper().strip()
    return TOURNAMENT_MODELS.get(comp_upper, WEB_AGENT_MODEL)


def _get_local_data(competition: str) -> dict:
    """
    Extrae datos locales disponibles (tabla, resultados, fixtures) del pipeline.
    Esto enriquece el prompt sin depender solo de web_search.
    """
    data = {"tabla": [], "ultimos_resultados": [], "proximos_partidos": []}
    
    try:
        # Intentar cargar tabla de posiciones desde pipeline_stats.json o similar
        if os.path.exists("pipeline_stats.json"):
            with open("pipeline_stats.json", "r", encoding="utf-8") as f:
                stats = json.load(f) or {}
                comp_stats = stats.get("data", {}).get("competitions", [])
                for comp in comp_stats:
                    if (comp.get("competition") or "").upper() == (competition or "").upper():
                        # Extraer posiciones si existen
                        if "standings" in comp:
                            data["tabla"] = comp["standings"][:10]  # Top 10
                        break
    except Exception:
        pass
    
    try:
        # Intentar cargar resultados recientes desde pipeline_result.json
        if os.path.exists("pipeline_result.json"):
            with open("pipeline_result.json", "r", encoding="utf-8") as f:
                results = json.load(f) or {}
                comp_results = results.get("data", {}).get("competitions", [])
                for comp in comp_results:
                    if (comp.get("competition") or "").upper() == (competition or "").upper():
                        matches = comp.get("matches", [])
                        # Tomar últimos 5 resultados
                        data["ultimos_resultados"] = matches[-5:]
                        break
    except Exception:
        pass
    
    try:
        # Intentar cargar fixtures próximos desde pipeline_fixtures.json
        if os.path.exists("pipeline_fixtures.json"):
            with open("pipeline_fixtures.json", "r", encoding="utf-8") as f:
                fixtures_all = json.load(f) or []
                comp_fixtures = [f for f in fixtures_all if (f.get("competition") or "").upper() == (competition or "").upper()]
                # Tomar próximos 5 partidos
                data["proximos_partidos"] = comp_fixtures[:5]
    except Exception:
        pass
    
    return data


def _format_local_data_section(local_data: dict) -> str:
    """
    Formatea los datos locales para inyectarlos en el prompt como contexto conocido.
    """
    lines = ["\n=== DATOS LOCALES DISPONIBLES (del pipeline de análisis) ==="]
    
    if local_data.get("tabla"):
        lines.append("\n📊 TABLA DE POSICIONES (últimos datos conocidos):")
        for i, pos in enumerate(local_data["tabla"][:10], 1):
            team = pos.get("team", "?")
            pts = pos.get("points", 0)
            pj = pos.get("played", 0)
            lines.append(f"  {i}. {team}: {pts} pts ({pj} PJ)")
    
    if local_data.get("ultimos_resultados"):
        lines.append("\n🏁 ÚLTIMOS RESULTADOS:")
        for match in local_data["ultimos_resultados"]:
            home = match.get("home_team", "?")
            away = match.get("away_team", "?")
            score = match.get("score", "?")
            date = (match.get("utc_date") or "")[:10]
            lines.append(f"  • {home} vs {away}: {score} ({date})")
    
    if local_data.get("proximos_partidos"):
        lines.append("\n📅 PRÓXIMOS PARTIDOS (según pipeline):")
        for match in local_data["proximos_partidos"]:
            home = match.get("home_team", "?")
            away = match.get("away_team", "?")
            date = (match.get("utc_date") or match.get("commence_time") or "")[:10]
            lines.append(f"  • {home} vs {away} ({date})")
    
    lines.append("\n🔍 INVESTIGACIÓN COMPLEMENTARIA:")
    lines.append("Usa web_search para encontrar información ADICIONAL no disponible arriba:")
    lines.append("- Cambios de DT, lesiones de figuras, noticias recientes (últimas 48h)")
    lines.append("- Contexto psicológico, crisis o rachas positivas")
    lines.append("- Análisis táctico y forma actual basados en el contexto web")
    
    return "\n".join(lines)


# ── Prompts ────────────────────────────────────────────────────────────────
DEFAULT_WEB_PROMPT = (
    "Busca en internet un panorama ACTUAL de los equipos de la jornada. "
    "Distingue hechos confirmados de versiones no confirmadas."
)

# ── Nombres legibles por torneo ────────────────────────────────────────────
COMPETITION_NAMES = {
    "CHI1": "Primera División de Chile",
    "UCL":  "UEFA Champions League",
}

# ── Helper de Wishlist ─────────────────────────────────────────────────────
def _build_wishlist_block(fixtures: list[dict]) -> str:
    """
    Construye un bloque de texto con las NECESIDADES PERSISTENTES del analista.
    Distingue entre intereses GLOBALES (se buscan siempre) e intereses por EQUIPO.
    """
    if not fixtures:
        return ""

    from utils.wishlist import get_wishlist_for_teams, load_analyst_wishlist

    CATEGORY_ICONS = {
        "injuries":  "🏥",
        "tactical":  "🧠",
        "stats":     "📊",
        "market":    "💰",
        "context":   "📋",
        "h2h":       "⚔️",
    }
    PRIORITY_ORDER = {"alta": 0, "media": 1, "baja": 2}

    all_items = load_analyst_wishlist()
    # 1. Separar intereses GLOBALES (teams_affected vacío)
    global_items = [i for i in all_items if not i.get("teams_affected")]
    global_items_sorted = sorted(global_items, key=lambda x: PRIORITY_ORDER.get(x.get("priority", "baja"), 2))
    
    seen_global_needs = set()
    lines = [
        "",
        "=" * 60,
        "⚡ INTERESES Y NECESIDADES PERSISTENTES DEL ANALISTA:",
        "El analista tiene estos intereses generales y específicos.",
        "Busca información relevante y respóndela en 'context_signals'.",
        "=" * 60,
    ]

    if global_items_sorted:
        lines.append("\n🌟 INTERESES GENERALES (Buscar para TODOS los equipos/partidos):")
        for item in global_items_sorted[:8]: # Cap para no saturar
            priority = item.get("priority", "media").upper()
            category = item.get("category", "info")
            icon = CATEGORY_ICONS.get(category, "❓")
            need = item.get("need", "")
            if need and need not in seen_global_needs:
                lines.append(f"  {icon} [{priority}] {need}")
                seen_global_needs.add(need)

    # 2. Intereses por equipo/partido
    processed_pairs: set[str] = set()
    found_any_match_specific = False

    for fix in fixtures:
        home = (fix.get("home_team") or "").strip()
        away = (fix.get("away_team") or "").strip()
        pair_key = f"{home}|{away}"
        if pair_key in processed_pairs or (not home and not away):
            continue
        processed_pairs.add(pair_key)

        teams_in_match = [t for t in [home, away] if t]
        # get_wishlist_for_teams ahora devuelve tanto globales como específicos.
        # Filtramos para mostrar solo los específicos aquí, ya que los globales se mostraron arriba.
        all_relevant = get_wishlist_for_teams(teams_in_match)
        team_specific_items = [i for i in all_relevant if i.get("teams_affected")]
        
        if not team_specific_items:
            continue

        if not found_any_match_specific:
            lines.append("\n📌 NECESIDADES ESPECÍFICAS POR PARTIDO:")
            found_any_match_specific = True

        date_str = (fix.get("utc_date") or fix.get("commence_time") or "")[:10]
        lines.append(f"\n📅 PARTIDO: {home} vs {away}{f' ({date_str})' if date_str else ''}")

        items_sorted = sorted(team_specific_items, key=lambda x: PRIORITY_ORDER.get(x.get("priority", "baja"), 2))
        for item in items_sorted:
            priority = item.get("priority", "media").upper()
            category = item.get("category", "info")
            icon = CATEGORY_ICONS.get(category, "❓")
            need = item.get("need", "")
            affected = ", ".join(item.get("teams_affected") or teams_in_match)
            lines.append(f"  {icon} [{priority}] {affected}: {need}")

    if not global_items and not found_any_match_specific:
        return ""

    lines += [
        "",
        "=" * 60,
        "IMPORTANTE: Incluye las respuestas en el campo 'context_signals'",
        "de cada equipo correspondiente como señales estructuradas.",
        "=" * 60,
    ]
    return "\n".join(lines)


# ── Prompt por torneo ──────────────────────────────────────────────────────
def _build_tournament_prompt(competition: str, teams: list[str], fixtures: list[dict]) -> str:
    """Construye el prompt contextual para una búsqueda web por torneo,
    incluyendo las necesidades específicas que el analista marcó en la wishlist."""
    comp_name = COMPETITION_NAMES.get(competition, competition)
    today = datetime.now().strftime("%d/%m/%Y")

    # Armar lista de partidos de la jornada
    fixture_lines = []
    for f in fixtures:
        home = f.get("home_team", "?")
        away = f.get("away_team", "?")
        date = (f.get("utc_date") or f.get("commence_time") or "")[:10]
        fixture_lines.append(f"  - {home} vs {away} (fecha aprox: {date})")

    fixtures_str = "\n".join(fixture_lines) if fixture_lines else "  (partidos no especificados)"
    # Increase from [:20] to [:100] to include more teams in web search context
    teams_str = ", ".join(teams[:100]) if teams else "(todos los equipos de la competencia)"

    # Bloque de necesidades específicas del analista desde la wishlist
    wishlist_block = _build_wishlist_block(fixtures)
    if wishlist_block:
        logger.info(f"  📋 Wishlist del analista inyectada en prompt de {competition}")
    
    # Inyectar datos locales si están disponibles
    local_data = _get_local_data(competition)
    local_data_section = _format_local_data_section(local_data)

    return f"""Eres un analista deportivo experto. Hoy es {today}.

TORNEO PRINCIPAL: {comp_name} ({competition})
EQUIPOS INVOLUCRADOS EN LA PRÓXIMA JORNADA: {teams_str}

PARTIDOS PRÓXIMOS A JUGARSE EN {competition}:
{fixtures_str}

Busca en internet información ACTUAL, RECIENTE y de ÚLTIMO MINUTO sobre estos equipos para ayudar a pronosticar sus PRÓXIMOS partidos.

{local_data_section}

**REQUERIMIENTO CRÍTICO**: Identifica eventos "rompe-esquemas" que cambien el panorama psicológico o deportivo del equipo, por ejemplo:
- Eliminaciones de torneos internacionales (Copa Libertadores/Sudamericana) aunque hayan ocurrido hace 2-3 días.
- Clasificaciones heroicas o campeonatos recientes.
- Renuncias de DT o crisis institucionales graves.
- Lesiones de figuras clave reportadas en los últimos 5 días.

Es CRUCIAL que investigues para CADA EQUIPO de los partidos listados:

1. **Resultados de la Jornada Anterior**: Busca los resultados de TODOS los partidos de la última fecha jugada en {competition}. Necesitamos saber marcadores y quién ganó/perdió.
2. **Último resultado específico del equipo**: resultado, marcador, rival y fecha (en liga o copa).
3. **Impacto anímico y deportivo**: figuras destacadas, eliminaciones recientes, crisis o rachas tras el último resultado.
4. **Estado actual en la tabla**: posición exacta y puntos actualizados al día de hoy.
5. **Bajas de ÚLTIMO MINUTO**: lesiones, suspensiones, dudas médicas de hoy.
6. **Cambios recientes**: DT nuevo, transferencias, reestructuraciones.
7. **Panorama General del Torneo**: Quién es el líder actual, cercanía de puntos en la zona alta/baja (especialmente entre los equipos que juegan), y qué equipos son la sorpresa o están en crisis profunda esta semana.
---
{wishlist_block}
Escribe un informe exhaustivo, profundo narrativo (texto libre).
NO formatees en JSON todavía. Solo provee los datos claros y la noticia pura equipo por equipo con todos los detalles descubiertos.
"""


def _build_extraction_prompt(raw_text: str, competition: str) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    return f"""Eres un extractor de datos JSON estrictamente estructurado.
Hoy es {today}. Convierte la siguiente narrativa de investigación deportiva sobre la competencia {competition} al formato JSON exigido.

TEXTO DE INVESTIGACIÓN:
{raw_text}

Responde SÓLO en formato JSON con la siguiente estructura exacta:
{{
  "competition": "{competition}",
  "generated_at": "{today}",
  "competition_summary": "Resumen macro del torneo.",
  "teams": [
    {{
      "team": "Nombre oficial del equipo",
      "position_in_table": 3,
      "points": 18,
      "last_result": "Equipo A 2-1 Equipo B",
      "figures": ["Jugador1", "Jugador2"],
      "injuries": ["Jugador suspendido"],
      "form": "W D W",
      "context_signals": [
        {{
          "type": "injury_news|disciplinary_issue|form|motivation|tactical|lineup|coach_identity|coach_change|macrostats|other",
          "signal": "Respuesta breve al analista",
          "fact": "La métrica o noticia cruda",
          "player_or_coach": "Nombre implicado o null",
          "date": "YYYY-MM-DD del evento investigado",
          "source": "URL o fuente periodística",
          "confidence": 0.95,
          "staleness_risk": "low|medium|high",
          "requires_revalidation": true
        }}
      ]
    }}
  ]
}}
IMPORTANTE: Extrae TODO equipo mencionado de forma estricta. Prioriza buscar fechas implícitas en el texto y convertirlas a YYYY-MM-DD.
"""


# ── Cache ──────────────────────────────────────────────────────────────────
def _is_cache_fresh(state: Optional[dict] = None) -> bool:
    """
    True si el archivo existe y la última entrada de las competencias activas 
    fue generada hace menos de WEB_AGENT_CACHE_TTL_HOURS horas.
    """
    if not os.path.exists(WEB_AGENT_OUTPUT_FILE):
        return False
    try:
        with open(WEB_AGENT_OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Si el usuario pregunta por una liga específica, chequeamos si esa liga está fresca
        active_comps = []
        if state:
            odds_list = state.get("odds_canonical") or []
            active_comps = list({match.get("competition", "").upper() for match in odds_list if match.get("competition")})

        generated_at_str = (data.get("generated_at") or "")[:19]
        if not generated_at_str:
            return False
            
        generated_at = datetime.fromisoformat(generated_at_str)
        age = datetime.now() - generated_at
        return age < timedelta(hours=WEB_AGENT_CACHE_TTL_HOURS)
    except Exception:
        return False


def _load_cache() -> Optional[dict]:
    """Carga el resultado persistido si existe."""
    try:
        with open(WEB_AGENT_OUTPUT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_output(new_payload: dict) -> None:
    """
    Persiste el resultado del Web Agent a disco de forma ACUMULATIVA.
    Mezcla los nuevos hallazgos con el historial existente.
    """
    try:
        history = {}
        if os.path.exists(WEB_AGENT_OUTPUT_FILE):
            try:
                with open(WEB_AGENT_OUTPUT_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                history = {}

        # Estructura base si el archivo es nuevo o inválido
        if "data" not in history:
            history["data"] = {"competitions": []}
        
        # Actualizar metadatos raíz para Auditoría de API
        history["ok"] = new_payload.get("ok", True)
        history["model"] = new_payload.get("model") or history.get("model") or WEB_AGENT_MODEL
        history["generated_at"] = new_payload.get("generated_at")
        history["completed_at"] = new_payload.get("completed_at") or datetime.now(timezone.utc).isoformat()
        history["last_run_started_at"] = new_payload.get("started_at")
        if new_payload.get("error"):
            history["error"] = new_payload.get("error")
        elif "error" in history:
            del history["error"] # Limpiar error previo si este run es OK
        
        new_comps = new_payload.get("data", {}).get("competitions") or []
        existing_comps = history["data"].get("competitions") or []
        
        for n_comp in new_comps:
            comp_id = n_comp.get("competition")
            # Buscar si ya existe esta competencia en el historial
            found_comp = next((c for c in existing_comps if c.get("competition") == comp_id), None)
            
            if not found_comp:
                # Si no existe, la agregamos tal cual (limitada)
                n_comp["teams"] = n_comp.get("teams", [])[-100:] # Limitar
                existing_comps.append(n_comp)
            else:
                # Si existe, mezclamos los equipos
                existing_teams = found_comp.get("teams") or []
                new_teams = n_comp.get("teams") or []
                
                for nt in new_teams:
                    nt_name = nt.get("team", "").lower().strip()
                    # Buscar el equipo en el historial de esa competencia
                    idx = next((i for i, t in enumerate(existing_teams) if t.get("team", "").lower().strip() == nt_name), -1)
                    
                    if idx != -1:
                        # Actualizar equipo existente con info nueva
                        existing_teams[idx] = nt
                    else:
                        # Agregar nuevo equipo
                        existing_teams.append(nt)
                
                # Mantener solo los últimos 100 reportes de equipos por competencia para control de tamaño
                found_comp["teams"] = existing_teams[-100:]
                found_comp["raw_text"] = n_comp.get("raw_text", "") # El texto crudo sí es del último run

        history["data"]["competitions"] = existing_comps

        with open(WEB_AGENT_OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        logger.info(f"✓ Web Agent output ACUMULATIVO guardado en {WEB_AGENT_OUTPUT_FILE}")
    except Exception as e:
        logger.warning(f"No se pudo guardar {WEB_AGENT_OUTPUT_FILE} de forma acumulativa: {e}")


# ── Cliente OpenAI ─────────────────────────────────────────────────────────
def _make_client() -> Optional["OpenAI"]:
    if OpenAI is None:
        return None
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    timeout = float(os.getenv("WEB_AGENT_TIMEOUT_SECONDS", "120"))
    return OpenAI(timeout=timeout)


# ── Stale Shield (Matriz TTL) ─────────────────────────────────────────────────

def _stale_shield_filter(signals: list[dict], reference_date: datetime) -> tuple[list[dict], int]:
    """
    Filtra señales estructuradas basándose en su 'date', 'type' y 'staleness_risk'.
    Retorna (valid_signals, dropped_count).
    """
    valid = []
    dropped_count = 0
    
    for sig in signals:
        if not isinstance(sig, dict): continue
        
        # Penalización severa a señales sin fecha
        sig_date_str = str(sig.get("date", "")).strip()
        if not sig_date_str or sig_date_str.lower() in ("null", "none", ""):
            dropped_count += 1
            logger.debug(f"  ❌ Stale Shield: Descartada señal por no tener fecha: {sig.get('signal')}")
            continue
            
        try:
            # Asume formato YYYY-MM-DD
            sig_date = datetime.strptime(sig_date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            dropped_count += 1
            logger.debug(f"  ❌ Stale Shield: Fecha inválida '{sig_date_str}'")
            continue
            
        age_days = (reference_date - sig_date).days
        sig_type = str(sig.get("type", "")).lower()
        risk = str(sig.get("staleness_risk", "")).lower()
        
        keep = True
        reason = ""
        
        # Matriz de TTL por tipo de señal:
        # form, previous_result, momentum: 3-5 días
        if sig_type in ("form", "previous_result", "momentum", "macrostats"):
            if age_days > 5:
                keep, reason = False, f"TTL Form excedido ({age_days}d > 5d)"
        # injury_news, suspension, lineup_doubt: 2-5 días
        elif sig_type in ("injury_news", "suspension", "lineup_doubt", "disciplinary_issue"):
            if age_days > 5:
                keep, reason = False, f"TTL Injury/Lineup excedido ({age_days}d > 5d)"
        # coach_identity, coach_change: estricto, requiere fecha reciente
        elif "coach" in sig_type:
            if age_days > 14: # Un DT dura más, pero la *noticia* de cambio debe ser fresca. Si es identity persistimos más, si es change es corto.
                # Si es un "coach_change" el TTL es 5 días
                if sig_type == "coach_change" and age_days > 5:
                    keep, reason = False, f"TTL Coach Change excedido ({age_days}d > 5d)"
                elif risk == "high" or sig.get("requires_revalidation"):
                    keep, reason = False, f"Coach Stale Risk High ({age_days}d)"
        # player_membership, transfer:
        elif "player" in sig_type or "transfer" in sig_type:
            if age_days > 14 and risk == "high":
                keep, reason = False, f"Player Membership dudosamente caduca ({age_days}d)"
        # table, position, macro_context: 1-3 días
        elif sig_type in ("table", "position", "macro_context", "context"):
            if age_days > 3:
                keep, reason = False, f"TTL Macro Context excedido ({age_days}d > 3d)"
        
        # Override por riesgo estipulado por GPT-5
        if risk == "high" and age_days > 2:
            keep, reason = False, f"High Staleness Risk explicitado por LLM ({age_days}d)"

        if keep:
            valid.append(sig)
        else:
            dropped_count += 1
            logger.debug(f"  ❌ Stale Shield Drop: [{sig_type}] {reason}: '{sig.get('signal')}'")
            
    return valid, dropped_count


# ── Validación y limpieza de signals ────────────────────────────────────────

def _normalize_string(s: str) -> str:
    """Normaliza string removiendo acentos y espacios múltiples"""
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = ' '.join(s.split())  # Coloca espacios múltiples a simples
    return s.lower()

def _validate_and_clean_signals(team_data: dict) -> dict:
    """
    Valida que las context_signals sean coherentes con los datos estructurados.
    Elimina signals que contradiguen explícitamente los datos (position, points, last_result).
    También elimina signals que claramente pertenecen a otro equipo.
    """
    position = team_data.get("position_in_table")
    points = team_data.get("points")
    last_result = (team_data.get("last_result", "") or "").lower()
    team_name_orig = (team_data.get("team", "") or "").strip()
    team_name_norm = _normalize_string(team_name_orig)
    
    signals = team_data.get("context_signals") or []
    cleaned_signals = []
    
    # PATRONES DE CONTAMINACIÓN CRUZADA - Equipo específico → Señales que pertenecen a OTRO equipo
    CONTAMINATION_RULES = {
        # Si el equipo NO es Deportes Concepción, eliminar signals con:
        ("concepcion", "deportes", "concepción"): [
            ("almendra", "patricio"),  # DT de Concepción
            ("colista absoluto", "solo 4 puntos"),  # Descripción de Concepción
            ("derrota 3-0", "audax"),  # Resultado de Concepción
        ],
        # Si el equipo NO es Cobresal, eliminar:
        ("cobresal",): [
            ("goleada 5-2", "limache", "recibio"),  # Cobresal recibió 5-2 de Limache
        ],
        # General para todos los equipos excepto La Calera:
        ("union", "calera"): [
            ("cambio reciente de dt", None),  # Solo si position != 6 o points != 9
        ],
    }
    
    for sig in signals:
        if not isinstance(sig, dict):
            logger.debug(f"  ⚠️ Signal no es dict: {sig}")
            continue
        
        sig_text_orig = sig.get("signal") or ""
        sig_text = _normalize_string(sig_text_orig)
        sig_type = sig.get("type", "")
        
        eliminate = False
        reason = ""
        
        # ======================== REGLA 1: Almendra ========================
        # "Almendra" es DT de Deportes Concepción, no de otros
        if "almendra" in sig_text or "patricio" in sig_text:
            if "concepcion" not in team_name_norm and "union la calera" not in team_name_norm:
                eliminate = True
                reason = "contiene 'Almendra' (DT de Concepción)"
        
        # ====================== REGLA 2: Colista absoluto ======================
        # "Colista absoluto con 4 puntos" es de Concepción (posición 16+, 4 pts)
        # Si el equipo tiene position != 16+ o points != 4, NO es Concepción
        if ("colista absoluto" in sig_text or "colista con solo 4" in sig_text) and not eliminate:
            if position and position <= 14:  # El equipo está en posición razonable
                eliminate = True
                reason = f"colista absoluto con 4 puntos (pero este equipo está en posición {position})"
            elif points and points > 4:  # El equipo tiene más puntos
                eliminate = True
                reason = f"colista absoluto con 4 puntos (pero este equipo tiene {points} puntos)"
        
        # ==================== REGLA 3: Goleada 5-2 ante Limache ====================
        # "Recibió goleada 5-2 ante Limache" → fue COBRESAL
        if ("goleada 5-2" in sig_text or "recibio" in sig_text and "5-2" in sig_text) and "limache" in sig_text and not eliminate:
            if "cobresal" not in team_name_norm:
                eliminate = True
                reason = "recibió 5-2 ante Limache (pero este equipo no es Cobresal)"
        
        # ==================== REGLA 4: Derrota 3-0 ante Audax ====================
        # "Derrota 3-0 ante Audax" → fue DEPORTES CONCEPCIÓN
        if "derrota 3-0" in sig_text and "audax" in sig_text and not eliminate:
            if "concepcion" not in team_name_norm:
                eliminate = True
                reason = "derrota 3-0 ante Audax (pero este equipo no es Concepción)"
        
        # ==================== REGLA 5: Recuperó la punta del torneo ====================
        # "Recuperó la punta con victoria 2-0" → NO es La Calera (pos 6)
        if "recupero la punta" in sig_text or ("punta del torneo" in sig_text and "victoria" in sig_text) and not eliminate:
            if position and position > 5:  # No están en zona de punta
                eliminate = True
                reason = f"recuperó la punta (pero este equipo está en posición {position})"
        
        # ==================== REGLA 6: Validate based on last_result ====================
        # Si el signal menciona un resultado específico pero last_result no coincide:
        if "3-3" in sig_text and "o'higgins" in sig_text and not eliminate:
            # Solo La Calera tiene este resultado
            if "union" not in team_name_norm or "calera" not in team_name_norm:
                if "3-3" not in last_result or "o'higgins" not in last_result:
                    eliminate = True
                    reason = "menciona 3-3 ante O'Higgins (pero este equipo no tuvo ese resultado)"
        
        # ==================== REGLA 7: Redundancia/Meta-signals ====================
        # Los signals que comienzan con "signal": "..." son duplicaciones malformadas del LLM
        if '\"signal\":' in sig_text_orig or sig_text_orig.startswith("cambio reciente de dt/entrenador:") and not eliminate:
            # Estos son meta-signals corruptos del LLM
            eliminate = True
            reason = "signal malformado/corrupto (contiene 'signal' escapada)"
        
        if eliminate:
            logger.debug(f"  ❌ [{team_name_orig}] Signal eliminada ({reason}): {sig_text[:70]}...")
        else:
            cleaned_signals.append(sig)
    
    team_data["context_signals"] = cleaned_signals
    if len(cleaned_signals) < len(signals):
        logger.info(f"    ✓ {team_name_orig}: {len(signals)} → {len(cleaned_signals)} signals (eliminadas {len(signals) - len(cleaned_signals)})")
    
    return team_data
def _extract_signals_from_narrative(raw_text: str, team_name: str) -> list[dict]:
    """
    Post-procesa el raw_text narrativo para extraer context_signals estructuradas.
    Busca patrones de:
    - Cambios de DT / entrenadores
    - Rachas de resultados
    - Lesiones / bajas
    - Crisis o contexto emocional
    - Análisis táctico
    
    IMPORTANTE: Solo extrae señales que mencionen explícitamente el equipo (team_name)
    para evitar contaminación cruzada entre equipos.
    
    Returns: list[dict] con signals adicionales estructuradas
    """
    if not raw_text or not team_name:
        return []
    
    signals = []
    text_lower = raw_text.lower()
    team_lower = team_name.lower().strip()
    
    # Sanitizar team name para buscar en texto (remover tildes básicas)
    team_search = team_lower
    
    # Patrón 1: Cambios de DT - SOLO si la línea menciona el equipo
    if any(phrase in text_lower for phrase in ["despid", "renunci", "nuevo dt", "nuevo entrenador", "cambio de dk", "cambio de entrenador"]):
        for line in raw_text.split('\n'):
            line_lower = line.lower()
            # Verificar que la línea menciona el equipo antes de asignarla
            if any(phrase in line_lower for phrase in ["despid", "renunci", "nuevo dt", "entrenador"]) and team_search in line_lower:
                signals.append({
                    "type": "coaching_change",
                    "signal": f"Cambio reciente de DT/entrenador: {line.strip()[:150]}",
                    "confidence": 0.85
                })
                break
    
    # Patrón 2: Crisis defensiva / ofensiva - SOLO si menciona el equipo
    if any(phrase in text_lower for phrase in ["crisis defensiva", "crisis en defensa", "goleada", "gol", "débil en defensa", "muchos goles"]):
        for line in raw_text.split('\n'):
            line_lower = line.lower()
            if ("defensiva" in line_lower or "defensivo" in line_lower or "goleada" in line_lower) and team_search in line_lower:
                if len(line.strip()) > 20:
                    signals.append({
                        "type": "tactical",
                        "signal": f"Crisis/debilidad detectada: {line.strip()[:150]}",
                        "confidence": 0.75
                    })
                    break
    
    # Patrón 3: Rachas positivas o negativas - SOLO si menciona el equipo
    racha_patterns = [
        ("victoria", "positive streak"),
        ("derrota", "negative streak"),
        ("invicto", "unbeaten run"),
        ("sin ganar", "winless run"),
        ("mejor inicio", "strong start"),
    ]
    for pattern, signal_type in racha_patterns:
        if pattern in text_lower:
            for line in raw_text.split('\n'):
                line_lower = line.lower()
                if pattern in line_lower and team_search in line_lower and len(line.strip()) > 20:
                    signals.append({
                        "type": "form",
                        "signal": f"Racha: {line.strip()[:130]}",
                        "confidence": 0.80
                    })
                    break
    
    # Patrón 4: Lesiones o bajas - SOLO si menciona el equipo
    if any(phrase in text_lower for phrase in ["lesión", "lesionado", "baja", "suspendido", "dudoso", "parte médico"]):
        for line in raw_text.split('\n'):
            line_lower = line.lower()
            if any(phrase in line_lower for phrase in ["lesión", "lesionado", "baja", "suspendido", "dudoso"]) and team_search in line_lower:
                if len(line.strip()) > 20:
                    signals.append({
                        "type": "injury_news",
                        "signal": f"Baja o lesión: {line.strip()[:130]}",
                        "confidence": 0.80
                    })
                    break
    
    # Patrón 5: Contexto emocional / motivacional - SOLO si menciona el equipo
    motivation_keywords = ["moral", "ánimo", "confianza", "motivado", "desmotivado", "tristeza", "crisis emocional", "presión", "confianza"]
    if any(kw in text_lower for kw in motivation_keywords):
        for line in raw_text.split('\n'):
            line_lower = line.lower()
            if any(kw in line_lower for kw in motivation_keywords) and team_search in line_lower:
                if len(line.strip()) > 20:
                    signals.append({
                        "type": "motivation",
                        "signal": f"Contexto emocional: {line.strip()[:130]}",
                        "confidence": 0.70
                    })
                    break
    
    # Patrón 6: Liderazgo o posición especial - SOLO si menciona el equipo
    if any(phrase in text_lower for phrase in ["líder", "puntero", "campeón", "zona baja", "descenso", "fondo", "colista"]):
        for line in raw_text.split('\n'):
            line_lower = line.lower()
            if any(phrase in line_lower for phrase in ["líder", "puntero", "campeón", "zona", "descenso", "colista"]) and team_search in line_lower:
                if len(line.strip()) > 20:
                    signals.append({
                        "type": "form",
                        "signal": f"Posición/contexto: {line.strip()[:130]}",
                        "confidence": 0.75
                    })
                    break
    
    return signals


# ── Llamada a la API ───────────────────────────────────────────────────────
def _call_web_search(client: "OpenAI", prompt: str, competition: str, model: str = None) -> Optional[dict]:
    """
    Hace una llamada a la Responses API con web_search y parsea el JSON de respuesta.
    Devuelve el dict con la lista de equipos, o None si falla.
    
    Args:
        client: Cliente OpenAI
        prompt: Prompt de búsqueda
        competition: Código de torneo (ej: "UCL", "CHI1")
        model: Modelo a usar. Si es None, se selecciona dinámicamente.
    """
    if model is None:
        model = get_model_for_tournament(competition)
    logger.info(f"  🌐 Web Agent: buscando contexto para {competition} (modelo: {model})...")

    try:
        # FASE 1: Research Pass (GPT-5 u OpenAI Web Search)
        response = client.responses.create(
            model=model,
            input=prompt,
            tools=[{"type": "web_search"}],
            max_output_tokens=10000,
        )

        if hasattr(response, "usage") and response.usage:
            track_tokens(
                model=model,
                prompt_tokens=getattr(response.usage, "prompt_tokens", 0),
                completion_tokens=getattr(response.usage, "completion_tokens", 0),
            )

        raw_text = getattr(response, "output_text", "") or str(response)

        # FASE 2: Extraction Pass (Modelo eficiente para formatear JSON estructurado)
        logger.info(f"  🧠 Web Agent: Extrayendo señales estructuradas (Extraction Pass)...")
        from langchain_core.messages import HumanMessage
        from utils.llm_factory import get_llm
        
        # Usamos un modelo sin search, económico (ej. gemini-1.5-flash) pero enfocado en json
        extractor_llm = get_llm(temperature=0.0) 
        extraction_prompt = _build_extraction_prompt(raw_text, competition)
        
        # Invocamos la extracción. 
        # Como es langchain, y pedimos JSON, podemos parsear el restultado
        extraction_response = extractor_llm.invoke([HumanMessage(content=extraction_prompt)])
        raw_content = extraction_response.content if hasattr(extraction_response, "content") else str(extraction_response)
        
        # Normalización de lista (Gemini a veces devuelve lista de partes)
        if isinstance(raw_content, list):
            structured_content = "".join([part.get("text", "") if isinstance(part, dict) else str(part) for part in raw_content])
        else:
            structured_content = str(raw_content)
        
        json_match = None
        import re
        m = re.search(r"\{[\s\S]*\}", structured_content)
        if m:
            try:
                parsed = json.loads(m.group(0))
                teams = parsed.get("teams") or []
                
                # FASE 3: Validation Pass
                for team in teams:
                    team_name = team.get("team", "")
                    
                    # VALIDAR y LIMPIAR: Reglas hardcodeadas de cross-contamination
                    team = _validate_and_clean_signals(team)
                    
                    # STALE SHIELD: Aplicar la matriz de TTL a context_signals
                    surviving_signals, dropped_signals = _stale_shield_filter(team.get("context_signals", []), datetime.now(timezone.utc))
                    team["context_signals"] = surviving_signals
                    
                    if dropped_signals > 0:
                        logger.info(f"    🛡️ Stale Shield [UCL/Local]: {team_name} purgó {dropped_signals} señales caducas devueltas por el web agent.")
                
                parsed["teams"] = teams
                logger.info(f"  ✓ {competition}: {len(teams)} equipos validados tras JSON extraction")
                
                # Conservamos el raw text original por propósitos de auditoría/legacy
                parsed["raw_text"] = raw_text 
                return parsed
            except json.JSONDecodeError as e:
                logger.warning(f"  ⚠️ Error decodificando el JSON de extracción: {e}")

        logger.warning(f"  ⚠️ {competition}: Fallo en Extraction Pass, guardando research crudo")
        return {"teams": [], "raw_text": raw_text}

    except Exception as e:
        logger.error(f"  ❌ Web Agent fallo en {competition}: {e}")
        return None


# ── Extracción de equipos y fixtures del state ────────────────────────────
def _extract_fixtures_by_competition(state: dict) -> dict[str, dict]:
    """
    Extrae de state los partidos (odds_canonical o fixtures) agrupados por competencia.
    Returns: {"CHI1": {"teams": [...], "fixtures": [...]}, ...}
    """
    result: dict[str, dict] = {}

    # Intentar desde odds_canonical (fuente primaria)
    for event in (state.get("odds_canonical") or []):
        comp = (event.get("competition") or "").strip().upper()
        if not comp:
            continue
        if comp not in result:
            result[comp] = {"teams": set(), "fixtures": []}
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        if home:
            result[comp]["teams"].add(home)
        if away:
            result[comp]["teams"].add(away)
        result[comp]["fixtures"].append(event)

    # Fallback: desde fixtures
    for fix in (state.get("fixtures") or []):
        comp = (fix.get("competition") or "").strip().upper()
        if not comp:
            continue
        if comp not in result:
            result[comp] = {"teams": set(), "fixtures": []}
        home = fix.get("home_team", "")
        away = fix.get("away_team", "")
        if home:
            result[comp]["teams"].add(home)
        if away:
            result[comp]["teams"].add(away)
        result[comp]["fixtures"].append(fix)

    # Convertir sets a listas
    for comp in result:
        result[comp]["teams"] = sorted(result[comp]["teams"])

    return result


# ── Nodo principal ─────────────────────────────────────────────────────────
def web_agent_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Nodo LangGraph del Web Agent.

    - Hace 1 llamada por torneo (CHI1, UCL) con todos los equipos de la jornada
    - Persiste en web_agent_output.json (TTL configurable, default 6h)
    - Si el cache está fresco, lo reutiliza sin llamar a la API
    """
    logger.info("=" * 60)
    logger.info("WEB AGENT — contexto de jornada por torneo")

    # ── Cache check ─────────────────────────────────────────────────────
    if _is_cache_fresh(state):
        cached = _load_cache()
        if cached:
            comps = [c["competition"] for c in (cached.get("data", {}).get("competitions") or [])]
            logger.info(f"✓ Web Agent: cache fresco ({WEB_AGENT_CACHE_TTL_HOURS}h TTL) — reutilizando: {comps}")
            return state  # El Insights Agent ya lee el archivo directamente

    # ── Preparar client ─────────────────────────────────────────────────
    client = _make_client()
    if not client:
        logger.warning("⚠️ Web Agent: no hay cliente OpenAI disponible, saltando.")
        return state

    # ── Extraer fixtures del state ───────────────────────────────────────
    fixtures_by_comp = _extract_fixtures_by_competition(state)
    manual_copa_keys = get_recent_manual_match_keys("COPA")
    if manual_copa_keys and "COPA" in fixtures_by_comp:
        from utils.normalizer import TeamNormalizer
        normalizer = TeamNormalizer()
        comp_data = fixtures_by_comp["COPA"]
        original_fixtures = comp_data.get("fixtures") or []
        filtered_fixtures = []
        filtered_teams = set()
        for fix in original_fixtures:
            key = (
                f"COPA:{normalizer.clean(str(fix.get('home_team') or ''))}:"
                f"{normalizer.clean(str(fix.get('away_team') or ''))}"
            )
            if key not in manual_copa_keys:
                continue
            filtered_fixtures.append(fix)
            if fix.get("home_team"):
                filtered_teams.add(fix.get("home_team"))
            if fix.get("away_team"):
                filtered_teams.add(fix.get("away_team"))
        if filtered_fixtures:
            logger.info(
                f"  ✂️ Web Agent: COPA restringido a universo manual "
                f"({len(original_fixtures)} -> {len(filtered_fixtures)} fixtures)"
            )
            fixtures_by_comp["COPA"] = {
                "teams": sorted(filtered_teams),
                "fixtures": filtered_fixtures,
            }
    # ── Extraer ligas prioritarias del state ─────────────────────────────
    # Priorizamos lo que venga en 'odds_canonical' (partidos reales en este run)
    odds_list = state.get("odds_canonical") or []
    active_comp_keys = {match.get("competition", "").upper() for match in odds_list if match.get("competition")}
    
    # Si no hay odds, usamos la lista de competencias del state
    if not active_comp_keys:
        active_comps = list(state.get("competitions") or [])
        active_comp_keys = {c.get("competition", "").upper() for c in active_comps if c.get("competition")}

    if not fixtures_by_comp:
        logger.warning("⚠️ Web Agent: no se encontraron fixtures en el state, saltando.")
        return state

    # ── 1 llamada por torneo ─────────────────────────────────────────────
    competitions_output = []
    started_at = datetime.now(timezone.utc).isoformat()

    for comp, comp_data in fixtures_by_comp.items():
        # Solo procesar competencias activas en esta ejecución
        if active_comp_keys and comp not in active_comp_keys:
            logger.info(f"  ⏭ {comp}: liga no activa en este run, saltando búsqueda web.")
            continue

        teams = comp_data["teams"]
        fixtures = comp_data["fixtures"]

        if not teams:
            logger.warning(f"  ⚠️ {comp}: sin equipos, saltando.")
            continue

        logger.info(f"  🏆 {comp}: {len(teams)} equipos, {len(fixtures)} partidos próximos")

        prompt = _build_tournament_prompt(comp, teams, fixtures)
        model = get_model_for_tournament(comp)
        parsed = _call_web_search(client, prompt, comp, model=model)

        if parsed is None:
            logger.warning(f"  ⚠️ {comp}: fallo en búsqueda web, continuando sin datos.")
            continue

        # Log de la salida del agente web
        raw_output = parsed.get("raw_text", "")
        if raw_output:
            output_preview = raw_output[:500] + "..." if len(raw_output) > 500 else raw_output
            logger.info(f"\n{'='*60}\n🤖 SALIDA DEL AGENTE WEB - {comp} ({model}):\n{'='*60}\n{output_preview}\n{'='*60}\n")
        
        # Log estadístico
        teams_found = len(parsed.get("teams", []))
        logger.info(f"  ✅ {comp}: {teams_found} equipos analizados, resumen: {parsed.get('competition_summary', '')[:100]}...")

        competitions_output.append({
            "competition": comp,
            "model": get_model_for_tournament(comp),
            "competition_summary": parsed.get("competition_summary", ""),
            "teams": parsed.get("teams", []),
            "raw_text": parsed.get("raw_text", ""),
        })

    if not competitions_output:
        logger.warning("⚠️ Web Agent: no se obtuvo contexto de ningún torneo.")
        return state

    # ── Persistir resultado ──────────────────────────────────────────────
    # Reportar el modelo utilizado (puede variar por competencia, reportamos el primero)
    used_model = competitions_output[0].get("model") if competitions_output else WEB_AGENT_MODEL
    payload = {
        "ok": True,
        "model": used_model,
        "models_used": {c.get("competition"): c.get("model") for c in competitions_output},
        "generated_at": datetime.now().isoformat(),
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "competitions": competitions_output
        }
    }
    _save_output(payload)
    logger.info(f"✓ Web Agent: contexto generado para {[c['competition'] for c in competitions_output]}")

    return state


# ── Función standalone (uso desde UI o scripts) ────────────────────────────
def run_web_search_agent(user_prompt: str = "", competition: str = None) -> dict[str, Any]:
    """
    Interfaz standalone para llamar desde la UI sin pipeline state.
    Inyecta datos locales si están disponibles.
    
    Args:
        user_prompt: Prompt personalizado del usuario
        competition: Código de torneo opcional (ej: "CHI1", "UCL"). Si no se proporciona, se detecta del prompt.
    """
    client = _make_client()
    started_at = datetime.now(timezone.utc).isoformat()
    if not client:
        return {"ok": False, "error": "No client OpenAI disponible", "started_at": started_at}

    prompt = user_prompt or (
        "Busca un panorama ACTUAL de la Primera División de Chile (CHI1) y la UEFA Champions League (UCL). "
        "Incluye: posición en tabla, últimos resultados, figuras, bajas conocidas y contexto para pronóstico."
    )
    
    # Detectar competición del prompt si no se proporciona explícitamente
    if not competition:
        # Heurística simple: buscar menciones de torneos en el prompt
        prompt_upper = prompt.upper()
        if "CHI1" in prompt_upper or "PRIMERA DIVISIÓN DE CHILE" in prompt_upper:
            competition = "CHI1"
        elif "CHI2" in prompt_upper or "SEGUNDA DIVISIÓN" in prompt_upper:
            competition = "CHI2"
        elif "UCL" in prompt_upper or "CHAMPIONS LEAGUE" in prompt_upper or "UEFA" in prompt_upper:
            competition = "UCL"
        else:
            competition = "CHI1"  # Default
    
    model = get_model_for_tournament(competition)
    logger.info(f"run_web_search_agent: {competition} → {model}")
    
    # Inyectar datos locales en el prompt
    local_data = _get_local_data(competition)
    local_data_section = _format_local_data_section(local_data)
    enriched_prompt = f"{prompt}\n\n{local_data_section}"

    try:
        response = client.responses.create(
            model=model,
            input=enriched_prompt,
            tools=[{"type": "web_search"}],
            max_output_tokens=6000,
        )
        if hasattr(response, "usage") and response.usage:
            track_tokens(
                model=model,
                prompt_tokens=getattr(response.usage, "prompt_tokens", 0),
                completion_tokens=getattr(response.usage, "completion_tokens", 0),
            )
        raw_text = getattr(response, "output_text", "") or str(response)
        return {
            "ok": True,
            "raw_text": raw_text,
            "model": model,
            "competition": competition,
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "started_at": started_at}
