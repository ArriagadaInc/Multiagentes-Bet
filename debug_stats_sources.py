#!/usr/bin/env python3
"""
Script de debugging para verificar qué datos trae cada fuente de stats.
Muestra ESPN, Football-Data, UEFA, FBref para UCL y CHI1.
"""

import json
import os
import sys
import logging
from datetime import datetime

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)-8s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler()]
)

from agents.stats_agent import ESPNAdapter, FootballDataAdapter, UefaAdapter, FbrefAdapter
from utils.http import HTTPClient
from utils.cache import CacheManager

# ============================================================================
# CONFIGURACIÓN
# ============================================================================

COMPETITIONS = {
    "UCL": {
        "competition": "UCL",
        "espn_slug": "uefa-champions-league",
        "competition_code": "CL",
        "api_football_season": 2026,
    },
    "CHI1": {
        "competition": "CHI1",
        "espn_slug": "chile-campeonato",
        "competition_code": "CLI",
        "api_football_season": 2026,
    }
}

API_KEY_FOOTBALL_DATA = os.getenv("FOOTBALL_DATA_API_KEY", "demo")

# ============================================================================
# INICIALIZAR ADAPTADORES
# ============================================================================

http_client = HTTPClient(timeout_seconds=20, max_retries=2)
cache_manager = CacheManager()

espn_adapter = ESPNAdapter(http_client, cache_manager)
football_data_adapter = FootballDataAdapter(http_client, API_KEY_FOOTBALL_DATA)
uefa_adapter = UefaAdapter(http_client, cache_manager)
fbref_adapter = FbrefAdapter(http_client, cache_manager)

# ============================================================================
# FUNCIÓN: Mostrar datos de un adaptador
# ============================================================================

def show_adapter_data(adapter_name, adapter, competition_config, competition_label):
    """Ejecuta un adaptador y muestra los resultados"""
    print(f"\n{'='*80}")
    print(f"  {adapter_name.upper()} ({competition_label})")
    print(f"{'='*80}")
    
    try:
        results = adapter.fetch_stats(competition_config)
        
        if not results:
            print(f"❌ SIN DATOS - {adapter_name} no retornó nada para {competition_label}")
            return
        
        print(f"\n✅ {len(results)} equipos encontrados:\n")
        
        for i, stat_obj in enumerate(results, 1):
            # Convertir a dict si es Pydantic model
            if hasattr(stat_obj, 'dict'):
                stat_dict = stat_obj.dict()
            else:
                stat_dict = stat_obj if isinstance(stat_obj, dict) else vars(stat_obj)
            
            team = stat_dict.get('team', 'Unknown')
            canonical = stat_dict.get('canonical_name', 'N/D')
            provider = stat_dict.get('provider', 'N/D')
            
            print(f"  {i:2d}. Team: {team:30} | Canonical: {canonical:20} | Provider: {provider}")
            
            # Mostrar estadísticas
            stats = stat_dict.get('stats', {})
            if isinstance(stats, dict):
                pos = stats.get('position', '?')
                pts = stats.get('points', '?')
                pg = stats.get('played', '?')
                print(f"       ├─ Position: {pos:3} | Points: {pts:3} | Played: {pg}")
            
            # Mostrar datos avanzados si existen
            adv = stat_dict.get('advanced_stats', {})
            if adv:
                print(f"       ├─ Advanced Stats: {list(adv.keys())}")
            
            # Mostrar alineación si existe
            lineup = stat_dict.get('lineup')
            if lineup:
                print(f"       ├─ Lineup: Formation {lineup.get('formation', 'N/D')}")
            
            # Mostrar data quality
            quality = stat_dict.get('data_quality_score', 'N/D')
            print(f"       └─ Data Quality: {quality}\n")
    
    except Exception as e:
        print(f"❌ ERROR en {adapter_name}: {str(e)[:120]}")
        import traceback
        traceback.print_exc()

# ============================================================================
# MAIN
# ============================================================================

def main():
    print("\n" + "="*80)
    print("  🔍 DEBUG: VERIFICACIÓN DE FUENTES DE ESTADÍSTICAS")
    print("  Mostrando datos de: ESPN, Football-Data, UEFA, FBref")
    print("  Fecha de ejecución:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("="*80)
    
    # Iterar sobre competiciones
    for comp_label, comp_config in COMPETITIONS.items():
        print(f"\n\n{'#'*80}")
        print(f"#  COMPETICIÓN: {comp_label}")
        print(f"{'#'*80}")
        
        # ESPN
        show_adapter_data("ESPN", espn_adapter, comp_config, comp_label)
        
        # Football-Data
        show_adapter_data("Football-Data", football_data_adapter, comp_config, comp_label)
        
        # UEFA (solo UCL)
        if comp_label == "UCL":
            show_adapter_data("UEFA", uefa_adapter, comp_config, comp_label)
        else:
            print(f"\n{'='*80}")
            print(f"  UEFA (CHI1)")
            print(f"{'='*80}")
            print("  ⚠️  UEFA solo aplica a UCL - activado durante competiciones europeas")
        
        # FBref (solo UCL)
        if comp_label == "UCL":
            show_adapter_data("FBref", fbref_adapter, comp_config, comp_label)
        else:
            print(f"\n{'='*80}")
            print(f"  FBref (CHI1)")
            print(f"{'='*80}")
            print("  ⚠️  FBref solo aplica a UCL - requerida para métricas avanzadas (xG)")
    
    print(f"\n\n{'='*80}")
    print("  ✅ DEBUG COMPLETADO")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    main()
