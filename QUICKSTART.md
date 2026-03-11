# QUICK START - Agente #2 (Odds Fetcher) en 5 Minutos

## Paso 1: Instalar Dependencias (1 min)

```bash
# Crear virtual environment (opcional pero recomendado)
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt
```

## Paso 2: Configurar API Key (2 min)

```bash
# 1. Obtener API key
#    Ir a: https://the-odds-api.com
#    Registrarse (gratis, 500 calls/mes)
#    Copiar API key

# 2. Crear .env
cp .env.example .env

# 3. Editar .env con tu API key
#    Reemplazar: sk_live_YOUR_API_KEY_HERE
#    Con tu API key real
```

Archivo `.env` debe verse así:
```
ODDS_API_KEY=sk_live_tu_api_key_aqui_1234567890abcdef
ODDS_REGIONS=eu
ODDS_MARKETS=h2h
ODDS_FORMAT=decimal
ODDS_CACHE_TTL_SECONDS=600
ODDS_TIMEOUT_SECONDS=20
ODDS_RETRIES=2
```

## Paso 3: Validar Instalación (1 min)

```bash
# Ejecutar validación
python test_validation.py

# Output esperado:
# ✓ PASS: Imports
# ✓ PASS: Entorno
# ✓ PASS: Módulo Principal
# ✓ PASS: Construcción de Grafo
# ✓ PASS: Creación de Estado
# ✓ PASS: Validación API Key
# 
# Total: 6/6
# ✓ SETUP VÁLIDO - Listo para ejecutar
```

## Paso 4: Ejecutar el Agente (1 min)

```bash
# Ejecución simple
python run_graph.py

# Output esperado:
# ======================================================================
# INICIANDO EJECUCIÓN DEL GRAFO
# ======================================================================
# 
# RESUMEN - METADATOS
# ======================================================================
# Generado en: 2026-02-18T14:30:00Z
# Tiempo de procesamiento: 2.45s
# 
# Estadísticas:
#   Total eventos: 42
#   Llamadas API: 2
#   Cache hits: 0
# 
# Por competencia:
#   UCL: ✓ OK - 24 subEvents
#   CHI1: ✓ OK - 18 subEvents
# 
# ...
```

## ✓ ¡LISTO!

Ahora tienes:
- ✓ Grafo LangGraph construido
- ✓ Odds fetcher funcional
- ✓ Datos normalizados en `odds_canonical`
- ✓ Resultado guardado en `odds_result.json`

---

## Siguientes Pasos Opcionales

### Ver Ejemplos

```bash
python example_usage.py
```

Esto ejecuta 6 ejemplos de uso:
1. Standalone (sin fixtures)
2. Con fixtures (matching)
3. Competencias personalizadas
4. Metadatos y auditoría
5. Batch processing
6. Guardar en formatos custom

### Modificar Configuración

Edita `.env` para:
- Cambiar región (ODDS_REGIONS: "us", "br", etc.)
- Aumentar cache TTL (ODDS_CACHE_TTL_SECONDS: 3600)
- Reducir timeout (ODDS_TIMEOUT_SECONDS: 10)
- Filtrar bookmakers (ODDS_BOOKMAKERS: "draftkings,betmgm")

### Usar Fixtures Locales

Si tienes fixtures del Agente #1:

```bash
# 1. Coloca tu JSON en fixtures.json
#    Formato: [
#      {
#        "id": "fix_1",
#        "competition": "UCL",
#        "home_team": "Real Madrid",
#        "away_team": "Bayern",
#        "utcDate": "2026-02-25T20:00:00Z"
#      },
#      ...
#    ]

# 2. Ejecuta (auto-detecta fixtures.json)
python run_graph.py

# 3. El agente intenta matchear automáticamente
```

---

## Troubleshooting Rápido

| Problema | Solución |
|----------|----------|
| `ODDS_API_KEY not configured` | Edita `.env` y agrega tu API key |
| `ModuleNotFoundError: langchain` | Ejecuta `pip install -r requirements.txt` |
| `401 Unauthorized` | API key inválida, regenera en https://the-odds-api.com |
| `429 Rate Limited` | Espera 60s, o aumenta `ODDS_CACHE_TTL_SECONDS` |
| `TimeOut` | Aumenta `ODDS_TIMEOUT_SECONDS` en `.env` |

---

## Próximas Fases

Una vez que esto funcione:

1. **Agente #1 (Fixtures)**: Obtener fixtures desde football-data.org
2. **Agente #3 (Analyst)**: Usar odds + fixtures para predecir
3. **Dashboard**: Visualizar resultados
4. **BD**: Persistir histórico de odds

---

## Documentación Completa

Ver:
- [README.md](README.md) - Guía completa
- [ARCHITECTURE.md](ARCHITECTURE.md) - Arquitectura y extensiones
- [example_usage.py](example_usage.py) - 6 ejemplos prácticos
- [graph_odds_pipeline.py](graph_odds_pipeline.py) - Código fuente (bien comentado)

---

¡**Listo para empezar!** ✓
