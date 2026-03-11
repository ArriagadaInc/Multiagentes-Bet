
import json
import logging
import os
from dotenv import load_dotenv
load_dotenv()

from agents.odds_agent import odds_fetcher_node
from state import AgentState

# Setup básico
logging.basicConfig(level=logging.INFO)

# Estado mínimo
state = AgentState(
    competitions=[{"competition": "UCL"}],
    odds_canonical=[],
    odds_raw={},
    meta={"errors": {}, "cache_hits": {}},
    messages=[]
)

# Ejecutar nodo
print(">>> Ejecutando Odds Fetcher tras el fix...")
new_state = odds_fetcher_node(state)

# Analizar resultados
odds = new_state.get("odds_canonical", [])
print(f"\nRecuperados {len(odds)} eventos.")

inter_ev = None
real_ev = None

# Buscar Inter y Real Madrid
for ev in odds:
    h = ev.get("home_team", "")
    a = ev.get("away_team", "")
    
    if "Inter" in h:
        inter_ev = ev
    if "Real Madrid" in h:
        real_ev = ev

print("\n--- RESULTADOS VERIFICACIÓN ---")

if inter_ev:
    print(f"✅ Inter encontrado: {inter_ev['home_team']} vs {inter_ev['away_team']}")
    # Tomar primer bookmaker
    if inter_ev["bookmakers"]:
        bk = inter_ev["bookmakers"][0]
        h_odd = bk.get("home_odds")
        print(f"   Cuota Local (Inter): {h_odd}")
        
        if h_odd < 2.0:
            print("   🎉 RECTIFICADO: Cuota lógica para favorito local (< 2.0)")
        else:
            print("   ⚠️ AÚN PROBABLEMENTE INVERTIDO: Cuota alta para favorito local")
else:
    print("❌ Inter no encontrado en resultados.")

if real_ev:
    print(f"\n✅ Real Madrid encontrado: {real_ev['home_team']} vs {real_ev['away_team']}")
    if real_ev["bookmakers"]:
        bk = real_ev["bookmakers"][0]
        h_odd = bk.get("home_odds")
        print(f"   Cuota Local (Real Madrid): {h_odd}")
        
        if h_odd > 5.0: 
             print("   ⚠️ AÚN INVERTIDO (Real Madrid debería pagar poco)")
        else:
             print("   🎉 RECTIFICADO: Cuota lógica.")
