"""
Manual Odds Agent

Objetivo:
- Permitir una vÃ­a manual y trazable para cargar cuotas de mercado desde una imagen.
- Pensado como contingencia para torneos con baja cobertura API/web (ej. CHI2).
- La salida se persiste y luego se fusiona a odds_canonical en el pipeline normal.

Regla de diseÃ±o:
- No bypass del pipeline.
- No llegan partidos al analista sin cuotas.
- Las cuotas manuales deben terminar convertidas a odds_canonical.
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
import re
import uuid
import hashlib
from datetime import datetime, timedelta
from typing import Any, Optional

from pydantic import BaseModel, Field
from dotenv import load_dotenv

from utils.normalizer import TeamNormalizer, slugify

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore


logger = logging.getLogger(__name__)

MANUAL_ODDS_STORE = "pipeline_manual_odds.json"
MANUAL_ODDS_UPLOAD_DIR = "data/manual_odds_uploads"
DEFAULT_MANUAL_ODDS_MODEL = os.getenv("MANUAL_ODDS_MODEL", "gpt-4o")
MANUAL_ODDS_MAX_AGE_DAYS = int(os.getenv("MANUAL_ODDS_MAX_AGE_DAYS", "7"))


class ManualOddsRow(BaseModel):
    match_date: Optional[str] = Field(None, description="YYYY-MM-DD")
    match_time: Optional[str] = Field(None, description="HH:MM")
    home_team: str
    away_team: str
    home: float
    draw: float
    away: float
    confidence: float = 0.0
    raw_text: Optional[str] = None


class ManualOddsExtraction(BaseModel):
    competition: Optional[str] = None
    bookmaker: Optional[str] = None
    market_name: Optional[str] = None
    extraction_confidence: float = 0.0
    notes: Optional[str] = None
    matches: list[ManualOddsRow] = Field(default_factory=list)


def _extract_json_candidate(text: str) -> str:
    """Extrae el primer bloque JSON plausible desde la salida del modelo."""
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"```$", "", raw).strip()
    m = re.search(r"\{[\s\S]*\}", raw)
    return m.group(0) if m else raw


def _make_client():
    # Respaldo defensivo: si el proceso actual no cargó .env, lo hacemos aquí.
    load_dotenv(".env")
    if OpenAI is None:
        raise RuntimeError("OpenAI SDK no disponible.")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY no configurada.")
    return OpenAI(api_key=api_key)


def _image_to_data_url(image_path: str) -> str:
    mime = mimetypes.guess_type(image_path)[0] or "image/png"
    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def save_uploaded_manual_odds_image(file_name: str, file_bytes: bytes) -> str:
    """Persiste la imagen subida por el usuario para trazabilidad y reproceso."""
    os.makedirs(MANUAL_ODDS_UPLOAD_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", file_name or "manual_odds.png")
    out_path = os.path.join(MANUAL_ODDS_UPLOAD_DIR, f"{timestamp}_{safe_name}")
    with open(out_path, "wb") as f:
        f.write(file_bytes)
    return out_path


def extract_manual_odds_from_image(image_path: str, competition_hint: Optional[str] = None) -> dict[str, Any]:
    """
    Usa un modelo multimodal para leer cuotas 1X2 desde una captura.

    La salida es estructurada para que luego el usuario la revise en UI
    antes de inyectarla al pipeline.
    """
    started_at = datetime.now().isoformat()
    client = _make_client()
    model = DEFAULT_MANUAL_ODDS_MODEL
    data_url = _image_to_data_url(image_path)

    prompt = f"""
Extrae SOLO cuotas pre-match 1X2 desde esta captura de apuestas deportivas.

Reglas:
- Devuelve JSON vÃ¡lido, sin markdown.
- Interpreta columnas L/E/V como Local/Empate/Visitante.
- Si la captura muestra un torneo, extrae ese torneo.
- Si ves varias fechas, conserva la fecha correcta de cada fila.
- Ignora menÃºs, sidebar, badges irrelevantes y mercados que no sean 1X2.
- Si hay dudas menores de OCR, prioriza coherencia visual del layout.
- No inventes partidos ni cuotas.
- Si un valor no es legible, omite esa fila.

Hint de competencia: {competition_hint or "desconocida"}

