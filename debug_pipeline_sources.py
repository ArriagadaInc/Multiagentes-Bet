#!/usr/bin/env python3
"""
Script mejorado para mostrar qué datos reales está trayendo cada fuente.
Inspecciona los JSONs de salida del pipeline.
"""

import json
import os
from datetime import datetime
from pathlib import Path

# ============================================================================
# ARCHIVOS DEL PIPELINE
# ============================================================================

FILES = {
    "odds": "pipeline_odds.json",
    "stats": "pipeline_stats.json",
    "fixtures": "pipeline_fixtures.json",
    "insights": "pipeline_insights.json",
    "match_contexts": "pipeline_match_contexts.json",
}

def load_json(filepath):
    """Carga un JSON de forma segura"""
    try:
        if not os.path.exists(filepath):
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  [ERROR] Cargando {filepath}: {e}")
        return None

def show_stats_sources():
    """Analiza pipeline_stats.json para mostrar de dónde vienen los datos"""
    print("\n" + "="*100)
    print("  [STATS] FUENTES DE ESTADÍSTICAS (pipeline_stats.json)")
    print("="*100)
    
    data = load_json(FILES["stats"])
    if not data:
        print("  [!] Archivo no existe o vacio. Ejecuta el pipeline primero.")
        return
    
    # Agrupar por competición y proveedor
    by_comp_provider = {}
    
    for stat in data:
        comp = stat.get("competition", "Unknown")
        provider = stat.get("provider", "unknown")
        key = f"{comp}|{provider}"
        
        if key not in by_comp_provider:
            by_comp_provider[key] = []
        by_comp_provider[key].append(stat)
    
    print(f"\n  Total: {len(data)} equipos en {len(by_comp_provider)} combinaciones de competición/proveedor\n")
    
    for key in sorted(by_comp_provider.keys()):
        comp, provider = key.split("|")
        stats_list = by_comp_provider[key]
        
        print(f"\n  [*] {comp} - {provider.upper()}: {len(stats_list)} equipos")
        print(f"     {'-'*80}")
        
        for i, stat in enumerate(stats_list[:5], 1):  # Mostrar primeros 5
            team = stat.get("team", "Unknown")
            canonical = stat.get("canonical_name", "N/D")
            quality = stat.get("data_quality_score", "?")
            
            stats_data = stat.get("stats", {})
            pos = stats_data.get("position", "?")
            pts = stats_data.get("points", "?")
            
            print(f"     {i}. {team:25} | Canonical: {canonical:20} | Pos: {pos:2} | Pts: {pts:3} | Quality: {quality}")
        
        if len(stats_list) > 5:
            print(f"     ... y {len(stats_list) - 5} más")

def show_match_contexts():
    """Muestra los match_contexts con los datos enriquecidos"""
    print("\n" + "="*100)
    print("  [MATCHES] MATCH CONTEXTS (pipeline_match_contexts.json)")
    print("    Aqui es donde se unen ODDS + STATS + INSIGHTS")
    print("="*100)
    
    data = load_json(FILES["match_contexts"])
    if not data:
        print("  [!] Archivo no existe o vacio.")
        return
    
    # Agrupar por competición
    by_comp = {}
    for mc in data:
        comp = mc.get("competition", "Unknown")
        if comp not in by_comp:
            by_comp[comp] = []
        by_comp[comp].append(mc)
    
    print(f"\n  Total: {len(data)} partidos en {len(by_comp)} competiciones\n")
    
    for comp in sorted(by_comp.keys()):
        matches = by_comp[comp]
        print(f"\n  [*] {comp}: {len(matches)} partidos")
        print(f"     {'-'*80}")
        
        for i, mc in enumerate(matches[:3], 1):  # Mostrar primeros 3
            h_cn = mc.get("home", {}).get("canonical_name", "?")
            a_cn = mc.get("away", {}).get("canonical_name", "?")
            date = mc.get("match_date", "?")
            quality = mc.get("data_quality", {}).get("score", "?")
            
            h_has_stats = "[+]" if mc.get("home", {}).get("stats") else "[-]"
            h_has_insights = "[+]" if mc.get("home", {}).get("insights") else "[-]"
            a_has_stats = "[+]" if mc.get("away", {}).get("stats") else "[-]"
            a_has_insights = "[+]" if mc.get("away", {}).get("insights") else "[-]"
            
            print(f"     {i}. {date} | {h_cn:20} vs {a_cn:20}")
            print(f"        Home: Stats{h_has_stats} Insights{h_has_insights} | Away: Stats{a_has_stats} Insights{a_has_insights} | Quality: {quality}")
            
            # Mostrar qué datos tiene
            home_stats = mc.get("home", {}).get("stats")
            if home_stats:
                provider = home_stats.get("provider", "?")
                pos = home_stats.get("stats", {}).get("position", "?")
                print(f"        └─ Home stats from {provider}: Position {pos}")
        
        if len(matches) > 3:
            print(f"     ... y {len(matches) - 3} más")

