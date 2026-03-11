"""
# 🏗️ ARCHITECTURE GUIDE

Guía de diseño, patrones y extensibilidad del pipeline multiagente.

## 📐 Principios de Diseño

### 1. Modularidad
- Cada agente en archivo separado
- Utilities compartidas reutilizables
- No circular imports

### 2. Extensibilidad
- Agentes desacoplados
- Fácil agregar Agente #3, #4, etc.
- State TypedDict flexible

### 3. Resiliencia
- Manejo de errores sin botar pipeline
- Cache para reducir llamadas API
- Retries con exponential backoff

### 4. Observabilidad
- Logging en cada paso
- Audit trail en state["messages"]
- Metadata detallada en resultados

## 🏛️ Estructura Modular

```
pipeline/
│
├── state.py
│   └── AgentState TypedDict: estado compartido global
│
├── utils/
│   ├── cache.py: CacheManager (TTL-based disk caching)
│   ├── http.py: HTTPClient (retries, backoff, timeouts)
│   └── matching.py: [futuro] fuzzy matching utilities
│
├── agents/
│   ├── fixtures_agent.py: FixturesFetcher + fixtures_fetcher_node()
│   ├── odds_agent.py: OddsFetcher + odds_fetcher_node()
│   └── [futuro] analyzer_agent.py: AnalyzerAgent + analyzer_node()
│
├── graph_pipeline.py
│   ├── build_pipeline(): Construye LangGraph
│   ├── create_initial_state(): Inicializa estado
│   └── PipelineExecutor: Ejecuta el grafo compilado
│
└── run_pipeline.py
    └── main(): Entry point
```

## 🔄 State Flow

### AgentState TypedDict

```python
AgentState = TypedDict({
    # Audit trail
    "messages": list[BaseMessage],
    
    # Agente #1 outputs
    "fixtures": Optional[list[dict]],
    "fixtures_raw": Optional[dict],
    
    # Agente #2 outputs
    "odds_raw": Optional[dict],
    "odds_canonical": Optional[list[dict]],
    
    # Agente #3+ inputs/outputs [futures]
    # "predictions": Optional[list[dict]],
    
    # Configuration
    "competitions": list[dict],
    
    # Shared metadata
    "meta": dict
})
```

### Metadata Structure

```python
{
    "generated_at": "ISO8601 timestamp",
    "include_fixtures": bool,
    "include_odds": bool,
    
    # Counts
    "total_fixtures": int,
    "total_odds": int,
    "fixtures_counts": {"UCL": 85, "CHI1": 0},
    "odds_counts": {"UCL": 150, "CHI1": 123},
    
    # Cache hits
    "cache_hits": {
        "fixtures": int,
        "odds": int
    },
    
    # Errors per agent
    "errors": {
        "fixtures": {"CHI1": "reason..."},
        "odds": {}
    },
    
    # Performance
    "processing_time_seconds": float,
    "rate_limit_info": {"remaining": int, "reset_at": str}
}
```

## 🔌 Cómo Agregar un Agente (Agente #3)

### Step 1: Crear archivo agent

```python
# agents/analyzer_agent.py

from state import AgentState
from langchain_core.messages import HumanMessage

async def analyzer_node(state: AgentState) -> AgentState:
    \"\"\"
    Analiza fixtures + odds para generar predicciones.
    \"\"\"
    # Lee fixtures y odds del estado
    fixtures = state.get("fixtures", [])
    odds = state.get("odds_canonical", [])
    
    # Tu lógica aquí
    predictions = analyze(fixtures, odds)
    
    # Actualiza estado
    state["predictions"] = predictions
    state["messages"].append(
        HumanMessage(content=f"Generated {len(predictions)} predictions")
    )
    
    return state
```

### Step 2: Agregar al grafo

```python
# graph_pipeline.py

from agents.analyzer_agent import analyzer_node

def build_pipeline() -> StateGraph:
    graph = StateGraph(AgentState)
    
    # Nodos existentes
    graph.add_node("fixtures_fetcher", fixtures_fetcher_node)
    graph.add_node("odds_fetcher", odds_fetcher_node)
    
    # Nuevo nodo
    graph.add_node("analyzer", analyzer_node)
    
    # Edges
    graph.add_edge(START, "fixtures_fetcher")
    graph.add_edge("fixtures_fetcher", "odds_fetcher")
    graph.add_edge("odds_fetcher", "analyzer")  # ← Nuevo
    graph.add_edge("analyzer", END)
    
    return graph
```

### Step 3: ✅ Listo

El pipeline automáticamente ejecutará: fixtures → odds → analyzer

## 🛡️ Patrón: Resiliencia

### Cache Layer (utils/cache.py)

```python
# Beneficios:
# - Reduce API calls (cost ~50% reduction)
# - Cumple rate limits (no exceder cuota)
# - Respuesta más rápida (cache hit ~10ms vs API ~500ms)

cache = CacheManager(cache_dir="./cache", default_ttl_seconds=600)

# Try cache first
data = cache.load("fixtures", "CL", "SCHEDULED")

# If miss, fetch from API
if not data:
    data = fetch_from_api()
    cache.save(data, "fixtures", "CL", "SCHEDULED")
```

### HTTP Client with Retries (utils/http.py)

```python
# Beneficios:
# - Retry automático en transient failures
# - Exponential backoff (1s, 2s, espera)
# - Timeout enforcement (conexión + read)

client = HTTPClient(timeout_seconds=20, max_retries=2)

# Automáticamente:
# 1. Intenta GET
# 2. Si timeout/429/5xx -> espera + reintenta
# 3. Si 401/403/404 -> error inmediato (no reintenta)

data, status, error = client.get(
    "https://api.football-data.org/v4/competitions/CL/matches",
    headers={"X-Auth-Token": key},
    params={"status": "SCHEDULED"}
)
```

## 📊 Patrón: Normalización

Cada agente transforma API responses a formato canónico:

### Fixtures (Agente #1)

```
football-data.org {
    "id": 300123456,
    "utcDate": "2024-01-15T20:00:00Z",
    "homeTeam": {"name": "Real Madrid"},
    "awayTeam": {"name": "AC Milan"},
    ...
}
        ↓
Canonical {
    "fixture_id": "300123456",
    "utc_date": "2024-01-15T20:00:00Z",
    "home_team": "Real Madrid",
    "away_team": "AC Milan",
    "competition": "UCL",
    ...
}
```

### Odds (Agente #2)

```
The Odds API {
    "id": "event_id",
    "home_team": "Real Madrid",
    "bookmakers": [{
        "markets": [{
            "outcomes": [
                {"name": "Real Madrid", "price": 2.50},
                {"name": "Draw", "price": 3.20},
                {"name": "AC Milan", "price": 1.90}
            ]
        }]
    }]
}
        ↓
Canonical {
    "event_id": "event_id",
    "home_team": "Real Madrid",
    "bookmakers": [{
        "home_odds": 2.50,
        "draw_odds": 3.20,
        "away_odds": 1.90,
        ...
    }],
    ...
}
```

**Ventaja**: Agentes downstream trabajan con formato consistente, independiente del proveedor.

## 🔗 Patrón: Error Handling

### Non-Breaking Errors

```python
# Si Chile no disponible en football-data
try:
    result = fetch("CL")  # OK
except APIError as e:
    meta["errors"]["fixtures"]["CHI1"] = "No coverage in free tier"
    # ✓ Continúa con UCL (no botas todo el pipeline)
```

### Retry Logic

```python
for attempt in range(max_retries):
    try:
        data = http_client.get(url)
        return data
    except Timeout:
        if attempt < max_retries - 1:
            time.sleep(backoff_factors[attempt])
            continue  # Reintentar
        else:
            return error  # Max retries agotados
```

## 🎯 Testing

### Unit test agent en aislamiento

```python
# test_fixtures_agent.py

import pytest
from agents.fixtures_agent import FixturesFetcher

def test_fetch_matches():
    fetcher = FixturesFetcher(api_key="test_key")
    result = fetcher.fetch_matches_for_competition("CL")
    assert result["success"]
    assert len(result["data"]["matches"]) > 0

def test_normalize_fixtures():
    fetcher = FixturesFetcher()
    raw = [{
        "id": 123,
        "utcDate": "2024-01-15T20:00:00Z",
        "homeTeam": {"name": "Real"},
        "awayTeam": {"name": "Milan"},
        "status": "SCHEDULED"
    }]
    normalized = fetcher.normalize_fixtures(raw, "UCL", "CL")
    assert normalized[0]["home_team"] == "Real"
```

### Integration test (full pipeline)

```python
# test_pipeline_integration.py

import pytest
from graph_pipeline import PipelineExecutor, create_initial_state

@pytest.mark.asyncio
async def test_full_pipeline():
    competitions = [
        {"competition": "UCL", "competition_code": "CL"},
    ]
    initial_state = create_initial_state(competitions)
    executor = PipelineExecutor()
    result = executor.execute(initial_state)
    
    assert result["meta"]["total_fixtures"] > 0
    assert result["meta"]["total_odds"] > 0
    assert len(result["errors"]["fixtures"]) >= 0
```

## 🚀 Performance Optimization

### 1. Cache Strategy

```
First run:  fixtures_CL → API call (500ms) + odds_UCL → API call (400ms)
Second run: fixtures_CL → cache (10ms) + odds_UCL → cache (10ms)
                                    ↓
            Total time saved: ~880ms
```

### 2. Parallel Fetches

[Futuro] Usar concurrent.asyncio para:
```python
async def fetch_all_competitions():
    # Fetch fixtures + odds in parallel para cada competencia
    tasks = [
        fetch_fixtures("CL"),
        fetch_odds("UCL"),
        fetch_odds("CHI1")
    ]
    results = await asyncio.gather(*tasks)
```

### 3. Incremental Updates

[Futuro] Cache + delta updates:
```python
# En lugar de refetch todo, solo fetch nuevos/modificados desde last_sync
last_sync = cache.get_timestamp("fixtures_CL")
date_from = last_sync  # ← New API param
result = fetch(date_from=date_from)  # Only newer matches
```

## 📐 Logging Architecture

```python
# Cada módulo:
import logging
logger = logging.getLogger(__name__)

# Niveles usados:
logger.debug("Detailed trace (cache operations, retries internals)")
logger.info("Normal flow (agent steps, results, cache hits)")
logger.warning("Non-critical issues (429 retry, missing data)")
logger.error("Errors that don't halt pipeline (API 404 for one competition)")
logger.critical("Fatal errors (missing API key, etc.)")
```

## 🎓 Design Patterns Used

1. **TypedDict** para state type-safe
2. **Async/await** para future scaling
3. **Context managers** (__enter__/__exit__) para resource cleanup
4. **Factory pattern** (build_pipeline, create_initial_state)
5. **Retry pattern** con exponential backoff
6. **Cache-aside** pattern para disk caching

## 📝 Docstring Standards

Cada función tiene:

```python
def my_function(param1: str, param2: int) -> dict:
    \"\"\"
    Brief one-liner description.
    
    Longer description explaining purpose, use cases, and important considerations.
    
    Args:
        param1: Description of param1
        param2: Description of param2
    
    Returns:
        Description of return value structure:
        {
            "key": "example value if complex"
        }
    
    Raises:
        ValueError: When param1 is invalid
        APIError: When API call fails
    
    Example:
        >>> result = my_function("test", 42)
        >>> print(result["key"])
    
    Note:
        Important implementation details or gotchas.
    \"\"\"
```

## 🔮 Future Extensibility

### Adding new provider

```python
# agents/odds_agent_v2.py

class BetfairOddsFetcher:
    \"\"\"Fetch from Betfair instead of The Odds API\"\"\"
    
    def fetch_odds(self) -> dict:
        # ... Betfair-specific logic
        return normalized_to_canonical_format()
```

### Adding Geographic Filtering

```python
# state.py

AgentState = TypedDict({
    ...
    "geo_config": {
        "regions": ["EU", "US"],
        "countries": ["ES", "AR", "CL"]
    }
})
```

### Adding Real-time Webhooks

```python
# agents/webhook_listener.py

async def webhook_listener_node(state: AgentState) -> AgentState:
    \"\"\"Listen for odds movement events\"\"\"
    # Integra webhook para line movement notifications
    return state
```

---

**Key Takeaway**: La arquitectura es modular, resiliente y fácil de extender. Cada agente es independiente pero comparte estado de manera segura a través de TypedDict.

