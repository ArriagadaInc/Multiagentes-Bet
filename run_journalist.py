import os
import json
import logging
from dotenv import load_dotenv
from agents.journalist_agent import journalist_agent_node

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

import sys
import io

# Forzar UTF-8 en la salida estándar
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def main():
    # Cargar variables de entorno
    load_dotenv()
    
    # Simular estado inicial de LangGraph
    state = {
        "competitions": [
            {"competition": "CHI1"},
            {"competition": "UCL"}
        ],
        "meta": {"errors": {}}
    }
    
    # Ejecutar nodo
    logger.info("Iniciando ejecución standalone del Agente Periodista...")
    final_state = journalist_agent_node(state)
    
    # Mostrar resultados
    results = final_state.get("journalist_videos")
    if results:
        print("\n" + "="*80)
        print("RESULTADO DEL AGENTE PERIODISTA")
        print("="*80)
        print(json.dumps(results, indent=2, ensure_ascii=False))
        
        # Guardar resultado en un archivo para inspección
        output_file = "journalist_test_output.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n✓ Resultado completo guardado en: {output_file}")
    else:
        print("\n❌ El agente no devolvió resultados.")

if __name__ == "__main__":
    main()
