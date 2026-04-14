import json
import logging
import os
import sys
# Permitir que el script corra como standalone y reconozca la carpeta utils/
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from datetime import datetime
from dotenv import load_dotenv
from duckduckgo_search import DDGS
from utils.llm_factory import get_llm
import time
from functools import wraps

# Cargar variables de entorno al inicio
load_dotenv()

# Configuración de logs
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

TEAM_HISTORY_FILE = os.path.join("data", "knowledge", "team_history.json")

def _load_team_history():
    if os.path.exists(TEAM_HISTORY_FILE):
        try:
            with open(TEAM_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error cargando team history: {e}")
    return {}

def _save_team_history(data):
    try:
        with open(TEAM_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error guardando team history: {e}")

def with_retry(max_retries=3, delay_secs=2):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_err = e
                    logger.warning(f"Error en {func.__name__} (intento {attempt+1}/{max_retries}): {e}. Reintentando en {delay_secs}s...")
                    time.sleep(delay_secs)
            logger.error(f"Fallo definitivo en {func.__name__} tras {max_retries} intentos. Último error: {last_err}")
            raise last_err
        return wrapper
    return decorator

@with_retry(max_retries=3, delay_secs=2)
def _search_web(query: str, max_results: int = 3) -> str:
    """Busca en la web usando DDGS y devuelve el contenido extraído concatenado."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            if not results:
                return ""
            snippets = [f"Fuente: {r.get('title', '')}\nSnippet: {r.get('body', '')}" for r in results]
            return "\n\n".join(snippets)
    except Exception as e:
        logger.error(f"Error en búsqueda web para '{query}': {e}")
        return ""

def _evaluate_insight(llm, team: str, insight: str, date: str) -> dict:
    """
    Fase 1: El LLM determina si la señal es un 'Dato Duro' verificable.
    Si lo es, define el query.
    """
    prompt = f"""Eres un Agente Auditor (Night Watchman).
Tu objetivo inicial es clasificar si el siguiente insight contiene DATOS DUROS VERIFICABLES que ameriten una búsqueda en la web, o si es mera apreciación/táctica/subjetividad.

Datos puros:
- Resultados exactos de partidos recientes (ej: 3-1, ganó, perdió)
- Lesiones o sanciones concretas (ej: "operado de rodilla", "baja 3 semanas")
- Cesantías/Cambios de DT

Equipo Mencionando: {team}
Fecha Referencia: {date}
Insight a evaluar: {insight}

Si es un dato duro riesgoso, genera un QUERY corto y preciso para DuckDuckGo.
Si NO es un dato duro (ej: "Bloque bajo esperado", "Están motivados", "Buen momentum"), classifycate como skip.

Responde SOLO en JSON:
{{
  "is_verifiable_fact": true/false,
  "query": "tu query de busqueda web si es factible, null si no",
  "reason": "por qué"
}}
"""
    try:
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        if isinstance(content, list):
             content = "".join([part.get("text", "") if isinstance(part, dict) else str(part) for part in content])
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        return json.loads(content)
    except Exception as e:
        logger.warning(f"Error evaluando factibilidad: {e}")
        return {"is_verifiable_fact": False}

def _verify_and_correct(llm, team: str, insight: str, web_context: str) -> dict:
    """
    Fase 2: Cruza el insight original con los resultados de la web para detectar alucinaciones.
    """
    prompt = f"""Eres un Auditor de Veracidad (Night Watchman).
Vas a comparar una afirmación almacenada en nuestra base de datos contra el contexto web real extraído de internet.

Afirmación a auditar (Para el equipo {team}):
"{insight}"

Contexto extraído de la Web de forma reciente:
{web_context}

REGLAS:
1. Si el contexto web confirma la afirmación (o al menos no la contradice firmemente), mantén la integridad.
2. Si el contexto web demuestra que la afirmación es FALSA (ej: resultados invertidos, lesión inexistente, jugador equivocado), DEBES CORREGIRLA.

Responde SOLO en JSON:
{{
  "is_hallucination": true/false,
  "confidence_in_verdict": 0.0 to 1.0,
  "action": "keep" o "correct",
  "corrected_text": "Si action es correct, escribe el insight corregido basado en la web, y añadele al final '[CORREGIDO POR AUDITORIA WEB]'. Si es keep, envia null."
}}
"""
    try:
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        if isinstance(content, list):
             content = "".join([part.get("text", "") if isinstance(part, dict) else str(part) for part in content])
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        return json.loads(content)
    except Exception as e:
        logger.warning(f"Error verificando vs web: {e}")
        return {"is_hallucination": False, "action": "keep"}

def audit_history(target_team: str = "all", limit_per_team: int = -1, target_competition: str = None):
    history = _load_team_history()
    # Usaremos el modelo fast/general para el trigger y auditoría
    llm = get_llm()
    if not llm:
        logger.error("No se pudo instanciar LLM. Saliendo.")
        return

    if target_team == "all":
        teams_to_check = history.keys()
    elif "," in target_team:
        teams_to_check = [t.strip().lower() for t in target_team.split(",") if t.strip()]
    else:
        teams_to_check = [target_team.lower()]
    
    corrections_made = 0
    facts_checked = 0

    for team in teams_to_check:
        if team not in history:
            continue
        
        logger.info(f"=== Auditando a la sombra: {team.upper()} ===")
        all_insights = history[team]
        
        # Filtrar por competencia si se solicita
        if target_competition:
            insights_list = [item for item in all_insights if item.get("competition") == target_competition]
        else:
            insights_list = all_insights

        if not insights_list:
            continue
            
        
        # Opcional: solo auditar los más recientes
        if limit_per_team > 0:
            insights_list = insights_list[-limit_per_team:]
            
        for i, item in enumerate(insights_list):
            text = item.get("insight", "")
            date = item.get("date", "")
            
            if "[CORREGIDO POR AUDITORIA]" in text or "[AUDITADO OK]" in text or item.get("is_audited"):
                continue # Ya fue curado o verificado anteriormente
                
            # Fase 1: Es auditable?
            eval_res = _evaluate_insight(llm, team, text, date)
            
            if eval_res.get("is_verifiable_fact") and eval_res.get("query"):
                query = eval_res["query"]
                logger.info(f"  🔍 Fact detectado: '{text[:40]}...'. Buscando: {query}")
                facts_checked += 1
                
                # Fase 2: Web Search
                web_data = _search_web(query)
                
                if not web_data:
                    logger.warning("     ⚠️ Sin resultados web. Ignorando.")
                    continue
                    
                # Fase 3: Arbitraje final
                verdict = _verify_and_correct(llm, team, text, web_data)
                
                if verdict.get("is_hallucination") and verdict.get("action") == "correct" and verdict.get("corrected_text"):
                    logger.warning(f"     🚨 ALUCINACIÓN DETECTADA! Confianza: {verdict.get('confidence_in_verdict')}")
                    logger.warning(f"     Original: {text}")
                    logger.warning(f"     Corregido: {verdict.get('corrected_text')}")
                    
                    # Machacamos en memoria el objeto
                    item["insight"] = verdict.get("corrected_text")
                    corrections_made += 1
                else:
                    logger.info("     ✅ Verdadero / Mantenido.")
                    # Marcar como auditado ok para no repetir
                    item["insight"] = f"[AUDITADO OK] {text}"
                    item["is_audited"] = True
                    
    # Guardar estado final
    _save_team_history(history)
    logger.info("=================================")
    logger.info(f"Auditoría Finalizada. Hechos revisados: {facts_checked} | Correcciones: {corrections_made}")
    logger.info("=================================")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Guardia Nocturno: Web-Fact Checking de la memoria del sistema.")
    parser.add_argument("--team", type=str, default="all", help="Equipo a auditar o 'all' para todos.")
    parser.add_argument("--competition", type=str, default=None, help="Filtrar por competencia (ej: UCL, CHI1).")
    parser.add_argument("--limit", type=int, default=15, help="Cuantas señales recientes por equipo chequear (def: 15). -1 = todas.")
    args = parser.parse_args()
    
    logger.info(f"Iniciando Guardia Nocturno. Equipo: {args.team}, Competencia: {args.competition}, Límite: {args.limit}")
    audit_history(target_team=args.team, limit_per_team=args.limit, target_competition=args.competition)
