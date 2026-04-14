import logging
import os
import sys
import argparse

from agents.evaluator_agent import ResultEvaluator
from utils.network_env import sanitize_process_proxy_env


def main():
    parser = argparse.ArgumentParser(description="Ejecutor del Agente Revisor / Evaluador")
    parser.add_argument("--force", action="store_true", help="Forzar re-evaluación total")
    args = parser.parse_args()

    # Sanitizar entorno de red/proxy
    sanitize_process_proxy_env()
    
    # ASCII-only header para evitar problemas de codificación en terminales básicas
    print("=" * 60)
    print(f"INICIANDO EVALUACION DE PREDICCIONES (ESPN API) - [FORCE={args.force}]")
    print("=" * 60)

    # Asegurar que el directorio de predicciones existe
    os.makedirs("predictions", exist_ok=True)

    # Configurar logging para ver progreso del matching/evaluacion
    # Usamos nivel INFO por defecto para ver qué partidos se están procesando
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stdout
    )

    try:
        evaluator = ResultEvaluator()
        evaluator.evaluate_all(force=args.force)
        
        print("\n" + "=" * 60)
        print("OK - Evaluacion finalizada exitosamente.")
        print("Reporte generado en predictions/evaluation_summary.json")
        print("=" * 60)
    except Exception as e:
        print(f"\nFATAL: Error durante la ejecucion del evaluador: {e}")
        logging.exception(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
