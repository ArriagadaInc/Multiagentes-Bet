"""
Agente Periodista: descubrimiento de videos de YouTube relevantes
para la competencia CHI1 (Liga de Primera) y UCL (Champions League).

Salidas:
- state["journalist_videos"]: Datos crudos de videos descubiertos por competencia.
- state["insights_sources"]: dict {comp_id: [url1, url2, ...]} para el insights_agent.
"""

import os
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Union

from state import AgentState
from utils.youtube_api import YouTubeAPI
from utils.token_tracker import TokenTrackingCallbackHandler
from utils.normalizer import TeamNormalizer, slugify
from agents.manual_odds_agent import get_recent_manual_match_keys

try:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage
except ImportError:
    pass

logger = logging.getLogger(__name__)

from agents.sources.primerabchile_chi2 import fetch_primerabchile_signals

# ============================================================================
# CONFIGURACIÓN Y CONSTANTES
# ============================================================================


KEYWORDS_CHILE = {
    "topics": [
        # Análisis táctico profundo (PRIORIDAD PREMIUM)
        "pronóstico", "predicción", "previa", "apuestas", "antes del partido", "análisis",
        "táctica", "pizarra", "pizarra táctica", "onces",
        "formación", "sistema de juego", "análisis de rivales", "análisis táctico",
        "pressing", "bloque bajo", "bloque medio", "transiciones", "salida de balón",
        "once probable", "alineación probable", "convocados", "bajas confirmadas",
        # En inglés
        "prediction", "preview", "betting", "analysis", "tactical", "tactics",
        "lineup", "starting xi", "injuries", "match preview",
        "formation analysis", "pressing triggers",
        # En portugués
        "prognóstico", "previsão", "apostas", "análise", "tático", "tática",
        "escalação", "onze inicial", "lesões",
        # Contexto de competencia
        "tabla de posiciones", "líder del torneo", "lucha por la punta",
        "análisis de la fecha", "panorama del campeonato",
        "duelo directo", "clásico chileno"
    ],
    "subject": [
        "liga de primera mercado libre 2026", "campeonato nacional chile",
        "primera división chile", "tnt sports", "tst", "todos somos técnicos",
        "chilean primera division", "chilean first division",
        "chile national championship", "campeonato chileno",
        "liga de primera chile", "campeonato nacional do chile"
    ]
}

KEYWORDS_UCL = {
    "topics": [
        # Análisis táctico profundo (PRIORIDAD PREMIUM)
        "pronóstico", "predicción", "previa", "apuestas deportivas", "análisis", "resumen",
        "especial", "analisis champions league", "pronosticos champions league",
        "táctica", "pizarra", "pizarra táctica", "onces",
        "formación táctica", "sistema de juego", "análisis del rival",
        "presión alta", "bloque defensivo", "build-up", "pressing alto",
        "once probable", "bajas confirmadas", "sanciones", "alineación confirmada",
        # En inglés
        "prediction", "preview", "betting", "analysis", "tactical", "tactics",
        "lineup", "starting xi", "injuries", "champions league preview",
        "match analysis", "tactical breakdown", "key battles",
        # En portugués
        "prognóstico", "previsão", "apostas", "análise", "tático", "tática",
        "escalação", "onze inicial", "lesões",
        # Contexto de competencia
        "standings", "league table", "title race", "relegation battle",
        "tabla de posiciones", "quién es el líder", "análisis de la jornada",
        "llave de octavos", "llave de cuartos", "eliminatoria champions"
    ],
    "subject": [
        "champions", "champions league", "uefa champions", "futbol europeo",
        "diario as", "espn fans", "ucl", "thonybet",
        "european football", "uefa champions league"
    ]
}


# ============================================================================
# CANALES DE ANALISTAS TÁCTICOS DE ALTA CONFIANZA (Curaduría Premium T7)
# ============================================================================
# Canal ID → bonus de score (0.0–0.3). Valores más altos = canal con más señal táctica real.
# Se aplica en score_relevance como bonus adicional sobre el score base.
# Actualizar según canales verificados con análisis de calidad.
CHANNEL_QUALITY_BOOST: dict[str, float] = {
    # CHI1 — Analistas de Chile
    "UCa8G7sHFJJOyj4K2ZJSiEA": 0.25,  # TNT Sports CL (Todos Somos Técnicos)
    # UCL — Analistas tácticos UCL
    "UCnkp2klbpVG_fVp2xjLI5AQ": 0.25,  # ThonyBet (pronosticosdeportivos)
    "UCLTsHiAES6T2SvknwWIbASw": 0.15,  # @ElPortaldelAscenso (CHI2)
    # Añadir más canales via JOURNALIST_CHANNEL_WHITELIST_* en .env
}



def _get_env_list(key: str, default: str = "") -> List[str]:
    val = os.getenv(key, default)
    return [x.strip() for x in val.split(",") if x.strip()]


# ============================================================================
# LÓGICA DE FILTRADO TEMPORAL
# ============================================================================

def is_within_lookback(published_at: str, published_after: str) -> bool:
    """Verifica si un video está dentro de la ventana de tiempo (comparación de strings ISO)."""
    if not published_at or not published_after:
        return False
    # Asegurar que ambos terminen en Z para comparación directa de strings ISO
    p_at = published_at.replace("+00:00", "Z")
    p_after = published_after.replace("+00:00", "Z")
    return p_at >= p_after


