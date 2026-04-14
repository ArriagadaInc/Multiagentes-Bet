import json
import os
import re

HISTORY_FILE = "predictions/predictions_history.json"

def deep_clean():
    if not os.path.exists(HISTORY_FILE):
        print(f"Error: {HISTORY_FILE} no encontrado.")
        return

    print(f"Iniciando limpieza profunda de {HISTORY_FILE}...")
    
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        history = json.load(f)

    # 1. Saneamiento inicial (Ligas y Fechas)
    for p in history:
        pid = str(p.get("prediction_id", ""))
        
        # Saneamiento de Liga (competition)
        if not p.get("competition") or p.get("competition") == "None":
            if pid.startswith("UCL_"): p["competition"] = "UCL"
            elif pid.startswith("CHI1_"): p["competition"] = "CHI1"
            elif pid.startswith("CHI2_"): p["competition"] = "CHI2"
        
        # Saneamiento de Fecha (match_date)
        if not p.get("match_date") or str(p.get("match_date")).lower() in ["none", "null", ""]:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", pid)
            if m:
                p["match_date"] = f"{m.group(1)}T00:00:00Z"

    # 2. Deduplicación por Calidad
    # Usaremos una llave: (Liga, Local, Visita, Fecha_limpia)
    # Si hay 2, preferimos el que NO tenga '?' en el ID y tenga status != 'NO_DATE'
    unique_data = {}
    
    for p in history:
        comp = p.get("competition", "unknown")
        home = str(p.get("home_team", "")).lower().strip()
        away = str(p.get("away_team", "")).lower().strip()
        date_raw = str(p.get("match_date", "unknown"))[:10]
        
        # Filtro de basura obvia
        pid = str(p.get("prediction_id", ""))
        if "?" in pid and len(history) > 50: # Solo borrar si parece un ID corrupto
             # Si ya tenemos uno bueno para este partido, ignoramos este rotos
             pass 

        key = (comp, home, away, date_raw)
        
        if key not in unique_data:
            unique_data[key] = p
        else:
            existing = unique_data[key]
            # Cruce de calidad:
            # - ¿Cuál tiene ID válido? (sin '?')
            # - ¿Cuál tiene evaluación realizada?
            current_is_valid = "?" not in str(p.get("prediction_id"))
            existing_is_valid = "?" not in str(existing.get("prediction_id"))
            
            if current_is_valid and not existing_is_valid:
                unique_data[key] = p
            elif current_is_valid == existing_is_valid:
                # Si ambos son del mismo tipo, preferimos el que tenga más campos
                if len(str(p)) > len(str(existing)):
                    unique_data[key] = p

    new_history = list(unique_data.values())
    
    # 3. Purga final de IDs corruptos residuales
    # Solo eliminar si el usuario explícitamente tiene una alternativa o si están rotos (NO_DATE)
    final_history = [p for p in new_history if "?" not in str(p.get("prediction_id"))]
    
    removed = len(history) - len(final_history)
    
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(final_history, f, indent=2, ensure_ascii=False)
    
    print(f"Limpieza profunda completada.")
    print(f"Registros iniciales: {len(history)}")
    print(f"Registros finales: {len(final_history)}")
    print(f"Eliminados (Basura/Duplicados): {removed}")

if __name__ == "__main__":
    deep_clean()
