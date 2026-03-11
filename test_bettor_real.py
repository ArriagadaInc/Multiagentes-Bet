
import json
import logging
from agents.bettor_agent import bettor_agent_node
from state import AgentState

logging.basicConfig(level=logging.INFO)

def main():
    # Cargar datos previos
    try:
        with open("pipeline_predictions.json", "r", encoding="utf-8") as f:
            predictions = json.load(f)
        with open("pipeline_odds.json", "r", encoding="utf-8") as f:
            odds = json.load(f)
    except FileNotFoundError:
        print("No se encontraron archivos de pipeline previos. Ejecuta run_pipeline.py primero.")
        return

    # Mock state
    state = AgentState(
        predictions=predictions,
        odds_canonical=odds,
        betting_tips=[]
    )

    print(f"Cargadas {len(predictions)} predicciones y {len(odds)} eventos de odds.")

    # Ejecutar nodo
    new_state = bettor_agent_node(state)
    
    tips = new_state.get("betting_tips", [])
    print(f"\nGenerados {len(tips)} tips de apuesta.")
    
    for tip in tips:
        if tip.get("type") == "value_bet":
            print(f"✅ VALUE BET: {tip['match']} ({tip['pick']}) @ {tip['odds']} (Edge: {tip['edge_pct']}%)")
        else:
            print(f"🔗 COMBO: {tip['type']} @ {tip['total_odds']}")

if __name__ == "__main__":
    main()
