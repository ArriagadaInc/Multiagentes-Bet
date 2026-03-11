"""
Runner standalone para Analyst Web Check.

Uso típico:
python run_analyst_web_check.py `
  --competition CHI1 `
  --home "Colo Colo" `
  --away "Universidad de Chile" `
  --match-id "CHI1_2026-03-01_colo-colo_universidad-de-chile" `
  --question "Confirmar estado de Lucas Assadi (lesión, tiempo de baja)" `
  --question "Confirmar si Octavio Rivero sigue en duda"
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from agents.analyst_web_check import run_analyst_web_check


def _setup_logging(verbose: bool = True) -> None:
    """Configura logging simple para pruebas locales."""
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    )


def _parse_args() -> argparse.Namespace:
    """Parámetros CLI del runner standalone."""
    parser = argparse.ArgumentParser(description="Ejecuta una verificación web puntual para el analista.")
    parser.add_argument("--match-id", default="", help="Match ID canónico (opcional pero recomendado).")
    parser.add_argument("--competition", default="", help="Competencia (ej. CHI1, UCL).")
    parser.add_argument("--home", default="", help="Equipo local.")
    parser.add_argument("--away", default="", help="Equipo visitante.")
    parser.add_argument("--question", action="append", default=[], help="Pregunta puntual a verificar (repetible, max 3).")
    parser.add_argument("--lookback-days", type=int, default=7, help="Ventana temporal en días (default 7).")
    parser.add_argument("--trigger-reason", default="manual_test", help="Motivo del trigger (auditoría).")
    parser.add_argument("--output", default="analyst_web_check_output.json", help="Archivo JSON de salida.")
    parser.add_argument("--context-file", default="", help="JSON opcional con contexto previo (`source_context`).")
    parser.add_argument("--quiet", action="store_true", help="Reduce logging.")
    return parser.parse_args()


def _load_context_file(path_str: str) -> dict[str, Any]:
    """Carga contexto JSON opcional para orientar el web-check."""
    if not path_str:
        return {}
    p = Path(path_str)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def main() -> int:
    args = _parse_args()
    _setup_logging(verbose=not args.quiet)
    logger = logging.getLogger(__name__)
    logger.info("ANALYST WEB CHECK RUNNER: iniciando")

    request = {
        "match_id": args.match_id,
        "competition": args.competition,
        "home_team": args.home,
        "away_team": args.away,
        "lookback_days": args.lookback_days,
        "questions": args.question[:3],
        "trigger_reason": args.trigger_reason,
        "source_context": _load_context_file(args.context_file),
    }

    result = run_analyst_web_check(request)

    out_path = Path(args.output)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Salida guardada en %s", out_path)

    # Resumen rápido en consola para debugging.
    print("=" * 80)
    print("RESULTADO ANALYST WEB CHECK")
    print("=" * 80)
    print(f"OK: {result.get('ok')}")
    if result.get("error"):
        print(f"Error: {result.get('error')}")
    data = result.get("data") or {}
    checks = data.get("checks") or []
    print(f"Checks: {len(checks)}")
    for i, chk in enumerate(checks[:3], start=1):
        print(f"{i}. {chk.get('status')} - {chk.get('question')}")
        print(f"   {chk.get('answer_summary')}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

