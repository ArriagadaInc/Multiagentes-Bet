import re
import time
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from utils.normalizer import TeamNormalizer
from utils.llm_factory import get_llm

logger = logging.getLogger(__name__)

import os
from agents.sources.footystats_chi2 import fetch_footystats_fixtures
from agents.sources.web_odds_scraper import fetch_direct_web_odds
from agents.analyst_web_check import run_analyst_web_check
from agents.manual_odds_agent import build_manual_odds_for_fixtures, get_recent_manual_match_keys

try:
    from duckduckgo_search import DDGS as _DDGS
    _ddg_available = True
except Exception:
    _DDGS = None
    _ddg_available = False


def _extract_primary_source_url(check: dict) -> str:
    """Extrae la URL principal desde el schema actual de analyst_web_check."""
    sources = check.get("sources") or []
    if isinstance(sources, list):
        for src in sources:
            if isinstance(src, dict) and src.get("url"):
                return str(src["url"])
    source_links = check.get("source_links") or []
    if isinstance(source_links, list) and source_links:
        return str(source_links[0])
    return "unknown"


def _extract_odds_numbers_from_summary(summary: str) -> list[float]:
    """Extrae cuotas 1X2 desde el texto libre del web check."""
    text = str(summary or "").strip()
    if not text:
        return []

    odds_tag = re.search(r"<odds>(.*?)</odds>", text, flags=re.IGNORECASE | re.DOTALL)
    if odds_tag:
        raw = odds_tag.group(1).replace(",", ".")
        nums = re.findall(r"(\d+(?:\.\d+)?)", raw)
        if len(nums) >= 3:
            try:
                return [float(nums[0]), float(nums[1]), float(nums[2])]
            except Exception:
                return []

    tagged_home = re.findall(r"(?:^|[\s|,;])(?:1|h|local)\s*[:=]\s*(\d+(?:[.,]\d+)?)", text, flags=re.IGNORECASE)
    tagged_draw = re.findall(r"(?:^|[\s|,;])(?:x|draw|empate)\s*[:=]\s*(\d+(?:[.,]\d+)?)", text, flags=re.IGNORECASE)
    tagged_away = re.findall(r"(?:^|[\s|,;])(?:2|a|visitante)\s*[:=]\s*(\d+(?:[.,]\d+)?)", text, flags=re.IGNORECASE)
    if tagged_home and tagged_draw and tagged_away:
        try:
            return [
                float(tagged_home[0].replace(",", ".")),
                float(tagged_draw[0].replace(",", ".")),
                float(tagged_away[0].replace(",", ".")),
            ]
        except Exception:
            pass

    nums = re.findall(r"(\d+(?:\.\d{1,2}))", text.replace(",", "."))
    plausible = []
    for n in nums:
        try:
            val = float(n)
        except Exception:
            continue
        if 1.05 < val < 20.0:
            plausible.append(val)
    return plausible[:3] if len(plausible) >= 3 else []


def _build_odds_questions(home: str, away: str, competition: str, match_date: str) -> list[str]:
    """Construye preguntas espec?ficas para extraer cuotas 1X2."""
    comp_name = "la Primera B de Chile" if competition == "CHI2" else f"el torneo {competition}"
    questions = [
        f"Busca las cuotas 1X2 actuales o m?s recientes disponibles para el partido {home} vs {away}, programado para {match_date}, en {comp_name}.",
        "Devuelve los valores num?ricos para Local (1), Empate (X) y Visitante (2) dentro de etiquetas <odds>H, D, A</odds> si encuentras una l?nea de mercado verificable.",
    ]
    if competition == "CHI2":
        questions.extend([
            "Prioriza Betano.cl, Coolbet.cl y Latamwin. Si no hay mercado local abierto, busca en OddsPortal, Oddspedia, bet365, 1xBet o Pinnacle.",
            "Si solo encuentras una referencia de mercado en un agregador reputado, ?sala igual. No uses picks editoriales ni probabilidades inventadas.",
        ])
    else:
        questions.extend([
            "Prioriza Betano, Coolbet, Latamwin, bet365, Pinnacle u OddsPortal/Oddspedia si ayudan a confirmar la l?nea.",
            "No inventes cuotas. Si no existe mercado verificable, dilo expl?citamente.",
        ])
    return questions


