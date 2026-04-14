import os

APP_FILE = "app.py"

def patch_app():
    if not os.path.exists(APP_FILE):
        print(f"Error: {APP_FILE} not found.")
        return

    with open(APP_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Patch the filter to include PENDING/None
    old_filter = 'evaluated_history = [p for p in history_data if p.get("evaluation_status") in ["OK", "NOT_FOUND", "NO_DATE"]]'
    new_filter = 'evaluated_history = [p for p in history_data if p.get("evaluation_status") in ["OK", "NOT_FOUND", "NO_DATE", None, "PENDING"]]'
    
    if old_filter in content:
        content = content.replace(old_filter, new_filter)
        print("Patched evaluation filter.")
    else:
        print("Warning: Could not find old filter string.")

    # 2. Patch the sorting before st.dataframe
    # We find the st.dataframe call for the evaluation history
    # The context is Renaming columns then rename -> table_df
    
    target_block = """                # Seleccionar y renombrar columnas
                disp_cols = {
                    "match_date": "Fecha",
                    "competition": "Liga",
                    "home_team": "Local",
                    "away_team": "Visita",
                    "prediction": "Tendencia",
                    "score_prediction": "Obj. Marc.",
                    "actual_score": "Marcador Real",
                    "score_acc": "Prec.",
                    "evaluation_status": "Estado",
                    "correct": "Acierto",
                    "analyst_model_id": "Modelo"
                }
                
                # Asegurar que las columnas existen
                valid_disp_cols = {k: v for k, v in disp_cols.items() if k in h_df.columns}
                table_df = h_df[list(valid_disp_cols.keys())].rename(columns=valid_disp_cols)"""

    replacement_block = target_block + """
                
                # Ordenar por Fecha (descendente)
                if "Fecha" in table_df.columns:
                    table_df = table_df.sort_values(by="Fecha", ascending=False)"""

    if target_block in content:
        content = content.replace(target_block, replacement_block)
        print("Patched table sorting.")
    else:
        # Try a more generic match if exact string fails due to whitespace
        print("Warning: Could not find exact target block for sorting. Attempting regex...")
        import re
        content = re.sub(
            r"(table_df = h_df\[list\(valid_disp_cols\.keys\(\)\)\]\.rename\(columns=valid_disp_cols\))",
            r"\1\n                \n                # Ordenar por Fecha (descendente)\n                if 'Fecha' in table_df.columns:\n                    table_df = table_df.sort_values(by='Fecha', ascending=False)",
            content
        )

    with open(APP_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    print("app.py patched successfully.")

if __name__ == "__main__":
    patch_app()
