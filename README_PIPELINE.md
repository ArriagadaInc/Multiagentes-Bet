# README Pipeline

Documento operativo del pipeline principal de `Multiagentes-Bet`.

Este archivo describe el flujo real de procesamiento, sus entradas, sus salidas y las reglas importantes que condicionan la ejecución.

## Propósito
El pipeline existe para transformar un conjunto heterogéneo de datos de fútbol en un `match_context` confiable por partido y, a partir de eso, producir:
- predicciones 1X2
- score estimado
- trazabilidad de decisiones
- recomendaciones de apuesta

No todo partido que aparece en fixtures termina siendo analizado. El sistema filtra por cuotas, calidad y contexto disponible.

## Flujo real
```text
Fixtures
  -> Web Fixtures / Web Odds fallback
  -> Odds
  -> prune_fixtures_node
  -> Stats
  -> Journalist
  -> Web
  -> Insights
  -> Normalizer
  -> Gate
  -> Analyst
  -> Bettor
  -> Reporter / persistencia
```

## Resumen por etapa
### 1. Fixtures Agent
- obtiene fixtures por competencia
- aplica ventanas por torneo
- normaliza partidos

### 1.1 Web Fixtures / Web Odds Fallback
- contingencia si faltan fixtures u odds
- útil en torneos con cobertura parcial

### 2. Odds Agent
- genera `odds_canonical`
- define el universo realmente apostable
- regla operativa: un partido no debe llegar al analista sin cuotas

### 3. `prune_fixtures_node`
- elimina fixtures sin cobertura real de cuotas
- evita que el pipeline completo se ensanche inútilmente

### 4. Stats Agent
- tabla, posición, GF/GC, forma y estadísticas verificables
- evita mezclar ligas o competencias distintas

### 5. Journalist Agent
- descubre videos y fuentes recientes
- usa bypass de caché para ahorrar consumo cuando ya existe análisis previo

### 6. Web Agent
- búsqueda web y scraping complementario
- actúa como respaldo contextual

### 7. Insights Agent
- fusiona señales desde:
  - YouTube
  - Web
  - noticia manual
  - historial persistente
- sanea y atomiza señales antes de consolidarlas

### 8. Normalizer Agent
- arma `match_contexts` canónicos
- cruza fixtures, odds, stats e insights
- reinserta historial persistente con filtros de higiene

### 9. Gate Agent
- filtro de calidad previo al analista
- estados habituales:
  - `clean`
  - `degraded`
  - `observation`
  - `dropped`

### 10. Analyst Agent
- genera predicción 1X2 y marcador sugerido
- usa el contexto consolidado y el estado del gate
- puede apoyarse en `Analyst Web Check`

### 11. Bettor Agent
- compara mercado vs probabilidad estimada
- detecta edge
- propone value bets y stakes
- además existe un flujo paralelo UI para `Betano Optimizer`

## Artefactos principales
El pipeline persiste artefactos intermedios para trazabilidad.

Ejemplos:
- `pipeline_fixtures.json`
- `pipeline_odds.json`
- `pipeline_stats.json`
- `pipeline_insights.json`
- `pipeline_match_contexts.json`
- `pipeline_predictions.json`
- `pipeline_bets.json`
- `pipeline_trace_report.json`

Flujos adicionales recientes:
- `pipeline_manual_odds.json`
- `pipeline_betano_ocr.json`
- `pipeline_betano_normalized.json`
- `pipeline_betting_portfolio.json`

## Inputs manuales soportados
### Noticias manuales
Archivo operativo:
- `data/inputs/manual_news_input.json`

Compatibilidad actual:
- texto libre
- texto guiado por equipo
- JSON válido

### Cuotas manuales desde imagen
- disponibles en la UI
- se persistían y luego se fusionan a `odds_canonical`

### Betano Optimizer
- OCR de boleta Betano
- cruce con predicciones vigentes
- optimización de bankroll desde UI

## Reglas operativas importantes
### 1. Cuotas mandan
Si no hay cuotas, el partido no debería llegar al analista.

### 2. El historial no se reinyecta ciegamente
Las señales persistentes pasan por filtros para evitar:
- pseudo-JSON
- blobs de calendario
- contexto macro mal guardado
- ruido histórico de bajo valor

### 3. El gate no es decorativo
Aunque el analista pueda trabajar con `degraded` u `observation`, el estado del gate afecta la lectura de confianza y la decisión de apuesta.

### 4. `COPA` y `CHI2` tienen reglas especiales de universo
Cuando existe universo manual de cuotas, el pipeline se restringe para no abrir partidos ajenos a la boleta/corrida deseada.

## Ejecución
### Pipeline principal
```powershell
python run_pipeline.py
```

### Desde Streamlit
```powershell
streamlit run app.py
```

### Bettor on-demand
```powershell
python run_bettor.py
```

## Configuración
Copiar `.env.example` a `.env` y completar según el entorno.

Variables típicas:
- `OPENAI_API_KEY`
- `GEMINI_API_KEY` o `GOOGLE_API_KEY`
- `ODDS_API_KEY`
- `FOOTBALL_DATA_API_KEY`

No versionar:
- `.env`
- caches de ejecución
- inputs manuales del usuario
- memoria operativa persistente
- uploads de imágenes

## Archivos de referencia
- `README.md`: visión general del sistema
- `agentes_flow.md`: descripción detallada del flujo actual
- `bitacora.md`: decisiones, fixes y cambios de arquitectura