def fetch_fixtures_via_web(competition_label: str, competition_name: str) -> List[Dict[str, Any]]:
    """
    Fallback method to find fixtures using web search when official APIs fail.
    Uses DuckDuckGo directly + LLM to parse, bypassing analyst_web_check's
    limitation of not providing web results in expensive_mode.
    """
    if competition_label == "CHI2":
        search_name = "Primera B de Chile"
    elif competition_label == "CHI1":
        search_name = "Primera División de Chile Campeonato Itaú"
    else:
        search_name = competition_name
        
    logger.info(f"FALLBACK: Buscando fixtures para {competition_label} ({search_name}) vía Web (DDG directo)...")

    if not _ddg_available:
        logger.warning("DuckDuckGo no disponible. Saltando fetch_fixtures_via_web.")
        return []

    # --- 1. Buscar en la web directamente con queries especializadas ---
    today = datetime.now(timezone.utc)
    today_str = today.strftime("%Y-%m-%d")
    current_month = today.strftime("%B %Y")
    
    # Query robusto: busca jornada actual, resultados recientes y próximos partidos
    # Esto ayuda a no saltarse partidos que están ocurriendo o acaban de ocurrir
    query = f"{search_name} resultados fixtures jornada actual próximos partidos {today_str} {current_month}"
    try:
        with _DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=15))
        raw_search = " | ".join([f"{r.get('title','')} {r.get('body','')}" for r in results])
    except Exception as e:
        logger.error(f"WEB FIXTURES: Error en búsqueda DDG: {e}")
        return []

    logger.info(f"WEB FIXTURES DEBUG: DDG raw results:\n{raw_search[:1000]}")

    if not raw_search or len(raw_search) < 30:
        logger.warning("WEB FIXTURES: Búsqueda DDG sin resultados útiles.")
        return []

    # --- 2. Enviar a LLM para que formatee el resultado ---
    llm = get_llm(temperature=0)
    prompt = f"""A continuación aparecen resultados de búsqueda web sobre la {search_name}. 
Tu tarea es extraer ÚNICAMENTE los partidos que AÚN NO SE HAN JUGADO (estado NS / programados) que están en los próximos 7 días desde hoy ({today}).
Ignora partidos ya jugados (que muestren resultado como 2-1, etc.).

Para cada partido encontrado, responde EXACTAMENTE con el formato:
[YYYY-MM-DD HH:MM] Equipo Local vs Equipo Visitante

Si no hay hora confirmada usa 00:00. Si no encuentras partidos futuros válidos, responde SOLO: NO_FIXTURES.

RESULTADOS DE BÚSQUEDA:
{raw_search[:3000]}"""

    try:
        resp = llm.invoke(prompt)
        raw_content = resp.content
        if isinstance(raw_content, list):
            raw_content = " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in raw_content)
        summary = str(raw_content).strip()
    except Exception as e:
        logger.error(f"WEB FIXTURES: Error en LLM formatting: {e}")
        return []

    logger.info(f"WEB FIXTURES DEBUG: LLM formatted:\n{summary}")

    if "NO_FIXTURES" in summary:
        logger.info("WEB FIXTURES: LLM confirmó que no hay partidos futuros en los resultados.")
        return []

    # --- 3. Parsear con regex ---
    fixtures = []
    normalizer = TeamNormalizer()
    pattern = r"\[(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\]\s+(.*?)\s+vs\s+(.*)"
    for line in summary.split("\n"):
        m = re.search(pattern, line)
        if m:
            date_str, time_str, home, away = m.groups()
            home, away = home.strip(), away.strip()
            fixtures.append({
                "fixture_id": f"web_{competition_label}_{normalizer.clean(home)}_{normalizer.clean(away)}",
                "competition": competition_label,
                "provider": "web_fallback",
                "utc_date": f"{date_str}T{time_str}:00Z",
                "status": "NS",
                "home_team": home,
                "away_team": away,
                "season": 2026
            })

    logger.info(f"WEB FIXTURES: {len(fixtures)} partido(s) extraídos.")
    return fixtures

