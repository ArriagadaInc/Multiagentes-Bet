import json
import os
import glob
from datetime import datetime

PREDS_DIR = "predictions"
HISTORY_FILE = os.path.join(PREDS_DIR, "predictions_history.json")

def consolidate():
    print("Iniciando consolidación de historial...")
    
    # 1. Cargar el historial actual
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            try:
                history = json.load(f)
            except:
                history = []
    else:
        history = []
    
    # Crear set de IDs existentes para evitar duplicados
    existing_ids = {p.get("prediction_id") for p in history if p.get("prediction_id")}
    print(f"Historial actual tiene {len(history)} registros.")
    
    # 2. Buscar archivos diarios (YYYY-MM-DD.json)
    daily_files = glob.glob(os.path.join(PREDS_DIR, "202*-*-*.json"))
    
    added_count = 0
    for file_path in daily_files:
        # Saltar archivos que no sean el formato exacto de fecha si los hay
        base = os.path.basename(file_path)
        if not base.startswith("202"): continue
        
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                daily_preds = json.load(f)
                if not isinstance(daily_preds, list):
                    continue
            except:
                continue
            
            for p in daily_preds:
                pid = p.get("prediction_id")
                if pid and pid not in existing_ids:
                    # Asegurar campos mínimos si faltan
                    if "match_date" not in p and "generated_at" in p:
                        p["match_date"] = p["generated_at"]
                    
                    history.append(p)
                    existing_ids.add(pid)
                    added_count += 1
    
    # 3. Guardar historial consolidado
    if added_count > 0:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        print(f"Consolidación completada. Se añadieron {added_count} registros nuevos.")
    else:
        print("No se encontraron registros nuevos para añadir.")

if __name__ == "__main__":
    consolidate()
