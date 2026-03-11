"""
# 🎯 Multiagent Sports Betting Pipeline

Multiagent LangGraph pipeline para análisis de apuestas deportivas.

## 📊 Arquitectura

Pipeline orchestration:
```
START → Agente #1 (Fixtures) → Agente #2 (Odds) → END
```

### Agente #1: Fixtures Fetcher
- **Provider**: football-data.org API v4
- **Output**: Partidos programados (fixtures)
- **Competencias**: 
  - ✅ UEFA Champions League (CL)
  - ⚠️ Campeonato Chileno (si disponible en tier)

### Agente #2: Odds Fetcher
- **Provider**: The Odds API v4
- **Output**: Cuotas de apuestas normalizadas
- **Mercados**: h2h (1X2), decimales
- **Bookmakers**: 50+ operadores por evento

## 🛠️ Instalación

### 1. Crear Virtual Environment

```bash
python -m venv venv

# Windows
.\\venv\\Scripts\\Activate.ps1

# macOS/Linux
source venv/bin/activate
```

### 2. Instalar Dependencias

```bash
pip install -r requirements.txt
```

### 3. Configurar Variables de Entorno

#### Obtener API Keys

**Football-Data.org:**
1. Registrarse en https://www.football-data.org/client/register
2. Copiar API key
3. Agregar a `.env`:
   ```
   FOOTBALL_DATA_API_KEY=tu_clave_aqui
   ```

**The Odds API:**
- Ya configurado: `ODDS_API_KEY=ad1d775d001c9771a9467db8f7c3884d`

#### Ejemplo .env completo

```bash
# Fixtures
FOOTBALL_DATA_API_KEY=YOUR_KEY
FOOTBALL_DATA_BASE_URL=https://api.football-data.org
FIXTURES_STATUS=SCHEDULED
FIXTURES_TIMEOUT_SECONDS=20
FIXTURES_RETRIES=2
FIXTURES_CACHE_TTL_SECONDS=900

# Odds
ODDS_API_KEY=ad1d775d001c9771a9467db8f7c3884d
ODDS_BASE_URL=https://api.odds.to
ODDS_REGIONS=eu
ODDS_MARKETS=h2h
ODDS_TIMEOUT_SECONDS=20
ODDS_RETRIES=2
ODDS_CACHE_TTL_SECONDS=600
```

## 🚀 Ejecución Rápida

### Ejecutar pipeline completo

```bash
python run_pipeline.py
```

### Salida esperada

```
================================================================================
  SPORTS BETTING ANALYSIS - MULTIAGENT PIPELINE
================================================================================

📝 Loading environment configuration...
  ✓ All required environment variables are set

🔧 Initializing pipeline state...
  ✓ Initial state created

🚀 Executing multiagent pipeline...
============================================================
AGENTE #1: FIXTURES FETCHER (football-data.org)
============================================================

>>> Fetching UCL (code=CL)...
✓ UCL: 85 fixtures

>>> Fetching CHI1 (code=None)...
Skipping CHI1: No competition code available (may not be in free tier)

============================================================
AGENTE #2: ODDS FETCHER (The Odds API)
============================================================

>>> Fetching odds for UCL...
✓ UCL: 150 odds events

>>> Fetching odds for CHI1...
✓ CHI1: 123 odds events

📊 EXECUTION METADATA
  Total Fixtures: 85
  Total Odds Events: 273
  Processing time: 3.42s

✅ PIPELINE EXECUTION SUCCESSFUL
```

## 📂 Estructura de Directorios

```
Futbol/
├── agents/                      # Agentes del pipeline
│   ├── __init__.py
│   ├── fixtures_agent.py        # Agente #1 - Fixtures Fetcher
│   └── odds_agent.py            # Agente #2 - Odds Fetcher
├── utils/                       # Utilidades compartidas
│   ├── __init__.py
│   ├── cache.py                 # Caché en disco con TTL
│   └── http.py                  # Cliente HTTP resiliente
├── cache/                       # Caché de API (auto-generado)
│   ├── fixtures_CL_SCHEDULED.json
│   └── odds_UCL_h2h.json
├── state.py                     # Estado compartido (TypedDict)
├── graph_pipeline.py            # Orchestración LangGraph
├── run_pipeline.py              # Script de ejecución
├── requirements.txt
├── .env                         # Variables de entorno
├── .env.example                 # Template
└── README.md                    # Este archivo
```

## 📋 Formato de Datos

### Fixtures (Salida Agente #1)

```json
{
  "competition": "UCL",
  "provider": "football-data",
  "competition_code": "CL",
  "fixture_id": "300123456",
  "utc_date": "2024-01-15T20:00:00Z",
  "status": "SCHEDULED",
  "matchday": 1,
  "home_team": "Real Madrid",
  "away_team": "AC Milan",
  "venue": "Estádio de Luz",
  "season": 2023
}
```

### Odds (Salida Agente #2)

```json
{
  "competition": "UCL",
  "provider": "the_odds_api",
  "event_id": "evt_12345",
  "sport_key": "soccer_uefa_champs_league",
  "commence_time": "2024-01-15T20:00:00Z",
  "home_team": "Real Madrid",
  "away_team": "AC Milan",
  "bookmakers_count": 50,
  "bookmakers": [
    {
      "key": "bet365",
      "title": "Bet365",
      "home_odds": 2.50,
      "draw_odds": 3.20,
      "away_odds": 1.90
    },
    {
      "key": "betfair",
      "title": "Betfair",
      "home_odds": 2.45,
      "draw_odds": 3.25,
      "away_odds": 1.95
    }
  ]
}
```

### Estado Compartido (AgentState)

```python
{
  "messages": [...],                # Audit trail de LangChain
  "fixtures": [...],                # Fixtures normalizados
  "fixtures_raw": {"UCL": {...}},  # Raw responses por competencia
  "odds_raw": {"UCL": {...}},      # Raw responses por competencia
  "odds_canonical": [...],          # Odds normalizados
  "competitions": [...],            # Configuración
  "meta": {
    "total_fixtures": 85,
    "total_odds": 273,
    "fixtures_counts": {"UCL": 85, "CHI1": 0},
    "odds_counts": {"UCL": 150, "CHI1": 123},
    "cache_hits": {"fixtures": 1, "odds": 0},
    "errors": {
      "fixtures": {"CHI1": "No coverage..."},
      "odds": {}
    },
    "processing_time_seconds": 3.42
  }
}
```

## 🔄 Archivos de Caché

El sistema guarda respuestas en disco para minimizar llamadas API:

```bash
cache/
├── fixtures_CL_SCHEDULED.json     # 5 min (900s)
├── fixtures_CHI1_SCHEDULED.json
├── odds_UCL_h2h.json             # 10 min (600s)
└── odds_CHI1_h2h.json
```

### Limpiar caché

```python
from utils.cache import CacheManager

cache = CacheManager()
cache.clear()  # Borrar todo
cache.clear("fixtures")  # Borrar solo fixtures
```

## 💻 Uso Programático

```python
from graph_pipeline import PipelineExecutor, create_initial_state

# Definir competencias
competitions = [
    {"competition": "UCL", "fixtures_provider": "football-data", "competition_code": "CL"},
    {"competition": "CHI1", "fixtures_provider": "football-data", "competition_code": None}
]

# Crear estado inicial
initial_state = create_initial_state(competitions)

# Ejecutar pipeline
executor = PipelineExecutor()
result = executor.execute(initial_state)

# Acceder resultados
print(f"Fixtures: {len(result['fixtures'])}")
print(f"Odds: {len(result['odds_canonical'])}")
print(f"Errors: {result['meta']['errors']}")
```

## 🐛 Troubleshooting

### Error: "FOOTBALL_DATA_API_KEY not set"

**Solución**: Agregar a `.env`:
```bash
FOOTBALL_DATA_API_KEY=tu_clave_aqui
```

### Error: "No coverage available"

**Causa**: Campeonato Chileno no está disponible en el tier free de football-data.

**Solución**: 
- El pipeline continúa sin botar error
- Verifica `meta['errors']['fixtures']['CHI1']` para detalles
- Considera upgrade de plan o usar otro proveedor

### Error: 429 (Rate Limited)

**Causa**: API respondió con rate limit.

**Solución**:
- Aumenta `FIXTURES_CACHE_TTL_SECONDS` o `ODDS_CACHE_TTL_SECONDS`
- El sistema reintenta automáticamente
- Espera antes de siguiente invocación

### Cache inválido

```bash
# Borrar caché problemático
python -c "from utils.cache import CacheManager; CacheManager().clear()"
```

## 📊 Monitoreo

Ver estado del caché:

```python
from utils.cache import CacheManager

cache = CacheManager()
info = cache.get_cache_info()
print(f"Archivos en caché: {info['total_files']}")
for file in info['files']:
    print(f"  {file['name']}: {file['size_kb']}KB, {file['age_seconds']}s atrás")
```

## 🔐 Seguridad

- **Never** commit `.env` (incluido en `.gitignore`)
- **Never** hardcode API keys en código
- **Always** use environment variables
- **Rotate** API keys si están comprometidas

## 📈 Próximos Pasos

### Agente #3 (Analyzer)
- Input: fixtures + odds normalizados
- Output: predicciones sin recomendaciones de apuestas
- Status: Programado

### Extensiones
- Más competencias (La Liga, Serie A, etc.)
- Más mercados (spreads, totales, etc.)
- WebSocket para odds en vivo
- Persistencia en MongoDB

## 📞 Soporte

Para issues:
1. Verificar `.env` está correcto
2. Verificar API keys son válidas
3. Ver logs en `run_pipeline.py` output
4. Borrar caché y reintentar

## 📜 Licencia

Internal use only.

---

**Última actualización**: Febrero 2024
**Versión**: 2.0 (Multiagent Architecture)
