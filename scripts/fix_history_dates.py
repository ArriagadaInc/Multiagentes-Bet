import json
import os
import re

HISTORY_FILE = "predictions/predictions_history.json"

def fix_dates():
    if not os.path.exists(HISTORY_FILE):
        print(f"Error: {HISTORY_FILE} no encontrado.")
        return

    print(f"Saneando fechas en {HISTORY_FILE}...")
    
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        history = json.load(f)

    fixed_count = 0
    for p in history:
        date_val = p.get("match_date")
        # Si la fecha es None, "", o "null"
        if not date_val or str(date_val).lower() in ["none", "null", ""]:
            pred_id = str(p.get("prediction_id", ""))
            # Buscar patrón YYYY-MM-DD
            match = re.search(r"(\d{4}-\d{2}-\d{2})", pred_id)
            if match:
                extracted_date = match.group(1)
                p["match_date"] = f"{extracted_date}T00:00:00Z" # Formato ISO básico
                fixed_count += 1
            else:
                # Intentar con generated_at si existe
                gen_at = p.get("generated_at")
                if gen_at:
                    p["match_date"] = gen_at
                    fixed_count += 1

    if fixed_count > 0:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        print(f"Saneamiento completado. Se corrigieron {fixed_count} registros.")
    else:
        print("No se encontraron registros con fechas faltantes que pudieran repararse.")

if __name__ == "__main__":
    fix_dates()
