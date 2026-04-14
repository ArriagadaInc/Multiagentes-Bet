"""
Script de Auditoría y Limpieza de duplicados en team_history.json.
Uso: python scripts/audit_team_history.py --threshold 0.8
"""

import json
import os
import argparse
import unicodedata
import re
from difflib import SequenceMatcher

def normalize_text(text):
    if not text:
        return ""
    # Remover acentos y pasar a minúsculas
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii').lower()
    # Remover puntuación y espacios múltiples
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()

def audit_and_clean(file_path, threshold=0.8):
    if not os.path.exists(file_path):
        print(f"Error: No se encuentra {file_path}")
        return

    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    total_before = 0
    total_after = 0
    teams_affected = 0

    cleaned_data = {}

    for team, entries in data.items():
        if not isinstance(entries, list):
            cleaned_data[team] = entries
            continue

        total_before += len(entries)
        unique_entries = []
        
        # Procesar de más reciente a más antiguo (reversa)
        # para mantener siempre la versión más nueva de una información
        for entry in reversed(entries):
            text = normalize_text(entry.get("insight", ""))
            if not text:
                continue
            
            is_duplicate = False
            for existing in unique_entries:
                existing_text = normalize_text(existing.get("insight", ""))
                
                # Check exacto primero
                if text == existing_text:
                    is_duplicate = True
                    break
                
                # Check fuzzy si superamos el threshold
                if similarity(text, existing_text) >= threshold:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                unique_entries.append(entry)

        # Volver al orden original (cronológico)
        unique_entries.reverse()
        cleaned_data[team] = unique_entries
        total_after += len(unique_entries)
        
        if len(unique_entries) < len(entries):
            teams_affected += 1
            print(f"  - {team}: {len(entries)} -> {len(unique_entries)} (limpiados {len(entries) - len(unique_entries)})")

    # Guardar backup
    backup_path = file_path + ".bak"
    with open(backup_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    # Guardar original limpio
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(cleaned_data, f, indent=2, ensure_ascii=False)

    print("\n" + "="*50)
    print("RESUMEN DE AUDITORÍA v14.4")
    print("="*50)
    print(f"Entradas totales antes: {total_before}")
    print(f"Entradas totales después: {total_after}")
    print(f"Registros eliminados: {total_before - total_after}")
    print(f"Equipos afectados: {teams_affected}")
    print(f"Backup guardado en: {backup_path}")
    print("="*50)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--file", default="data/knowledge/team_history.json")
    args = parser.parse_args()
    
    audit_and_clean(args.file, args.threshold)
