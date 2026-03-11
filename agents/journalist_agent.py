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
from typing import List, Dict, Any, Optional

from state import AgentState
from utils.youtube_api import YouTubeAPI
from utils.cache import load_cache, save_cache
from utils.token_tracker import TokenTrackingCallbackHandler

try:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage
except ImportError:
    pass

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURACIÓN Y CONSTANTES
# ============================================================================

KEYWORDS_CHILE = {
    "topics": [
        "pronóstico", "predicción", "previa", "apuestas", "antes del partido", "análisis",
        "reacción", "capítulo", "táctica", "pizarra", "onces",
        "prediction", "preview", "betting", "analysis", "tactical", "tactics",
        "lineup", "starting xi", "injuries",
        "prognóstico", "previsão", "apostas", "análise", "tático", "tática",
        "escalação", "onze inicial", "lesões",
        "tabla de posiciones", "líder del torneo", "lucha por la punta",
        "análisis de la fecha", "panorama del campeonato"
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
        "pronóstico", "predicción", "previa", "apuestas deportivas", "análisis", "resumen",
        "especial", "analisis champions league", "pronosticos champions league",
        "táctica", "pizarra", "pizarra táctica", "onces",
        "prediction", "preview", "betting", "analysis", "tactical", "tactics",
        "lineup", "starting xi", "injuries",
        "prognóstico", "previsão", "apostas", "análise", "tático", "tática",
        "escalação", "onze inicial", "lesões",
        "standings", "league table", "title race", "relegation battle",
        "tabla de posiciones", "quién es el líder", "análisis de la jornada"
    ],
    "subject": [
        "champions", "champions league", "uefa champions", "futbol europeo",
        "diario as", "espn fans", "ucl", "thonybet",
        "european football", "uefa champions league"
    ]
}


def _get_env_list(key: str, default: str = "") -> List[str]:
    val = os.getenv(key, default)
    return [x.strip() for x in val.split(",") if x.strip()]


# ============================================================================
# LÓGICA DE SCORING Y SELECCIÓN
# ============================================================================

