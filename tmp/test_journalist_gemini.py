import os
import json
from dotenv import load_dotenv

# Forzar lectura de entorno
load_dotenv()

# Setear explicitamente modo economico
os.environ["EXPENSIVE_MODE"] = "false"

def run_test():
    print("Iniciando test del Journalist Agent (Mock) usando Factory...")
    try:
        from utils.llm_factory import get_llm
        from agents.journalist_agent import _refine_candidates_with_llm
        
        # Confirmamos factory
        llm = get_llm()
        print(f"Modo Economico resuelto a: {type(llm).__name__}")
        
        # Creamos mock candidates
        mock_candidates = [
            {
                "title": "UCL TACTICAL ANALYSIS: Real Madrid vs City",
                "channel": {"title": "Tactics Pro"},
                "description_snippet": "In-depth look at Carlo Ancelotti's midfield setup and how they neutralized Haaland."
            },
            {
                "title": "I played FIFA 26 as Real Madrid",
                "channel": {"title": "Gamer123"},
                "description_snippet": "Opening packs and playing division rivals with my new UCL squad."
            },
            {
                "title": "Bellingham INJURY UPDATE before UCL clash",
                "channel": {"title": "Madrid News"},
                "description_snippet": "Medical report shows Jude will miss the next 3 weeks."
            }
        ]
        
        print(f"\nEvaluando {len(mock_candidates)} candidatos con el LLM...")
        result = _refine_candidates_with_llm(mock_candidates, "UCL")
        
        print("\n--- RESULTADOS ---")
        for res in result:
            print(f"- MANTENIDO: {res['title']}")
            
        print("\nPrueba finalizada excitósamente")
        
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    run_test()
