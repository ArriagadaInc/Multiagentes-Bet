"""
Ejemplos de uso avanzado del Agente #2 (Odds Fetcher).

Este archivo demuestra cómo usar el grafo de odds fetcher
desde otro código Python, con diferentes casos de uso.

CASOS CUBIERTOS:
1. Uso básico standalone
2. Uso con fixtures cargados desde JSON
3. Uso con competencias personalizadas
4. Acceso a metadatos y auditoría
5. Procesamiento en batch

AUTOR: Equipo de Desarrollo
VERSIÓN: 1.0
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage
from graph_odds_pipeline import (
    build_odds_fetcher_graph,
    AgentState,
    COMPETITION_MAPPING
)

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# EJEMPLO 1: USO BÁSICO STANDALONE
# ============================================================================

def example_1_basic_standalone():
    """
    Caso más simple: consultar odds sin fixtures.
    
    Útil para:
    - Testing rápido
    - Ejecutar agente independientemente
    - Obtener odds sin contexto de fixtures
    """
    print("\n" + "="*70)
    print("EJEMPLO 1: Standalone (sin fixtures)")
    print("="*70)
    
    # Construir grafo
    graph = build_odds_fetcher_graph()
    
    # Crear estado inicial
    state: AgentState = {
        "messages": [HumanMessage(content="Inicia fetcher")],
        "fixtures": None,
        "odds_raw": None,
        "odds_canonical": None,
        "competitions": [
            {"competition": "UCL", "sport_key": "soccer_uefa_champs_league"},
            {"competition": "CHI1", "sport_key": "soccer_chile_campeonato"}
        ],
        "meta": {}
    }
    
    # Invocar
    result = graph.invoke(state)
    
    # Acceder resultados
    print(f"\nTotal eventos: {result['meta']['total_events']}")
    print(f"API calls: {result['meta']['api_calls']}")
    print(f"Cache hits: {result['meta']['cache_hits']}")
    print(f"Tiempo: {result['meta']['processing_time_seconds']:.2f}s")
    
    # Mostrar primer evento
    if result['odds_canonical']:
        event = result['odds_canonical'][0]
        print(f"\nPrimer evento:")
        print(f"  {event['competition']}: {event['home_team']} vs {event['away_team']}")
        print(f"  Bookmakers: {len(event['bookmakers'])}")


# ============================================================================
# EJEMPLO 2: CON FIXTURES (MATCHING)
# ============================================================================

def example_2_with_fixtures():
    """
    Caso con fixtures cargados desde JSON.
    
    El agente intent matchear odds con fixtures por:
    - Similitud de nombres de equipos
    - Ventana de tiempo (±4 horas)
    
    Útil para enriquecer odds con contexto de fixtures.
    """
    print("\n" + "="*70)
    print("EJEMPLO 2: Con Fixtures (Matching)")
    print("="*70)
    
    # Cargar fixtures desde JSON
    fixtures_path = Path("fixtures.json")
    if not fixtures_path.exists():
        print(f"⚠ {fixtures_path} no encontrado, usando ejemplos inline")
        fixtures = [
            {
                "id": "fix_1",
                "competition": "UCL",
                "home_team": "Real Madrid",
                "away_team": "Bayern Munich",
                "status": "SCHEDULED",
                "utcDate": "2026-02-25T20:00:00Z"
            },
            {
                "id": "fix_2",
                "competition": "CHI1",
                "home_team": "Universidad de Chile",
                "away_team": "Colo-Colo",
                "status": "SCHEDULED",
                "utcDate": "2026-02-20T22:00:00Z"
            }
        ]
    else:
        with open(fixtures_path, 'r', encoding='utf-8') as f:
            fixtures = json.load(f)
    
    print(f"Fixtures cargados: {len(fixtures)}")
    
    # Construir grafo
    graph = build_odds_fetcher_graph()
    
    # Estado CON fixtures
    state: AgentState = {
        "messages": [HumanMessage(content="Inicia fetcher con fixtures")],
        "fixtures": fixtures,
        "odds_raw": None,
        "odds_canonical": None,
        "competitions": [
            {"competition": "UCL", "sport_key": "soccer_uefa_champs_league"},
            {"competition": "CHI1", "sport_key": "soccer_chile_campeonato"}
        ],
        "meta": {}
    }
    
    # Invocar
    result = graph.invoke(state)
    
    # Mostrar matches
    matched_count = 0
    for event in result['odds_canonical']:
        if event.get('fixture_match', {}).get('matched'):
            matched_count += 1
            match_info = event['fixture_match']
            print(f"\n✓ Match encontrado: {event['home_team']} vs {event['away_team']}")
            print(f"  Score: {match_info['match_score']}")
    
    print(f"\nTotal matches: {matched_count}/{len(result['odds_canonical'])}")


# ============================================================================
# EJEMPLO 3: COMPETENCIAS PERSONALIZADAS
# ============================================================================

def example_3_custom_competitions():
    """
    Solo consultar competencias específicas.
    
    Útil para limitar API calls o enfocarse en ligas específicas.
    """
    print("\n" + "="*70)
    print("EJEMPLO 3: Competencias Personalizadas (solo UCL)")
    print("="*70)
    
    graph = build_odds_fetcher_graph()
    
    # Estado con solo UCL
    state: AgentState = {
        "messages": [HumanMessage(content="Solo UCL")],
        "fixtures": None,
        "odds_raw": None,
        "odds_canonical": None,
        "competitions": [
            # Solo Champions League
            {"competition": "UCL", "sport_key": "soccer_uefa_champs_league"}
        ],
        "meta": {}
    }
    
    result = graph.invoke(state)
    
    print(f"Total eventos (solo UCL): {result['meta']['total_events']}")
    print(f"Competencias consultadas: {list(result['meta']['competitions'].keys())}")
    
    # Verificar que solo hay UCL
    for event in result['odds_canonical']:
        assert event['competition'] == 'UCL', "Solo debería haber UCL"


# ============================================================================
# EJEMPLO 4: ACCESO A METADATOS Y AUDITORÍA
# ============================================================================

def example_4_metadata_audit():
    """
    Inspeccionar metadatos detallados y audit trail.
    
    Útil para debugging y monitoreo de performance.
    """
    print("\n" + "="*70)
    print("EJEMPLO 4: Metadatos y Auditoría")
    print("="*70)
    
    graph = build_odds_fetcher_graph()
    
    state: AgentState = {
        "messages": [HumanMessage(content="Auditoría")],
        "fixtures": None,
        "odds_raw": None,
        "odds_canonical": None,
        "competitions": [
            {"competition": "UCL", "sport_key": "soccer_uefa_champs_league"},
            {"competition": "CHI1", "sport_key": "soccer_chile_campeonato"}
        ],
        "meta": {}
    }
    
    result = graph.invoke(state)
    
    # ====== METADATOS ======
    meta = result['meta']
    print("\nMETADATOS:")
    print(f"  Timestamp: {meta['generated_at']}")
    print(f"  Total eventos: {meta['total_events']}")
    print(f"  Tiempo procesamiento: {meta['processing_time_seconds']:.2f}s")
    print(f"  API calls: {meta['api_calls']}")
    print(f"  Cache hits: {meta['cache_hits']}")
    
    # ====== ERRORES ======
    if meta.get('errors'):
        print(f"\nERRORES: {len(meta['errors'])}")
        for err in meta['errors']:
            print(f"  - {err['error']}")
    else:
        print(f"\n✓ Sin errores")
    
    # ====== ESTADÍSTICAS POR COMPETENCIA ======
    print("\nPOR COMPETENCIA:")
    for comp, comp_data in meta['competitions'].items():
        cached_label = " (CACHED)" if comp_data.get('cache_hit') else ""
        error_label = f" - ERROR: {comp_data['error']}" if comp_data.get('error') else ""
        print(f"  {comp}: {comp_data['events']} eventos{cached_label}{error_label}")
    
    # ====== AUDIT TRAIL ======
    print("\nAUDIT TRAIL (Mensajes):")
    for i, msg in enumerate(result['messages'], 1):
        role = msg.__class__.__name__
        content = msg.content[:100] if len(msg.content) > 100 else msg.content
        print(f"  [{i}] {role}: {content}...")


# ============================================================================
# EJEMPLO 5: PROCESAMIENTO EN BATCH
# ============================================================================

def example_5_batch_processing():
    """
    Procesar múltiples competencias y generar reporte.
    
    Útil para pipelines que necesitan ejecución configurable.
    """
    print("\n" + "="*70)
    print("EJEMPLO 5: Batch Processing y Reporte")
    print("="*70)
    
    graph = build_odds_fetcher_graph()
    
    # Definir competitions a procesar
    competitions_to_process = [
        [{"competition": "UCL", "sport_key": "soccer_uefa_champs_league"}],
        [{"competition": "CHI1", "sport_key": "soccer_chile_campeonato"}],
        [
            {"competition": "UCL", "sport_key": "soccer_uefa_champs_league"},
            {"competition": "CHI1", "sport_key": "soccer_chile_campeonato"}
        ]
    ]
    
    results_summary = []
    
    for batch_num, competitions in enumerate(competitions_to_process, 1):
        comp_names = ", ".join([c['competition'] for c in competitions])
        print(f"\nBatch {batch_num}: {comp_names}")
        
        state: AgentState = {
            "messages": [HumanMessage(content=f"Batch {batch_num}")],
            "fixtures": None,
            "odds_raw": None,
            "odds_canonical": None,
            "competitions": competitions,
            "meta": {}
        }
        
        result = graph.invoke(state)
        
        # Recopilar datos del batch
        summary = {
            "batch": batch_num,
            "competitions": comp_names,
            "total_events": result['meta']['total_events'],
            "api_calls": result['meta']['api_calls'],
            "cache_hits": result['meta']['cache_hits'],
            "processing_time": result['meta']['processing_time_seconds'],
            "has_errors": len(result['meta']['errors']) > 0
        }
        results_summary.append(summary)
        
        print(f"  ✓ {summary['total_events']} eventos, {summary['processing_time']:.2f}s")
    
    # Mostrar resumen comparativo
    print("\n" + "-"*70)
    print("RESUMEN COMPARATIVO DE BATCHES:")
    print("-"*70)
    for summary in results_summary:
        print(f"Batch {summary['batch']} ({summary['competitions']})")
        print(f"  Eventos: {summary['total_events']}, "
              f"Calls: {summary['api_calls']}, "
              f"Cache: {summary['cache_hits']}, "
              f"Time: {summary['processing_time']:.2f}s")


# ============================================================================
# EJEMPLO 6: GUARDANDO RESULTADOS EN CUSTOM FORMAT
# ============================================================================

def example_6_save_custom_format():
    """
    Ejecutar y guardar resultados en diferentes formatos.
    
    Útil para integración con otros sistemas.
    """
    print("\n" + "="*70)
    print("EJEMPLO 6: Guardar en Formatos Custom")
    print("="*70)
    
    graph = build_odds_fetcher_graph()
    
    state: AgentState = {
        "messages": [HumanMessage(content="Save formats")],
        "fixtures": None,
        "odds_raw": None,
        "odds_canonical": None,
        "competitions": [
            {"competition": "UCL", "sport_key": "soccer_uefa_champs_league"}
        ],
        "meta": {}
    }
    
    result = graph.invoke(state)
    
    # Guardar como JSON completo
    output_file = Path("odds_output_example.json")
    output_data = {
        "meta": result['meta'],
        "odds_canonical": result['odds_canonical'],
        "execution_timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"✓ Guardado en {output_file.name}")
    
    # Crear CSV simple
    csv_file = Path("odds_output_example.csv")
    if result['odds_canonical']:
        with open(csv_file, 'w', encoding='utf-8') as f:
            f.write("competition,home_team,away_team,commence_time,bookmakers_count,cached\n")
            
            for event in result['odds_canonical']:
                comp = event.get('competition', '')
                home = event.get('home_team', '').replace(',', ';')
                away = event.get('away_team', '').replace(',', ';')
                time = event.get('commence_time', '')
                bms = len(event.get('bookmakers', []))
                matched = "yes" if event.get('fixture_match', {}).get('matched') else "no"
                
                line = f"{comp},{home},{away},{time},{bms},{matched}"
                f.write(line + '\n')
        
        print(f"✓ Guardado en {csv_file.name}")


# ============================================================================
# FUNCIÓN PRINCIPAL
# ============================================================================

def main():
    """Ejecutar todos los ejemplos."""
    print("\n" + "="*70)
    print("EJEMPLOS DE USO - AGENTE #2 (ODDS FETCHER)")
    print("="*70)
    
    try:
        # Ejecutar ejemplos
        example_1_basic_standalone()
        example_2_with_fixtures()
        example_3_custom_competitions()
        example_4_metadata_audit()
        example_5_batch_processing()
        example_6_save_custom_format()
        
        print("\n" + "="*70)
        print("✓ TODOS LOS EJEMPLOS COMPLETADOS")
        print("="*70 + "\n")
    
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
