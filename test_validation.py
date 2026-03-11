"""
Test Simple del Pipeline Multiagente - Validación de instalación y setup.

Este script ejecuta pruebas rápidas para asegurar que:
1. Dependencias están instaladas correctamente
2. Variables de entorno están configuradas
3. La API key es válida
4. El grafo se construye correctamente
5. Se puede inicializar un estado

Uso:
    python test_validation.py
    python test_validation.py --quick    (skip API call)
    python test_validation.py --verbose

Salida:
    ✓ PASS: Si todo está bien
    ✗ FAIL: Si algo no está configurado
"""

import sys
import os
from pathlib import Path


def test_imports():
    """Test 1: Verificar imports de dependencias."""
    print("\n[1/6] Verificando imports...")
    
    try:
        import langchain
        print("    ✓ langchain")
    except ImportError as e:
        print(f"    ✗ langchain: {e}")
        return False
    
    try:
        import langgraph
        print("    ✓ langgraph")
    except ImportError as e:
        print(f"    ✗ langgraph: {e}")
        return False
    
    try:
        import requests
        print("    ✓ requests")
    except ImportError as e:
        print(f"    ✗ requests: {e}")
        return False
    
    try:
        import dotenv
        print("    ✓ python-dotenv")
    except ImportError as e:
        print(f"    ✗ python-dotenv: {e}")
        return False
    
    print("    ✓ All imports OK")
    return True


def test_env_setup():
    """Test 2: Verificar variables de entorno."""
    print("\n[2/6] Verificando variables de entorno...")
    
    from dotenv import load_dotenv
    load_dotenv()
    
    # Football Data API Key
    fd_key = os.getenv("FOOTBALL_DATA_API_KEY")
    if not fd_key:
        print("    ✗ FOOTBALL_DATA_API_KEY no configurada")
        return False
    print(f"    ✓ FOOTBALL_DATA_API_KEY configurada ({fd_key[:10]}...)")
    
    # Odds API Key
    api_key = os.getenv("ODDS_API_KEY")
    if not api_key:
        print("    ✗ ODDS_API_KEY no configurada")
        return False
    
    if api_key == "sk_live_YOUR_API_KEY_HERE":
        print("    ✗ ODDS_API_KEY contiene valor por defecto")
        return False
    
    print(f"    ✓ ODDS_API_KEY configurada ({api_key[:10]}...)")
    
    regions = os.getenv("ODDS_REGIONS", "eu")
    print(f"    ✓ ODDS_REGIONS: {regions}")
    
    markets = os.getenv("ODDS_MARKETS", "h2h")
    print(f"    ✓ ODDS_MARKETS: {markets}")
    
    ttl = os.getenv("ODDS_CACHE_TTL_SECONDS", "600")
    print(f"    ✓ ODDS_CACHE_TTL_SECONDS: {ttl}")
    
    return True


def test_module_import():
    """Test 3: Importar módulos principales del pipeline."""
    print("\n[3/6] Importando módulos principales...")
    
    try:
        from state import AgentState
        print("    ✓ state.AgentState")
    except ImportError as e:
        print(f"    ✗ state: {e}")
        return False
    
    try:
        from agents.fixtures_agent import FixturesFetcher, fixtures_fetcher_node
        print("    ✓ agents.fixtures_agent")
    except ImportError as e:
        print(f"    ✗ agents.fixtures_agent: {e}")
        return False
    
    try:
        from agents.odds_agent import OddsFetcher, odds_fetcher_node
        print("    ✓ agents.odds_agent")
    except ImportError as e:
        print(f"    ✗ agents.odds_agent: {e}")
        return False
    
    try:
        from agents.fallback_agent import fixtures_fallback_node
        print("    ✓ agents.fallback_agent")
    except ImportError as e:
        print(f"    ✗ agents.fallback_agent: {e}")
        return False
    
    try:
        from agents.youtube_selector import youtube_selector_node
        print("    ✓ agents.youtube_selector")
    except ImportError as e:
        print(f"    ✗ agents.youtube_selector: {e}")
        return False
    
    try:
        from agents.insights_agent import insights_agent_node
        print("    ✓ agents.insights_agent")
    except ImportError as e:
        print(f"    ✗ agents.insights_agent: {e}")
        return False
    
    try:
        from graph_pipeline import build_pipeline, create_initial_state, PipelineExecutor
        print("    ✓ graph_pipeline")
    except ImportError as e:
        print(f"    ✗ graph_pipeline: {e}")
        return False
    
    print("    ✓ All modules OK")
    return True


