import json
import os

HISTORY_FILE = r"c:\desarrollos\apuestas\Futbol\data\knowledge\team_history.json"

def cleanup_history():
    if not os.path.exists(HISTORY_FILE):
        print("File not found")
        return

    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Identificar claves
    provincial_key = "provincial curico unido"
    canonical_key = "curicó unido"
    fallback_key = "curico unido"

    # Obtener entradas de Provincial
    provincial_entries = data.pop(provincial_key, [])
    fallback_entries = data.pop(fallback_key, [])
    
    # Asegurar que canonical_key existe
    if canonical_key not in data:
        data[canonical_key] = []
    
    # Fusionar sin duplicados exactos
    seen_insights = {json.dumps(e, sort_keys=True) for e in data[canonical_key]}
    
    for entry in provincial_entries + fallback_entries:
        entry_s = json.dumps(entry, sort_keys=True)
        if entry_s not in seen_insights:
            data[canonical_key].append(entry)
            seen_insights.add(entry_s)

    # Ordenar por fecha si es posible
    try:
        data[canonical_key].sort(key=lambda x: x.get("date", "0000-00-00"))
    except:
        pass

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"Saneamiento completado: {len(provincial_entries)} entradas de 'provincial' y {len(fallback_entries)} de 'fallback' migradas a '{canonical_key}'.")

if __name__ == "__main__":
    cleanup_history()
