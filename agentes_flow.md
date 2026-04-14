# Arquitectura Multi-Agente - EvaluaPro (Futbol)

Documento de referencia del flujo actual del sistema: pipeline principal, memoria, guardrails, agentes auxiliares y notas operativas.

**Última actualización:** 2026-04-14 (v14.16 - Routing Selectivo LLM: Claude solo en Insights + Analyst)

## Visión General
El sistema separa responsabilidades en capas:

1. `Datos base`
   Fixtures + Odds + Stats.
2. `Contexto`
   YouTube + Web + noticias manuales + historial persistente.
3. `Consolidación`
   Construcción de `match_contexts` canónicos.
4. `Control de calidad`
   Partición epistemológica de señales + `Gate Agent`.
5. `Predicción`
   `analyst_agent` con contexto completo y `Analyst Web Check` on-demand.
6. `Decisión de apuesta`
   `bettor_agent` con matching canónico de mercado.
7. `Auditoría`
   `Trace Report`, `Rastreo`, reporter ASCII y memoria persistente.

---

## Mapa del Flujo

```mermaid
graph TD
    START((INICIO)) --> AG1[Fixtures Agent]
    AG1 --> AG11[Web Fixtures / Web Odds Fallback]
    AG11 --> AG2[Odds Agent]
    AG2 --> PRUNE[prune_fixtures_node]
    PRUNE -- sin cuotas --> END((FIN))
    PRUNE -- con cuotas --> ROUTER{should_continue}

    ROUTER -- no fixtures or no odds --> END
    ROUTER -- fixtures+odds --> AG3[Stats Agent]
    AG3 --> AG4[Journalist Agent]
    AG4 --> AG5[Web Agent]
    AG5 --> AG6[Insights Agent]
    AG6 --> AG7[Normalizer Agent]
    AG7 --> AG8[Gate Agent]
    AG8 --> AG9[Analyst Agent]
    AG9 --> AG10[Bettor Agent]
    AG10 --> REP[Reporter / Persistencia]
    REP --> END

    HIST[(team_history.json)] -. historial .--> AG6
    HIST -. reinyección filtrada .--> AG7
    AG9 -. on demand .--> WC[Analyst Web Check]
    WC -. señales verificadas .--> AG9

    CACHE[(youtube_insights_cache.json)] -. bypass conocidos .--> AG4
```

---

## Pipeline Principal

### 1. Fixtures Agent
- Fuente primaria de fixtures por competencia.
- Normaliza partidos a formato canónico.
- Entrega `fixtures` al pipeline.

### 1.1 Web Fixtures / Web Odds Fallback
- Capa de resiliencia si faltan fixtures u odds.
- Para CHI2 se usa además como camino de contingencia cuando no hay cobertura nativa de cuotas.
- Registra auditoría por partido en `web_odds_audit`.

### 2. Odds Agent
- Fuente primaria de cuotas de mercado.
- Entrega `odds_canonical`.
- Regla de oro vigente:
  - **ningún partido llega al Analista sin cuotas de mercado**.

### 3. Stats Agent
- Agrega tabla, rendimiento, goles, posición y stats verificables.
- Tiene guardrails para evitar contaminación cross-competition.

### 4. Journalist Agent
- Descubre y prioriza videos / fuentes periodísticas.
- Alimenta la capa de contexto con material reciente.
- **LLM:** usa perfil `journalist_fast` → `gpt-4o-mini` (OpenAI), independiente de `EXPENSIVE_MODE`.
- **Bypass de caché (v14.15):** Antes de curar videos con LLM, cruza los `video_id` contra `youtube_insights_cache.json`. Los videos ya procesados se aceptan sin gastar tokens (`[CACHE HIT BYPASS]`).
- **Salida persistida:** `pipeline_journalist.json` (habilita el botón de Pipeline Parcial en Streamlit).