def test_graph_build():
    """Test 4: Construir grafo."""
    print("\n[4/6] Construyendo grafo LangGraph...")
    
    try:
        from graph_pipeline import build_pipeline
        graph = build_pipeline()
        print("    ✓ Grafo construido exitosamente")
        print(f"    ✓ Nodos: {len(graph.nodes)}")
        return True
    except Exception as e:
        print(f"    ✗ Error al construir grafo: {e}")
        return False


def test_state_creation():
    """Test 5: Crear estado inicial."""
    print("\n[5/6] Creando estado inicial...")
    
    try:
        from graph_pipeline import create_initial_state
        
        competitions = [
            {"competition": "UCL", "fixtures_provider": "football-data", "competition_code": "CL"},
            {"competition": "CHI1", "fixtures_provider": "api-football", "competition_code": None}
        ]
        
        state = create_initial_state(competitions, fixtures_days_ahead=7)
        
        print("    ✓ Estado creado exitosamente")
        print(f"    ✓ Competencias: {len(state['competitions'])}")
        print(f"    ✓ Meta keys: {list(state['meta'].keys())}")
        return True
    except Exception as e:
        print(f"    ✗ Error al crear estado: {e}")
        return False


def test_api_key_validity(skip=False):
    """Test 6: Validar API key (llamada rápida)."""
    print("\n[6/6] Validando API key de Odds...")
    
    if skip:
        print("    ⊘ Skipped (--quick)")
        return True
    
    try:
        import os
        from dotenv import load_dotenv
        import requests
        
        load_dotenv()
        api_key = os.getenv("ODDS_API_KEY")
        
        if not api_key:
            print("    ✗ ODDS_API_KEY vacía")
            return False
        
        # Test simple: GET sin parámetros (no consume cuota)
        url = f"https://api.the-odds-api.com/v4/sports"
        params = {"apiKey": api_key}
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            print("    ✓ API key Valid!")
            return True
        elif response.status_code == 401:
            print("    ✗ API key inválida (401 Unauthorized)")
            return False
        elif response.status_code == 429:
            print("    ⚠ API key válida pero rate limited (429)")
            return True
        else:
            print(f"    ⚠ Status {response.status_code}: {response.text[:100]}")
            return True
    
    except Exception as e:
        print(f"    ✗ Error en validación: {e}")
        return False


def main():
    """Ejecutar suite de tests."""
    print("="*70)
    print("VALIDACIÓN DE SETUP - PIPELINE MULTIAGENTE")
    print("="*70)
    
    skip_api_test = "--quick" in sys.argv
    verbose = "--verbose" in sys.argv
    
    # Array de tests
    tests = [
        ("Imports", test_imports),
        ("Entorno", test_env_setup),
        ("Módulos del Pipeline", test_module_import),
        ("Construcción de Grafo", test_graph_build),
        ("Creación de Estado", test_state_creation),
        ("Validación API Key", lambda: test_api_key_validity(skip=skip_api_test))
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"    ✗ Excepción no manejada: {e}")
            if verbose:
                import traceback
                traceback.print_exc()
            results.append((test_name, False))
    
    # Resumen
    print("\n" + "="*70)
    print("RESUMEN:")
    print("="*70)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total}")
    
    if passed == total:
        print("\n✓ SETUP VÁLIDO - Listo para ejecutar 'python run_pipeline.py'")
        return 0
    else:
        print(f"\n✗ {total - passed} ERRORES - Revisa configuración")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
