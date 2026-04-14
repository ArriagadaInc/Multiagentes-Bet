"""
Analyst Web Check (standalone, no integrado todavía)

Objetivo:
- Permitir verificaciones web puntuales (on-demand) para el analista.
- Confirmar señales acotadas (lesiones, sanciones, expulsiones, castigos, dudas).
- Complementar con referencia breve de jugador/persona cuando haga falta contexto (rol/importancia).
- Devolver JSON estructurado, corto y auditable.

Diseño:
- NO reemplaza al Agente Web general.
- NO hace scouting panorámico.
- Está pensado para 1-2 preguntas muy concretas por partido.
"""

from __future__ import annotations

import json
import logging
import os
import re
import hashlib
from pydantic import BaseModel, Field
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, List

from utils.token_tracker import track_tokens
from utils.llm_factory import get_llm

try:
    from langchain_community.tools import DuckDuckGoSearchRun
    ddg_search = DuckDuckGoSearchRun()
except Exception:
    ddg_search = None

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - falla controlada en runtime si falta SDK
    OpenAI = None  # type: ignore

logger = logging.getLogger(__name__)


DEFAULT_ANALYST_WEB_CHECK_MODEL = os.getenv("ANALYST_WEB_CHECK_MODEL", "gpt-4o")
DEFAULT_ANALYST_WEB_CHECK_TOOL = os.getenv("ANALYST_WEB_CHECK_TOOL_TYPE", "web_search")

ANALYST_WEB_CHECK_CACHE_FILE = "data/cache/analyst_web_check_cache.json"
CACHE_TTL_HOURS = 12

def _get_cache_key(request: dict) -> str:
    match_id = str(request.get("match_id", "")).strip()
    questions = "|".join([str(q).strip() for q in request.get("questions", [])])
    raw = f"{match_id}::{questions}"
    return hashlib.md5(raw.encode()).hexdigest()