### 5. Web Agent
- Complementa contexto con búsqueda web y scrapers directos.
- Sirve como respaldo cuando YouTube aporta poco o falla.

### 6. Insights Agent
Responsabilidad:
- fusionar señales desde:
  - `YouTube`
  - `Web`
  - `Noticias Manuales`
  - `History`

Capacidades actuales:
- deduplicación y saneamiento semántico
- soporte para noticia manual en 3 modos:
  - `texto libre`
  - `texto limpio guiado`
  - `JSON válido`
- saneamiento pre-gate de señales contaminadas

#### 6.1 Noticia Manual
Entrada:
- `data/inputs/manual_news_input.json`

Compatibilidad vigente:
- texto libre
- texto limpio con secciones por equipo
- JSON válido estructurado

Formato recomendado:
- encabezados por torneo / partido / equipo
- bloque de señales por equipo
- una señal por línea
- texto atómico, sin tablas ni pseudo-JSON

Parser tolerante:
- si el texto viene limpio, extrae mejor
- si viene libre, no rompe compatibilidad
- si detecta JSON válido, usa el parser estructurado

Guardrails:
- descarta pseudo-JSON
- descarta calendarios cruzados
- descarta contexto macro del torneo como señal de equipo
- descarta blobs largos de baja atomicidad

### 7. Normalizer Agent
Responsabilidad:
- construir `match_contexts` canónicos por partido
- unir fixtures, odds, stats e insights
- generar `match_id` y `match_key` estables
- particionar señales limpias vs sospechosas

#### 7.1 Reinyección de historial
El normalizador reinyecta contexto persistente desde `team_history.json`, pero ya no lo hace de forma ciega.

Guardrails activos:
- bloquea pseudo-JSON histórico
- bloquea calendarios cruzados
- bloquea contexto macro del torneo persistido como señal de equipo
- bloquea señales manuales viejas demasiado largas
- bloquea entradas de bajo valor tipo:
  - `sin parte médico nuevo`
  - `enfermería prácticamente vacía`
  - `sin bajas estructurales nuevas`
- bloquea contexto viejo de copas sin valor pre-match claro:
  - `EFL Cup`
  - `Carabao Cup`

Decisión arquitectónica confirmada:
- **no basta con sanear en `insights_agent`; también hay que blindar la reinyección desde `team_history` en `normalizer_agent`.**

### 8. Gate Agent
Responsabilidad:
- filtro de completitud y evaluador cualitativo pre-analista
- aplica reglas de degradación según calidad de stats, señales y mercado

Estados posibles:
- `clean` (buena calidad)
- `degraded` (incertidumbre media)
- `observation` (incertidumbre alta o baja calidad)
- `dropped` (solo si faltan cuotas de mercado)

Aprendizaje confirmado (v14.12):
- El Gate dejó de ser un bloqueador estricto. Partidos con baja calidad o stats faltantes se marcan como `observation` y avanzan al Analista, delegando en el LLM la valoración final de la incertidumbre.

### 9. Analyst Agent
Responsabilidad:
- producir predicción 1X2 y score estimado
- analizar la certidumbre/calidad promedio de las señales a través del `signal_quality_comment` (v14.12)
- penalizar la confianza (`confidence`) si el Gate detectó "niebla informativa"
- apoyarse en `match_context` validado por el Gate

Capacidades:
- matching canónico con `match_id` / `match_key`
- uso explícito de `Analyst Web Check`
- persistencia de señales útiles derivadas del `web_check`
- bitácora de necesidades del analista
- traza completa para `Trace Report`

**LLM (v14.15):**
- `EXPENSIVE_MODE=false`: Gemini Flash → fallback automático a `gpt-4o-mini` si Gemini falla.
- `EXPENSIVE_MODE=true`: `claude-sonnet-4-6` (Anthropic) — máxima calidad analítica.