def is_target_match(
    title: str, 
    description: str, 
    fixtures: List[Dict[str, str]], 
    competition_validation_terms: List[str], 
    source_type: str, 
    normalizer: Any = None, 
    channel_title: str = "",
    target_team: str = None
) -> Dict[str, Any]:
    """
    Validación de target de jornada v2.
    Separa validación de competencia de curaduría y usa fixtures reales.
    """
    raw_text = (f"{title} {description} {channel_title}").lower()
    text_slug = slugify(raw_text)
    
    # 1. Normalizar y detectar términos de competencia
    comp_slugs = [slugify(t) for t in competition_validation_terms if t]
    matched_comp = [t for t in comp_slugs if t in text_slug]

    # 2. Identificar equipos mencionados (usando normalizador)
    mentioned_canon_teams = set()
    if normalizer:
        # Usar el manual_map del normalizador para encontrar aliasSlug -> canon
        for alias, canon in normalizer.manual_map.items():
            if slugify(alias) in text_slug and len(alias) > 3:
                mentioned_canon_teams.add(canon)
        
        # También chequear nombres canónicos directos
        for canon in set(normalizer.manual_map.values()):
            if slugify(canon) in text_slug:
                mentioned_canon_teams.add(canon)
    
    # 3. Mapear fixtures a canónicos para comparación
    canon_fixtures = []
    all_target_teams = set()
    for f in fixtures:
        # Soportar tanto 'home' como 'home_team'
        h_raw = f.get("home_team") or f.get("home", "")
        a_raw = f.get("away_team") or f.get("away", "")
        h = normalizer.clean(h_raw) if normalizer else h_raw
        a = normalizer.clean(a_raw) if normalizer else a_raw
        canon_fixtures.append({"home": h, "away": a})
        if h: all_target_teams.add(h)
        if a: all_target_teams.add(a)

    # 4. Clasificar equipos encontrados
    matched_targets = mentioned_canon_teams.intersection(all_target_teams)
    foreign_teams = mentioned_canon_teams.difference(all_target_teams)
    
    # --- REGLAS DE RECHAZO (RUIDO) ---

    # A) Equipos foráneos de peso (Spam/Genérico)
    if len(foreign_teams) >= 2 and source_type != "whitelist":
        return {"ok": False, "reason": "too_many_foreign_teams", "teams": list(matched_targets), "comp": matched_comp}

    # B) Demasiados fixtures válidos mezclados (Resumen de jornada, no análisis profundo)
    fixtures_hit = 0
    for f in canon_fixtures:
        if (f["home"] and f["home"] in mentioned_canon_teams) or (f["away"] and f["away"] in mentioned_canon_teams):
            fixtures_hit += 1
    
    if fixtures_hit > 2 and source_type != "whitelist":
        return {"ok": False, "reason": "too_many_fixtures_mixed", "teams": list(matched_targets), "comp": matched_comp}

    # --- REGLAS DE ACEPTACIÓN ---

    if source_type.startswith("dynamic"):
        # En modo dinámico, buscamos al menos el target_team (canónico)
        canon_target = normalizer.clean(target_team) if normalizer and target_team else target_team
        if canon_target in mentioned_canon_teams:
            # 1 team + comp
            if matched_comp:
                return {"ok": True, "reason": "target_team_plus_comp", "teams": list(matched_targets), "comp": matched_comp}
            # 1 team + rival real
            for f in canon_fixtures:
                if (f["home"] == canon_target and f["away"] in mentioned_canon_teams) or \
                   (f["away"] == canon_target and f["home"] in mentioned_canon_teams):
                    return {"ok": True, "reason": "target_pair_found", "teams": list(matched_targets), "comp": matched_comp}
        return {"ok": False, "reason": "dynamic_target_miss", "teams": list(matched_targets), "comp": matched_comp}

    else:
        # Whitelist o Generic
        # 1. Prioridad: Dupla real en el texto
        for f in canon_fixtures:
            if f["home"] in mentioned_canon_teams and f["away"] in mentioned_canon_teams:
                return {"ok": True, "reason": "fixture_pair_found", "teams": list(matched_targets), "comp": matched_comp}
        
        # 2. Whitelist: Acepta 1 equipo + término de competencia
        if source_type == "whitelist" and matched_comp:
            if len(matched_targets) >= 1:
                return {"ok": True, "reason": "whitelist_team_plus_comp", "teams": list(matched_targets), "comp": matched_comp}
            
            # --- TAREA 9: Soporte a Resúmenes de Jornada (Whitelist Flex) ---
            # Si es whitelist y menciona la competencia + palabras clave de Jornada, aceptamos
            # incluso si no nombra un equipo específico en el título/descripción.
            matchday_keywords = ["fecha", "jornada", "pormenores", "resumen de la", "analisis de la", "compacto", "goles", "repaso"]
            if any(k in raw_text for k in matchday_keywords):
                return {"ok": True, "reason": "whitelist_matchday_summary", "teams": list(matched_targets), "comp": matched_comp}
            
        # 3. Generic: 1 equipo + comp NO es suficiente según Álvaro
        if source_type == "generic" and matched_comp and len(matched_targets) == 1:
             return {"ok": False, "reason": "generic_single_team_not_enough", "teams": list(matched_targets), "comp": matched_comp}

    return {"ok": False, "reason": "no_valid_combination", "teams": list(matched_targets), "comp": matched_comp}




# ============================================================================
# LÓGICA DE SCORING Y SELECCIÓN
# ============================================================================

