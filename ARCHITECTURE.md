# Arquitectura del Agente #2 (Odds Fetcher) - Guía para Desarrolladores

## 1. Visión General

El Agente #2 es un componente modular de un pipeline multiagente construido con **LangGraph**. Su responsabilidad es:

```
┌─────────────────────────────────────────────────────────┐
│  PIPELINE MULTIAGENTE (MVP)                             │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Agente #1          Agente #2            Agente #3      │
│  (Fixtures)      (Odds Fetcher)      (Analyst/Forecast) │
│  ────────────    ──────────────      ─────────────────  │
│  - Liga/CL        - The Odds API      - Probabilidad    │
│  - Equipos        - Champions League  - Predicción      │
│  - Fechas         - Liga Chilena      - Análisis        │
│  - Status         - Normalización     - Output: JSON    │
│  - Output: JSON   - Matching          - No apostar      │
│                   - Cache             - Input: odds+fix │
│                   - Output: canonical │                  │
│                   - Input: optional   │                  │
│                                                          │
│  Flow: Agente#1 output --→ Agente#2 --→ Agente#3       │
│                    (optional)                            │
└─────────────────────────────────────────────────────────┘
```

## 2. Componentes Principales

### 2.1 AgentState (TypedDict)

Define la estructura de datos que fluye por el grafo:

```python
class AgentState(TypedDict):
    messages: List[BaseMessage]           # Auditoría
    fixtures: Optional[List[dict]]        # Del Agente #1
    odds_raw: Optional[dict]              # Raw de API
    odds_canonical: Optional[List[dict]]  # Normalizado
    competitions: List[dict]              # Configuración
    meta: dict                            # Metadatos
```

**Flujo**: Estado entra en nodo → nodo modifica → estado sale

### 2.2 odds_fetcher_node

Nodo principal que realiza:

1. **Lectura de configuración**: `ODDS_API_KEY`, TTL, timeouts, etc.
2. **Loop de competencias**: Para cada competencia (UCL, CHI1):
   - Intenta cargar cache (hit → ahorra API call)
   - Si miss, llama API con reintentos
   - Normaliza respuesta
   - Matchea con fixtures (si existen)
   - Guarda cache
3. **Compilación de metadatos**: Counts, errores, timing
4. **Retorno**: State modificado

**Decisión de diseño**: Loop secuencial (no paralelo) para simplificar y mantener control de errores.

### 2.3 Flujo de Datos Detallado

```
inicial_state
    │
    ├─ messages: [msg1]
    ├─ fixtures: null o [fixture1, fixture2]
    ├─ competitions: [{"UCL": ...}, {"CHI1": ...}]
    └─ meta: {}
    │
    ▼
[odds_fetcher_node]
    │
    ├─ Para UCL:
    │   ├─ cache.load("soccer_uefa...") → MISS
    │   ├─ api.fetch(sport_key="soccer_uefa...") → success
    │   ├─ normalize_odds(raw_event1) → normalized_event1
    │   ├─ match_to_fixtures(normalized_event1, fixtures) → con fixture_match
    │   ├─ cache.save(raw_response)
    │   └─ agregar a canonical
    │
    ├─ Para CHI1:
    │   ├─ cache.load("soccer_chile...") → HIT
    │   ├─ skip API call (usa cache)
    │   ├─ normalize_odds (del cache)
    │   ├─ match_to_fixtures
    │   └─ agregar a canonical
    │
    └─ compilar meta + messages
    │
    ▼
final_state
    ├─ messages: [msg1, msg2(auditoría del nodo)]
    ├─ odds_raw: {"soccer_uefa...": raw_response, ...}
    ├─ odds_canonical: [event1, event2, ...]  ← para Agente #3
    └─ meta: {total_events: 42, cache_hits: 1, ...}
```

## 3. Anatomía de Funciones Clave

### 3.1 load_cache(sport_key, markets, regions, ttl_seconds) → Optional[dict]

**Propósito**: Evitar API calls al tener datos recientes en disco.

**Lógica**:
```
cache_path = "./cache/odds_<sport_key>_<markets>_<regions>.json"

if NOT existe(cache_path):
    return None  # cache miss

data = read_json(cache_path)
age = now - data["_cached_at"]

if age > ttl_seconds:
    return None  # expirado

return data  # cache hit ✓
```

**Costo**: 0 API calls cuando hit.

### 3.2 fetch_odds_from_api(...) → dict

**Propósito**: Obtener datos de The Odds API v4 con resiliencia.

**Resilience Pattern**:
```
intento = 0
while intento <= retries:
    try:
        response = requests.get(url, params, timeout)
        
        if status == 200:
            return {"success": True, "data": ...}
        elif status == 401:
            return {"success": False, "error": "Invalid key"} (fallback)
        elif status == 429:
            return {"success": False, "error": "Rate limited"} (no reintentar)
        elif status >= 500:
            dormir(2^intento)
            intento += 1
            continue
    except Timeout:
        dormir(2^intento)
        intento += 1
        continue

return {"success": False, "error": "Exhausted retries"}
```

