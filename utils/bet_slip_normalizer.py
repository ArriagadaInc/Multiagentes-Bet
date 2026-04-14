"""
Normalización de cuotas OCR/Betano contra el universo actual del pipeline.
"""

from __future__ import annotations

from typing import Any, Optional

from utils.normalizer import TeamNormalizer


normalizer = TeamNormalizer()


def _pick_odds_from_row(row: dict[str, Any], pick: str) -> Optional[float]:
    if pick == "1":
        return _safe_float(row.get("home"))
    if pick == "X":
        return _safe_float(row.get("draw"))
    if pick == "2":
        return _safe_float(row.get("away"))
    return None


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _index_match_contexts(match_contexts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    idx: dict[str, dict[str, Any]] = {}
    for mc in match_contexts or []:
        match_id = str(mc.get("match_id") or "").strip()
        if match_id:
            idx[match_id] = mc
        home = normalizer.clean(str(mc.get("home", {}).get("canonical_name") or mc.get("home_team") or "")).lower()
        away = normalizer.clean(str(mc.get("away", {}).get("canonical_name") or mc.get("away_team") or "")).lower()
        if home and away:
            idx[f"{home}_{away}"] = mc
    return idx


def _find_prediction_for_row(row: dict[str, Any], predictions: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    row_home = normalizer.clean(str(row.get("home_team") or "")).lower()
    row_away = normalizer.clean(str(row.get("away_team") or "")).lower()
    row_date = str(row.get("match_date") or "").strip()

    if not row_home or not row_away:
        return None

    exact_candidates = []
    fuzzy_candidates = []
    for pred in predictions or []:
        pred_home = normalizer.clean(str(pred.get("home_team") or "")).lower()
        pred_away = normalizer.clean(str(pred.get("away_team") or "")).lower()
        pred_date = str(pred.get("match_date") or "")[:10]
        if pred_home == row_home and pred_away == row_away:
            if row_date and pred_date and pred_date == row_date:
                return pred
            exact_candidates.append(pred)
            continue
        if normalizer.find_match(row_home, [pred_home], threshold=0.75) and normalizer.find_match(row_away, [pred_away], threshold=0.75):
            fuzzy_candidates.append(pred)

    if exact_candidates:
        return exact_candidates[0]
    if fuzzy_candidates:
        return fuzzy_candidates[0]
    return None


def normalize_betano_bets(
    ocr_payload: dict[str, Any],
    predictions: list[dict[str, Any]],
    match_contexts: list[dict[str, Any]] | None = None,
    min_ocr_confidence: float = 0.80,
) -> dict[str, Any]:
    """
    Convierte una captura OCR de cuotas en apuestas elegibles para el optimizador.

    La lógica usa el pick del analista como selección primaria.
    """
    eligible_bets: list[dict[str, Any]] = []
    rejected_bets: list[dict[str, Any]] = []
    ctx_idx = _index_match_contexts(match_contexts or [])
    bookmaker = str(ocr_payload.get("bookmaker") or "Betano").strip() or "Betano"
    competition = str(ocr_payload.get("competition") or "").strip()

    for row in (ocr_payload.get("matches") or []):
        pred = _find_prediction_for_row(row, predictions or [])
        if not pred:
            rejected_bets.append({
                "row": row,
                "reason": "prediction_not_found",
            })
            continue

        pick = str(pred.get("prediction") or "").strip().upper()
        selected_odds = _pick_odds_from_row(row, pick)
        if not selected_odds or selected_odds <= 1.0:
            rejected_bets.append({
                "row": row,
                "prediction_id": pred.get("prediction_id"),
                "reason": "selected_odds_missing_for_pick",
            })
            continue

        row_conf = _safe_float(row.get("confidence"))
        extraction_conf = _safe_float(ocr_payload.get("extraction_confidence"))
        ocr_conf = min([x for x in [row_conf, extraction_conf] if x is not None], default=0.0)
        if ocr_conf < min_ocr_confidence:
            rejected_bets.append({
                "row": row,
                "prediction_id": pred.get("prediction_id"),
                "reason": "ocr_confidence_too_low",
                "ocr_confidence": ocr_conf,
            })
            continue

        match_id = str(pred.get("prediction_id") or pred.get("match_id") or pred.get("event_id") or "").strip()
        mc = ctx_idx.get(match_id)
        if not mc:
            key = f"{normalizer.clean(str(pred.get('home_team') or '')).lower()}_{normalizer.clean(str(pred.get('away_team') or '')).lower()}"
            mc = ctx_idx.get(key)
        dq = (mc or {}).get("data_quality") or {}
        gate_status = str(dq.get("gate_status") or "clean").strip().lower()
        if gate_status == "blocked":
            rejected_bets.append({
                "row": row,
                "prediction_id": pred.get("prediction_id"),
                "reason": "gate_blocked",
            })
            continue

        missing_data = list(pred.get("missing_data") or [])
        eligible_bets.append({
            "match_id": match_id,
            "competition": competition or pred.get("competition"),
            "home_team": pred.get("home_team"),
            "away_team": pred.get("away_team"),
            "match_date": str(pred.get("match_date") or row.get("match_date") or "")[:10],
            "market_type": "1X2",
            "selection": pick,
            "odds_decimal": float(selected_odds),
            "bookmaker": bookmaker,
            "ocr_confidence": float(ocr_conf),
            "raw_row": row,
            "analyst_pick": pick,
            "analyst_confidence": float(pred.get("confidence") or 0.0),
            "analyst_probability_raw": float(pred.get("confidence") or 0.0) / 100.0,
            "gate_status": gate_status,
            "signal_risk_level": dq.get("signal_risk_level", "unknown"),
            "data_quality_flags": missing_data,
            "had_youtube_insights": not any("youtube" in str(x).lower() for x in missing_data),
            "had_espn_stats": not any("stats" in str(x).lower() for x in missing_data),
            "prediction_rationale": pred.get("rationale"),
            "score_prediction": pred.get("score_prediction"),
        })

    return {
        "competition": competition,
        "bookmaker": bookmaker,
        "eligible_bets": eligible_bets,
        "rejected_bets": rejected_bets,
    }
