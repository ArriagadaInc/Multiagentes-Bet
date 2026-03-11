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
from datetime import datetime, timezone
from typing import Any, Optional

from utils.token_tracker import track_tokens

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - falla controlada en runtime si falta SDK
    OpenAI = None  # type: ignore

logger = logging.getLogger(__name__)


DEFAULT_ANALYST_WEB_CHECK_MODEL = os.getenv("ANALYST_WEB_CHECK_MODEL", "gpt-4.1")
DEFAULT_ANALYST_WEB_CHECK_TOOL = os.getenv("ANALYST_WEB_CHECK_TOOL_TYPE", "web_search")


def _make_client() -> Optional["OpenAI"]:
    """Crea cliente OpenAI con timeout configurable."""
    if OpenAI is None:
        logger.error("openai package no disponible para analyst_web_check")
        return None
    if not os.getenv("OPENAI_API_KEY"):
        logger.error("OPENAI_API_KEY no configurada")
        return None
    try:
        timeout_s = float(os.getenv("ANALYST_WEB_CHECK_TIMEOUT_SECONDS", "60"))
    except ValueError:
        timeout_s = 60.0
    return OpenAI(timeout=timeout_s)


def _response_to_text(resp: Any) -> str:
    """
    Extrae texto de Responses API de forma defensiva.
    Soporta variantes de SDK que exponen `output_text` o `output`.
    """
    txt = getattr(resp, "output_text", None)
    if isinstance(txt, str) and txt.strip():
        return txt.strip()

    try:
        chunks: list[str] = []
        for item in (getattr(resp, "output", None) or []):
            if getattr(item, "type", None) != "message":
                continue
            for c in (getattr(item, "content", None) or []):
                if getattr(c, "type", None) in ("output_text", "text"):
                    t = getattr(c, "text", None)
                    if isinstance(t, str):
                        chunks.append(t)
        if chunks:
            return "\n".join(chunks).strip()
    except Exception:
        pass

    return str(resp)


def _strip_markdown_fences(text: str) -> str:
    """Quita fences ```json si el modelo responde con markdown."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*\n?", "", t)
        t = re.sub(r"\n?```\s*$", "", t)
    return t.strip()


def _extract_json_candidate(text: str) -> str:
    """
    Extrae el bloque JSON principal si el modelo mezcla texto y JSON.
    Esto hace el parser más resiliente sin cambiar semántica.
    """
    t = _strip_markdown_fences(text)
    i = t.find("{")
    j = t.rfind("}")
    if i != -1 and j != -1 and j > i:
        return t[i : j + 1]
    return t


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
- Si la pregunta menciona un jugador/persona (ej: Assadi, Vidal), puedes buscar una referencia breve útil para pronóstico:
  quién es, rol (goleador/arquero titular/figura/capitán/DT), y relevancia aproximada en el equipo.
- No hagas scouting general de toda la competencia.
- Si no encuentras confirmación, dilo claramente.
- Si la info es rumor/no confirmada, márcala como rumor.
- Incluye fecha cuando exista.
- Usa español.

Responde SOLO con JSON válido (sin markdown) con esta estructura:
{{
  "as_of_date": "{today}",
  "match_id": "{match_id}",
  "lookback_days": {lookback_days},
  "trigger_reason": "{trigger_reason}",
  "checks": [
    {{
      "question": "texto de la pregunta",
      "status": "confirmed|partially_confirmed|unconfirmed|conflicting|not_found",
      "answer_summary": "respuesta breve",
      "context_signals": [
        {{
          "type": "injury_news|disciplinary_issue|home_venue_issue|coach_change|player_role_context|other",
          "signal": "señal breve",
          "evidence": "hecho resumido con contexto de rol si aplica (ej: goleador, arquero titular, capitán, DT)",
          "date": "YYYY-MM-DD o null",
          "confidence": 0.0,
          "is_rumor": false,
          "provenance": ["analyst_web_check"]
        }}
      ],
      "sources": [
        {{
          "title": "título",
          "url": "https://...",
          "publisher": "medio",
          "published_at": "YYYY-MM-DD o desconocido"
        }}
      ],
      "confidence": 0.0
    }}
  ]
}}
""".strip()


