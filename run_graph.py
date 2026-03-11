"""
Script de ejecución para el Agente #2 (Odds Fetcher) con LangGraph.

Este script orquesta la ejecución del pipeline de odds, manejando:
1. Carga de variables de entorno (.env)
2. Inicialización del estado inicial
3. Carga opcional de fixtures desde JSON local
4. Ejecución del grafo
5. Pretty-print de resultados

Uso:
    python run_graph.py
    python run_graph.py --fixtures fixtures.json  (si tienes fixtures)
    python run_graph.py --verbose  (más logging)

Prerequisitos:
    1. variables de entorno en .env (especialmente ODDS_API_KEY)
    2. dependencies instaladas: pip install -r requirements.txt
    3. Opcionalmente, fixtures.json en el mismo directorio

Author: Equipo de Desarrollo - Febrero 2026
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from langchain_core.messages import HumanMessage
from graph_odds_pipeline import (
    build_odds_fetcher_graph,
    AgentState,
    COMPETITION_MAPPING
)

# ============================================================================
# CONFIGURACIÓN
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# FUNCIONES DE UTILIDAD
# ============================================================================

def load_fixtures(fixtures_path: str) -> Optional[list]:
    """
    Carga fixtures desde un archivo JSON.
    
    Formato esperado:
        [
            {
                "id": "1",
                "competition": "UCL",
                "home_team": "Real Madrid",
                "away_team": "Bayern Munich",
                "status": "SCHEDULED",
                "utcDate": "2026-02-25T20:00:00Z",
                ...
            },
            ...
        ]
    
    Args:
        fixtures_path (str): Ruta al archivo JSON de fixtures
    
    Returns:
        Optional[list]: Lista de fixtures o None si falla
    """
    fixtures_file = Path(fixtures_path)
    
    if not fixtures_file.exists():
        logger.warning(f"Archivo de fixtures no encontrado: {fixtures_path}")
        return None
    
    try:
        with open(fixtures_file, 'r', encoding='utf-8') as f:
            fixtures = json.load(f)
        
        logger.info(f"Fixtures cargados: {len(fixtures)} eventos")
        return fixtures
    
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error al cargar fixtures: {e}")
        return None


def create_initial_state(fixtures: Optional[list] = None) -> AgentState:
    """
    Crea el estado inicial para el grafo.
    
    El estado inicial contiene:
    - Competencias a consultar (UCL, CHI1)
    - Fixtures opcionales del Agente #1
    - Messages vacío (para auditoría)
    - Meta estructurado pero vacío (se llena en odds_fetcher_node)
    
    Args:
        fixtures (Optional[list]): Fixtures cargados (o None)
    
    Returns:
        AgentState: Estado inicial
    """
    # Definir competencias a consultar
    competitions = [
        {
            "competition": "UCL",
            "sport_key": "soccer_uefa_champs_league"
        },
        {
            "competition": "CHI1",
            "sport_key": "soccer_chile_campeonato"
        }
    ]
    
    # Crear mensaje inicial
    initial_messages = [
        HumanMessage(
            content="Inicia Agente #2: Odds Fetcher. Consultando odds..."
        )
    ]
    
    # Construir estado inicial
    state: AgentState = {
        "messages": initial_messages,
        "fixtures": fixtures,
        "odds_raw": None,
        "odds_canonical": None,
        "competitions": competitions,
        "meta": {}
    }
    
    return state


def print_meta_summary(meta: dict) -> None:
    """
    Imprime un resumen formateado de los metadatos del pipeline.
    
    Args:
        meta (dict): Metadatos del resultaado final
    """
    print("\n" + "="*70)
    print("RESUMEN - METADATOS")
    print("="*70)
    
    print(f"Generado en: {meta.get('generated_at', 'N/A')}")
    print(f"Tiempo de procesamiento: {meta.get('processing_time_seconds', 0):.2f}s")
    print(f"\nEstadísticas:")
    print(f"  Total eventos: {meta.get('total_events', 0)}")
    print(f"  Llamadas API: {meta.get('api_calls', 0)}")
    print(f"  Cache hits: {meta.get('cache_hits', 0)}")
    
    print(f"\nPor competencia:")
    for comp_code, comp_data in meta.get("competitions", {}).items():
        status = "✓ OK" if not comp_data.get("error") else "✗ ERROR"
        cached = " (cached)" if comp_data.get("cache_hit") else ""
        print(f"  {comp_code}: {status} - {comp_data.get('events', 0)} subEvents{cached}")
        if comp_data.get("error"):
            print(f"    Error: {comp_data.get('error')}")
    
    if meta.get("errors"):
        print(f"\nErrores totales: {len(meta.get('errors'))}")
        for error in meta.get("errors", [])[:5]:  # mostrar primeros 5
            print(f"  - {error.get('error', 'Unknown')}")
    
    print("="*70 + "\n")


def print_canonical_summary(canonical_events: list, max_print: int = 5) -> None:
    """
    Imprime un resumen de los eventos canonicalizados.
    
    Muestra los primeros N eventos completos (con pretty-print JSON),
    seguido de un conteo total.
    
    Args:
        canonical_events (list): Lista de eventos normalizados
        max_print (int): Máximo número de eventos a imprimir completo
    """
    print("\n" + "="*70)
    print("ODDS CANÓNICOS (Formato Normalizado)")
    print("="*70)
    
    if not canonical_events:
        print("  [Sin eventos]")
        return
    
    print(f"Total de eventos: {len(canonical_events)}\n")
    
    # Imprimir primeros N eventos
    for i, event in enumerate(canonical_events[:max_print], 1):
        print(f"\n[Evento {i}/{min(len(canonical_events), max_print)}]")
        print(json.dumps(event, indent=2, ensure_ascii=False))
    
    if len(canonical_events) > max_print:
        remaining = len(canonical_events) - max_print
        print(f"\n... y {remaining} evento(s) más (no mostrado(s))")
    
    print("="*70 + "\n")


def print_messages_audit_trail(messages: list) -> None:
    """
    Imprime el trail de auditoría de mensajes.
    
    Args:
        messages (list): Lista de BaseMessage
    """
    print("\n" + "="*70)
    print("AUDIT TRAIL - MENSAJES DEL PIPELINE")
    print("="*70)
    
    for i, msg in enumerate(messages, 1):
        role = getattr(msg, "__class__").__name__
        content = msg.content if hasattr(msg, "content") else str(msg)
        print(f"\n[{i}] {role}:")
        print(f"    {content[:200]}..." if len(content) > 200 else f"    {content}")
    
    print("\n" + "="*70 + "\n")


# ============================================================================
# FUNCIÓN PRINCIPAL
# ============================================================================

def main():
    """
    Ejecuta el pipeline principal del Agente #2.
    
    1. Parsea argumentos de línea de comandos
    2. Carga fixtures si se proporcionan
    3. Construye el grafo LangGraph
    4. Crea estado inicial
    5. Invoca el grafo
    6. Imprime resultados
    """
    logger.info("Iniciando Agente #2 (Odds Fetcher v2) con LangGraph")
    
    # ====== ARGUMENTOS ======
    fixtures_path = "fixtures.json"  # default
    verbose = "--verbose" in sys.argv
    
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.info("Modo verbose activado")
    
    # ====== CARGAR FIXTURES (OPCIONAL) ======
    fixtures = None
    if Path(fixtures_path).exists():
        logger.info(f"Detectado {fixtures_path}, cargando fixtures...")
        fixtures = load_fixtures(fixtures_path)
    else:
        logger.info("Ejecutando en modo standalone (sin fixtures)")
    
    # ====== CONSTRUIR GRAFO ======
    logger.info("Construyendo grafo LangGraph...")
    graph = build_odds_fetcher_graph()
    
    # ====== CREAR ESTADO INICIAL ======
    logger.info("Creando estado inicial...")
    initial_state = create_initial_state(fixtures=fixtures)
    
    # ====== INVOCAR GRAFO ======
    print("\n" + "="*70)
    print("INICIANDO EJECUCIÓN DEL GRAFO")
    print("="*70)
    logger.info("Invocando grafo...")
    
    try:
        result_state = graph.invoke(initial_state)
    except Exception as e:
        logger.error(f"Error al invocar grafo: {e}", exc_info=True)
        sys.exit(1)
    
    # ====== RESULTADOS ======
    print("\n✓ Ejecución completada\n")
    
    # Imprimir audit trail
    if result_state.get("messages"):
        print_messages_audit_trail(result_state["messages"])
    
    # Imprimir metadatos
    if result_state.get("meta"):
        print_meta_summary(result_state["meta"])
    
    # Imprimir eventos canonical
    if result_state.get("odds_canonical"):
        print_canonical_summary(result_state["odds_canonical"], max_print=3)
    else:
        print("\n⚠ No se obtuvieron eventos de odds")
    
    # ====== GUARDAR RESULTADO COMPLETO (OPCIONAL) ======
    output_file = Path("odds_result.json")
    try:
        # Serializar - remover BaseMessage objects
        serializable_state = {
            "meta": result_state.get("meta"),
            "odds_canonical": result_state.get("odds_canonical"),
            "odds_raw_keys": list(result_state.get("odds_raw", {}).keys()),
            "execution_timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(serializable_state, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Resultado completo guardado en: {output_file}")
    
    except Exception as e:
        logger.warning(f"No se pudo guardar resultado en JSON: {e}")
    
    print(f"\n✓ Pipeline finalizado exitosamente\n")


if __name__ == "__main__":
    main()
