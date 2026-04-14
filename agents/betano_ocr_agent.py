"""
Betano OCR Agent

Lectura estructurada de capturas de cuotas pre-match 1X2 de Betano.
Se mantiene separado del flujo de cuotas manuales genérico para poder
pedir una extracción más disciplinada y luego optimizar bankroll.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from agents.manual_odds_agent import (
    ManualOddsExtraction,
    _extract_json_candidate,
    _image_to_data_url,
    _make_client,
    save_uploaded_manual_odds_image,
)

BETANO_OCR_MODEL = "gpt-4o"


def save_uploaded_betano_image(file_name: str, file_bytes: bytes) -> str:
    return save_uploaded_manual_odds_image(file_name=file_name, file_bytes=file_bytes)


def extract_betano_odds_from_image(image_path: str, competition_hint: Optional[str] = None) -> dict[str, Any]:
    """
    Extrae cuotas 1X2 visibles en una captura de Betano.

    La salida mantiene el mismo shape base de las cuotas manuales:
    competition/bookmaker/market_name/matches[]
    """
    client = _make_client()
    data_url = _image_to_data_url(image_path)

    prompt = f"""
Extrae SOLO cuotas pre-match 1X2 desde esta captura de Betano.

Reglas:
- Devuelve JSON válido, sin markdown.
- La casa debe quedar como "Betano" salvo que la imagen contradiga eso.
- Interpreta columnas Local/Empate/Visita o equivalentes 1/X/2.
- Si la captura muestra fecha u hora, consérvalas.
- Ignora mercados que no sean resultado final 1X2.
- No inventes partidos, cuotas ni fechas.
- Si una fila es ilegible o parcial, omítela.
- Si la competencia es visible, extráela; si no, usa el hint.

Hint de competencia: {competition_hint or "desconocida"}

Responde con este schema exacto:
{{
  "competition": "COPA",
  "bookmaker": "Betano",
  "market_name": "Resultado Final",
  "extraction_confidence": 0.0,
  "notes": "breve",
  "matches": [
    {{
      "match_date": "2026-04-15",
      "match_time": "19:00",
      "home_team": "CA Boca Juniors",
      "away_team": "Barcelona SC",
      "home": 1.62,
      "draw": 3.70,
      "away": 5.80,
      "confidence": 0.95,
      "raw_text": "Boca Juniors vs Barcelona SC 1.62 3.70 5.80"
    }}
  ]
}}
""".strip()

    response = client.responses.create(
        model=BETANO_OCR_MODEL,
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
    payload = parsed.model_dump()
    payload["bookmaker"] = "Betano"
    payload["competition"] = payload.get("competition") or competition_hint
    payload["market_name"] = payload.get("market_name") or "Resultado Final"

    return {
        "ok": True,
        "model": BETANO_OCR_MODEL,
        "image_path": image_path,
        "raw_text": raw_text,
        "data": payload,
    }