**Fallback heurístico (Plan Z):**
Cuando el LLM falla o devuelve JSON inválido, el Analista cae a heurística basada en posición y forma:
- La fecha se extrae de `utc_date` del fixture (fix v14.15, evita `"?"`)
- Los campos `form` del API se normalizan a `""` si llegan `None` (fix v14.14, evita `AttributeError`)
- El rationale heurístico es primitivo pero no colapsa la aplicación

#### 9.2 Etiquetado de tabla por competencia
- el analista no debe reinterpretar stats continentales como si fueran tabla doméstica
- cuando el dato viene de `UCL`, la posición debe tratarse como:
  - `POSICIÓN EN TABLA UCL (fase liga previa)`
- decisión confirmada:
  - la competencia de origen de la tabla debe viajar explícita hasta el prompt
  - así se evita narrativa errónea tipo `9º en liga` cuando el dato real era `UCL position=9`

#### 9.1 Analyst Web Check
- verificación web puntual on-demand
- cacheado con TTL para evitar gasto repetido
- sus respuestas útiles pueden persistirse a historial
- se evita repetir la misma duda si ya está resuelta en memoria reciente

### 10. Bettor Agent
Responsabilidad:
- comparar predicción vs mercado
- decidir si hay valor de apuesta

Capacidades:
- matching canónico de predicción con odds
- trazabilidad del input y output en `Trace Report`
- respeto por `Gate` y restricciones de riesgo

---

## Memoria del Sistema

### `team_history.json`
- memoria episódica por equipo
- almacena señales históricas reutilizables
- ahora cuenta con doble defensa:
  1. saneamiento al persistir / consumir en `insights_agent`
  2. saneamiento al reinyectar en `normalizer_agent`
- ubicación canónica:
  - `data/knowledge/team_history.json`
- backups automáticos:
  - `data/knowledge/backups/`

### `analyst_web_check_cache.json`
- cache de verificaciones web del analista
- reduce repetición y consumo innecesario

### `analyst_wishlist.json`
- wishlist / necesidades del analista para futura investigación

### `analyst_memory.json`
- memoria de lecciones o heurísticas del analista

---

## Observabilidad y UI

### Rastreo de Agentes
- muestra flujo por partido
- visible en Streamlit

### Trace Report
- persistido en `pipeline_trace_report.json`
- muestra input/output por etapa
- foco especial en:
  - `analyst_agent`
  - `bettor_agent`
  - `gate_agent`

### Insights Persistentes
- pestaña de Streamlit para mantenimiento de memoria persistente
- trabaja directamente sobre `team_history.json`
- permite:
  - editar señales persistidas
  - eliminar señales malas
  - guardar con backup automático
- objetivo:
  - auditar memoria viva del sistema
  - corregir o purgar señales antes de su reinyección al pipeline

### OCR de cuotas manuales
- pestaña separada: `Cuotas Manuales`
- permite subir imagen, revisar OCR y ejecutar pipeline
- pensado como contingencia para ligas con pobre cobertura de odds
- regla operativa consolidada para `COPA` y `CHI2`:
  - si existen cuotas manuales recientes, ese universo manual manda
  - aplica tanto en modo barato como en modo caro
  - implica recorte de:
    - `fixtures` efectivos
    - `odds_canonical`
    - scope de `journalist_agent`
    - scope de `web_agent`
    - fallback web de cuotas

### Agente Revisor / Evaluador
- standalone
- fuera del pipeline principal
- compara predicciones históricas con resultados reales

---

## LLM Factory (`utils/llm_factory.py`)

Sistema centralizado de enrutado de LLMs. Todos los agentes deben usar `get_llm()` para instanciar modelos.

### Regla Fundamental (v14.16)
> **Claude (`claude-sonnet-4-6`) está reservado EXCLUSIVAMENTE para `insights_core` y `analyst_core`.**
> Activar `EXPENSIVE_MODE=true` no afecta a ningún otro agente.

### Matriz de Routing Completa