def fetch_odds_via_web(home: str, away: str, competition: str, fix: Dict) -> Optional[Dict[str, Any]]:
    """
    Busca cuotas 1X2 para un partido espec?fico v?a web (Oddspedia, Betano, etc.)
    Retorna un diccionario con cuotas y metadatos de provenance.
    """
    logger.info(f"FALLBACK: Buscando cuotas para {home} vs {away}...")

    # Capa 0: scraper directo sin LLM. Si encuentra algo válido, evitamos costo.
    direct_res = fetch_direct_web_odds(home, away, competition)
    if direct_res:
        direct_res["captured_at"] = datetime.now().isoformat()
        logger.info(f"WEB ODDS: cuotas encontradas por scraper directo para {home} vs {away}")
        return direct_res

    match_date = fix.get("utc_date", "marzo 2026")
    req = {
        "competition": competition,
        "trigger_reason": "fetch_odds_fallback",
        "questions": _build_odds_questions(home, away, competition, match_date),
        "lookback_days": 4,
    }

    result = run_analyst_web_check(req)
    if not result.get("ok") or not result.get("data"):
        return None

    check = (result["data"].get("checks") or [{}])[0]
    summary = check.get("answer_summary", "")
    logger.info(f"WEB ODDS DEBUG: Raw summary for {home} vs {away}:\n{summary}")
    source_url = _extract_primary_source_url(check)
    numbers = _extract_odds_numbers_from_summary(summary)

    if len(numbers) < 3 and competition == "CHI2":
        logger.info(f"WEB ODDS: sin cuotas parseables para {home} vs {away}; segunda pasada ampliada")
        req_second = {
            "competition": competition,
            "trigger_reason": "fetch_odds_fallback_second_pass",
            "questions": [
                f"Busca una referencia 1X2 de mercado para {home} vs {away} ({match_date}).",
                "Acepta cuotas de agregadores reputados (OddsPortal, Oddspedia) o casas reales internacionales (bet365, Pinnacle, 1xBet). Devuelve <odds>H, D, A</odds> si hallas una l?nea verificable.",
                "Si no existe ninguna l?nea real de mercado, responde expl?citamente que no hay cuotas verificables disponibles.",
            ],
            "lookback_days": 7,
        }
        result_second = run_analyst_web_check(req_second)
        if result_second.get("ok") and result_second.get("data"):
            check_second = (result_second["data"].get("checks") or [{}])[0]
            summary_second = check_second.get("answer_summary", "")
            logger.info(f"WEB ODDS DEBUG 2nd pass for {home} vs {away}:\n{summary_second}")
            numbers = _extract_odds_numbers_from_summary(summary_second)
            second_url = _extract_primary_source_url(check_second)
            if second_url != "unknown":
                source_url = second_url

    if len(numbers) >= 3:
        try:
            h, d, a = float(numbers[0]), float(numbers[1]), float(numbers[2])
            overround = (1 / h) + (1 / d) + (1 / a)
            if 1.0 < overround < 1.40:
                return {
                    "home": h,
                    "draw": d,
                    "away": a,
                    "odds_source_type": "web_scraped",
                    "odds_source_name": "analyst_web_check_extraction",
                    "source_url": source_url,
                    "captured_at": datetime.now().isoformat(),
                    "extraction_method": "llm_web_check_v3",
                    "extraction_confidence": 0.8,
                    "market_data_quality": "medium" if overround < 1.15 else "low",
                }
            logger.warning(f"WEB ODDS: Overround inv?lido ({overround:.3f}) para {home} vs {away}. Rechazando.")
        except (ValueError, ZeroDivisionError):
            pass
    return None

