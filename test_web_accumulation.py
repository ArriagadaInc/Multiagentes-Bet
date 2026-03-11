
import json
import os
import sys
import logging

# Configurar logging para ver la salida del agente
logging.basicConfig(level=logging.INFO)

# Añadir el directorio actual al path para importar web_agent
sys.path.append(os.getcwd())
from agents.web_agent import _save_output, WEB_AGENT_OUTPUT_FILE

def test_accumulation():
    print("--- TEST DE ACUMULACIÓN ---")
    
    # Limpiar archivo previo si existe para empezar de cero
    if os.path.exists(WEB_AGENT_OUTPUT_FILE):
        os.remove(WEB_AGENT_OUTPUT_FILE)
    
    # Simular RUN 1: Universidad de Chile
    payload1 = {
        "generated_at": "2026-03-05T10:00:00",
        "started_at": "2026-03-05T09:59:00",
        "data": {
            "competitions": [
                {
                    "competition": "CHI1",
                    "teams": [
                        {
                            "team": "Universidad de Chile",
                            "last_result": "U. de Chile 0-1 Palestino",
                            "raw_context": "Noticia vieja"
                        }
                    ]
                }
            ]
        }
    }
    
    print("Guardando Run 1...")
    _save_output(payload1)
    
    # Simular RUN 2: Colo-Colo (debería sumarse)
    payload2 = {
        "generated_at": "2026-03-05T11:00:00",
        "started_at": "2026-03-05T10:59:00",
        "data": {
            "competitions": [
                {
                    "competition": "CHI1",
                    "teams": [
                        {
                            "team": "Colo-Colo",
                            "last_result": "Colo-Colo 2-0 Huachipato",
                            "raw_context": "Noticia nueva Colo Colo"
                        }
                    ]
                }
            ]
        }
    }
    
    print("Guardando Run 2...")
    _save_output(payload2)
    
    # Simular RUN 3: Actualizar Universidad de Chile
    payload3 = {
        "generated_at": "2026-03-05T12:00:00",
        "started_at": "2026-03-05T11:59:00",
        "data": {
            "competitions": [
                {
                    "competition": "CHI1",
                    "teams": [
                        {
                            "team": "Universidad de Chile",
                            "last_result": "U. de Chile entrena para el Superclásico",
                            "raw_context": "Noticia fresca"
                        }
                    ]
                }
            ]
        }
    }
    
    print("Guardando Run 3 (Actualización)...")
    _save_output(payload3)
    
    # Verificar resultado final
    if os.path.exists(WEB_AGENT_OUTPUT_FILE):
        with open(WEB_AGENT_OUTPUT_FILE, "r", encoding="utf-8") as f:
            final_data = json.load(f)
            
        print("\nResultado Final:")
        comps = final_data.get("data", {}).get("competitions", [])
        for c in comps:
            print(f"Liga: {c['competition']}")
            for t in c.get("teams", []):
                print(f"  - {t['team']}: {t['last_result']} | Context: {t['raw_context'][:20]}...")
        
        # Validar
        teams = {t['team'] for c in comps for t in c.get("teams", [])}
        if "Universidad de Chile" in teams and "Colo-Colo" in teams and len(teams) == 2:
            print("\n✅ TEST EXITOSO: Los equipos se acumularon y actualizaron correctamente.")
        else:
            print("\n❌ TEST FALLIDO: Error en la acumulación.")

if __name__ == "__main__":
    test_accumulation()