| Perfil | `EXPENSIVE_MODE=false` | `EXPENSIVE_MODE=true` | Agente Consumidor |
|---|---|---|---|
| `insights_core` | Gemini Flash | **Claude claude-sonnet-4-6** | Insights Agent |
| `analyst_core` | Gemini Flash | **Claude claude-sonnet-4-6** | Analyst Agent |
| `journalist_fast` | gpt-4o-mini | gpt-4o-mini | Journalist Agent |
| `web_research_forced` | gpt-4.1 | gpt-4.1 | Web Agent |
| `tournament_research_gpt51` | gpt-5.1 | gpt-5.1 | Tournament Research |
| `default` (sin perfil) | Gemini Flash | Gemini Flash | Gate, Bettor, otros |

### Fallback Automático (modo barato)
Cuando Gemini falla (Rate Limit / ResourceExhausted):
```
Gemini Flash → falla → gpt-4o-mini (OpenAI) → resultado
```
El fallback es transparente: el agente no sabe qué modelo lo resolvió.

### Variables de Entorno Relevantes
```
GEMINI_API_KEY / GOOGLE_API_KEY   # Requerida en modo barato (Gemini)
OPENAI_API_KEY                    # Requerida para fallback y perfiles OpenAI
ANTHROPIC_API_KEY                 # Requerida en modo caro (Claude)
EXPENSIVE_MODE=false/true         # Activa Claude SOLO en insights_core + analyst_core
ANTHROPIC_MODEL=claude-sonnet-4-6  # Modelo Claude (opcional, este es el default)
GEMINI_MODEL=gemini-flash-latest  # Modelo Gemini (opcional)
FALLBACK_MODEL=gpt-4o-mini        # Modelo fallback OpenAI (opcional)
JOURNALIST_MODEL=gpt-4o-mini      # Modelo del periodista (opcional)
```

> [!IMPORTANT]
> Al agregar variables al `.env` en Windows PowerShell, **NO usar** `echo VAR >> .env`.
> PowerShell escribe en UTF-16-LE con bytes nulos que rompen python-dotenv.
> Usar edición directa del archivo o `Add-Content -Encoding utf8`.

---

## Pipeline Parcial (Modo de Recuperación)

Cuando el Periodista (YouTube) tiene éxito pero el Analista falla por Rate Limit:

1. La salida del Periodista se persiste en `pipeline_journalist.json`.
2. Desde la UI Streamlit: botón **"EJECUTAR PARCIAL (DESDE PERIODISTA)"**.
3. Script: `run_pipeline_from_journalist.py` — carga los artefactos y reanuda desde Insights.

```bash
# Equivalente por CLI:
python run_pipeline_from_journalist.py \
  --journalist pipeline_journalist.json \
  --odds pipeline_odds.json \
  --stats pipeline_stats.json
```

---

## Reglas de Diseño Confirmadas

1. No llega al analista ningún partido sin cuotas de mercado.
2. El texto manual debe seguir aceptando texto libre.
3. El formato limpio guiado tiene prioridad operativa porque reduce ruido.
4. Las señales históricas no se deben reinyectar ciegamente.
5. El fuzzy matching es fallback; primero van `match_id`, `match_key` y nombres canónicos.
6. En `COPA` y `CHI2`, `fixtures.json` no debe ensanchar artificialmente la corrida.
7. En `COPA`, si hay cuotas manuales recientes, `odds_canonical` se recorta al universo manual antes de `journalist`, `web_agent`, `normalizer` y `gate`.

---

## Nota Operativa Validada - UCL 2026-04-13
Se validó una corrida completa con:
- `fixtures=4`
- `odds=4`
- `stats=8`
- `insights=8`
- `predictions=4`

La causa del problema previo de `0 predicciones` fue:
- memoria histórica contaminada reinyectada al `MatchContext`
- más falsos positivos del `signal_partitioner`