def score_relevance(
    title: str,
    description: str,
    keywords: Union[Dict[str, List[str]], List[str]],
    teams: List[str] = None,
    competition: Optional[str] = None,
) -> Dict[str, Any]:
    """Calcula la relevancia de un video basado en palabras clave y equipos."""
    title = title or ""
    description = description or ""
    text = (title + " " + description).lower()
    
    # Manejar tanto diccionarios como listas de keywords
    if isinstance(keywords, dict):
        matched_topics = [k for k in keywords.get("topics", []) if k in text]
        matched_subjects = [k for k in keywords.get("subject", []) if k in text]
    else:
        # keywords es una lista simple
        matched_topics = [k for k in keywords if k in text]
        matched_subjects = []
    
    context_terms = [
        "lesión", "lesiones", "baja", "bajas", "sanción", "sanciones",
        "entrevista", "conferencia", "parte médico", "plantel", "convocados",
        "once", "alineación", "alineaciones", "once probable",
        "injury", "injuries", "suspension", "suspensions", "press conference",
        "lineup", "starting xi",
    ]
    matched_context = [k for k in context_terms if k in text]

    score = 0.0
    base_both = float(os.getenv("JOURNALIST_SCORE_BASE_BOTH", "0.5"))
    base_any = float(os.getenv("JOURNALIST_SCORE_BASE_ANY", "0.3"))
    weight_both = float(os.getenv("JOURNALIST_SCORE_WEIGHT_BOTH", "0.05"))
    weight_any = float(os.getenv("JOURNALIST_SCORE_WEIGHT_ANY", "0.03"))
    priority_bonus = float(os.getenv("JOURNALIST_SCORE_PRIORITY_BONUS", "0.3"))
    context_bonus = float(os.getenv("JOURNALIST_SCORE_CONTEXT_BONUS", "0.2"))

    if matched_topics and matched_subjects:
        score = base_both + (len(matched_topics) + len(matched_subjects)) * weight_both
    elif matched_topics or matched_subjects or matched_context:
        score = base_any + (len(matched_topics) + len(matched_subjects) + len(matched_context)) * weight_any

    priority_terms_base = [
        "todos somos técnicos", "tst", "análisis de la fecha",
        "pronósticos para la fecha", "especial", "pizarra táctica",
        # Premium táctico (Tarea 7)
        "análisis táctico", "pizarra táctica completa", "desglose táctico",
        "tactical breakdown", "formations explained", "pressing triggers",
        "once probable confirmada", "bajas de último minuto",
        "analista táctico", "thonybet apuesta", "pronóstico experto"
    ]
    has_priority = any(term in text for term in priority_terms_base)
    if has_priority:
        score += priority_bonus
    if matched_context:
        score += context_bonus

    # FILTRO NEGATIVO: Términos que indican contenido de baja calidad / SEO genérico
    negative_terms = [
        # Deportes/ligas incorrectos
        "caixun",
        "mlb", "nba", "beisbol", "béisbol", "baloncesto", "basket", "tenis", "ufc",
        # Política / no deportes
        "elecciones", "politica", "política", "gaviota", "rcp",
        # Ligas incorrectas
        "liga mx", "river plate", "banfield",
        # SEO genérico / clickbait / highlights sin análisis
        "highlights", "resumen gol", "mejores goles", "top 10 goles",
        "gol del año", "fails", "clips", "compilación de", "compilación goles",
        "funny moments", "amazing goals", "skills compilation",
        "best goals ever", "goals of the week",
        # Contenido de entretenimiento / sin valor táctico
        "reacciona", "reaccion a", "parodia", "fifa pack", "eafc pack",
        "opening packs", "modo carrera", "videojuego",
        # Formatos multipartido sin foco
        "todos los goles", "jornada completa goles", "recap jornada",
    ]
    
    # Términos que requieren coincidencia exacta/palabra completa
    negative_regex = [
        r"\bla liga\b", r"\blaliga\b"
    ]

    ucl_title_override = False
    if (competition or "").upper() == "UCL":
        title_lower = title.lower()
        ucl_title_override = any(t in title_lower for t in ["champions league", "uefa champions", " ucl ", "ucl", "champions"])

    # Aplicar filtros si NO hay override de prioridad ni de UCL
    is_negative = any(term in text for term in negative_terms) or \
                  any(re.search(pattern, text) for pattern in negative_regex)

    if is_negative and not ucl_title_override and not has_priority:
        logger.info(f"Filtro negativo activado para: {title}")
        return {"score": 0.0, "matched_keywords": []}

    # BONUS EQUIPOS
    if teams:
        title_lower = title.lower()
        desc_lower = description.lower()
        for team in teams:
            team_lower = team.lower()
            if team_lower in title_lower:
                score += 0.4
                matched_topics.append(f"equipo_titulo:{team}")
                break
            if team_lower in desc_lower:
                score += 0.2
                matched_topics.append(f"equipo_desc:{team}")
                break

    # CHANNEL QUALITY BOOST (Tarea 7: Curaduría Premium)
    # Usa el dict de módulo directamente (mismo scope, sin import circular)
    channel_id_from_video = ""
    if isinstance(teams, dict):
        channel_id_from_video = teams.get("channel_id", "")
    if channel_id_from_video:
        boost = CHANNEL_QUALITY_BOOST.get(channel_id_from_video, 0.0)
        if boost > 0.0:
            score = min(score + boost, 1.0)
            matched_topics.append(f"channel_quality_boost:{channel_id_from_video}")

    score = min(score, 1.0)
    return {
        "score": round(score, 2),
        "matched_keywords": list(set(matched_topics + matched_subjects + matched_context))
    }


def score_reputation(video: Dict[str, Any], channel: Dict[str, Any], whitelist: List[str]) -> Dict[str, Any]:
    """Calcula la reputación del canal/video."""
    channel_id = channel.get("id")
    is_whitelist = channel_id in whitelist

    min_subs = int(os.getenv("JOURNALIST_MIN_SUBSCRIBERS", "200000"))
    min_views = int(os.getenv("JOURNALIST_MIN_VIEWS", "2000"))

    v_stats = video.get("statistics", {})
    c_stats = channel.get("statistics", {})

    views = int(v_stats.get("viewCount", 0))
    subs = int(c_stats.get("subscriberCount", 0))

    score = 0.0
    method = "fallback"

    if is_whitelist:
        score = 1.0
        method = "whitelist"
    else:
        score += min(subs / (min_subs * 2), 0.6)
        score += min(views / (min_views * 5), 0.4)

    return {
        "score": round(score, 2),
        "method": method,
        "metrics": {
            "views": views,
            "subs": subs,
            "likes": int(v_stats.get("likeCount", 0)),
            "comments": int(v_stats.get("commentCount", 0))
        }
    }


def select_top_videos(candidates: List[Dict[str, Any]], competition: str, n: int = 4) -> List[Dict[str, Any]]:
    """Selecciona los mejores N videos por relevancia (sustancia), frescura y finalmente reputación."""
    def _sort_key(v):
        rel = v["relevance"]["score"]
        # Convertir fecha a timestamp para frescura
        try:
            date_val = datetime.fromisoformat(v["published_at"].replace("Z", "+00:00")).timestamp()
        except Exception:
            date_val = 0
        rep = v["reputation"]["score"]
        # Orden: 1. Relevancia (Alineación con equipos/jornada), 2. Fecha (Lo más nuevo), 3. Reputación (Fama)
        return (rel, date_val, rep)

    sorted_vids = sorted(candidates, key=_sort_key, reverse=True)
    unique_vids = []
    seen_ids = set()
    for v in sorted_vids:
        if v["video_id"] not in seen_ids:
            unique_vids.append(v)
            seen_ids.add(v["video_id"])
            if len(unique_vids) >= n:
                break
    return unique_vids


