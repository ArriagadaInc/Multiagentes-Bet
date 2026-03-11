import json
import os
import logging
import sys

# Agregar path actual para imports locales
sys.path.append(os.getcwd())

from agents.bettor_agent import bettor_agent_node

# Configuración básica de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("run_bettor")

# Fix para emojis en Windows (forzar UTF-8 en stdout)
import io
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

def main():
    logger.info("🚀 Iniciando Agente Apostador On-Demand...")
    
    # 1. Cargar Predicciones
    preds_file = "pipeline_predictions.json"
    if not os.path.exists(preds_file):
        logger.error(f"No se encontró {preds_file}")
        print(f"❌ Error: No se encontró {preds_file}")
        return
    
    try:
        with open(preds_file, "r", encoding="utf-8") as f:
            predictions = json.load(f)
    except Exception as e:
        logger.error(f"Error al leer predicciones: {e}")
        return

    # 2. Cargar Cuotas
    odds_file = "pipeline_odds.json"
    if not os.path.exists(odds_file):
        logger.error(f"No se encontró {odds_file}")
        print(f"❌ Error: No se encontró {odds_file}")
        return

    try:
        with open(odds_file, "r", encoding="utf-8") as f:
            odds_canonical = json.load(f)
    except Exception as e:
        logger.error(f"Error al leer cuotas: {e}")
        return

    # 3. Preparar estado (AgentState es un TypedDict, pero en runtime es un dict)
    state = {
        "predictions": predictions,
        "odds_canonical": odds_canonical,
        "betting_tips": []
    }

    # 4. Ejecutar Nodo
    try:
        updated_state = bettor_agent_node(state)
        tips = updated_state.get("betting_tips", [])
        
        # 5. Guardar en pipeline_bets.json para que el dashboard lo vea
        output_file = "pipeline_bets.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(tips, f, indent=2, ensure_ascii=False)
            
        logger.info(f"✅ Éxito: Se generaron y guardaron {len(tips)} consejos de apuesta en {output_file}.")
        print(f"✅ Éxito: Se generaron {len(tips)} consejos de apuesta.")
        
    except Exception as e:
        logger.error(f"Fallo crítico en el Agente Apostador: {e}")
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
