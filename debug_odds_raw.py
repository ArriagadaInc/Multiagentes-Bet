
import json
import logging

def main():
    try:
        with open("pipeline_odds.json", "r", encoding="utf-8") as f:
            # Este archivo ya tiene la data procesada/normalizada, asi que podría no mostrar el RAW original
            # si odds_agent.py ya lo transformó mal y borró la estructura original de outcomes.
            # PERO, según el código de odds_agent.py, state["odds_raw"] guarda la respuesta cruda.
            pass
            
            # Vamos a buscar si existe un log o si podemos inferirlo del 'pipeline_state.json' si existiera,
            # o mejor aún, mirar lo que 'odds_agent' guardó en la cache.
            
    except Exception as e:
        print(f"Error: {e}")

    # Como no tengo acceso fácil al raw exacto de esa ejecución (salvo que esté en odds_raw en state),
    # voy a mirar 'pipeline_odds.json' a ver si tiene pistas, o asumir el error por inspección de código.
    # El usuario pidió "logea el RAW JSON completo".
    # En la ejecución anterior, odds_agent.py guardó:
    # state["odds_raw"][comp_label] = result["data"]
    
    # Voy a intentar leer el pickle del state si existe, o el json debug si lo guardamos.
    # En run_pipeline.py guardamos:
    # with open("pipeline_odds.json", "w") as f: json.dump(state.get("odds_canonical"), f, ...)
    # O sea, pipeline_odds.json TIENE LO NORMALIZADO (YA CORRUPTO).
    
    # SOLUCION: El script 'odds_agent.py' usa CacheManager.
    # Podemos leer la cache del disco para ver el RAW response.
    
    from utils.cache import CacheManager
    cache = CacheManager()
    
    # Keys probables: odds_UCL_h2h, odds_CHI1_h2h
    print("\n--- INSPECCIONANDO CACHE (RAW API RESPONSE) ---")
    
    raw_ucl = cache.load("odds", "UCL", "h2h")
    if raw_ucl:
        print(f"✅ Cache encontrada para UCL. Eventos: {len(raw_ucl)}")
        
        # Buscar el partido del Inter o Real Madrid
        targets = ["Inter", "Real Madrid", "Paris Saint-Germain"]
        
        for event in raw_ucl:
            h = event.get("home_team", "")
            a = event.get("away_team", "")
            
            match_found = False
            for t in targets:
                if t in h or t in a:
                    match_found = True
                    break
            
            if match_found:
                print(f"\n⚽ EVENTO RAW: {h} vs {a}")
                print(f"   ID: {event.get('id')}")
                
                # Imprimir outcomes del primer bookmaker
                if event.get("bookmakers"):
                    bk = event["bookmakers"][0]
                    print(f"   Bookmaker: {bk.get('title')} ({bk.get('key')})")
                    for mkt in bk.get("markets", []):
                        if mkt["key"] == "h2h":
                            print("   Outcomes (Orden Real en JSON):")
                            for i, out in enumerate(mkt.get("outcomes", [])):
                                print(f"     [{i}] Name: '{out.get('name')}' | Price: {out.get('price')}")
                                
                            # Verificamos hipótesis:
                            # Si [0] es el visitante o empate, y el código asume [0]=Home, ahí está el bug.
    else:
        print("❌ No se encontró cache para UCL.")

if __name__ == "__main__":
    main()