def _load_cache() -> dict:
    if os.path.exists(ANALYST_WEB_CHECK_CACHE_FILE):
        try:
            with open(ANALYST_WEB_CHECK_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_cache(cache: dict):
    os.makedirs(os.path.dirname(ANALYST_WEB_CHECK_CACHE_FILE), exist_ok=True)
    try:
        with open(ANALYST_WEB_CHECK_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Error guardando caché de Web Check: {e}")

def _get_check_llm():
    """Obtiene el LLM para web-check."""
    return get_llm(model_name=DEFAULT_ANALYST_WEB_CHECK_MODEL)

class ContextSignal(BaseModel):
    type: str = Field(description="injury_news|disciplinary_issue|home_venue_issue|coach_change|player_role_context|other")
    signal: str = Field(description="señal breve")
    evidence: str = Field(description="hecho resumido con contexto de rol si aplica")
    date: Optional[str] = Field(None, description="YYYY-MM-DD o null")
    confidence: float = Field(default=0.0)
    is_rumor: bool = Field(default=False)
    provenance: List[str] = Field(default_factory=lambda: ["analyst_web_check"])

class SourceInfo(BaseModel):
    title: str
    url: str
    publisher: str
    published_at: Optional[str] = Field(None, description="YYYY-MM-DD o desconocido")

class CheckResult(BaseModel):
    question: str
    status: str = Field(description="confirmed|partially_confirmed|unconfirmed|conflicting|not_found")
    answer_summary: str
    context_signals: List[ContextSignal] = Field(default_factory=list)
    sources: List[SourceInfo] = Field(default_factory=list)
    confidence: float = Field(default=0.0)

class WebCheckOutput(BaseModel):
    as_of_date: str
    match_id: str
    lookback_days: int
    trigger_reason: str
    checks: List[CheckResult] = Field(default_factory=list)


def _make_client():
    """Mantenemos por compatibilidad interna si se forza Expensive Mode."""
    if OpenAI is None: return None
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# Helper obsoleto eliminado: _response_to_text
# Helper obsoleto eliminado: _strip_markdown_fences
# Helper obsoleto eliminado: _extract_json_candidate


def _build_check_prompt(request: dict[str, Any]) -> str:
    """
    Construye prompt acotado para verificación puntual.
    La salida se fuerza a JSON estructurado con schema corto.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    match_id = str(request.get("match_id") or "").strip()
    competition = str(request.get("competition") or "").strip()
    home_team = str(request.get("home_team") or "").strip()
    away_team = str(request.get("away_team") or "").strip()
    trigger_reason = str(request.get("trigger_reason") or "").strip()
    try:
        lookback_days = max(1, int(request.get("lookback_days") or 7))
    except Exception:
        lookback_days = 7

    raw_questions = request.get("questions") or []
    questions = [str(q).strip() for q in raw_questions if str(q).strip()][:3]
    if not questions:
        questions = ["Confirmar si hay una baja, sanción o castigo relevante reciente para este partido."]

    # Contexto opcional con señales previas para focalizar la búsqueda.
    source_context = request.get("source_context") or {}
    source_context_json = json.dumps(source_context, ensure_ascii=False)[:4000]

    questions_block = "\n".join([f"- {q}" for q in questions])

    return f"""
Eres un verificador web para un analista deportivo. Tu tarea NO es hacer un panorama completo.
Tu tarea es SOLO confirmar o aclarar información puntual para un partido específico.

Fecha de referencia (UTC): {today}
Ventana temporal objetivo: últimos {lookback_days} días

PARTIDO:
- match_id: {match_id or "N/A"}
- competencia: {competition or "N/A"}
- local: {home_team or "N/A"}
- visita: {away_team or "N/A"}
- trigger_reason: {trigger_reason or "N/A"}

PREGUNTAS A VERIFICAR (máximo 3):
{questions_block}

CONTEXTO PREVIO (solo para orientar, no asumir que es verdad):
{source_context_json}

ALCANCE (muy importante):
- Prioriza confirmar lesiones, suspendidos, expulsiones, castigos, dudas médicas y sanciones.
- También puedes confirmar cambios de DT o castigos de localía SI la pregunta lo pide.
- Si la pregunta menciona un jugador/persona (ej: Assadi, Vidal), puedes buscar una referencia breve útil para pronóstico.
- No hagas scouting general de toda la competencia.
- Si no encuentras confirmación, dilo claramente.
- Si la info es rumor/no confirmada, márcala como rumor.
- Incluye fecha cuando exista.
- Usa español.
""".strip()


# Función validación obsoleta eliminada: _validate_check_output
# Función reparación LLM obsoleta eliminada: _repair_json_with_llm


def run_analyst_web_check(request: dict[str, Any]) -> dict[str, Any]:
    """
    Ejecuta una verificación web puntual y devuelve resultado estructurado.
    Este entrypoint está pensado para ser reutilizado por `analyst_agent` en el futuro.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    llm = _get_check_llm()
    if llm is None:
        return {
            "ok": False,
            "error": "LLM no disponible (revisar llm_factory).",
            "started_at": started_at,
        }
        
    cache_key = _get_cache_key(request)
    cache = _load_cache()
    
    # HIT DE CACHÉ
    if cache_key in cache:
        entry = cache[cache_key]
        saved_at = entry.get("completed_at")
        if saved_at:
            try:
                dt = datetime.fromisoformat(saved_at)
                if datetime.now(timezone.utc) - dt < timedelta(hours=CACHE_TTL_HOURS):
                    logger.info("ANALYST WEB CHECK: [HIT] Retornando de caché (key: %s)", cache_key)
                    entry["from_cache"] = True
                    return entry
            except Exception:
                pass
    model = getattr(llm, "model_name", getattr(llm, "model", DEFAULT_ANALYST_WEB_CHECK_MODEL))

    tool_type = DEFAULT_ANALYST_WEB_CHECK_TOOL
    prompt = _build_check_prompt(request)

    logger.info(
        "ANALYST WEB CHECK: iniciando verificación (model=%s, tool=%s, match_id=%s)",
        model, tool_type, request.get("match_id"),
    )

    try:
        expensive_mode = os.getenv("EXPENSIVE_MODE", "false").lower() in ("true", "1", "yes")
        
        llm_with_struct = llm.with_structured_output(WebCheckOutput)
        parsed = None
        raw_text = ""
        
        if expensive_mode and "gpt-" in str(model).lower():
            # Pasada por openai directo obsoleta para structured_output robusto, forzamos Langchain.
            logger.info("ANALYST WEB CHECK: Utilizando Langchain structured output en lugar de client bruto para %s", model)
            resp = llm_with_struct.invoke(prompt)
            if hasattr(resp, "model_dump"):
                parsed = resp.model_dump()
            elif hasattr(resp, "dict"):
                parsed = resp.dict()
            else:
                parsed = resp
        else:
            # Ruta Económica (Gemini + DDG)
            search_context = ""
            if ddg_search:
                search_context = ddg_search.run(request.get("trigger_reason", "futbol noticias"))
            
            full_prompt = f"{prompt}\n\nCONTEXTO BÚSQUEDA WEB:\n{search_context}"
            resp = llm_with_struct.invoke(full_prompt)
            if hasattr(resp, "model_dump"):
                parsed = resp.model_dump()
            elif hasattr(resp, "dict"):
                parsed = resp.dict()
            else:
                parsed = resp
            
            track_tokens(model=model, prompt_tokens=len(full_prompt)//4, completion_tokens=500)

        result = {
            "ok": True if parsed else False,
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "tool_type": tool_type,
            "data": parsed or {},
            "validation_errors": [],
            "raw_text": raw_text,
            "parse_repaired": False,
            "parse_repair_failed": False,
            "from_cache": False
        }
        
        # GUARDAR EN CACHÉ
        if result["ok"]:
            cache[cache_key] = result
            _save_cache(cache)
            logger.info("ANALYST WEB CHECK: [SAVED] Caché actualizada (key: %s)", cache_key)
            
        return result


    except Exception as e:
        logger.error("ANALYST WEB CHECK error: %s", e, exc_info=True)
        return {
            "ok": False,
            "error": str(e),
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "tool_type": tool_type,
        }


def analyst_web_check_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Nodo futuro opcional (no integrado).
    Guarda el resultado del web-check en `state["analyst_web_checks"]`.
    """
    req = state.get("analyst_web_check_request") or {}
    state["analyst_web_checks"] = run_analyst_web_check(req)
    return state
