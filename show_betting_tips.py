
import json
import os
from datetime import datetime
import glob

def main():
    # Buscar el archivo de apuestas más reciente en predictions y bets
    # run_pipeline.py guarda en pipeline_bets.json
    # bettor_agent.py guarda en bets/YYYY-MM-DD_bets.json
    
    # Priority 1: pipeline_bets.json (latest run)
    target_file = "pipeline_bets.json"
    
    if not os.path.exists(target_file):
        # Fallback to bets/ directory
        list_of_files = glob.glob('bets/*_bets.json') 
        if list_of_files:
            target_file = max(list_of_files, key=os.path.getctime)
        else:
            print("❌ No se encontraron archivos de apuestas.")
            return

    try:
        with open(target_file, "r", encoding="utf-8") as f:
            bets = json.load(f)
    except Exception as e:
        print(f"Error leyendo {target_file}: {e}")
        return

    print(f"\n💰 REPORTE DE APUESTAS ({len(bets)} tips) - Fuente: {target_file}")
    print("=" * 100)
    
    # Separar singles y combos
    singles = [b for b in bets if b.get("type") == "value_bet"]
    combos = [b for b in bets if "combo" in b.get("type", "")]

    if singles:
        print(f"\n📌 VALUE BETS SIMPLES ({len(singles)})")
        print(f"{'PARTIDO':<45} | {'PICK':<5} | {'CUOTA':<6} | {'EDGE':<6} | {'CONF':<5} | {'STAKE':<5} | {'RATIONALE'}")
        print("-" * 120)
        for s in singles:
            match = s.get("match", "")[:42]
            pick = s.get("pick", "")
            odds = s.get("odds", 0)
            edge = s.get("edge_pct", 0)
            conf = s.get("confidence", 0)
            stake = s.get("stake_units", 0)
            rationale = s.get("rationale", "")
            
            # Highlight high edge
            edge_str = f"{edge:.1f}%"
            if edge > 20:
                edge_str = f"🔥 {edge:.1f}%"
            
            print(f"{match:<45} | {pick:<5} | {odds:<6} | {edge_str:<6} | {conf:<5} | {stake:<5} | {rationale}")

    if combos:
        print(f"\n🔗 COMBINADAS SUGERIDAS ({len(combos)})")
        for i, c in enumerate(combos, 1):
            print(f"\n   #{i} {c.get('type').upper()} (Cuota Total: {c.get('total_odds')}) - Stake: {c.get('stake_units')}u")
            for leg in c.get("legs", []):
                print(f"      - {leg.get('match')} -> {leg.get('pick')} ({leg.get('odds')})")
            print(f"      📝 {c.get('rationale')}")

    print("\n" + "=" * 100)

if __name__ == "__main__":
    main()
