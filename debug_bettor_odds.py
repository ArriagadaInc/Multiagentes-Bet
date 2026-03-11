
import json
import logging
from agents.bettor_agent import _find_market_odds, _calculate_implied_prob

logging.basicConfig(level=logging.INFO)

def main():
    try:
        with open("pipeline_predictions.json", "r", encoding="utf-8") as f:
            predictions = json.load(f)
        with open("pipeline_odds.json", "r", encoding="utf-8") as f:
            odds = json.load(f)
    except Exception as e:
        print(f"Error loading files: {e}")
        return

    print(f"DEBUGGING ODDS EXTRACTION FOR {len(predictions)} PREDICTIONS\n")
    
    for pred in predictions:
        home = pred.get("home_team")
        away = pred.get("away_team")
        pick = pred.get("prediction")
        conf = pred.get("confidence", 0)
        
        print(f"--- Análisis: {home} vs {away} (Pick: {pick}, Conf: {conf}%) ---")
        
        market = _find_market_odds(pred, odds)
        
        if market:
            odd = market["odds"]
            implied = _calculate_implied_prob(odd)
            edge = conf - implied
            
            print(f"   >>> CUOTA ENCONTRADA: {odd} ({market['bookmaker']})")
            print(f"   >>> Implied Prob: {implied:.1f}%")
            print(f"   >>> EDGE: {edge:.1f}%")
            
            if edge >= 5.0 and conf >= 60:
                 print("   ✅ cumple criterios de VALUE BET")
            else:
                 print(f"   ❌ NO value (Edge < 5% o Conf < 60%)")
        else:
            print("   ⚠️ NO SE ENCONTRÓ CUOTA (Fallo en matching de outcome)")
            # Intentar diagnósticar outcomes disponibles
            # Replicar búsqueda de evento para mostrar sus outcomes
            from agents.bettor_agent import normalizer
            pred_home = home
            pred_away = away
            found_ev = None
            for ev in odds:
                if normalizer.find_match(pred_home, [ev["home_team"]], 0.6) and normalizer.find_match(pred_away, [ev["away_team"]], 0.6):
                    found_ev = ev
                    break
            
            if found_ev:
                print(f"      Evento Odds: '{found_ev['home_team']}' vs '{found_ev['away_team']}'")
                print("      Outcomes disponibles en Bookmakers:")
                for bk in found_ev.get("bookmakers", [])[:3]: # Solo primeros 3
                     for mkt in bk.get("markets", []):
                         if mkt["key"] == "h2h":
                             out_names = [o["name"] for o in mkt["outcomes"]]
                             print(f"        - {bk['title']}: {out_names}")

            
        print("")

if __name__ == "__main__":
    main()