def web_fixtures_fetcher_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Nodo de LangGraph para capturar fixtures vía web si las APIs fallaron.
    """
    # Si ya tiene fixtures (ej: desde fixtures.json), no hacemos nada
    if state.get("fixtures") and len(state["fixtures"]) > 0:
        # Pero nos aseguramos de que tengan IDs compatibles
        return state
        
    competitions = state.get("competitions", [])
    all_web_fixtures = []
    
    for comp in competitions:
        label = comp.get("competition")
        name = comp.get("name", label)
        if label in ["CHI1", "CHI2"]:
            # 1. Intentar FootyStats si está habilitado (prioridad sobre DDG para CHI2)
            if label == "CHI2" and os.getenv("USE_FOOTYSTATS_CHI2", "0") == "1":
                try:
                    fs_fix = fetch_footystats_fixtures()
                    if fs_fix:
                        logger.info(f"✓ Inyectados {len(fs_fix)} fixtures desde FootyStats (Fuente Fija CHI2)")
                        all_web_fixtures.extend(fs_fix)
                        continue # Si FootyStats funcionó, no necesitamos DDG para CHI2
                except Exception as e:
                    logger.error(f"Error llamando a FootyStats: {e}")

            # 2. Fallback DDG (si FootyStats no está, falló, o es liga CHI1)
            web_fix = fetch_fixtures_via_web(label, name)
            all_web_fixtures.extend(web_fix)
            
    if all_web_fixtures:
        state["fixtures"] = (state.get("fixtures") or []) + all_web_fixtures
        state["meta"]["total_fixtures"] = len(state["fixtures"])
        logger.info(f"✓ Inyectados {len(all_web_fixtures)} fixtures desde la Web")
        
    return state

def web_odds_fetcher_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Busca cuotas vía web para fixtures que no tengan odds_canonical o que sean incompletas.
    """
    fixtures = state.get("fixtures", [])
    date_from = state.get("fixtures_date_from")
    date_to = state.get("fixtures_date_to")
    odds_list = state.get("odds_canonical") or []
    meta = state.setdefault("meta", {})
    web_odds_audit = meta.setdefault("web_odds_audit", [])
    manual_odds_audit = meta.setdefault("manual_odds_audit", [])

    # Defensa extra: si un proveedor upstream devolvió fixtures fuera de la
    # ventana pedida, no dejamos que consuman scraping web ni tiempo de API.
    if date_from and date_to:
        def _fixture_in_state_window(fix: Dict[str, Any]) -> bool:
            try:
                iso = str(fix.get("utc_date") or "")
                if not iso:
                    return False
                parsed = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                start = datetime.fromisoformat(f"{date_from}T00:00:00+00:00")
                end = datetime.fromisoformat(f"{date_to}T23:59:59+00:00")
                return start <= parsed <= end
            except Exception:
                return False

        before = len(fixtures)
        fixtures = [fix for fix in fixtures if _fixture_in_state_window(fix)]
        if len(fixtures) != before:
            logger.info(
                f"WEB ODDS: filtro defensivo por ventana aplicado: "
                f"{before} -> {len(fixtures)} fixtures dentro de {date_from} a {date_to}"
            )
            state["fixtures"] = fixtures

    manual_copa_keys = get_recent_manual_match_keys("COPA")
    if manual_copa_keys:
        def _fixture_manual_key(fix: Dict[str, Any]) -> str:
            comp = str(fix.get("competition") or "").upper().strip()
            home = normalizer.clean(str(fix.get("home_team") or ""))
            away = normalizer.clean(str(fix.get("away_team") or ""))
            return f"{comp}:{home}:{away}"

        normalizer = TeamNormalizer()
        before = len(fixtures)
        filtered = []
        for fix in fixtures:
            if str(fix.get("competition") or "").upper() != "COPA":
                filtered.append(fix)
                continue
            if _fixture_manual_key(fix) in manual_copa_keys:
                filtered.append(fix)
        if filtered and len(filtered) != before:
            logger.info(
                f"WEB ODDS: COPA restringido a universo manual: "
                f"{before} -> {len(filtered)} fixtures"
            )
            fixtures = filtered
            state["fixtures"] = fixtures

    # Antes de salir a la web, intentamos fusionar cuotas manuales revisadas por el usuario.
    manual_odds, manual_audit = build_manual_odds_for_fixtures(fixtures, odds_list)
    if manual_audit:
        manual_odds_audit.extend(manual_audit)
    if manual_odds:
        odds_list = odds_list + manual_odds
        state["odds_canonical"] = odds_list
        logger.info(f"✓ Inyectadas {len(manual_odds)} cuotas manuales OCR al pipeline")
    
    # Crear un set de match_keys o combinaciones de equipos ya existentes para búsqueda rápida
    existing_matches = set()
    normalizer = TeamNormalizer()
    for o in odds_list:
        h_norm = normalizer.clean(o.get("home_team", ""))
        a_norm = normalizer.clean(o.get("away_team", ""))
        h = h_norm if h_norm else o.get("home_team", "").lower()
        a = a_norm if a_norm else o.get("away_team", "").lower()
        existing_matches.add(f"{h} vs {a}")
        if o.get("match_key"):
            existing_matches.add(o["match_key"])

    missing_fixtures = []
    for fix in fixtures:
        home = fix.get("home_team", "")
        away = fix.get("away_team", "")
        comp = fix.get("competition", "Unknown")
        h_norm = normalizer.clean(home)
        a_norm = normalizer.clean(away)
        h = h_norm if h_norm else home.lower()
        a = a_norm if a_norm else away.lower()
        match_key = f"{h} vs {a}"
        
        # Solo actuar si no hay cuotas ya
        if match_key in existing_matches:
            continue
        missing_fixtures.append(fix)

    copa_fallback_limit = int(os.getenv("COPA_MAX_WEB_ODDS_FALLBACK", "1" if manual_copa_keys else "2"))
    if copa_fallback_limit >= 0:
        copa_missing = [f for f in missing_fixtures if str(f.get("competition") or "").upper() == "COPA"]
        if len(copa_missing) > copa_fallback_limit:
            keep_ids = {id(f) for f in copa_missing[:copa_fallback_limit]}
            reduced = []
            for fix in missing_fixtures:
                if str(fix.get("competition") or "").upper() != "COPA":
                    reduced.append(fix)
                elif id(fix) in keep_ids:
                    reduced.append(fix)
                else:
                    web_odds_audit.append({
                        "competition": "COPA",
                        "match_id": fix.get("fixture_id"),
                        "home_team": fix.get("home_team"),
                        "away_team": fix.get("away_team"),
                        "status": "skipped_by_copa_fallback_limit",
                        "reason": f"COPA: fallback web limitado a {copa_fallback_limit} fixture(s) faltante(s).",
                        "captured_at": datetime.now().isoformat(),
                    })
            logger.info(
                f"WEB ODDS: COPA limitó fallback web de "
                f"{len(copa_missing)} a {copa_fallback_limit} fixtures faltantes"
            )
            missing_fixtures = reduced

    new_odds = []
    for fix in missing_fixtures:
        home = fix.get("home_team", "")
        away = fix.get("away_team", "")
        comp = fix.get("competition", "Unknown")
        web_res = fetch_odds_via_web(home, away, comp, fix)
        
        # Parche defensivo: Rate limit delay para la capa gratuita de Gemini (15 RPM)
        # Evitar sobrepasar la API al buscar múltiples cuotas en bucle cerrado
        time.sleep(8)
        
        if web_res:
            # Construir objeto canónico con provenance
            match_id = fix.get("fixture_id", f"web_fix_{home}_{away}")
            new_odd = {
                "competition": comp,
                "match_id": match_id,
                "home_team": home,
                "away_team": away,
                "home": web_res["home"],
                "draw": web_res["draw"],
                "away": web_res["away"],
                "provider": web_res["odds_source_name"],
                "odds_source_type": web_res["odds_source_type"],
                "source_url": web_res["source_url"],
                "captured_at": web_res["captured_at"],
                "extraction_method": web_res["extraction_method"],
                "extraction_confidence": web_res["extraction_confidence"],
                "market_data_quality": web_res["market_data_quality"],
                "timestamp": web_res["captured_at"],
                "bookmakers_count": 1,
                "bookmakers": [
                    {
                        "key": web_res["odds_source_name"],
                        "title": "Web Scraped",
                        "home_odds": web_res["home"],
                        "draw_odds": web_res["draw"],
                        "away_odds": web_res["away"]
                    }
                ]
            }
            new_odds.append(new_odd)
            existing_matches.add(match_key)
            web_odds_audit.append({
                "competition": comp,
                "match_id": match_id,
                "home_team": home,
                "away_team": away,
                "status": "odds_found",
                "source_url": web_res.get("source_url"),
                "odds_source_type": web_res.get("odds_source_type"),
                "extraction_method": web_res.get("extraction_method"),
                "market_data_quality": web_res.get("market_data_quality"),
                "captured_at": web_res.get("captured_at"),
            })
        else:
            web_odds_audit.append({
                "competition": comp,
                "match_id": fix.get("fixture_id", f"web_fix_{home}_{away}"),
                "home_team": home,
                "away_team": away,
                "status": "no_market_detected_web",
                "reason": "No se encontraron cuotas 1X2 verificables en scraper directo ni fallback web.",
                "captured_at": datetime.now().isoformat(),
            })
            
    if new_odds:
        state["odds_canonical"] = odds_list + new_odds
        logger.info(f"✓ Inyectadas {len(new_odds)} cuotas desde la Web (Resiliencia)")
        
    return state