La corrección efectiva fue:
1. mejorar parser y saneamiento de noticia manual en `insights_agent`
2. filtrar reinyección histórica en `normalizer_agent`
3. bajar falsos positivos en `utils/signal_partitioner.py`

Resultado final validado:
- `Gate`: 4 partidos pasados, 0 bloqueados
- `Analyst`: 4 predicciones generadas

---

## Nota Operativa Validada - COPA 2026-04-14
Se validó una corrida de `COPA` con prioridad de universo manual:
- `fixtures=16`
- `odds=3`
- `gate entrada=6`
- `predictions=5`

Problemas corregidos en esta línea:
1. `fixtures.json` ensanchaba la corrida y forzaba ventanas largas.
2. `odds_agent` seguía metiendo todos los eventos API aunque el usuario hubiera cargado cuotas manuales.
3. `journalist_agent` y `web_agent` heredaban un universo demasiado ancho para `COPA`.

Corrección efectiva:
1. `run_pipeline.py`
   - `COPA` y `CHI2` ignoran `fixtures.json` para bootstrap de ventana.
2. `agents/odds_agent.py`
   - `COPA` recorta `odds_canonical` al universo manual cuando existe.
3. `agents/web_fixtures_agent.py`
   - fallback web de cuotas limitado al universo manual de `COPA`.
4. `agents/journalist_agent.py`
   - `COPA` usa queries de Libertadores y scope reducido al universo manual.
5. `agents/web_agent.py`
   - `COPA` investiga solo el subconjunto manual cuando existe.

Resultado operativo:
- el pipeline dejó de inflarse por partidos fuera del universo deseado
- el `gate` pasó a trabajar con un set compacto y limpio
- la corrida quedó estable tanto en modo barato como en modo caro

---

## Archivos Clave
- `agents/journalist_agent.py` — descubrimiento de videos + curaduría con caché bypass
- `agents/insights_agent.py` — síntesis de señales desde YouTube/Web/Manual/History
- `agents/normalizer_agent.py` — construcción de match_contexts canónicos
- `agents/gate_agent.py` — control de calidad pre-analista
- `agents/analyst_agent.py` — predicción LLM + fallback heurístico
- `agents/bettor_agent.py` — decisión de apuesta con matching canónico
- `utils/llm_factory.py` — enrutado centralizado de LLMs (Multi-LLM v14.15)
- `utils/signal_partitioner.py` — partición epistemológica de señales
- `graph_pipeline.py` — grafo LangGraph con nodo `prune_fixtures_node`
- `run_pipeline.py` — ejecutor principal, exporta todos los artefactos intermedios
- `run_pipeline_from_journalist.py` — modo de recuperación parcial
- `prompts/evaluate_ocr.txt` — prompt principal de evaluación de exámenes
- `bitacora.md` — log maestro de sesiones y hitos


## Extensi?n UI - Betano Optimizer
Se a?adi? una capacidad paralela al flujo principal para casos donde el usuario trae una captura real de cuotas Betano.

Flujo:
1. `agents/betano_ocr_agent.py`
   - extrae cuotas `1X2` desde imagen
2. `utils/bet_slip_normalizer.py`
   - mapea las filas OCR al universo actual de `pipeline_predictions` + `pipeline_match_contexts`
3. `utils/probability_calibration.py`
   - recalibra la confianza del analista a probabilidad utilizable
4. `agents/bettor_agent.py`
   - helpers de optimizaci?n de bankroll:
     - simples con Kelly fraccional
     - combinadas 2-leg limitadas
5. `app.py`
   - pesta?a `Betano Optimizer`
   - persiste:
     - `pipeline_betano_ocr.json`
     - `pipeline_betano_normalized.json`
     - `pipeline_betting_portfolio.json`

Regla arquitect?nica:
- esta capacidad NO reemplaza el `bettor_agent_node` del pipeline principal
- vive como m?dulo opt-in para el caso de uso ?tengo una boleta real y quiero optimizar 10000 CLP con las probabilidades del sistema?