def score_relevance(
    title: str,
    description: str,
    keywords: Dict[str, List[str]],
    teams: List[str] = None,
    competition: Optional[str] = None,
) -> Dict[str, Any]:
    """Calcula la relevancia de un video basado en palabras clave y equipos."""
    title = title or ""
    description = description or ""
    text = (title + " " + description).lower()
    matched_topics = [k for k in keywords["topics"] if k in text]
    matched_subjects = [k for k in keywords["subject"] if k in text]
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

    priority_terms = [
        "todos somos técnicos", "tst", "análisis de la fecha",
        "pronósticos para la fecha", "especial", "pizarra táctica"
    ]
    has_priority = any(term in text for term in priority_terms)
    if has_priority:
        score += priority_bonus
    if matched_context:
        score += context_bonus

    # FILTRO NEGATIVO
    # Nota: Usamos límites de palabra (\b) para términos cortos o genéricos como 'la liga'
    # para evitar falsos positivos con 'la liga de primera'.
    negative_terms = [
        "ascenso", "caixun", "segunda división", "primera b",
        "mlb", "nba", "beisbol", "béisbol", "baloncesto", "basket", "tenis", "ufc",
        "elecciones", "politica", "política", "gaviota", "rcp",
        "liga mx", "river plate", "banfield"
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
    """Selecciona los mejores N videos por reputación, relevancia y fecha."""
    def _sort_key(v):
        rep = v["reputation"]["score"]
        rel = v["relevance"]["score"]
        date_val = datetime.fromisoformat(v["published_at"].replace("Z", "+00:00")).timestamp()
        return (rep, rel, date_val)

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
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from langchain_openai import ChatOpenAI
        model_name = os.getenv("JOURNALIST_LLM_MODEL", "gpt-4o")
        return ChatOpenAI(
            model=model_name,
            temperature=0.1,
            callbacks=[TokenTrackingCallbackHandler()]
        )
    except Exception as e:
        logger.warning(f"Error al inicializar LLM: {e}")
        return None


def _refine_candidates_with_llm(candidates: List[Dict[str, Any]], competition: str) -> List[Dict[str, Any]]:
    """Usa un LLM para filtrar candidatos y seleccionar los más útiles."""
    llm = _make_llm()
    if not llm:
        logger.info("LLM no disponible para refinamiento, usando todos los candidatos.")
        return candidates[:10]

    logger.info(f"Refinando {len(candidates)} candidatos para {competition} con LLM...")

    video_list_str = ""
    for i, v in enumerate(candidates):
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
        json_match = re.search(r'(\{.*\})', response.content, re.DOTALL)
        if json_match:
            eval_data = json.loads(json_match.group(1))
            useful_indices = [
                e["index"] for e in eval_data.get("evaluations", [])
                if e.get("status") == "UTIL"
            ]
            refined = [candidates[i] for i in useful_indices if i < len(candidates)]
            logger.info(f"LLM seleccionó {len(refined)} videos como útiles.")
            return refined
        else:
            logger.warning("No se pudo parsear la respuesta del LLM.")
            return candidates[:10]
    except Exception as e:
        logger.error(f"Error en el refinamiento LLM: {e}")
        return candidates[:10]


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
    published_after = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat().replace("+00:00", "Z")
    max_search = int(os.getenv("JOURNALIST_MAX_RESULTS_SEARCH", "25"))
    languages = _get_env_list("JOURNALIST_LANGUAGES", os.getenv("JOURNALIST_LANGUAGE", "es"))
    region_code = os.getenv("JOURNALIST_REGION_CODE", "CL")
    ttl = int(os.getenv("CACHE_TTL_SECONDS", "3600"))
    odds_list = state.get("odds_canonical") or []

    whitelist_chile = _get_env_list("JOURNALIST_CHANNEL_WHITELIST_CHILE")
    whitelist_ucl = _get_env_list("JOURNALIST_CHANNEL_WHITELIST_UCL")

    comp_configs = [
        {
            "id": "CHI1",
            "topic": "Liga de Primera Mercado Libre 2026",
            "keywords": KEYWORDS_CHILE,
            "whitelist": whitelist_chile,
            "region_code": os.getenv("JOURNALIST_REGION_CODE_CHI1", region_code),
            "must_include_terms": [
                "liga de primera mercado libre",
                "campeonato nacional chile",
            ],
            "queries_by_lang": {
                "es": [
                    "liga de primera mercado libre 2026 analisis tecnico",
                    "pronósticos liga de primera mercado libre chile",
                    "tnt sports chile todos somos técnicos capitulo completo",
                    "previa fecha liga de primera mercado libre"
                ],
                "en": [
                    "chilean primera division 2026 tactical analysis",
                    "chilean league predictions 2026",
                ],
                "pt": [
                    "liga de primera chile 2026 análise tática",
                    "campeonato chileno prognóstico 2026",
                ]
            }
        },
        {
            "id": "UCL",
            "topic": "UEFA Champions League",
            "keywords": KEYWORDS_UCL,
            "whitelist": whitelist_ucl,
            "region_code": os.getenv("JOURNALIST_REGION_CODE_UCL", ""),
            "must_include_terms": [
                "uefa champions league",
                "champions league",
            ],
            "queries_by_lang": {
                "es": [
                    "pronosticos champions league hoy",
                    "analisis tactico champions league ucl",
                    "pizarra tactica champions league",
                    "apuestas uefa champions league expertos"
                ],
                "en": [
                    "champions league predictions today",
                    "champions league tactical analysis",
                ],
                "pt": [
                    "prognósticos champions league hoje",
                    "análise tática champions league",
                ]
            }
        }
    ]
    
    # --- FILTRADO POR COMPETENCIA ACTIVA ---
    active_comp_ids = {match.get("competition", "").upper() for match in odds_list if match.get("competition")}
    if active_comp_ids:
        filtered_configs = [c for c in comp_configs if c["id"] in active_comp_ids]
        removed = [c["id"] for c in comp_configs if c["id"] not in active_comp_ids]
        if removed:
            logger.info(f"JOURNALIST: Ignorando configuraciones de ligas no activas: {removed}")
        comp_configs = filtered_configs

    journalist_results = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lookback_days": lookback_days,
        "sources": {"youtube": "data_api_v3"},
        "competitions": [],
        "meta": {
            "cache_hit": False,
            "total_candidates_scanned": 0,
            "rate_limit_notes": ""
        }
    }

    all_candidates_scanned = 0
    any_cache_hit = False

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
                playlist_items = api.get_playlist_items(uploads_playlist_id, max_results=15)

            if not playlist_items or (isinstance(playlist_items, dict) and playlist_items.get("error")):
                logger.warning(f"⚠️ API YouTube falló para {channel_id}. Usando FALLBACK yt-dlp.")
                playlist_items = api.get_latest_videos_no_api(channel_id, count=2)
                journalist_results["meta"]["rate_limit_notes"] = "Quota exceeded? Used yt-dlp fallback."

            if isinstance(playlist_items, list):
                for item in playlist_items:
                    if not isinstance(item, dict):
                        continue
                    item_id = item.get("id")
                    vid_id = item_id.get("videoId") if isinstance(item_id, dict) else None
                    vid_id = vid_id or item.get("snippet", {}).get("resourceId", {}).get("videoId")
                    if vid_id and vid_id not in seen_video_ids:
                        candidates.append({"video_id": vid_id, "snippet": item["snippet"], "source": "whitelist"})
                        seen_video_ids.add(vid_id)
                        logger.debug(f"[CANDIDATO] {vid_id} - {item['snippet'].get('title')} (Fuente: Whitelist)")

        # B) Búsqueda Dinámica por Equipos de la jornada (Prioridad 2)
        if os.getenv("JOURNALIST_QUOTA_MODE", "dynamic") != "whitelist_only":
            comp_teams = [match.get("home_team") for match in odds_list if match.get("competition") == comp_id] + \
                         [match.get("away_team") for match in odds_list if match.get("competition") == comp_id]
            unique_teams = list(set(comp_teams))[:6]

            if unique_teams:
                logger.info(f"Realizando búsquedas dinámicas para {comp_id} con equipos: {unique_teams}")
                for team in unique_teams:
                    if comp_id == "CHI1":
                        lang_templates = {
                            "es": f"{team} analisis tactico liga de primera mercado libre 2026",
                            "en": f"{team} chilean primera division tactical analysis 2026",
                            "pt": f"{team} análise tática liga de primera chile 2026"
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
                                    candidates.append({"video_id": vid_id, "snippet": item["snippet"], "source": f"dynamic_{team}"})
                                    seen_video_ids.add(vid_id)
                                    logger.debug(f"[CANDIDATO] {vid_id} - {item['snippet'].get('title')} (Fuente: Dinámica {team})")

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
                                candidates.append({"video_id": vid_id, "snippet": item["snippet"], "source": "generic"})
                                seen_video_ids.add(vid_id)
                                logger.info(f"[CANDIDATO] {vid_id} - {item['snippet'].get('title')} (Fuente: Genérica)")
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
    journalist_results["meta"]["cache_hit"] = any_cache_hit

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
    state["insights_sources"] = sources

    # Persistir salida para la UI de Auditoría
    try:
        with open("journalist_test_output.json", "w", encoding="utf-8") as f:
            json.dump(journalist_results, f, indent=2, ensure_ascii=False)
        logger.info("journalist_test_output.json actualizado")
    except Exception as e:
        logger.warning(f"No se pudo guardar journalist_test_output.json: {e}")

    logger.info(f"JOURNALIST AGENT: Terminado. {all_candidates_scanned} candidatos escaneados.")
    return state