def _validate_check_output(data: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Valida el contrato mínimo del analyst_web_check.
    Validación suave: tolera faltantes menores para no bloquear prototipado.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return False, ["La salida no es un objeto JSON."]

    if not isinstance(data.get("as_of_date"), str):
        errors.append("Falta `as_of_date` (string).")
    if not isinstance(data.get("checks"), list):
        errors.append("Falta `checks` (list).")
        return False, errors

    for i, chk in enumerate(data.get("checks") or []):
        if not isinstance(chk, dict):
            errors.append(f"checks[{i}] no es objeto.")
            continue
        for field in ("question", "status", "answer_summary"):
            if not isinstance(chk.get(field), str):
                errors.append(f"checks[{i}].{field} inválido.")
        if not isinstance(chk.get("context_signals"), list):
            errors.append(f"checks[{i}].context_signals debe ser lista.")
        if not isinstance(chk.get("sources"), list):
            errors.append(f"checks[{i}].sources debe ser lista.")
    return len(errors) == 0, errors


def _repair_json_with_llm(client: "OpenAI", broken_text: str) -> str:
    """
    Repara JSON malformado usando una llamada corta sin web_search.
    Se usa solo si el parser falla.
    """
    model = os.getenv("ANALYST_WEB_CHECK_REPAIR_MODEL", "gpt-4.1-mini")
    prompt = f"""
Corrige el siguiente JSON MALFORMADO para que sea JSON válido.
No cambies el significado ni inventes datos.
Responde SOLO con JSON válido.

JSON MALFORMADO:
{broken_text}
""".strip()
    resp = client.responses.create(model=model, input=prompt, max_output_tokens=3000)
    
    # Track tokens manually for direct OpenAI SDK call
    if hasattr(resp, 'usage') and resp.usage:
        track_tokens(
            model=model,
            prompt_tokens=getattr(resp.usage, 'prompt_tokens', 0),
            completion_tokens=getattr(resp.usage, 'completion_tokens', 0)
        )
    return _response_to_text(resp)


def run_analyst_web_check(request: dict[str, Any]) -> dict[str, Any]:
    """
    Ejecuta una verificación web puntual y devuelve resultado estructurado.
    Este entrypoint está pensado para ser reutilizado por `analyst_agent` en el futuro.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    client = _make_client()
    if client is None:
        return {
            "ok": False,
            "error": "OpenAI client no disponible (revisar OPENAI_API_KEY / SDK).",
            "started_at": started_at,
        }

    model = DEFAULT_ANALYST_WEB_CHECK_MODEL
    tool_type = DEFAULT_ANALYST_WEB_CHECK_TOOL
    prompt = _build_check_prompt(request)

    logger.info(
        "ANALYST WEB CHECK: iniciando verificación (model=%s, tool=%s, match_id=%s)",
        model, tool_type, request.get("match_id"),
    )

    try:
        resp = client.responses.create(
            model=model,
            input=prompt,
            tools=[{"type": tool_type}],
            max_output_tokens=5000,
        )

        # Track tokens manually for direct OpenAI SDK call
        if hasattr(resp, 'usage') and resp.usage:
            track_tokens(
                model=model,
                prompt_tokens=getattr(resp.usage, 'prompt_tokens', 0),
                completion_tokens=getattr(resp.usage, 'completion_tokens', 0)
            )
        raw_text = _response_to_text(resp)

        parsed = None
        validation_errors: list[str] = []
        try:
            parsed = json.loads(_extract_json_candidate(raw_text))
        except json.JSONDecodeError:
            logger.info("ANALYST WEB CHECK: JSON inválido, intentando reparación automática...")
            repaired = _repair_json_with_llm(client, _extract_json_candidate(raw_text))
            raw_text = raw_text + "\n\n### REPAIRED_JSON\n" + repaired
            parsed = json.loads(_extract_json_candidate(repaired))

        ok_valid, validation_errors = _validate_check_output(parsed or {})
        result = {
            "ok": bool(ok_valid),
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "tool_type": tool_type,
            "data": parsed or {},
            "validation_errors": validation_errors,
            "raw_text": raw_text,
        }
        if ok_valid:
            logger.info("ANALYST WEB CHECK: salida válida")
        else:
            logger.warning("ANALYST WEB CHECK: salida inválida (%d errores)", len(validation_errors))
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