Responde con este schema exacto:
{{
  "competition": "CHI2",
  "bookmaker": "Xperto",
  "market_name": "Resultado Final del Partido",
  "extraction_confidence": 0.0,
  "notes": "breve",
  "matches": [
    {{
      "match_date": "2026-04-12",
      "match_time": "12:30",
      "home_team": "Deportes CopiapÃ³",
      "away_team": "Deportes Recoleta",
      "home": 1.70,
      "draw": 2.55,
      "away": 3.15,
      "confidence": 0.95,
      "raw_text": "Deportes CopiapÃ³ vs Deportes Recoleta 1.70 2.55 3.15"
    }}
  ]
}}
""".strip()

    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": data_url},
                ],
            }
        ],
        max_output_tokens=2500,
    )

    raw_text = getattr(response, "output_text", "") or str(response)
    parsed_json = json.loads(_extract_json_candidate(raw_text))
    parsed = ManualOddsExtraction.model_validate(parsed_json)

    return {
        "ok": True,
        "started_at": started_at,
        "completed_at": datetime.now().isoformat(),
        "model": model,
        "image_path": image_path,
        "data": parsed.model_dump(),
        "raw_text": raw_text,
    }


def load_manual_odds_store() -> dict[str, Any]:
    if os.path.exists(MANUAL_ODDS_STORE):
        try:
            with open(MANUAL_ODDS_STORE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    data.setdefault("entries", [])
                    return data
        except Exception as e:
            logger.warning("No se pudo leer manual odds store: %s", e)
    return {"generated_at": datetime.now().isoformat(), "entries": []}


def save_manual_odds_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Agrega una captura ya revisada al store persistente, evitando duplicados."""
    store = load_manual_odds_store()
    entry = dict(entry)
    fingerprint_payload = {
        "competition": entry.get("competition"),
        "bookmaker": entry.get("bookmaker"),
        "market_name": entry.get("market_name"),
        "source_image_name": entry.get("source_image_name"),
        "source_image_path": entry.get("source_image_path"),
        "matches": entry.get("matches") or [],
    }
    fingerprint = hashlib.md5(
        json.dumps(fingerprint_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    for existing in store.get("entries", []):
        if existing.get("fingerprint") == fingerprint:
            return existing

    entry.setdefault("entry_id", str(uuid.uuid4()))
    entry.setdefault("captured_at", datetime.now().isoformat())
    entry.setdefault("source_type", "manual_ocr")
    entry.setdefault("fingerprint", fingerprint)
    store["entries"].append(entry)
    store["generated_at"] = datetime.now().isoformat()
    with open(MANUAL_ODDS_STORE, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2, ensure_ascii=False)
    return entry


def clear_manual_odds_store() -> None:
    with open(MANUAL_ODDS_STORE, "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now().isoformat(), "entries": []}, f, indent=2, ensure_ascii=False)


def _is_entry_recent(entry: dict[str, Any]) -> bool:
    captured_at = str(entry.get("captured_at") or "").strip()
    if not captured_at:
        return False
    try:
        dt = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except Exception:
        return False
    return dt >= datetime.now(dt.tzinfo) - timedelta(days=MANUAL_ODDS_MAX_AGE_DAYS)


def _find_fixture_match(row: dict[str, Any], fixtures: list[dict[str, Any]], competition: str) -> Optional[dict[str, Any]]:
    normalizer = TeamNormalizer()
    row_home = str(row.get("home_team") or "").strip()
    row_away = str(row.get("away_team") or "").strip()
    row_date = str(row.get("match_date") or "").strip()
    if not row_home or not row_away:
        return None

    candidates = [f for f in fixtures if str(f.get("competition") or "").upper() == competition.upper()]
    if not candidates:
        return None

    fixture_homes = [str(f.get("home_team") or "") for f in candidates]
    fixture_aways = [str(f.get("away_team") or "") for f in candidates]
    matched_home = normalizer.find_match(row_home, fixture_homes, threshold=0.7)
    matched_away = normalizer.find_match(row_away, fixture_aways, threshold=0.7)
    if not matched_home or not matched_away:
        return None

    for fix in candidates:
        fix_home = str(fix.get("home_team") or "")
        fix_away = str(fix.get("away_team") or "")
        if fix_home != matched_home or fix_away != matched_away:
            continue
        fix_date = str(fix.get("utc_date") or "")[:10]
        if row_date and fix_date and row_date != fix_date:
            continue
        return fix

    return None


def build_manual_odds_for_fixtures(
    fixtures: list[dict[str, Any]],
    existing_odds: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Convierte cuotas manuales persistidas en odds_canonical para la corrida actual.

    Retorna:
    - lista de nuevas odds canÃ³nicas
    - auditorÃ­a de matching/descartes
    """
    store = load_manual_odds_store()
    entries = store.get("entries") or []
    audits: list[dict[str, Any]] = []
    new_odds: list[dict[str, Any]] = []

    existing_keys = {
        f"{str(o.get('home_team') or '').lower()} vs {str(o.get('away_team') or '').lower()}"
        for o in (existing_odds or [])
    }

    for entry in entries:
        if not _is_entry_recent(entry):
            audits.append({
                "entry_id": entry.get("entry_id"),
                "status": "stale_entry",
                "competition": entry.get("competition"),
                "captured_at": entry.get("captured_at"),
            })
            continue

        competition = str(entry.get("competition") or "").upper()
        matches = entry.get("matches") or []
        for row in matches:
            fixture = _find_fixture_match(row, fixtures, competition)
            if not fixture:
                audits.append({
                    "entry_id": entry.get("entry_id"),
                    "status": "no_fixture_match",
                    "competition": competition,
                    "home_team": row.get("home_team"),
                    "away_team": row.get("away_team"),
                    "match_date": row.get("match_date"),
                })
                continue

            match_key = f"{str(fixture.get('home_team') or '').lower()} vs {str(fixture.get('away_team') or '').lower()}"
            if match_key in existing_keys:
                audits.append({
                    "entry_id": entry.get("entry_id"),
                    "status": "already_present",
                    "competition": competition,
                    "home_team": fixture.get("home_team"),
                    "away_team": fixture.get("away_team"),
                })
                continue

            canonical = {
                "competition": competition,
                "match_id": fixture.get("fixture_id", f"manual_{slugify(str(row.get('home_team')))}_{slugify(str(row.get('away_team')))}"),
                "home_team": fixture.get("home_team"),
                "away_team": fixture.get("away_team"),
                "home": float(row["home"]),
                "draw": float(row["draw"]),
                "away": float(row["away"]),
                "provider": entry.get("bookmaker") or "manual_ocr",
                "odds_source_type": "manual_ocr",
                "source_url": entry.get("source_image_path") or entry.get("source_image_name") or "manual_image",
                "captured_at": entry.get("captured_at"),
                "extraction_method": "manual_image_ocr_reviewed",
                "extraction_confidence": min(
                    float(entry.get("extraction_confidence") or 0.0),
                    float(row.get("confidence") or 0.0),
                ) if row.get("confidence") is not None else float(entry.get("extraction_confidence") or 0.0),
                "market_data_quality": "manual_reviewed",
                "timestamp": entry.get("captured_at"),
                "bookmakers_count": 1,
                "bookmakers": [
                    {
                        "key": entry.get("bookmaker") or "manual_ocr",
                        "title": entry.get("bookmaker") or "Manual OCR",
                        "home_odds": float(row["home"]),
                        "draw_odds": float(row["draw"]),
                        "away_odds": float(row["away"]),
                    }
                ],
            }
            new_odds.append(canonical)
            existing_keys.add(match_key)
            audits.append({
                "entry_id": entry.get("entry_id"),
                "status": "merged_into_pipeline",
                "competition": competition,
                "home_team": fixture.get("home_team"),
                "away_team": fixture.get("away_team"),
                "provider": canonical["provider"],
                "captured_at": canonical["captured_at"],
            })

    return new_odds, audits


def get_recent_manual_match_keys(competition: Optional[str] = None) -> set[str]:
    """
    Retorna un conjunto de match keys normalizadas desde el store manual reciente.

    Formato:
      COMP:home_slug:away_slug

    Se usa para acotar el universo del pipeline cuando el usuario ya cargó
    explícitamente una boleta/captura de cuotas por UI.
    """
    store = load_manual_odds_store()
    normalizer = TeamNormalizer()
    keys: set[str] = set()
    comp_filter = (competition or "").upper().strip()

    for entry in store.get("entries") or []:
        if not _is_entry_recent(entry):
            continue
        comp = str(entry.get("competition") or "").upper().strip()
        if comp_filter and comp != comp_filter:
            continue
        for row in entry.get("matches") or []:
            home = normalizer.clean(str(row.get("home_team") or "").strip())
            away = normalizer.clean(str(row.get("away_team") or "").strip())
            if not home or not away:
                continue
            keys.add(f"{comp}:{home}:{away}")
    return keys
