import re
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from agents.analyst_web_check import run_analyst_web_check
from utils.normalizer import TeamNormalizer

logger = logging.getLogger(__name__)

def fetch_fixtures_via_web(competition_label: str, competition_name: str) -> List[Dict[str, Any]]:
    """
    Fallback method to find fixtures using web search when official APIs fail.
    """
    # Usar nombre patrocinado para mayor precisión en 2026
    search_name = "Liga de Ascenso Caixun" if competition_label == "CHI2" else competition_name
    logger.info(f"FALLBACK: Buscando fixtures para {competition_label} ({search_name}) vía Web...")
    
    req = {
        "competition": competition_label,
        "trigger_reason": "fetch_fixtures_fallback",
        "questions": [
            f"Listar los próximos partidos de la {search_name} (Chile) para el fin de semana del 20 al 23 de marzo de 2026.",
            "Formatear CADA partido como una línea: [FECHA YYYY-MM-DD HH:MM] Local vs Visitante"
        ],
        "lookback_days": 1
    }
    
    result = run_analyst_web_check(req)
    if not result.get("ok") or not result.get("data"):
        return []
        
    fixtures = []
    normalizer = TeamNormalizer()
    
    # Intentar extraer del answer_summary usando regex
    summary = result["data"].get("checks", [{}])[0].get("answer_summary", "")
    lines = summary.split("\n")
    
    # Regex para capturar "[YYYY-MM-DD HH:MM] Home vs Away"
    pattern = r"\[(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\]\s+(.*?)\s+vs\s+(.*)"
    
    for line in lines:
        match = re.search(pattern, line)
        if match:
            date_str, time_str, home, away = match.groups()
            utc_date = f"{date_str}T{time_str}:00Z"
            
            fixtures.append({
                "fixture_id": f"web_{competition_label}_{normalizer.clean(home)}_{normalizer.clean(away)}",
                "competition": competition_label,
                "provider": "web_fallback",
                "utc_date": utc_date,
                "status": "NS",
                "home_team": home.strip(),
                "away_team": away.strip(),
                "season": 2026
            })
            
    return fixtures

def fetch_odds_via_web(home: str, away: str, competition: str, fix: Dict) -> Optional[Dict[str, Any]]:
    """
    Busca cuotas 1X2 para un partido específico vía web (Oddspedia, Betano, etc.)
    Retorna un diccionario con cuotas y metadatos de provenance.
    """
    logger.info(f"FALLBACK: Buscando cuotas para {home} vs {away}...")
    
    # Formatear fecha para el prompt
    match_date = fix.get("utc_date", "marzo 2026")
    
    req = {
        "competition": competition,
        "trigger_reason": "fetch_odds_fallback",
        "questions": [
            f"¿Cuáles son las cuotas 1X2 actuales para el partido {home} vs {away} que se juega el {match_date} en la Primera B de Chile?",
            "IMPORTANTE: Proporcionar los valores numéricos para Local (1), Empate (X) y Visitante (2) dentro de etiquetas <odds>H, D, A</odds> (ej: <odds>2.10, 3.40, 3.20</odds>).",
            "Busca específicamente en Betano.cl, Coolbet.cl o Latamwin. Si el mercado está cerrado, busca en Oddspedia para cuotas de referencia realistas.",
            "NO digas que es un evento futuro sin buscar; el mercado para la Primera B suele abrirse 48-72h antes."
        ],
        "lookback_days": 2
    }
    
    result = run_analyst_web_check(req)
    if not result.get("ok") or not result.get("data"):
        return None
        
    summary = result["data"].get("checks", [{}])[0].get("answer_summary", "")
    logger.info(f"WEB ODDS DEBUG: Raw summary for {home} vs {away}:\n{summary}")
    sources = result["data"].get("checks", [{}])[0].get("source_links", [])
    source_url = sources[0] if sources else "unknown"
    
    # Intentar extraer usando la etiqueta <odds>
    odds_tag = re.search(r"<odds>(.*?)</odds>", summary)
    if odds_tag:
        raw_odds_str = odds_tag.group(1).replace(",", ".")
        numbers = re.findall(r"(\d+(?:\.\d+)?)", raw_odds_str)
    else:
        # Fallback regex si no usó el tag but seems safe
        numbers = []

    if len(numbers) >= 3:
        try:
            h, d, a = float(numbers[0]), float(numbers[1]), float(numbers[2])
            overround = (1/h) + (1/d) + (1/a)
            
            # Validación de Overround (Margen razonable 101% - 130%)
            if 1.0 < overround < 1.40:
                return {
                    "home": h,
                    "draw": d,
                    "away": a,
                    "odds_source_type": "web_scraped",
                    "odds_source_name": "analyst_web_check_extraction",
                    "source_url": source_url,
                    "captured_at": datetime.now().isoformat(),
                    "extraction_method": "llm_web_check_v2",
                    "extraction_confidence": 0.8,
                    "market_data_quality": "medium" if overround < 1.15 else "low"
                }
            else:
                logger.warning(f"WEB ODDS: Overround inválido ({overround:.3f}) para {home} vs {away}. Rechazando.")
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
        if label == "CHI2":
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
    odds_list = state.get("odds_canonical") or []
    
    # Crear un set de match_keys o combinaciones de equipos ya existentes para búsqueda rápida
    existing_matches = set()
    for o in odds_list:
        h = o.get("home_team", "").lower()
        a = o.get("away_team", "").lower()
        existing_matches.add(f"{h} vs {a}")
        if o.get("match_key"):
            existing_matches.add(o["match_key"])

    new_odds = []
    for fix in fixtures:
        home = fix.get("home_team")
        away = fix.get("away_team")
        comp = fix.get("competition", "Unknown")
        match_key = f"{home.lower()} vs {away.lower()}"
        
        # Solo actuar si no hay cuotas ya
        if match_key in existing_matches:
            continue
            
        web_res = fetch_odds_via_web(home, away, comp, fix)
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
            
    if new_odds:
        state["odds_canonical"] = odds_list + new_odds
        logger.info(f"✓ Inyectadas {len(new_odds)} cuotas desde la Web (Resiliencia)")
        
    return state
