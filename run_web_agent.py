"""
Runner standalone del Agente Web.

Uso:
    python run_web_agent.py
    python run_web_agent.py --prompt "busca..."
"""

import argparse
import io
import json
import logging
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

from agents.web_agent import DEFAULT_WEB_PROMPT, run_web_search_agent


# Force UTF-8 en Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Ejecuta el Agente Web (búsqueda web vía OpenAI Responses).")
    parser.add_argument("--prompt", default=DEFAULT_WEB_PROMPT, help="Prompt de búsqueda/panorama.")
    parser.add_argument("--output", default="web_agent_output.json", help="Archivo JSON de salida.")
    parser.add_argument("--save-raw", action="store_true", help="Guardar también texto bruto del modelo.")
    return parser.parse_args()


def main():
    load_dotenv()
    args = parse_args()

    logger.info("WEB AGENT RUNNER: iniciando")
    result = run_web_search_agent(user_prompt=args.prompt)

    # Persistir salida completa (incluye validación)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    logger.info("Salida guardada en %s", args.output)

    if args.save_raw and result.get("raw_text"):
        raw_path = os.path.splitext(args.output)[0] + ".raw.txt"
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(result["raw_text"])
        logger.info("Raw text guardado en %s", raw_path)

    print("\n" + "=" * 80)
    print("RESULTADO AGENTE WEB")
    print("=" * 80)
    print(f"OK: {result.get('ok')}")
    if result.get("error"):
        print(f"Error: {result.get('error')}")
    if result.get("validation_errors"):
        print("Validation errors:")
        for e in result["validation_errors"]:
            print(f" - {e}")

    data = result.get("data") or {}
    comps = data.get("competitions") or []
    print(f"Competencias: {len(comps)}")
    for comp in comps:
        teams = comp.get("teams") or []
        print(f" - {comp.get('competition')}: {len(teams)} equipos")
    print(f"Timestamp: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()