# ============================================================================
# FILTRADO LLM
# ============================================================================

def _make_llm() -> Optional[Any]:
    try:
        from utils.llm_factory import get_llm
        # No pasar callbacks aqui - llm_factory lo maneja
        return get_llm(temperature=0.1, profile="journalist_fast")
    except Exception as e:
        logger.warning(f"Error al inicializar LLM: {e}")
        return None


def _refine_candidates_with_llm(candidates: List[Dict[str, Any]], competition: str) -> List[Dict[str, Any]]:
    """Usa un LLM para filtrar candidatos y seleccionar los más útiles. Hace Bypass si el video ya está cacheado."""
    try:
        if os.path.exists("youtube_insights_cache.json"):
            with open("youtube_insights_cache.json", "r", encoding="utf-8") as f:
                insights_cache = json.load(f)
        else:
            insights_cache = {}
    except Exception:
        insights_cache = {}

    known_videos = []
    unknown_candidates = []
    for c in candidates:
        v_id = c.get("video_id")
        if v_id and v_id in insights_cache:
            known_videos.append(c)
            logger.info(f"[CACHE HIT BYPASS] Video ya procesado en insights_cache: {v_id}. Se omite de la cura LLM.")
        else:
            unknown_candidates.append(c)

    if not unknown_candidates:
        logger.info("Todos los videos de esta tanda ya estaban curados en caché. No se invocará a LLM.")
        return known_videos[:10]

    llm = _make_llm()
    if not llm:
        logger.info("LLM no disponible para refinamiento, usando todos los candidatos.")
        return (known_videos + unknown_candidates)[:10]

    logger.info(f"Refinando {len(unknown_candidates)} candidatos UNKNOWN para {competition} con LLM...")

    video_list_str = ""
    for i, v in enumerate(unknown_candidates):
        video_list_str += f"[{i}] TÍTULO: {v['title']}\n"
        video_list_str += f"    CANAL: {v['channel']['title']}\n"
        video_list_str += f"    DESCRIPCIÓN: {v['description_snippet']}\n\n"

    system_prompt = f"""Eres un periodista deportivo de élite especializado en {competition}.
Tu misión es seleccionar videos que aporten CONTEXTO ÚTIL y señales de valor para el análisis del partido.

CRITERIOS:
1. DESCARTA: Videojuegos (FIFA/EAFC), simulaciones sin análisis, spam.
2. ACEPTA: análisis generales, previas, lesiones, sanciones, entrevistas, resúmenes.
3. PRIORIZA: videos con información accionable (bajas, once probable, cambios tácticos).

Responde únicamente con un objeto JSON:
{{
  "evaluations": [
    {{ "index": 0, "status": "UTIL", "reason": "..." }},
    {{ "index": 1, "status": "DESCARTAR", "reason": "..." }}
  ]
}}"""

    user_prompt = f"Videos para evaluar:\n\n{video_list_str}"

    try:
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ])

        # Normalizar response.content a string (Gemini puede devolver lista de partes)
        raw_content = response.content if hasattr(response, "content") else str(response)
        if isinstance(raw_content, list):
            content_text = " ".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in raw_content
            ).strip()
            if not content_text:
                raise ValueError(
                    f"llm_refine_failed: response.content es lista vacía o sin texto. "
                    f"raw={raw_content!r}"
                )
        else:
            content_text = str(raw_content)

        json_match = re.search(r'(\{.*\})', content_text, re.DOTALL)
        if json_match:
            eval_data = json.loads(json_match.group(1))
            useful_indices = [
                e["index"] for e in eval_data.get("evaluations", [])
                if e.get("status") == "UTIL"
            ]
            refined = [unknown_candidates[i] for i in useful_indices if i < len(unknown_candidates)]
            logger.info(f"LLM seleccionó {len(refined)} videos como útiles.")
            return (known_videos + refined)[:10]  # Incluye los conocidos
        else:
            logger.warning(
                "llm_refine_failed: no se encontró JSON en la respuesta. "
                "fallback_used=top10_by_score"
            )
            return (known_videos + unknown_candidates)[:10]
    except Exception as e:
        logger.error(
            "llm_refine_failed: error en el refinamiento LLM: %s  fallback_used=top10_by_score",
            e,
        )
        return (known_videos + unknown_candidates)[:10]



# ============================================================================
# NODO PRINCIPAL
# ============================================================================