**Notas**:
- No lanza excepciones (fail gracefully)
- Retorna dict con "success" flag
- Backoff exponencial: 1s, 2s, 4s, 8s...

### 3.3 normalize_odds(raw_event, competition, sport_key) → dict

**Propósito**: Convertir respuesta de The Odds API a formato canónico.

**Transformación**:
```
INPUT (The Odds API):
{
    "id": "abc123",
    "sport_key": "soccer_uefa_champs_league",
    "home_team": "Real Madrid",
    "away_team": "Bayern Munich",
    "commence_time": "2026-02-25T20:00Z",
    "bookmakers": [
        {
            "key": "draftkings",
            "title": "DraftKings",
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Real Madrid", "price": 2.45},
                        {"name": "Draw", "price": 3.20},
                        {"name": "Bayern Munich", "price": 2.90}
                    ]
                }
            ]
        }
    ]
}

↓ normalize_odds() ↓

OUTPUT (Canónico):
{
    "competition": "UCL",
    "provider": "the_odds_api",
    "sport_key": "soccer_uefa_champs_league",
    "event_id": "abc123",
    "commence_time": "2026-02-25T20:00:00Z",
    "home_team": "Real Madrid",
    "away_team": "Bayern Munich",
    "market": "h2h",
    "bookmakers": [
        {
            "key": "draftkings",
            "title": "DraftKings",
            "last_update": "...",
            "outcomes": [...]  # flatten outcomes a nivel de bookmaker
        }
    ],
    "fixture_match": None  # se llena en match_to_fixtures()
}
```

**Ventajas**:
- Agnóstico al proveedor (fácil agregar Betfair, USSF, etc.)
- Outcomes a nivel de bookmaker (no anidado)
- Timestamps normalizados

### 3.4 match_to_fixtures(odds_event, fixtures) → dict

**Propósito**: Enriquecer odds con contexto de fixtures.

**Algoritmo**:
```
best_match = None
best_score = 0.0

for fixture in fixtures:
    if fixture.competition != odds_event.competition:
        continue  # filtrar por competencia
    
    home_sim = similarity(odds.home_team, fixture.home_team)
    away_sim = similarity(odds.away_team, fixture.away_team)
    time_match = within_window(odds.time, fixture.time, hours=4)
    
    if home_sim > 0.70 AND away_sim > 0.70 AND time_match:
        score = (home_sim + away_sim) / 2
        if score > best_score:
            best_match = fixture
            best_score = score

if best_match:
    odds_event.fixture_match = {
        "matched": True,
        "fixture_id": best_match.id,
        "match_score": best_score
    }

return odds_event
```

**Características**:
- Best-effort (si no matchea, OK)
- Fuzzy matching de nombres (SequenceMatcher)
- Ventana de tiempo ±4 horas (configurable)
- Threshold 0.70 (balanceado)

## 4. Extensiones Futuras

### 4.1 Agregar Agente #3 (Analyst)

**Setup**:
```python
# En build_odds_fetcher_graph():
graph.add_node("analyst", analyst_node)
graph.add_edge("odds_fetcher", "analyst")
graph.add_edge("analyst", END)
```

**Interfaz esperada de Agente #3**:
```python
def analyst_node(state: AgentState) -> AgentState:
    # Input: state["odds_canonical"] (poblado por Agente #2)
    # Input: state["fixtures"] (opcional, del Agente #1)
    # Output: state["forecast"] o state["analysis"]
    # NO recomendaciones de apuestas (solo probabilidades)
    pass
```

### 4.2 Agregar Nuevo Proveedor de Odds

**Pasos**:

1. **Crear función fetch similar**:
```python
def fetch_odds_from_betfair(market_id, api_key, ...):
    # Llamar Betfair API
    # Retornar {"success": True/False, "data": ...}
    pass
```

2. **Normalizar al mismo formato canónico**:
```python
def normalize_betfair_odds(raw_event, competition, sport_key):
    # Convertir Betfair API schema a canónico
    # Mismo output que normalize_odds()
    pass
```

3. **Extender odds_fetcher_node**:
```python
def odds_fetcher_node(state: AgentState) -> AgentState:
    # Agregar bloque para cada proveedor
    if provider == "the_odds_api":
        raw = fetch_odds_from_api(...)
    elif provider == "betfair":
        raw = fetch_odds_from_betfair(...)
    
    # Normalizar y agregar a canonical
```

4. **Actualizar state["provider"]** en normalized output.

### 4.3 Agregar Caching en BDD

**Actualmente**: Cache en disco (local).

**Futuro**: Persistencia en BD:
```python
# Reemplazar load_cache/save_cache con:
def load_cache_db(sport_key, markets, regions, ttl):
    # Query: SELECT * FROM odds_cache WHERE sport_key=? AND age < TTL
    pass

def save_cache_db(data, sport_key, markets, regions):
    # INSERT INTO odds_cache VALUES (...)
    pass
```

### 4.4 Más Mercados (Spreads, Totals, etc.)

**Actualmente**: Solo "h2h" (1X2).

**Extensión**:
```python
# Config:
ODDS_MARKETS = "h2h,spreads,totals"

# odds_fetcher_node:
for market in ["h2h", "spreads", "totals"]:
    normalized = normalize_for_market(raw_event, market)
    # La estructura canónica ya soporta N mercados
```