def show_odds_coverage():
    """Muestra la cobertura de odds"""
    print("\n" + "="*100)
    print("  [ODDS] ANALISIS: ODDS (pipeline_odds.json)")
    print("="*100)
    
    data = load_json(FILES["odds"])
    if not data:
        print("  [!] Archivo no existe o vacio.")
        return
    
    # Agrupar por competición
    by_comp = {}
    for odds in data:
        comp = odds.get("competition", "Unknown")
        if comp not in by_comp:
            by_comp[comp] = []
        by_comp[comp].append(odds)
    
    print(f"\n  Total: {len(data)} eventos con cuotas\n")
    
    for comp in sorted(by_comp.keys()):
        odds_list = by_comp[comp]
        print(f"\n  [*] {comp}: {len(odds_list)} eventos")
        print(f"     {'-'*80}")
        
        for i, odds in enumerate(odds_list[:3], 1):
            home = odds.get("home_team", "?")
            away = odds.get("away_team", "?")
            date = str(odds.get("commence_time", "?"))[:10]
            bm_count = odds.get("bookmakers_count", "?")
            
            print(f"     {i}. {date} | {home:20} vs {away:20} | {bm_count} bookmakers")
        
        if len(odds_list) > 3:
            print(f"     ... y {len(odds_list) - 3} más")

def show_real_madrid_tracking():
    """Muestra cómo se normaliza Real Madrid en todo el pipeline"""
    print("\n" + "="*100)
    print("  [DEBUG] Rastreo de 'Real Madrid' en todo el pipeline")
    print("="*100)
    
    print("\n  [1] En pipeline_odds.json:")
    odds_data = load_json(FILES["odds"])
    if odds_data:
        rm_odds = [o for o in odds_data if "real madrid" in o.get("home_team", "").lower() or "real madrid" in o.get("away_team", "").lower()]
        print(f"     Encontrado: {len(rm_odds)} evento(s)")
        for o in rm_odds:
            print(f"       -> {o.get('home_team')} vs {o.get('away_team')} ({o.get('competition')})")
    
    print("\n  [2] En pipeline_stats.json:")
    stats_data = load_json(FILES["stats"])
    if stats_data:
        rm_stats = [s for s in stats_data if "real madrid" in s.get("team", "").lower()]
        print(f"     Encontrado: {len(rm_stats)} entrada(s)")
        for s in rm_stats:
            team = s.get("team")
            canonical = s.get("canonical_name")
            provider = s.get("provider")
            print(f"       -> Team: '{team}' | Canonical: '{canonical}' | Provider: {provider}")
    
    print("\n  [3] En pipeline_match_contexts.json:")
    mc_data = load_json(FILES["match_contexts"])
    if mc_data:
        rm_matches = []
        for mc in mc_data:
            if "real madrid" in mc.get("home", {}).get("canonical_name", "").lower():
                rm_matches.append(mc)
            elif "real madrid" in mc.get("away", {}).get("canonical_name", "").lower():
                rm_matches.append(mc)
        
        print(f"     Encontrado: {len(rm_matches)} partido(s)")
        for mc in rm_matches:
            h_cn = mc.get("home", {}).get("canonical_name")
            a_cn = mc.get("away", {}).get("canonical_name")
            date = mc.get("match_date")
            h_team = mc.get("home", {}).get("stats", {}).get("team") if mc.get("home", {}).get("stats") else "N/D"
            print(f"       -> {date}: {h_cn} vs {a_cn}")
            if h_team and "real" in h_team.lower():
                print(f"          Home stats team: '{h_team}'")

def main():
    print("\n" + "="*100)
    print("=  [DEBUG] ANALISIS COMPLETO: FUENTES DE DATOS DEL PIPELINE")
    print("=  Momento: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("="*100)
    
    # Verificar que el pipeline se haya ejecutado
    if not os.path.exists(FILES["stats"]):
        print("\n  [!] ADVERTENCIA: Los archivos del pipeline no existen.")
        print("     Ejecuta primero: python run_pipeline.py")
        return
    
    show_stats_sources()
    show_odds_coverage()
    show_match_contexts()
    show_real_madrid_tracking()
    
    print("\n" + "="*100)
    print("=  [OK] ANALISIS COMPLETADO")
    print("="*100 + "\n")

if __name__ == "__main__":
    main()
