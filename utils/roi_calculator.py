import json
import os
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

PREDICTIONS_HISTORY_FILE = os.path.join("predictions", "predictions_history.json")
BETS_DIR = "bets"
ROI_OUTPUT_FILE = os.path.join("predictions", "roi_simulation.json")
FIXED_STAKE = 1000  # CLP por pronóstico

def _calculate_implied_odds(prob_str: Optional[str]) -> float:
    """Calcula cuota implícita desde un string de probabilidad (ej: '57.5')."""
    if not prob_str:
        return 0.0
    try:
        # Limpiar '%' si viniera
        prob = float(prob_str.replace('%', ''))
        if prob <= 0:
            return 0.0
        return round(100 / prob, 2)
    except (ValueError, TypeError):
        return 0.0

def _get_odds_from_bets(prediction_id: str) -> Optional[float]:
    """Busca la cuota en los archivos de bets/*.json usando el prediction_id."""
    if not os.path.exists(BETS_DIR):
        return None
        
    for filename in os.listdir(BETS_DIR):
        if not filename.endswith("_bets.json"):
            continue
            
        try:
            with open(os.path.join(BETS_DIR, filename), "r", encoding="utf-8") as f:
                bets = json.load(f)
                for bet in bets:
                    # El tip_id en bets suele ser "TIP_" + prediction_id
                    if bet.get("tip_id") == f"TIP_{prediction_id}" or bet.get("tip_id") == prediction_id:
                        return bet.get("odds")
        except Exception as e:
            logger.error(f"Error leyendo {filename}: {e}")
            
    return None

def run_simulation():
    """Ejecuta la simulación de ROI sobre el historial de predicciones con análisis temporal."""
    if not os.path.exists(PREDICTIONS_HISTORY_FILE):
        logger.error(f"No existe el archivo de historial: {PREDICTIONS_HISTORY_FILE}")
        return
        
    with open(PREDICTIONS_HISTORY_FILE, "r", encoding="utf-8") as f:
        history = json.load(f)
        
    evaluated_preds = [p for p in history if p.get("evaluation_status") == "OK" and p.get("result")]
    
    # Ordenar por fecha de partido o generación
    def get_sort_date(p):
        d = p.get("match_date") or p.get("generated_at") or "2000-01-01"
        return d[:10]
        
    evaluated_preds.sort(key=get_sort_date)
    
    total_invested = 0
    total_returned = 0
    cumulative_profit = 0
    detailed_results = []
    
    # Agregaciones temporales
    by_week = {}  # "YYYY-WW": {invested, returned}
    by_month = {} # "YYYY-MM": {invested, returned}
    
    for pred in evaluated_preds:
        p_id = pred.get("prediction_id")
        is_correct = pred.get("correct", False)
        
        # Fecha para series temporales
        date_str = pred.get("match_date") or pred.get("generated_at") or ""
        date_sort = date_str[:10] if date_str else "Unknown"
        
        # 1. Intentar obtener cuota real del registro de apuestas
        odds = _get_odds_from_bets(p_id)
        
        # 2. Fallback a cuota implícita del mercado grabada por el analista
        source = "bets_registry"
        if not odds:
            odds = _calculate_implied_odds(pred.get("market_prob_used"))
            source = "implied_market"
            
        if not odds or odds <= 1.0:
            continue
            
        total_invested += FIXED_STAKE
        
        payout = 0
        if is_correct:
            payout = FIXED_STAKE * odds
            total_returned += payout
            
        profit = payout - FIXED_STAKE
        cumulative_profit += profit
        
        res = {
            "prediction_id": p_id,
            "date": date_sort,
            "match": f"{pred.get('home_team')} vs {pred.get('away_team')}",
            "prediction": pred.get("prediction"),
            "correct": is_correct,
            "odds": odds,
            "odds_source": source,
            "stake": FIXED_STAKE,
            "payout": round(payout, 2),
            "profit": round(profit, 2),
            "cumulative_profit": round(cumulative_profit, 2)
        }
        detailed_results.append(res)
        
        # Lógica de agregación
        if date_sort != "Unknown":
            try:
                dt = datetime.strptime(date_sort, "%Y-%m-%d")
                week_key = dt.strftime("%Y-W%V")
                month_key = dt.strftime("%Y-%m")
                
                for key, container in [(week_key, by_week), (month_key, by_month)]:
                    if key not in container:
                        container[key] = {"invested": 0, "returned": 0, "bets": 0, "correct": 0}
                    container[key]["invested"] += FIXED_STAKE
                    container[key]["returned"] += payout
                    container[key]["bets"] += 1
                    if is_correct:
                        container[key]["correct"] += 1
            except:
                pass

    # Post-procesar agregaciones para incluir ROI %
    def finalize_agg(container):
        for k, v in container.items():
            net = v["returned"] - v["invested"]
            v["profit"] = round(net, 2)
            v["roi_pct"] = round((net / v["invested"] * 100), 2) if v["invested"] > 0 else 0
            v["win_rate"] = round((v["correct"] / v["bets"] * 100), 2) if v["bets"] > 0 else 0
        return container

    net_profit = total_returned - total_invested
    roi = (net_profit / total_invested) * 100 if total_invested > 0 else 0
    
    simulation = {
        "summary": {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "total_bets": len(detailed_results),
            "total_correct": sum(1 for r in detailed_results if r["correct"]),
            "win_rate": round(sum(1 for r in detailed_results if r["correct"]) / len(detailed_results) * 100, 2) if detailed_results else 0,
            "fixed_stake_per_bet": FIXED_STAKE,
            "total_invested": total_invested,
            "total_returned": round(total_returned, 2),
            "net_profit": round(net_profit, 2),
            "roi_pct": round(roi, 2)
        },
        "time_series": {
            "by_week": finalize_agg(by_week),
            "by_month": finalize_agg(by_month)
        },
        "detailed_results": detailed_results
    }
    
    os.makedirs(os.path.dirname(ROI_OUTPUT_FILE), exist_ok=True)
    with open(ROI_OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(simulation, f, indent=2, ensure_ascii=False)
        
    print(f"--- Simulación de ROI (Temporal) Completa ---")
    print(f"Semanas analizadas: {len(by_week)}")
    print(f"Meses analizados: {len(by_month)}")
    print(f"ROI Global: {simulation['summary']['roi_pct']}%")
    
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_simulation()