def journalist_agent_node(state: AgentState) -> AgentState:
    """
    Nodo LangGraph del Agente Periodista.
    Descubre videos de YouTube de alta calidad para CHI1 y UCL.
    Puebla state['journalist_videos'] y state['insights_sources'].
    """
    logger.info("=" * 60)
    logger.info("JOURNALIST AGENT: Descubriendo fuentes de YouTube de alta calidad")
    logger.info("=" * 60)

    api = YouTubeAPI()
    lookback_days = int(os.getenv("JOURNALIST_LOOKBACK_DAYS", "7"))
    # Cuantizar temporalmente la fecha restada (hora 00:00:00) para golpear caché de peticiones repetidas.
    published_after = (datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=lookback_days)).isoformat().replace("+00:00", "Z")
    max_search = int(os.getenv("JOURNALIST_MAX_RESULTS_SEARCH", "25"))
    languages = _get_env_list("JOURNALIST_LANGUAGES", os.getenv("JOURNALIST_LANGUAGE", "es"))
    region_code = os.getenv("JOURNALIST_REGION_CODE", "CL")
    ttl = int(os.getenv("CACHE_TTL_SECONDS", "3600"))
    
    # --- FILTRADO POR COMPETENCIA SOLICITADA (Optimización de Recursos) ---
    requested_comp_ids = {c.get("competition", "").upper() for c in state.get("competitions", []) if c.get("competition")}
    
    odds_list = state.get("odds_canonical") or []
    base_fixtures = state.get("fixtures") or []
    manual_copa_keys = get_recent_manual_match_keys("COPA")

    # Pre-filtrar partidos a monitorear para no procesar equipos de ligas no solicitadas
    monitored_matches = []
    seen_match_keys = set()
    normalizer_for_scope = TeamNormalizer()

    def _manual_scope_key(comp: str, home: str, away: str) -> str:
        return (
            f"{(comp or '').upper()}:"
            f"{normalizer_for_scope.clean(home or '')}:"
            f"{normalizer_for_scope.clean(away or '')}"
        )
    
    # Primero agregar desde odds_canonical (trae cuotas)
    for m in odds_list:
        comp_m = m.get('competition', '').upper()
        if requested_comp_ids and comp_m not in requested_comp_ids:
            continue
        if comp_m == "COPA" and manual_copa_keys:
            if _manual_scope_key(comp_m, m.get("home_team", ""), m.get("away_team", "")) not in manual_copa_keys:
                continue
            
        key = f"{comp_m}_{slugify(m.get('home_team', ''))}_{slugify(m.get('away_team', ''))}"
        monitored_matches.append(m)
        seen_match_keys.add(key)
    
    # Luego agregar desde fixtures si no estaban ya (caso offline/mock)
    for f in base_fixtures:
        comp = f.get("competition", "").upper()
        if requested_comp_ids and comp not in requested_comp_ids:
            continue
        if comp == "COPA" and manual_copa_keys:
            if _manual_scope_key(comp, f.get("home_team", ""), f.get("away_team", "")) not in manual_copa_keys:
                continue
            
        h = f.get("home_team")
        a = f.get("away_team")
        key = f"{comp}_{slugify(h or '')}_{slugify(a or '')}"
        if key not in seen_match_keys:
            # Normalizar al formato que espera el resto del periodista
            monitored_matches.append({
                "competition": comp,
                "home_team": h,
                "away_team": a,
                "utc_date": f.get("utc_date"),
                "status": f.get("status"),
                "fixture_id": f.get("fixture_id")
            })
            seen_match_keys.add(key)

    whitelist_chile = _get_env_list("JOURNALIST_CHANNEL_WHITELIST_CHILE")
    whitelist_ucl = _get_env_list("JOURNALIST_CHANNEL_WHITELIST_UCL")
    whitelist_copa = _get_env_list("JOURNALIST_CHANNEL_WHITELIST_COPA")

    all_comp_configs = [
        {
            "id": "CHI1",
            "topic": "Liga de Primera Mercado Libre 2026",
            "keywords": KEYWORDS_CHILE,
            "whitelist": whitelist_chile,
            "region_code": os.getenv("JOURNALIST_REGION_CODE_CHI1", region_code),
            "competition_validation_terms": [
                "liga de primera mercado libre",
                "campeonato nacional chile",
                "primera division",
                "futbol chileno"
            ],
            "must_include_terms": [
                "liga de primera mercado libre",
                "campeonato nacional chile",
                "tactico",
                "analisis"
            ],
            "queries_by_lang": {
                "es": [
                    # Prioridad: analistas tácticos reales (Curaduría Premium T7)
                    "tnt sports chile todos somos técnicos pizarra táctica",
                    "análisis táctico liga de primera mercado libre chile 2026",
                    "pronósticos fecha liga primera chile analista",
                    "previa táctica campeonato nacional chile 2026"
                ],
                "en": [
                    "chilean primera division tactical analysis 2026",
                    "chilean league match preview analyst 2026",
                ],
                "pt": [
                    "análise tática liga de primeira chile 2026",
                    "pronóstico analista campeonato chileno 2026",
                ]
            }
        },
        {
            "id": "UCL",
            "topic": "UEFA Champions League",
            "keywords": KEYWORDS_UCL,
            "whitelist": whitelist_ucl,
            "region_code": os.getenv("JOURNALIST_REGION_CODE_UCL", ""),
            "competition_validation_terms": [
                "champions",
                "ucl",
                "champions league",
                "uefa champions",
                "liga de campeones"
            ],
            "must_include_terms": [
                "uefa champions league",
                "ucl matchday",
                "octavos de final",
                "8vos de final",
                "analisis champions league"
            ],
            "queries_by_lang": {
                "es": [
                    # Prioridad: analistas tácticos con profundidad (Curaduría Premium T7)
                    "pizarra táctica champions league octavos analista",
                    "análisis táctico champions league ucl experto",
                    "thonybet pronosticos champions league previa",
                    "apuestas champions league expertos valor baja confirmada"
                ],
                "en": [
                    "champions league tactical breakdown analyst",
                    "champions league match preview formations injuries",
                ],
                "pt": [
                    "prognóstico analista champions league escalacão confirmada",
                    "análise tática champions league hoje",
                ]
            }
        },
        {
            "id": "CHI2",
            "topic": "Campeonato de Ascenso Chile (Primera B)",
            "keywords": KEYWORDS_CHILE,
            "whitelist": whitelist_chile + ["UCLTsHiAES6T2SvknwWIbASw"], # Agregado @ElPortaldelAscenso
            "region_code": os.getenv("JOURNALIST_REGION_CODE_CHI2", region_code),
            "competition_validation_terms": [
                "primera b",
                "ascenso chile",
                "campeonato de ascenso",
                "futbol chileno",
                "rangers", "magallanes", "wanderers"
            ],
            "must_include_terms": [
                "primera b",
                "ascenso",
                "tactico",
                "analisis"
            ],
            "queries_by_lang": {
                "es": [
                    "análisis táctico primera b chile ascenso 2026",
                    "pronósticos fecha ascenso chile analista",
                    "previa táctica campeonato ascenso chile 2026",
                    "resumen primera b chile fecha actual",
                    "rangers vs magallanes analisis"
                ],
                "en": [
                    "chilean second division tactical analysis 2026",
                    "chilean primera b match preview 2026",
                ],
                "pt": [
                    "análise tática campeonato de ascenso chile 2026",
                    "pronóstico analista primera b chile 2026",
                ]
            }
        },
        {
            "id": "COPA",
            "topic": "Copa Libertadores de América 2026",
            "keywords": ["copa libertadores", "conmebol", "palmeiras", "river", "boca", "fluminense", "cruzeiro", "apuestas copa"],
            "whitelist": whitelist_copa,
            "region_code": os.getenv("JOURNALIST_REGION_CODE_COPA", "BR"),
            "competition_validation_terms": [
                "copa libertadores",
                "conmebol libertadores",
                "copa america 2026",
                "futbol sudamericano"
            ],
            "must_include_terms": [
                "copa libertadores",
                "conmebol",
                "tactico",
                "analisis"
            ],
            "queries_by_lang": {
                "es": [
                    "análisis táctico copa libertadores 2026 octavos",
                    "pronóstico experto copa libertadores fase grupos",
                    "palmeiras river boca analisis previo libertadores",
                    "apuestas copa libertadores expertos valor confirmada",
                    "pizarra táctica libertadores semifinal 2026"
                ],
                "pt": [
                    "análise tática copa libertadores 2026 oitavas",
                    "prognóstico especialista libertadores fase de grupos",
                    "palmeiras fluminense cruzeiro análise prévia",
                    "apostas libertadores especialista valor confirmado",
                    "análise libertadores hoje tática formação"
                ],
                "en": [
                    "copa libertadores tactical analysis 2026",
                    "libertadores match preview formations injuries",
                    "conmebol libertadores betting insights"
                ]
            }
        }
    ]
    
    # --- FILTRADO POR COMPETENCIA SOLICITADA (Optimización de Recursos) ---
    if requested_comp_ids:
        comp_configs = [c for c in all_comp_configs if c["id"] in requested_comp_ids]
        removed = [c["id"] for c in all_comp_configs if c["id"] not in requested_comp_ids]
        if removed:
            logger.info(f"JOURNALIST: Optimizando recursos. Ignorando ligas no solicitadas: {removed}")
    else:
        comp_configs = all_comp_configs

    journalist_results = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lookback_days": lookback_days,
        "sources": {"youtube": "data_api_v3"},
        "competitions": [],
        "meta": {
            "total_candidates_scanned": 0,
            "rate_limit_notes": ""
        }
    }

    # Instanciar normalizador para matching de equipos (Bug B)
    normalizer = TeamNormalizer()
    rejected_by_date = 0
    rejected_by_target = 0
    all_candidates_scanned = 0

    for config in comp_configs:
        comp_id = config["id"]
        comp_region = config.get("region_code", region_code)
        must_include = [t.lower() for t in (config.get("must_include_terms") or [])]

        logger.info(f"Buscando videos para {comp_id}...")
        candidates = []
        seen_video_ids = set()
        errors = []

        # A) Búsqueda en WHITELIST (Prioridad 1)
        for channel_id in config["whitelist"]:
            uploads_playlist_id = api.get_uploads_playlist_id(channel_id)
            playlist_items = None

            if uploads_playlist_id:
                logger.info(f"Consultando últimos videos de whitelist: {channel_id}")
                # Aumentar profundidad para canales muy activos (ej: Primera B Chile)
                playlist_items = api.get_playlist_items(uploads_playlist_id, max_results=50)

            if not playlist_items or (isinstance(playlist_items, dict) and playlist_items.get("error")):
                logger.warning(f"YouTube Data API falló para {channel_id}, usando fallback yt-dlp...")
                playlist_items = api.get_latest_videos_no_api(channel_id, count=10)
                journalist_results["meta"]["rate_limit_notes"] = "Quota exceeded? Used yt-dlp fallback."

            if isinstance(playlist_items, list):
                for item in playlist_items:
                    if not isinstance(item, dict):
                        continue
                    item_id = item.get("id")
                    vid_id = item_id.get("videoId") if isinstance(item_id, dict) else None
                    vid_id = vid_id or item.get("snippet", {}).get("resourceId", {}).get("videoId")
                    if vid_id and vid_id not in seen_video_ids:
                        pub_at = item.get("snippet", {}).get("publishedAt")
                        title = item.get("snippet", {}).get("title", "")
                        desc = item.get("snippet", {}).get("description", "")
                        
                        # Filtro Live/Upcoming (Bug Auditor)
                        # EXCEPCIÓN: Permitir Live si es de canal Whitelist (suelen ser resúmenes terminados)
                        is_whitelist_channel = item.get("snippet", {}).get("channelId") in config["whitelist"]
                        if item.get("snippet", {}).get("liveBroadcastContent") in ("live", "upcoming") and not is_whitelist_channel:
                            logger.info(f"[RECHAZADO-LIVE] {vid_id} - {title} (No es whitelist)")
                            continue

                        # Filtro temporal
                        if not is_within_lookback(pub_at, published_after):
                            logger.info(f"[RECHAZADO-FECHA] {vid_id} - {title} (Fecha: {pub_at})")
                            rejected_by_date += 1
                            continue
                            
                        # Filtro de Target (Jornada) - Usando Normalizador (v2)
                        current_fixtures = [{"home": m["home_team"], "away": m["away_team"]} for m in monitored_matches if m.get("competition") == comp_id]
                        channel_title = item.get("snippet", {}).get("channelTitle", "")
                        match_res = is_target_match(title, desc, current_fixtures, config["competition_validation_terms"], 
                                                  "whitelist", normalizer=normalizer, channel_title=channel_title)
                        if not match_res["ok"]:
                            logger.info(f"[RECHAZADO-TARGET] {vid_id} - {title} | matched_teams={match_res['teams']} | matched_comp={match_res['comp']} | mode=whitelist | reason={match_res['reason']}")
                            rejected_by_target += 1
                            continue

                        candidates.append({"video_id": vid_id, "snippet": item["snippet"], "source": "whitelist"})
                        seen_video_ids.add(vid_id)
                        logger.debug(f"[CANDIDATO] {vid_id} - {title} (Fuente: Whitelist)")

        # B) Búsqueda Dinámica por Equipos de la jornada (Prioridad 2)
        if os.getenv("JOURNALIST_QUOTA_MODE", "dynamic") != "whitelist_only":
            comp_teams = [match.get("home_team") for match in monitored_matches if match.get("competition") == comp_id] + \
                         [match.get("away_team") for match in monitored_matches if match.get("competition") == comp_id]
            unique_teams = list(set(comp_teams))[:6]

            if unique_teams:
                logger.info(f"Realizando búsquedas dinámicas para {comp_id} con equipos: {unique_teams}")
                for team in unique_teams:
                    if comp_id in ["CHI1", "CHI2"]:
                        if comp_id == "CHI1":
                            suffix = "liga de primera mercado libre 2026"
                            suffix_en = "chilean primera division tactical analysis 2026"
                            suffix_pt = "análise tática liga de primera chile 2026"
                        else:
                            suffix = "primera b chile ascenso 2026"
                            suffix_en = "chilean primera b tactical analysis 2026"
                            suffix_pt = "análise tática primera b chile 2026"
                            
                        lang_templates = {
                            "es": f"{team} analisis tactico {suffix}",
                            "en": f"{team} {suffix_en}",
                            "pt": f"{team} {suffix_pt}"
                        }
                    else:
                        if comp_id == "COPA":
                            lang_templates = {
                                "es": f"{team} analisis tactico copa libertadores",
                                "en": f"{team} copa libertadores tactical analysis",
                                "pt": f"{team} análise tática copa libertadores"
                            }
                        else:
                            lang_templates = {
                                "es": f"{team} analisis tactico champions league",
                                "en": f"{team} champions league tactical analysis",
                                "pt": f"{team} análise tática champions league"
                            }
                    for lang in languages:
                        q = lang_templates.get(lang) or lang_templates.get("es")
                        logger.info(f"Buscando [{comp_id}] idioma={lang} query='{q}'")
                        search_items = api.search_videos(q, published_after, max_results=3, language=lang, region_code=comp_region)
                        if isinstance(search_items, list):
                            for item in search_items:
                                vid_id = item["id"].get("videoId")
                                if vid_id and vid_id not in seen_video_ids:
                                    pub_at = item.get("snippet", {}).get("publishedAt")
                                    title = item.get("snippet", {}).get("title", "")
                                    desc = item.get("snippet", {}).get("description", "")
                                    
                                    if not is_within_lookback(pub_at, published_after):
                                        logger.info(f"[RECHAZADO-FECHA] {vid_id} - {title} (Fecha: {pub_at})")
                                        rejected_by_date += 1
                                        continue
                                    
                                    # Filtro Live/Upcoming (Bug Auditor)
                                    is_whitelist_channel = item.get("snippet", {}).get("channelId") in config["whitelist"]
                                    if item.get("snippet", {}).get("liveBroadcastContent") in ("live", "upcoming") and not is_whitelist_channel:
                                        continue

                                    # Para búsqueda dinámica por equipo, el target es implícito pero re-validamos (v2)
                                    current_fixtures = [{"home": m["home_team"], "away": m["away_team"]} for m in monitored_matches if m.get("competition") == comp_id]
                                    channel_title = item.get("snippet", {}).get("channelTitle", "")
                                    match_res = is_target_match(title, desc, current_fixtures, config["competition_validation_terms"], 
                                                              f"dynamic_{team}", normalizer=normalizer, channel_title=channel_title, target_team=team)
                                    if not match_res["ok"]:
                                        logger.info(f"[RECHAZADO-TARGET] {vid_id} - {title} | matched_teams={match_res['teams']} | matched_comp={match_res['comp']} | mode=dynamic_{team} | reason={match_res['reason']}")
                                        rejected_by_target += 1
                                        continue

                                    candidates.append({"video_id": vid_id, "snippet": item["snippet"], "source": f"dynamic_{team}"})
                                    seen_video_ids.add(vid_id)
                                    logger.debug(f"[CANDIDATO] {vid_id} - {title} (Fuente: Dinámica {team})")

            # C) Búsquedas Genéricas de Respaldo (Prioridad 3)
            for lang in languages:
                queries = config.get("queries_by_lang", {}).get(lang) or config.get("queries_by_lang", {}).get("es") or []
                for q in queries:
                    logger.info(f"Buscando [{comp_id}] idioma={lang} query='{q}'")
                    search_items = api.search_videos(q, published_after, max_results=5, language=lang, region_code=comp_region)
                    if isinstance(search_items, list):
                        for item in search_items:
                            vid_id = item["id"].get("videoId")
                            if vid_id and vid_id not in seen_video_ids:
                                pub_at = item.get("snippet", {}).get("publishedAt")
                                title = item.get("snippet", {}).get("title", "")
                                desc = item.get("snippet", {}).get("description", "")

                                if not is_within_lookback(pub_at, published_after):
                                    logger.info(f"[RECHAZADO-FECHA] {vid_id} - {title} (Fecha: {pub_at})")
                                    rejected_by_date += 1
                                    continue
                                
                                # Las genéricas son las que más ruido meten: filtro estricto de equipos de jornada
                                # Filtro Live/Upcoming
                                is_whitelist_channel = item.get("snippet", {}).get("channelId") in config["whitelist"]
                                if item.get("snippet", {}).get("liveBroadcastContent") in ("live", "upcoming") and not is_whitelist_channel:
                                    continue

                                # Las genéricas son las que más ruido meten: filtro estricto (v2)
                                current_fixtures = [{"home": m["home_team"], "away": m["away_team"]} for m in odds_list if m.get("competition") == comp_id]
                                channel_title = item.get("snippet", {}).get("channelTitle", "")
                                match_res = is_target_match(title, desc, current_fixtures, config["competition_validation_terms"], 
                                                          "generic", normalizer=normalizer, channel_title=channel_title)
                                if not match_res["ok"]:
                                    logger.info(f"[RECHAZADO-TARGET] {vid_id} - {title} | matched_teams={match_res['teams']} | matched_comp={match_res['comp']} | mode=generic | reason={match_res['reason']}")
                                    rejected_by_target += 1
                                    continue

                                candidates.append({"video_id": vid_id, "snippet": item["snippet"], "source": "generic"})
                                seen_video_ids.add(vid_id)
                                logger.info(f"[CANDIDATO] {vid_id} - {title} (Fuente: Genérica)")
        else:
            logger.warning(f"Modo Whitelist Only activo. Saltando búsquedas para {comp_id}")

        all_candidates_scanned += len(candidates)

        if not candidates:
            journalist_results["competitions"].append({
                "competition": comp_id,
                "topic": config["topic"],
                "videos": [],
                "errors": ["No se encontraron videos candidatos en YouTube"]
            })
            continue

        # Enriquecer con estadísticas
        video_ids = [c["video_id"] for c in candidates]
        channel_ids = list(set(c["snippet"].get("channelId", "") for c in candidates if c.get("snippet")))

        v_stats_map = api.get_video_stats(video_ids)
        c_stats_map = api.get_channel_stats([cid for cid in channel_ids if cid])

        # Puntuar y Seleccionar
        logger.info(f"Puntuando {len(candidates)} candidatos para {comp_id}...")
        teams_in_comp = [match.get("home_team") for match in odds_list if match.get("competition") == comp_id] + \
                        [match.get("away_team") for match in odds_list if match.get("competition") == comp_id]
        teams_in_comp = [t for t in teams_in_comp if t]

        scored_vids = []
        for c in candidates:
            v_id = c["video_id"]
            snippet = c.get("snippet") or {}
            c_id = snippet.get("channelId", "")

            v_full = v_stats_map.get(v_id, {})
            c_full = c_stats_map.get(c_id, {})

            rel = score_relevance(
                snippet.get("title", ""),
                snippet.get("description", ""),
                config["keywords"],
                teams=set(teams_in_comp),
                competition=comp_id,
            )
            rep = score_reputation(v_full, c_full, config["whitelist"])

            min_rel = float(os.getenv("JOURNALIST_MIN_RELEVANCE", "0.1"))
            published_at = snippet.get("publishedAt", "2026-01-01T00:00:00Z")
            if (rel["score"] >= min_rel or (rep["method"] == "whitelist" and len(scored_vids) < 2)) and rel["score"] > 0:
                scored_vids.append({
                    "video_id": v_id,
                    "url": f"https://www.youtube.com/watch?v={v_id}",
                    "title": snippet.get("title", ""),
                    "published_at": published_at,
                    "channel": {"id": c_id, "title": snippet.get("channelTitle", "")},
                    "description_snippet": (snippet.get("description") or "")[:200] + "...",
                    "metrics": rep["metrics"],
                    "reputation": {"method": rep["method"], "score": rep["score"]},
                    "relevance": rel
                })
            else:
                reason = "Baja relevancia" if rel["score"] < min_rel else "Score 0"
                if rep["method"] != "whitelist":
                    logger.info(f"[RECHAZADO] {v_id} - {snippet.get('title')} (Motivo: {reason}, rel: {rel['score']:.2f})")

        # Refinamiento con LLM
        top_candidates = select_top_videos(scored_vids, comp_id, n=20)
        refined_videos = _refine_candidates_with_llm(top_candidates, comp_id)

        # Forzar inclusión de títulos clave (must_include)
        if must_include:
            must_hits = []
            for c in scored_vids:
                title = (c.get("title") or "").lower()
                if any(term in title for term in must_include):
                    must_hits.append(c)
            seen = set()
            merged = []
            for v in must_hits + refined_videos:
                vid = v.get("video_id")
                if not vid or vid in seen:
                    continue
                merged.append(v)
                seen.add(vid)
            refined_videos = merged

        final_videos = refined_videos[:10]
        for fv in final_videos:
            logger.info(f"[SELECCIONADO] {fv['video_id']} - {fv['title']} (Score: {fv['relevance']['score']:.2f})")

        journalist_results["competitions"].append({
            "competition": comp_id,
            "topic": config["topic"],
            "videos": final_videos,
            "errors": errors
        })

    journalist_results["meta"]["total_candidates_scanned"] = all_candidates_scanned
    journalist_results["meta"]["rejected_by_date"] = rejected_by_date
    journalist_results["meta"]["rejected_by_target"] = rejected_by_target

    state["journalist_videos"] = journalist_results

    # ── Poblar insights_sources para el insights_agent ─────────────────────
    sources = state.get("insights_sources") or {}
    for comp in journalist_results["competitions"]:
        comp_id = comp["competition"]
        urls = [v["url"] for v in comp.get("videos", [])]
        if urls:
            sources[comp_id] = urls
            logger.info(f"JOURNALIST: {len(urls)} URLs disponibles para insights_agent [{comp_id}]")
        else:
            logger.warning(f"JOURNALIST: Sin videos para {comp_id}, insights_agent no tendrá fuentes.")
        
        # --- TAREA EXTRA: Inyectar señales de PrimeraBChile para CHI2 si aplica ---
        if comp_id == "CHI2" and os.getenv("USE_PRIMERABCHILE_CHI2", "0") == "1":
            try:
                editorial_signals = fetch_primerabchile_signals()
                if editorial_signals:
                    editorial_urls = [s["url"] for s in editorial_signals if s.get("url")]
                    existing_urls = sources.get(comp_id, [])
                    # Mezclar y deduplicar
                    combined = list(set(existing_urls + editorial_urls))
                    sources[comp_id] = combined
                    logger.info(f"JOURNALIST: Inyectadas {len(editorial_urls)} fuentes editoriales desde PrimeraBChile para CHI2")
            except Exception as e:
                logger.error(f"Error inyectando fuentes de PrimeraBChile: {e}")
    state["insights_sources"] = sources

    # Persistir salida para la UI de Auditoría
    try:
        with open("journalist_test_output.json", "w", encoding="utf-8") as f:
            json.dump(journalist_results, f, indent=2, ensure_ascii=False)
        logger.info("journalist_test_output.json actualizado")
    except Exception as e:
        logger.warning(f"No se pudo guardar journalist_test_output.json: {e}")

    # Tarea 5/6: Registrar estados para el Reportero Operativo
    meta = state.get("meta", {})
    if "insights_sources_status" not in meta: meta["insights_sources_status"] = {}
    if "insights_sources_counts" not in meta: meta["insights_sources_counts"] = {}
    
    # Marcamos el estado por competencia
    for comp in journalist_results["competitions"]:
        c_id = comp["competition"]
        v_count = len(comp.get("videos", []))
        
        # Modo degradado si hubo fallos de API o similar (opcionalmente detectable vía meta local)
        status = "ok"
        if journalist_results["meta"].get("rate_limit_notes"):
            status = "degraded (api_fallback)"
        
        meta["insights_sources_status"][c_id] = status
        meta["insights_sources_counts"][c_id] = v_count

    state["meta"] = meta
    logger.info(f"JOURNALIST AGENT: Terminado. {all_candidates_scanned} candidatos escaneados.")
    return state
