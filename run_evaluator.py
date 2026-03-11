import logging
import os

from agents.evaluator_agent import ResultEvaluator


def main():
    print("=" * 60)
    print("INICIANDO EVALUACION DE PREDICCIONES (ESPN API)")
    print("=" * 60)

    # Asegurar que el directorio de predicciones existe
    os.makedirs("predictions", exist_ok=True)

    # Configurar logging para ver progreso del matching/evaluacion
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    evaluator = ResultEvaluator()
    evaluator.evaluate_all()

    # ASCII-only para evitar UnicodeEncodeError en terminal Windows (cp1252)
    print("OK - Evaluacion finalizada. Reporte generado en predictions/evaluation_summary.json")


if __name__ == "__main__":
    main()