## 5. Testing y Validation

### 5.1 Test Cases Principales

**test_validation.py** cubre:
```
[1] Imports: ¿Están las dependencias instaladas?
[2] Entorno: ¿.env configurado? ¿ODDS_API_KEY válida?
[3] Módulo: ¿Se importa graph_odds_pipeline?
[4] Grafo: ¿Se construye el StateGraph?
[5] Estado: ¿Se crea AgentState válido?
[6] API: ¿API key efectiva?
```

### 5.2 Propuesta de Unit Tests

```python
# tests/test_normalization.py
def test_normalize_odds_basic():
    raw = {...raw_event_from_api...}
    normalized = normalize_odds(raw, "UCL", "soccer_uefa_champs_league")
    
    assert normalized["competition"] == "UCL"
    assert normalized["market"] == "h2h"
    assert len(normalized["bookmakers"]) > 0
    
def test_normalize_odds_missing_fields():
    raw = {...incomplete_event...}
    normalized = normalize_odds(raw, "UCL", "soccer_uefa_champs_league")
    
    assert normalized is not None  # no crash

# tests/test_matching.py
def test_similar_team_name():
    assert similar_team_name("Real Madrid", "Real Madrid CF")
    assert not similar_team_name("Real Madrid", "Barcelona")

def test_time_within_window():
    t1 = "2026-02-25T20:00:00Z"
    t2 = "2026-02-25T21:30:00Z"  # 1.5 horas diferencia
    assert time_within_window(t1, t2, 4)  # Dentro de 4 horas

# tests/test_cache.py
def test_cache_save_load():
    data = {"results": [...]}
    save_cache(data, "soccer_uefa...", "h2h", "eu")
    loaded = load_cache("soccer_uefa...", "h2h", "eu", 600)
    
    assert loaded is not None
    assert loaded["results"] == data["results"]
```

### 5.3 Integration Test

```python
# tests/test_integration.py
def test_full_pipeline():
    graph = build_odds_fetcher_graph()
    
    state: AgentState = {...}
    result = graph.invoke(state)
    
    # Assertions
    assert result["meta"]["total_events"] > 0
    assert len(result["odds_canonical"]) > 0
    assert all("competition" in e for e in result["odds_canonical"])
```

## 6. Monitoreo y Observabilidad

### 6.1 Logging

```python
# Niveles:
logging.DEBUG    # Detalles internos (deshabilitar en prod)
logging.INFO     # Flujo normal
logging.WARNING  # Cosas que podrían ir mal
logging.ERROR    # Errores claros

# Ejemplos en código:
logger.info(f"Cache hit para {sport_key}")
logger.warning(f"Rate limited (429) por The Odds API")
logger.error(f"API key inválida: {e}")
```

### 6.2 Métricas en Meta

```
meta = {
    "generated_at": timestamp,
    "total_events": int,                 # KPI principal
    "cache_hits": int,                   # Eficiencia de cache
    "api_calls": int,                    # Costo de API
    "processing_time_seconds": float,    # Performance
    "errors": [error_list],              # Resiliencia
    "competitions": {comp: comp_meta}    # Granularidad
}
```

## 7. Decisiones de Diseño Explicadas

### ¿Por qué no LLM para obtener odds?

- No necesario: datos estructura
- Costo: LLM es ++caro que API
- Latencia: API es más rápido
- Confiabilidad: API > parsing de LLM

### ¿Por qué caching en disco?

- Simplicidad: no requiere BD externa
- Portabilidad: funciona en cualquier máquina
- Velocidad: IO local es rápido
- Futuro: fácil migrar a Redis/DB si crece

### ¿Por qué matching fuzzy?

- Nombres varían: "Real Madrid" vs "Real Madrid CF"
- Tiempo puede cambiar: ±4 horas es razonable
- Best-effort: si no matchea, ese OK
- No es crítico: es feature, no requirement

### ¿Por qué no parallelizar API calls?

- Complejidad: manejo de errores por request
- Rate limits: podría gatillar 429 más fácil
- Simplicidad MVP: preferimos código lineal y claro
- Futuro: fácil agregar si performance es issue

## 8. Performance y Escalabilidad

### Benchmarks Estimados

```
Sin cache (primera ejecución):
- 2 competencias: ~3-5 segundos
- 2 API calls: ~$0.004 costo

Con cache (hits):
- 2 competencias: ~0.1 segundos
- 0 API calls: $0 costo

Daily execution (24/7):
- TTL=600: ~4 calls/día = ~$0.008/día
- TTL=3600: ~1 call/día = ~$0.002/día
```

### Escalabilidad

```
Actual (MVP):
- 2 competiciones
- 1 mercado (h2h)
- 1 región (eu)
- ~40-100 eventos/consultá

Futuro:
- N competiciones (configurables)
- Múltiples mercados
- Múltiples regiones
- Proveedores en paralelo
- Histórico de cambios
```

---

**Fin de documento arquitectónico.**  
Cualquier pregunta, revisar commits en git o contactar equipo dev.
