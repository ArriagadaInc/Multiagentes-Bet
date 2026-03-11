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
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

from utils.token_tracker import track_tokens
from utils.wishlist import get_wishlist_for_teams

logger = logging.getLogger(__name__)

WEB_AGENT_OUTPUT_FILE = "web_agent_output.json"
WEB_AGENT_MODEL = os.getenv("WEB_AGENT_MODEL", "gpt-4.1")
WEB_AGENT_CACHE_TTL_HOURS = int(os.getenv("WEB_AGENT_CACHE_TTL_HOURS", "6"))


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
    teams_str = ", ".join(teams[:20]) if teams else "(todos los equipos de la competencia)"

    # Bloque de necesidades específicas del analista desde la wishlist
    wishlist_block = _build_wishlist_block(fixtures)
    if wishlist_block:
        logger.info(f"  📋 Wishlist del analista inyectada en prompt de {competition}")

    return f"""Eres un analista deportivo experto. Hoy es {today}.

TORNEO PRINCIPAL: {comp_name} ({competition})
EQUIPOS INVOLUCRADOS EN LA PRÓXIMA JORNADA: {teams_str}

PARTIDOS PRÓXIMOS A JUGARSE EN {competition}:
{fixtures_str}

Busca en internet información ACTUAL, RECIENTE y de ÚLTIMO MINUTO sobre estos equipos para ayudar a pronosticar sus PRÓXIMOS partidos.
IMPORTANTE: Aunque el torneo principal es {competition}, debes buscar el ÚLTIMO resultado y noticias de CUALQUIER competencia oficial (Copa Libertadores, Copa Chile, Sudamericana, etc.) que hayan jugado ayer o hoy.

**REQUERIMIENTO CRÍTICO**: Identifica eventos "rompe-esquemas" que cambien el panorama psicológico o deportivo del equipo, por ejemplo:
- Eliminaciones de torneos internacionales (Copa Libertadores/Sudamericana) aunque hayan ocurrido hace 2-3 días.
- Clasificaciones heroicas o campeonatos recientes.
- Renuncias de DT o crisis institucionales graves.
- Lesiones de figuras clave reportadas en los últimos 5 días.

Es CRUCIAL que investigues para CADA EQUIPO de los partidos listados:

1. **Último resultado en CUALQUIER competencia**: resultado, marcador, rival, fecha.
2. **Impacto anímico y deportivo**: figuras destacadas, eliminaciones recientes, crisis o rachas.
3. **Estado actual en la tabla**: posición, puntos y tendencia.
4. **Bajas de ÚLTIMO MINUTO**: lesiones, suspensiones, dudas médicas de hoy.
---
6. **Panorama General del Torneo**: Quién es el líder actual, cercanía de puntos en la zona alta/baja (especialmente entre los equipos que juegan), y qué equipos son la sorpresa o están en crisis profunda esta semana.
---
{wishlist_block}
Responde en formato JSON con esta estructura exacta:
{{
  "competition": "{competition}",
  "generated_at": "{today}",
  "competition_summary": "Resumen macro del torneo: quién es puntero, qué equipos vienen fuertes, quiénes están en crisis y qué tan determinante es esta jornada para la tabla.",
  "teams": [
    {{
      "team": "Nombre oficial del equipo",
      "position_in_table": 3,
      "points": 18,
      "last_result": "Equipo A 2-1 Equipo B (Competencia, Fecha X, DD/MM/YYYY)",
      "figures": ["Jugador1 (2 goles)", "Jugador2 (asistencia)"],
      "injuries": ["Jugador suspendido", "Jugador dudoso por lesión"],
      "form": "WDWLW",
      "context_signals": [
        {{"type": "injury_news|disciplinary_issue|form|motivation|tactical|lineup|other", "signal": "Respuesta a la pregunta del analista. Ej: Rivero NO está convocado (parte médico oficial del 06/03).", "confidence": 0.95}},
        {{"type": "motivation", "signal": "...", "confidence": 0.85}}
      ],
      "raw_context": "Resumen narrativo DE IMPACTO de 2-3 líneas con lo más relevante de ÚLTIMO MINUTO, respondiendo las preguntas del analista si aplica."
    }}
  ]
}}

IMPORTANTE: incluye SOLO a los equipos de los partidos indicados. Sé preciso, veraz y estructurado.
Prioriza noticias de los ÚLTIMOS 5 DÍAS si son eventos de alto impacto.
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


# ── Llamada a la API ───────────────────────────────────────────────────────
def _call_web_search(client: "OpenAI", prompt: str, competition: str) -> Optional[dict]:
    """
    Hace una llamada a la Responses API con web_search y parsea el JSON de respuesta.
    Devuelve el dict con la lista de equipos, o None si falla.
    """
    model = WEB_AGENT_MODEL
    logger.info(f"  🌐 Web Agent: buscando contexto para {competition} (modelo: {model})...")

    try:
        response = client.responses.create(
            model=model,
            input=prompt,
            tools=[{"type": "web_search"}],
            max_output_tokens=6000,
        )

        # Track tokens
        if hasattr(response, "usage") and response.usage:
            track_tokens(
                model=model,
                prompt_tokens=getattr(response.usage, "prompt_tokens", 0),
                completion_tokens=getattr(response.usage, "completion_tokens", 0),
            )

        raw_text = getattr(response, "output_text", "") or str(response)

        # Parsear JSON del output
        json_match = None
        # Intentar extraer bloque JSON del texto
        import re
        m = re.search(r"\{[\s\S]*\}", raw_text)
        if m:
            try:
                parsed = json.loads(m.group(0))
                teams = parsed.get("teams") or []
                logger.info(f"  ✓ {competition}: {len(teams)} equipos con contexto web")
                return parsed
            except json.JSONDecodeError:
                pass

        # Fallback: devolver el texto crudo como raw_context para el primer equipo
        logger.warning(f"  ⚠️ {competition}: no se pudo parsear JSON del Web Agent, guardando raw_text")
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
        parsed = _call_web_search(client, prompt, comp)

        if parsed is None:
            logger.warning(f"  ⚠️ {comp}: fallo en búsqueda web, continuando sin datos.")
            continue

        competitions_output.append({
            "competition": comp,
            "competition_summary": parsed.get("competition_summary", ""),
            "teams": parsed.get("teams", []),
            "raw_text": parsed.get("raw_text", ""),
        })

    if not competitions_output:
        logger.warning("⚠️ Web Agent: no se obtuvo contexto de ningún torneo.")
        return state

    # ── Persistir resultado ──────────────────────────────────────────────
    payload = {
        "ok": True,
        "model": WEB_AGENT_MODEL,
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
def run_web_search_agent(user_prompt: str = "") -> dict[str, Any]:
    """Interfaz standalone para llamar desde la UI sin pipeline state."""
    client = _make_client()
    started_at = datetime.now(timezone.utc).isoformat()
    if not client:
        return {"ok": False, "error": "No client OpenAI disponible", "started_at": started_at}

    model = WEB_AGENT_MODEL
    prompt = user_prompt or (
        "Busca un panorama ACTUAL de la Primera División de Chile (CHI1) y la UEFA Champions League (UCL). "
        "Incluye: posición en tabla, últimos resultados, figuras, bajas conocidas y contexto para pronóstico."
    )

    try:
        response = client.responses.create(
            model=model,
            input=prompt,
            tools=[{"type": "web_search"}],
            max_output_tokens=4000,
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
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "started_at": started_at}
