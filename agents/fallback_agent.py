"""
Fixtures Fallback Node

Si Agente #1 no entrega fixtures para una competencia, derive fixtures a
partir de Agente #2 (odds) tomando los partidos de los próximos 7 días.

Salida: añade fixtures "odds-derived" en formato canónico al estado.
"""

from datetime import datetime, timedelta, timezone
import os
from typing import Any
import logging

from state import AgentState

logger = logging.getLogger(__name__)


def _parse_iso_utc(dt_str: str) -> datetime | None:
    try:
        if not dt_str:
            return None
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        return None


def fixtures_fallback_node(state: AgentState) -> AgentState:
    """
    Deriva fixtures desde odds (Agente #2) para competencias sin fixtures
    de Agente #1, usando ventana fija de 7 días a partir de hoy.

    Reglas:
    - Competencias objetivo: todas las listadas en state["competitions"].
    - Si count de fixtures para la competencia == 0, tomar odds de esa
      competencia con commence_time ∈ [hoy, hoy+7] y crear fixtures
      canónicos con provider="odds-derived".
    - No duplica partidos si ya existen fixtures para esa competencia.
    """
    logger.info("=" * 60)
    logger.info("FIXTURES FALLBACK: deriving from odds (7-day window)")
    logger.info("=" * 60)

    fixtures = state.get("fixtures") or []
    odds = state.get("odds_canonical") or []

    # Ventana configurable (FALLBACK_DAYS, default 7)
    try:
        fallback_days = int(os.getenv("FALLBACK_DAYS", "7"))
    except ValueError:
        fallback_days = 7
    if fallback_days < 1:
        fallback_days = 1
    if fallback_days > 60:
        fallback_days = 60

    start = datetime.now(timezone.utc).replace(microsecond=0)
    end = start + timedelta(days=fallback_days)

    # Índice rápido de fixtures existentes por competencia para evitar duplicados
    existing_by_comp: dict[str, set[tuple[str, str, str]]] = {}
    for fx in fixtures:
        comp = fx.get("competition")
        key = (fx.get("home_team", ""), fx.get("away_team", ""), fx.get("utc_date", ""))
        existing_by_comp.setdefault(comp, set()).add(key)

    # Map de competencia -> competition_code desde config
    comp_code_map = {c.get("competition"): c.get("competition_code") for c in state.get("competitions", [])}

    added_total = 0
    # Preparar meta.fallback.by_competition
    meta = state.get("meta", {})
    fb = meta.setdefault("fallback", {})
    by_comp = fb.setdefault("by_competition", {})
    for comp_cfg in state.get("competitions", []):
        comp_label = comp_cfg.get("competition")
        # Si ya hay fixtures para esta competencia, no aplicar fallback
        count = (state.get("meta", {}).get("fixtures_counts", {}) or {}).get(comp_label, 0)
        if count and count > 0:
            continue

        # Seleccionar eventos de odds de esta competencia en los próximos 7 días
        derived = []
        for ev in odds:
            if ev.get("competition") != comp_label:
                continue
            dt = _parse_iso_utc(ev.get("commence_time", ""))
            if not dt or not (start <= dt <= end):
                continue
            key = (ev.get("home_team", ""), ev.get("away_team", ""), ev.get("commence_time", ""))
            if key in existing_by_comp.get(comp_label, set()):
                continue
            fixture = {
                "competition": comp_label,
                "provider": "odds-derived",
                "competition_code": comp_code_map.get(comp_label),
                "fixture_id": f"odds:{ev.get('event_id','')}",
                "utc_date": ev.get("commence_time", ""),
                "status": "SCHEDULED",
                "matchday": None,
                "home_team": ev.get("home_team", "Unknown"),
                "away_team": ev.get("away_team", "Unknown"),
                "venue": None,
                "season": None,
            }
            derived.append(fixture)

        if derived:
            fixtures.extend(derived)
            state["meta"]["fixtures_counts"][comp_label] = len(derived)
            added_total += len(derived)
            logger.info(f"Fallback {comp_label}: {len(derived)} fixtures (odds-derived)")
            by_comp[comp_label] = {
                "used": True,
                "added_count": len(derived),
                "window_days": fallback_days
            }
        else:
            # Mantener el 0 explícito
            state["meta"]["fixtures_counts"].setdefault(comp_label, 0)
            by_comp[comp_label] = {
                "used": False,
                "added_count": 0,
                "window_days": fallback_days
            }

    if added_total:
        state["fixtures"] = fixtures
        fb["fixtures_from_odds"] = True
        fb["added_count"] = fb.get("added_count", 0) + added_total
        logger.info(f"Fallback added total fixtures: {added_total}")
    else:
        logger.info("No fallback fixtures were added")

    return state
