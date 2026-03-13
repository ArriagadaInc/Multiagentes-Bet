## Sesión: Roadmap Fase 2 - Robustez Arquitectónica (10-Mar-2026) 🧠🛡️
💻 **Repositorio Oficial:** [ArriagadaInc/Multiagentes-Bet](https://github.com/ArriagadaInc/Multiagentes-Bet)

### 📌 Hitos Recientes de la Fase 2
- **Micro-tarea 6 (Modo Económico Dual OpenAI/Gemini)**: Implementación quirúrgica de un `llm_factory.py` y una variable de entorno `EXPENSIVE_MODE` (controlable via UI en `app.py`). Todos los agentes (`analyst`, `insights`, `evaluator`, `journalist`) fueron refactorizados para consumir el factory sin romper los contratos estrictos de LangChain (`bind_tools`, `with_structured_output`). Ahora se puede procesar con **GPT-5** (por defecto) o **Gemini 2.5 Flash-Lite** para escalar y abaratar costos manteniendo interoperabilidad. Autenticación con `GEMINI_API_KEY` o `GOOGLE_API_KEY` asegurada.
- **Micro-tarea 4.1 (Afinamiento de Sospecha)**: Lógica refinada para `is_suspicious`. Reducción pragmática de falsos positivos en `unknown_scope` limitándolos a señales empíricamente accionables (lesiones, rotaciones, fatiga). Deduplicación cruzada activada filtrando caracteres especiales y equivalencias.
- **Micro-tarea 5 (Aduana de Roster & Oponente)**: Creación de memoria de observación de "Entities" por equipo para el partido. Si un jugador es mencionado en el contexto de "home" pero solo fue detectado en "away", dispara gravedad `foreign_entity_in_team_signal`. El mismatch de `subject_type` ahora tolera menciones legítimas ("opponent_form") que no vienen estructuradas.

### 🎯 Idea rectora
No queremos meter "más IA" por meterla. Buscamos que el sistema sea más confiable, más auditable y menos vulnerable a señales contaminadas o a confianzas ficticias.

### 📝 Tareas para mejorar el modelo

| Estado | Tarea | Objetivo |
| :--- | :--- | :--- |
| ✅ | **1. Auditoría plana de señales antes del Analista** | Ver exactamente qué señales le están llegando al Analista, de qué fuente, equipo asociado y detectar ruido o cross-talk antes de tocar la lógica (`pipeline_signals_audit.json`). |
| ✅ | **2. Detección de señales sospechosas por partido** | Marcar silenciosamente señales dudosas (`is_suspicious`) usando 10 reglas clave: `foreign_entity`, deduplicación semántica cruzada, alerta de historia obsoleta, `subject_type_mismatch` y fechas omitidas, con radar contextual de rival. |
| ✅ | **3. Cuarentena de señales dudosas** | Primer paso de segregación listado. Separadas en `signals_clean` y `signals_suspicious` sin alterar el prompt del Analista ni borrar nada, pero apartadas para evitar que el Analista las lea como hecho puro. |
| ⏳ | **4. Validación básica de entidades** | Impedir errores groseros como jugadores en clubes equivocados, equipos confundidos o señales asociadas al partido incorrecto. |
| ⏳ | **5. Gate de calidad real, no decorativo** | Reemplazar la nota genérica actual por una evaluación de integridad de entidades, frescura, rumor, conflicto y riesgo manual. |
| ⏳ | **6. Brief estructurado para el Analista** | Enviar un expediente ordenado con hechos confirmados, conflictos y alertas en lugar de una bolsa de señales mezcladas. |
| ⏳ | **7. Endurecer el manejo del input manual** | Las noticias manuales no deben entrar con "autoridad automática". Deben ser trazables y pedir corroboración si son críticas. |
| ⏳ | **8. Hacer que el Bettor use la calidad del input** | Que no se apueste igual en un partido limpio que en uno contaminado. Afectar skip, edge mínimo y stake con la calidad de datos. |
| ⏳ | **9. Separar convicción narrativa de probabilidad apostable** | Dejar de tratar la confidence del LLM como probabilidad matemática real. Primero juicio experto; después, probabilidad calibrada. |
| ⏳ | **10. Calibración empírica y uso del mercado como ancla** | Que el sistema ajuste con disciplina una base de mercado preexistente según evidencia en lugar de "inventar" porcentajes absolutos. |
| ⏳ | **11. Clasificación por nivel de apostabilidad** | Distinguir partidos premium, tradable, experimental o skip, evitando que el sistema mezcle picks fuertes con exploratorios. |
| ⏳ | **12. Métricas de calidad más profundas** | Medir calibración, rendimiento por calidad de input, por conflicto y por fuente, dejando de mirar únicamente el ROI o acierto bruto. |

---

## Sesión: Panorama General, Debugging de Agentes y Dashboard (06-Mar-2026) ⚽📊🧠
### 🎯 Problemas Detectados y Resueltos
1.  **Falta de Contexto Macro**: El Analista no consideraba la situación de la tabla ni la importancia de la jornada.
2.  **Regresiones en Agentes**: Errores `AttributeError` en Insights y Analista debido a cambios en los tipos de datos del caché y payloads.
3.  **Dashboard Desincronizado**: La pestaña de Rastreo mostraba videos de prueba o fallaba al renderizar citas de YouTube en formato mixto (string/dict).
4.  **Error de Mapeo (UC)**: Universidad Católica no mostraba estadísticas debido a una colisión en la blacklist del normalizador con el sufijo `(CHI)`.

### ✅ Soluciones Implementadas
1.  **Integración Panorama General**: ...
2.  **Robustez de Datos**: ...
3.  **Refactor UI (`app.py`)**:
    *   Visualización de videos reales desde el `MatchContext`.
    *   Manejo flexible de citas de YouTube.
    *   **Estrategias Duales**: Implementación de pestañas separadas para "Construir Banca" y "La Pasada".
4.  **Estrategias de Apuesta (`bettor_agent.py`)**:
    *   **Banca**: Filtro de 60%+ confianza, cuotas moderada (1.40-2.10) y stake estable.
    *   **La Pasada**: Agrupa combinadas y singles de alta cuota (> 2.20) con stake agresivo.
5.  **Normalización Inteligente**: ...

### 📁 Archivos Modificados
| Archivo | Cambios |
|---|---|
| `agents/web_agent.py` | Extracción de `competition_summary`. |
| `agents/insights_agent.py` | Inyección de panorama y fix de regresión por caché. |
| `agents/analyst_agent.py` | Razonamiento context-aware y fix de `odds` variable. |
| `app.py` | Fix de videos, citas, NameError y validación de tipos. |
| `agents/normalizer_agent.py` | Suavizado de Regla 3 para Universidades. |
| `utils/chi1_golden_mapping.json` | Nuevos alias regionales. |
| `agentes_flow.md` | Documentación de persistencia y flujo de datos. |

### 📝 Resultado
El pipeline es ahora más inteligente (entiende la liga) y mucho más estable. El Dashboard es una herramienta de trazabilidad real y confiable.

---

## Sesión: Optimización de Cuota por Liga Activa (05-Mar-2026) 📉🛡️

### 🎯 Problema
El sistema realizaba búsquedas de videos (YouTube) y contexto web para todas las competencias configuradas (`CHI1` y `UCL`) en cada ejecución, incluso si el usuario solo estaba interesado en una de ellas. Esto generaba un gasto innecesario de cuota de API y tokens del LLM.

### ✅ Solución
Se implementó un filtrado estricto por **Liga Activa** en los agentes de entrada:
1.  **Agente Periodista (`journalist_agent.py`)**: Ahora detecta las competencias presentes en los partidos cargados (`odds_canonical`) y descarta automáticamente las configuraciones de búsqueda para ligas no activas.
2.  **Agente Web (`web_agent.py`)**: Se reforzó la lógica para que las búsquedas mediante `web_search` solo se disparen para las ligas que realmente se están analizando en el run actual.

### 📁 Archivos Modificados
| Archivo | Cambios |
|---|---|
| `agents/journalist_agent.py` | Filtrado dinámico de `comp_configs` según partidos del run. |
| `agents/web_agent.py` | Refuerzo de `active_comp_keys` basado en `odds_canonical`. |

### 📝 Resultado
Ahorro significativo de créditos en OpenAI y YouTube API cuando se trabaja con una sola liga (ej. solo `CHI1` o solo `UCL`). El sistema es ahora más eficiente y cuida el presupuesto del proyecto.

---

## Sesión: Optimización y Persistencia del Agente Web (05-Mar-2026) ⚽🌐🧠

### 🎯 Problema
El Agente Web ignoraba noticias de último minuto críticas (como la eliminación de la U de Chile en Copa Libertadores) debido a un error en el prompt ("partidos anteriores" en lugar de próximos) y a un alcance de búsqueda muy restrictivo. Además, los hallazgos de la web no se persistían adecuadamente, lo que los hacía volátiles ante la ventana de búsqueda de 48h.

### ✅ Solución
1.  **Optimización de Prompt (`web_agent.py`)**: Se eliminó el typo y se instruyó al agente a buscar noticias de las últimas 24-48 horas en **cualquier competencia** (nacional o internacional).
2.  **Puente de Persistencia (`insights_agent.py`)**: Se corrigió el mapeo de claves (`raw_context` y `last_result`) para que el Agente de Insights recoja y fusione los datos de la web.
3.  **Memoria de Largo Plazo**: Se aseguró que estos insights se guarden en `data/knowledge/team_history.json`, permitiendo que el Analista mantenga el contexto incluso cuando la noticia ya no es "tendencia" en la web.

### 📁 Archivos Modificados
| Archivo | Cambios |
|---|---|
| `agents/web_agent.py` | Prompt optimizado, corrección de typo y alcance ampliado. |
| `agents/insights_agent.py` | Fix en mapeo de claves (`raw_context`, `last_result`) y refuerzo de persistencia. |

### 📝 Resultado
Se verificó mediante tests que el sistema ahora detecta y **recuerda** eventos como la eliminación internacional de equipos, incluso si el run se realiza días después de la noticia original.

---

## Sesión: Aclaración de Roles y ADN (05-Mar-2026) 🧬

### 🎯 Aclaración Importante
Se establece formalmente que el equipo de trabajo está compuesto exclusivamente por:
- **Álvaro**: Interlocutor y tomador de decisiones.
- **Germán**: Agente de IA (Yo).

**Nota de ADN**: "Gepeto" no existe en este contexto. Todas las referencias anteriores a dicho rol quedan invalidadas y deben ser eliminadas de la documentación futura.

---

## Sesión: Corrección de Mezcla de Datos (Larrivey/Limache) y Mejoras UCL (05-Mar-2026) 🐛⚽

### 🎯 Problema
El Agente Revisor (`run_reviewer.py`) fallaba al escribir emojis en el log de consola de Windows. La codificación por defecto de la consola (`cp1252`) no soporta caracteres Unicode como 🔍, 📂, ✅, 🧠, etc.

```
UnicodeEncodeError: 'charmap' codec can't encode character '\U0001f50d'
```

### ✅ Solución
En `run_reviewer.py`, se reemplazó el `StreamHandler(sys.stdout)` por un wrapper explícito en `utf-8`:

```python
import io
if hasattr(sys.stdout, "buffer"):
    _utf8_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
else:
    _utf8_stdout = sys.stdout

logging.StreamHandler(_utf8_stdout)  # en lugar de sys.stdout directo
```

### 📁 Archivos Modificados
| Archivo | Cambios |
|---|---|
| `run_reviewer.py` | Forzar UTF-8 en StreamHandler de stdout |

### 📝 Nota adicional
Las 21 predicciones marcadas como `skipped` en el mismo log **no son un error** — el Post-Match Agent no sobreescribe resultados ya evaluados. Si se necesita forzar re-evaluación, se puede agregar un flag `--force` al script en el futuro.

---

## Sesión: Integración Web Agent + Prompts de Élite + Bitácora del Analista (02-Mar-2026) 🌐🧠✒️

### 🎯 Objetivos Logrados

#### 1. Web Agent Integrado Permanentemente al Pipeline Principal

- **`agents/web_agent.py`** completamente reescrito:
  - **1 llamada por torneo** (CHI1 + UCL = máximo 2 llamadas), no una por partido
  - Prompt **dinámico por jornada**: se construye desde `state["odds_canonical"]` — sabe exactamente qué equipos juegan y cuándo
  - Busca para cada equipo: últimos resultados, figuras del partido anterior, posición en tabla, forma reciente (W/D/L), bajas/lesiones/sanciones, contexto H2H, jornada actual
  - Respuesta en **JSON estructurado** compatible con `_load_web_agent_team_map()` del Insights Agent (sin cambios en el consumidor)
  - **Cache de 6h** configurable via `WEB_AGENT_CACHE_TTL_HOURS` — no repite llamadas si el archivo está fresco
  - Persiste en `web_agent_output.json`

- **`graph_pipeline.py`** actualizado:
  - Se eliminó el flag condicional `ENABLE_WEB_AGENT_IN_PIPELINE` — el Web Agent es ahora **permanente** en el flujo
  - Nuevo flujo: `odds → stats → journalist → web_agent → insights → normalizer → gate → analyst → bettor`

- **`app.py`** actualizado:
  - Nuevo paso en el progress bar: `58% 🌐 Agente Web buscando contexto de jornada...`
  - Diagrama de arquitectura actualizado: `web_agent` aparece como nodo propio (AG35, azul claro) con flechas hacia `web_agent_output.json` y al Insights Agent
  - `web_agent_output.json` aparece en el subgrafo de Persistencia (dorado)

#### 2. System Prompt del Insights Agent — Experto en Pronóstico

- **`agents/insights_agent.py`** — SYSTEM ROLE reescrito desde cero:
  - Identidad: *"Analista de élite en pronóstico deportivo con 20+ años de experiencia en modelado predictivo. Científico del pronóstico."*
  - **Variables orientativas (no limitantes)** que el agente debe buscar: disponibilidad de plantilla, forma reciente, contexto táctico, motivación, factores off-field, jornada, narrativa psicológica, señales de mercado, y **cualquier otra señal relevante** fuera de estas categorías
  - **Jerarquía de confianza de fuentes**: periodista > ESPN/Marca > ThonyBet > historial > noticias manuales > hincha > rumor
  - **Nuevos principios de output**: "más es más", "captura lo inesperado", "cuantifica cuando puedas"
  - Nueva categoría de tipo añadida a `context_signals`: `injury_news`, `form`, `motivation`, `h2h_context`

#### 3. System Prompt del Analyst Agent — El Mejor Predictor del Mundo

- **`agents/analyst_agent.py`** — SYSTEM ROLE reescrito:
  - Identidad: *"Combinas la rigurosidad de un quant financiero con el conocimiento de un scout de élite. Un error tiene costo real."*
  - **Proceso mental en 6 pasos**: Lee cuotas → evalúa qué cambia → pondera por calidad → calibra honestamente → verifica sesgos → escribe rationale
  - Contexto psicológico ampliado: efecto DT nuevo, crisis institucional, must-win, aggregate_score disadvantage
  - Nueva Regla 10: *"El Insights Agent ya hizo el trabajo de inteligencia. Tu trabajo es SINTETIZAR y DECIDIR."*

#### 4. Bitácora del Analista — Mejora Continua Persistente

- **`agents/analyst_agent.py`** — nueva funcionalidad:
  - El LLM ahora rellena el campo obligatorio `analyst_wishlist` en cada predicción: qué información le faltó para decidir con más confianza
  - Función `_persist_analyst_wishlist()` con **deduplicación semántica**: normaliza el texto, descarta ideas ya registradas, ignora respuestas triviales ("datos suficientes")
  - Persiste en `predictions/analyst_wishlist.json` (más reciente primero, máximo 200 entradas)
  - El campo se extrae con `pred.pop()` antes de guardar en el historial de predicciones (limpio para el resto del flujo)

- **`app.py`** — nueva sección en tab "Memoria del Analista":
  - Métricas: total de ideas, prioridad alta (🔴), prioridad media (🟡)
  - Filtro por prioridad
  - Cards con: necesidad completa, categoría, equipos afectados, partido que la generó, fecha de registro

### 📁 Archivos Modificados

| Archivo | Cambios |
|---|---|
| `agents/web_agent.py` | Reescrito completo — prompt dinámico, 1 llamada/torneo, cache 6h |
| `agents/insights_agent.py` | SYSTEM ROLE reescrito, variables abiertas, nuevas categorías |
| `agents/analyst_agent.py` | SYSTEM ROLE reescrito, campo wishlist, función _persist_analyst_wishlist |
| `graph_pipeline.py` | Web Agent activado siempre (sin flag), flujo documentado |
| `app.py` | Progress bar, diagrama arquitectura, sección Bitácora del Analista |

### 🔮 Próximos Pasos Sugeridos

- [ ] Ejecutar pipeline completo con la liga CHI1 para validar el flujo del Web Agent y la generación de wishlist
- [ ] Revisar las primeras entradas de `analyst_wishlist.json` para identificar qué atacar primero
- [ ] Evaluar si agregar el Web Agent al bloque de progreso de la UI con un expander de preview del resultado web


### 🎯 Objetivos Logrados
1.  **Simplificación Radical del Pipeline**: 
    -   Se eliminó el `fixtures_fetcher` (Agente #1 de football-data.org) por inconsistencias recurrentes.
    -   **The Odds API** es ahora la **Fuente de Verdad Única** para partidos (`odds_canonical`).
2.  **Caché de Insights de YouTube**:
    -   Implementado en `agents/insights_agent.py` usando `youtube_insights_cache.json`.
3.  **Matching Difuso de "Grado Industrial"**:
    -   Se evolucionó `_fuzzy_match` en `normalizer_agent.py` a un sistema de 4 estrategias.

## Sesión: Sincronización Pipeline-UI y Consolidación (21-Feb-2026)

### 🎯 Objetivos Logrados
1.  **Sincronización Total Normalizador-UI**:
    -   El `normalizer_agent` ahora persiste el objeto `MatchContext` completo.
2.  **Búsqueda Robusta en Frontend**:
    -   Implementada la función `_local_slug` en `app.py`.

## Sesión: Arquitectura Visual Premium y Persistencia CSV (21-Feb-2026, Noche)

### 🎯 Objetivos Logrados
1.  **Arquitectura con "Alma Robótica"**:
    -   Optimización de la pestaña de **Arquitectura** con iconos y estilo "Modern Tech".
2.  **Exportación CSV Acumulativa**:
    -   Implementada la generación de `predictions/predictions_history.csv`.

## Sesión: Usabilidad y Robustez de Insights (22-Feb-2026)

### 🎯 Objetivos Logrados
1.  **Puntaje de Confianza**: Nueva métrica (0-1) por insight.
2.  **Citas con Timestamps**: Extracción de citas textuales del video con sugerencia de minuto.

---

## Sesión: Insights Multifuente + Agente Web + Limpieza de Rastreo (24-25 Feb 2026) 🧠🌐

### 🎯 Objetivos Logrados
1. **Agente Web Standalone funcional y útil (OpenAI Responses + `web_search`)**
   - Creado `agents/web_agent.py` + `run_web_agent.py`.
   - Salida JSON estructurada y validable (`competitions`, `teams`, `web_insights`, `context_signals`, `sources`, `confidence`).
   - Reparación automática de JSON malformado vía segunda llamada LLM.
   - Pestaña Streamlit `Agente Web` para ejecutar/visualizar resultados.
   - Cobertura mejorada con sub-llamadas por competencia (`CHI1`/`UCL`) + segunda pasada por equipos faltantes.
   - **Fallback 7→14 días** implementado y luego **desactivado por defecto** para evitar contaminación temporal en el analista.

2. **Integración opcional del Agente Web al pipeline principal**
   - `graph_pipeline.py` ahora soporta flag:
     - `ENABLE_WEB_AGENT_IN_PIPELINE=1`
   - Flujo opcional:
     - `... -> journalist_agent -> web_agent -> insights_agent -> ...`
   - Sin flag, el pipeline sigue igual (backward compatible).

3. **`insights_agent` enriquecido y menos restrictivo**
   - Prompt relajado para capturar:
     - contexto off-field (racismo, sanciones, presión mediática, crisis institucional, etc.)
     - contexto del partido anterior
     - señales débiles/inferidas (con menor confianza)
     - noticias manuales del usuario
   - Soporte explícito de alias/apodos (incluyendo clubes chilenos y apodos por identidad/color).
   - Instrucción explícita para **explicar quién es la persona** mencionada (rol/importancia: goleador, arquero titular, figura, DT, etc.).
   - Instrucción para **marcar rumores** como tales (`is_rumor`) con menor confianza.
   - Instrucción para **extraer/inferir fecha** (`context_signals[].date`) cuando exista referencia temporal.
   - Aclaración específica CHI1:
     - `fecha/jornada` = ronda del campeonato (no necesariamente fecha calendario).

4. **Fusión/deduplicación de `context_signals` multifuente en `insights_agent`**
   - Primer paso completado y extendido:
     - `YouTube + Web + Manual + History`
   - Dedup por clave canónica de señal (`type + signal_normalized + date`).
   - Merge de:
     - `provenance`
     - `confidence` (máx)
     - `evidence` (concat si aporta)
     - `date` (si faltaba)
   - `source` del insight ahora refleja mezcla real (`youtube+web+manual+history`, etc.).

5. **Control de ruido histórico antes del analista**
   - `insights_agent` ahora poda señales `history` antes de fusionar:
     - configurable: `INSIGHTS_MAX_HISTORY_SIGNALS_TO_ANALYST` (default `4`)
     - prioriza tipos más útiles (`injury_news`, `disciplinary_issue`, `coach_change`, etc.)
     - evita repetir señales ya cubiertas por `youtube/web/manual`
     - limita saturación de tipos débiles (`morale`, `media_pressure`, `other`)

6. **`normalizer_agent` deja de inflar el texto de insights con histórico**
   - El histórico se mantiene en `context_signals` (estructurado), pero por defecto no se agrega al texto libre `insight`.
   - Nuevo env:
     - `NORMALIZER_MAX_HISTORY_BULLETS_IN_INSIGHT=0` (default)
   - Además, señales históricas agregadas por normalizer ahora incluyen:
     - `provenance: ["history"]`
   - Resultado: `Rastreo` más limpio y auditable.

7. **Mejoras fuertes en Streamlit (Rastreo + Logs + Insights + Agente Web)**
   - `Rastreo de Agentes` ahora muestra mejor lo que recibe el analista:
     - bullets línea por línea del `insight`
     - `source` del payload
     - `context_signals` con fecha, confianza y **badges de `provenance`**
     - marca visual `RUMOR`
     - expander con payload JSON completo
   - Nueva pestaña `Insights Persistentes` (`team_history.json`) con filtros por equipo/competencia/tipo/buscador.
   - Sidebar `Noticias Manuales (Insights)`:
     - guardar/limpiar
     - persistencia en `data/inputs/manual_news_input.json`
   - Corregido bug de Streamlit (`session_state`) al limpiar noticias con callbacks `on_click`.
   - Pestaña `Agente Web`:
     - prompt editable
     - ejecución
     - resumen por competencia
     - detalle por equipo
     - logs
     - **`coverage_meta` y `subcall_errors`** visibles.

8. **Correcciones de matching/normalización en UI (Rastreo)**
   - Búsqueda de predicción/apuesta prioriza `match_id` (slug del `match_id`) antes que nombres.
   - Esto corrigió casos de confusión tipo:
     - `Coquimbo Unido vs Deportes Concepción` vs `Universidad de Concepción`
   - `_canon_team` en UI remueve sufijos tipo `(CHI)` para matching más robusto.

### ✅ Validaciones observadas en corrida real (ejemplo Superclásico)
- `Rastreo` muestra `context_signals` con `youtube`, `web`, `history`.
- El analista usó correctamente:
  - momento de Colo-Colo
  - U sin victorias
  - baja de Assadi + duda de Rivero
- Predicción mejoró en claridad y confianza (`1`, ~68%) con rationale coherente.
- El bloque textual de insights quedó significativamente más limpio tras dejar histórico solo estructurado.

### 💡 Aprendizajes (Lessons Learned)
- **La fusión multifuente funciona mejor en `insights_agent`** (semántico) que en `normalizer_agent` (mecánico).
- **`history` aporta valor**, pero sin poda contamina rápido al analista con ruido/contradicciones.
- **La observabilidad en UI (provenance + payload real)** es clave para depurar calidad de predicción.
- **Ventana temporal del Agente Web importa mucho**:
  - 14 días mejora cobertura, pero puede introducir rival/contexto viejo y degradar predicción.
  - 7 días es más seguro para integrarlo al pipeline.
- **Los nombres de jugadores/DT sin rol no bastan**: el analista necesita “quién es” + impacto para ponderar correctamente.
- **Rumores sí sirven**, pero deben ir etiquetados y penalizados en confianza.
- En CHI1, **“fecha/jornada” ≠ fecha calendario**; hay que instruir explícitamente al LLM para no confundirlo.

### 🧪 Hipótesis / Observaciones
- Aún puede haber duplicados semánticos leves entre `youtube` y `history` cuando el wording cambia mucho.
- El analista podría beneficiarse de una regla explícita de ponderación por fuente/recencia:
  - `youtube/web` del run actual > `history`
  - `rumor` siempre con penalización adicional.

### 🚧 Pendientes (Tareas)
1. **Ponderación por fuente y actualidad en el analista** (pendiente decidido)
   - Reforzar en prompt/heurística:
     - `youtube/web` recientes > `history`
     - `history` como complemento si contradice señales frescas
     - `rumor` con penalización explícita

2. **Deduplicación semántica fina de señales**
   - Mejorar dedup más allá de `type + signal_normalized + date`
   - Objetivo: colapsar variantes de wording (`media_pressure` / `superclásico`) sin perder matiz.

3. **Integración formal del Agente Web en operación**
   - Validar varias corridas con `ENABLE_WEB_AGENT_IN_PIPELINE=1`
   - Medir impacto real en predicciones / picks vs baseline sin web.

4. **Registro de esta mejora en métricas**
   - Comparar:
     - cantidad de `context_signals` por equipo
     - mezcla de `provenance`
     - cambios en confianza del analista
     - cambios en edge/stake del apostador

### 🌱 Nice To Have
- Mostrar en `Rastreo` una etiqueta visual de **recencia** por señal (`hoy`, `1-3d`, `>7d`, histórico).
- Score de confiabilidad por `provenance` (ej. `web_verified`, `youtube_citation`, `manual_user`, `history_legacy`).
- Vista comparativa en UI:
  - “payload enviado al analista” vs “historial persistente” para auditar divergencias.
- Integrar `Agente Web` con selector de modelo en Streamlit (`gpt-4.1`, `gpt-4.1-mini`, `gpt-5`) para pruebas controladas.

### 🛠️ Cambios Técnicos (Resumen de archivos)
- **`agents/web_agent.py`**
  - agente standalone + JSON validation + JSON repair
  - sub-búsquedas por competencia
  - segunda pasada por faltantes
  - fallback 14d opcional (desactivado por defecto)
  - prompt por defecto enriquecido (resultados, figuras, lesionados, contexto institucional)
- **`run_web_agent.py`**
  - runner standalone del Agente Web
- **`graph_pipeline.py`**
  - integración opcional de `web_agent` por `ENABLE_WEB_AGENT_IN_PIPELINE`
- **`agents/insights_agent.py`**
  - prompt relajado + alias + rumores + fecha/jornada CHI1 + rol/importancia de personas
  - fusión/dedup `YouTube + Web + Manual + History`
  - poda de `history_signals` antes del analista
- **`agents/analyst_agent.py`**
  - incluye `context_signals` con fecha y marca de `RUMOR` en el contexto de prompt
- **`agents/normalizer_agent.py`**
  - deja histórico estructurado y no infla `insight` textual por defecto
  - agrega `provenance=["history"]` a señales históricas
- **`app.py`**
  - mejoras de `Rastreo` (payload real, provenance badges, rumor)
  - pestaña `Insights Persistentes`
  - pestaña `Agente Web` + `coverage_meta`
  - fix `manual_news` con callbacks
  - matching por `match_id` en rastreo (predicción/apuesta)

### 📝 Notas de Cierre
- El sistema quedó en un punto fuerte: **insights multifuente trazables** (YouTube/Web/Manual/History) con mejor control de ruido.
- La calidad percibida del analista mejora cuando el contexto llega estructurado y con `provenance`.
- Se deja pendiente (a propósito) la **ponderación por fuente/recencia en el analista** para la próxima sesión.

## Sesión: Analyst Web Check On-Demand (25-Feb-2026, Noche) 🔎

### 🎯 Objetivos Logrados
1. **Nuevo módulo standalone `Analyst Web Check`**
   - Creado `agents/analyst_web_check.py` con salida JSON estructurada y validación básica.
   - Creado `run_analyst_web_check.py` para pruebas manuales por CLI.
   - Diseño acotado: confirmar señales puntuales (lesiones, sanciones, expulsiones, castigos, dudas), no scouting general.
   - Reutiliza OpenAI Responses + `web_search` con fallback de reparación JSON.

2. **Integración opcional en `analyst_agent` (on-demand)**
   - Integrado por flags de entorno:
     - `ENABLE_ANALYST_WEB_CHECK`
     - `ANALYST_WEB_CHECK_LOOKBACK_DAYS`
   - Trigger simple y acotado para señales críticas (lesiones/sanciones/castigos/cambio de DT) con priorización de rumores o baja corroboración.
   - Fusión de señales verificadas al payload del analista con:
     - `provenance: ["analyst_web_check"]`

3. **Modo de prueba controlado**
   - Se implementó `FORCE_TEST` para validar flujo/UI sin depender del trigger normal:
     - `ANALYST_WEB_CHECK_FORCE_TEST=1`
   - Se implementó flag para desactivar temporalmente trigger normal y aislar la prueba:
     - `ANALYST_WEB_CHECK_DISABLE_NORMAL_TRIGGER=1`
   - Validación real exitosa: se ejecutó **1 solo check** en modo test controlado.

4. **Persistencia y UI en Rastreo**
   - `run_pipeline.py` guarda `pipeline_analyst_web_checks.json`
   - `app.py` (Rastreo) muestra nuevo bloque:
     - `1.5 Verificación Web del Analista (On-demand)`
   - Se visualizan:
     - trigger
     - preguntas
     - estado (`confirmed`, etc.)
     - señales
     - fuentes
     - payload completo del check

5. **Corrección de targeting del web-check (equipo objetivo vs rival)**
   - Se detectó un bug: el FORCE TEST podía elegir una señal del payload de un equipo que en realidad describía al rival (ej. Atalanta vs Dortmund con Emre Can/Schlotterbeck).
   - Se corrigió con heurística de tokens distintivos por equipo + detector de contexto de rival (`vs/contra/ante/frente a`).
   - Se endureció especialmente el FORCE TEST para señales de bajas/sanciones sin anclaje real al equipo target.
   - Validación posterior: el check pasó a una señal coherente del equipo local (`obligación emocional de remontada`).

### ✅ Validaciones Reales de la Sesión
- `Analyst Web Check` ejecuta y retorna salida válida (`gpt-4.1 + web_search`) dentro del `analyst_agent`.
- El pipeline sigue generando predicciones normales (`UCL` y `CHI1`) sin romperse.
- El bloque `1.5` aparece en `Rastreo` con información completa y auditable.
- El targeting del FORCE TEST quedó corregido para evitar falsos seeds del rival.

### 💡 Aprendizajes (Lessons Learned)
- Darle al analista **web libre** no es buena idea; darle **web-check acotado y triggerado** sí agrega valor sin romper trazabilidad.
- El `Analyst Web Check` debe ser **quirúrgico**, no panorámico.
- El targeting semántico por equipo es crítico: una señal puede venir en el payload de un equipo pero describir al rival.
- El modo `FORCE_TEST` fue útil para validar arquitectura/UI antes de afinar el trigger de producción.

### 🚧 Próximos Pasos
1. **Probar modo real (sin FORCE TEST)**
   - Dejar:
     - `ENABLE_ANALYST_WEB_CHECK=1`
     - `ANALYST_WEB_CHECK_LOOKBACK_DAYS=7`
   - Desactivar:
     - `ANALYST_WEB_CHECK_FORCE_TEST=0`
     - `ANALYST_WEB_CHECK_DISABLE_NORMAL_TRIGGER=0`
   - Medir cuántos checks dispara realmente y en qué partidos.

2. **Afinar trigger normal de producción**
   - Revisar si conviene restringir aún más `other` (mantener libertad acotada, pero sin ruido).
   - Ajustar umbrales de confidence/incertidumbre según observación real.

3. **Auditoría de impacto**
   - Comparar predicciones con/ sin `Analyst Web Check` en casos con rumores o dudas de bajas.
   - Observar cambios en `rationale`, `risk_factors`, confidence y edge.

4. **Bitácora de flags recomendados**
   - Documentar combinación de flags para:
     - producción
     - test controlado
     - debugging

### 🌱 Nice To Have
- Persistir en cada predicción un mini `source_audit` del analista:
  - `used_analyst_web_check`
  - `web_check_count`
  - `web_check_reason`
- Mostrar en `Rastreo` si el web-check **cambió** efectivamente el contexto del analista (antes/después).
- Selector/tabla en UI para listar todos los `pipeline_analyst_web_checks.json` de la corrida.
- Refactor futuro (pendiente intencional): backend pluggable del analista (`OpenAI/Gemini/...`) manteniendo contrato estable.

### 📝 Notas de Cierre
- Se valida una nueva capacidad estratégica del sistema: **el analista puede consultar web de forma acotada**, con control por flags y trazabilidad completa.
- Se mantiene la filosofía de arquitectura:
  - `Agente Web` = panorama general
  - `Analyst Web Check` = confirmación puntual on-demand
- Se deja el trigger con libertad acotada (como se acordó), evitando sobrerrestricción prematura.

## Sesión: Integración del Agente Revisor en UI + Estado de Evaluación UCL (26-Feb-2026) 📊

### 🎯 Objetivos Logrados
1. **Agente Revisor/Evaluador documentado explícitamente**
   - Confirmado que existe como módulo standalone:
     - `agents/evaluator_agent.py`
     - `run_evaluator.py`
   - Aclarado que **NO** forma parte del pipeline principal (LangGraph), sino que corre como proceso separado post-partido.

2. **Botón dedicado en UI para ejecutar el Revisor**
   - En `app.py` (pestaña `Evaluación de Rendimiento`) se agregó botón visible:
     - `🔎 Ejecutar Agente Revisor (Standalone)`
   - Esto permite ejecutarlo bajo demanda sin mezclarlo con el pipeline principal.

3. **Corrección de error del runner del Revisor en Windows (cp1252)**
   - Error observado: `UnicodeEncodeError` por `print("✓ ...")` en `run_evaluator.py`.
   - Solución aplicada:
     - Reescritura del script con mensajes ASCII-only (`OK - ...`) para compatibilidad con terminal Windows/cp1252.
   - Resultado: el runner ya no debería romperse al finalizar por temas de encoding.

4. **Documentación de arquitectura actualizada**
   - `agentes_flow.md` actualizado en detalle con:
     - flujo principal actual
     - `Web Agent` opcional
     - `Analyst Web Check` on-demand
     - `Agente Revisor` standalone
     - persistencias y flags
     - cheat sheet operativo (producción / test / debug)

### ✅ Observaciones Reales
- El revisor/evaluador sí estaba funcionando en lo esencial:
  - generó CSVs y resumen
  - el crash venía al final en un `print` Unicode (no en la lógica de evaluación).
- Persisten casos donde resultados UCL “de ayer” no aparecen evaluados en el resumen/historial.

### 🧪 Hipótesis (Pendiente para próxima sesión)
Sobre UCL no evaluado:
1. **Estados `PENDING` / `FUTURE_MATCH` por timezone**
   - Posible desfase entre `match_date`, hora UTC y la lógica `> now + 2h`.
2. **`NOT_FOUND` por matching ESPN**
   - El matching de evento puede fallar por nombres/fecha/cobertura del scoreboard.
3. **Predicciones no presentes/actualizadas en `predictions_history.json`**
   - El evaluador solo mira historial persistido, no `pipeline_predictions.json`.

### 🚧 Pendiente Principal (Próxima Sesión)
**Revisar por qué partidos UCL jugados no aparecen como evaluados**

Checklist propuesto:
1. Inspeccionar `predictions/predictions_history.json`:
   - `evaluation_status`
   - `match_date`
   - `event_id`
2. Inspeccionar `predictions/evaluation_summary.json`:
   - conteos `PENDING`, `FUTURE_MATCH`, `NOT_FOUND`
3. Endurecer evaluator:
   - ampliar ventana de fechas (`-1, 0, +1`)
   - mejorar logging de motivo por partido
   - mostrar ejemplos de UCL afectados en UI

### 🌱 Nice To Have
- Tarjeta en UI de evaluación con:
  - última fecha de evaluación
  - cantidad `PENDING`
  - cantidad `NOT_FOUND`
  - cantidad `FUTURE_MATCH`
- Tabla de “partidos pendientes de evaluar” con liga/fecha/motivo.
- Métrica futura para medir impacto de `Analyst Web Check` en accuracy (con vs sin web-check).

### 📝 Notas de Cierre
- Se consolidó el `Agente Revisor` como proceso aislado y controlable desde UI.
- La arquitectura y documentación quedaron más completas.
- Se deja explícitamente pendiente el debug de evaluación UCL para retomarlo con foco en estados (`PENDING/FUTURE_MATCH/NOT_FOUND`) y matching ESPN.

## Sesión: Insights Contextuales, Trazabilidad al Analista y Noticias Manuales (24-Feb-2026, madrugada/tarde) ✅

### 🎯 Objetivos trabajados
1. **Relajar el Agente de Insights** para capturar contexto útil (no solo táctica).
2. **Asegurar que el Analista reciba todos los insights relevantes** (incluyendo contexto persistido).
3. **Mejorar trazabilidad en Streamlit** (`Rastreo de Agentes` + historial persistente).
4. **Agregar input manual de noticias en Streamlit** para enriquecer el `insights_agent`.
5. **Corregir bugs de UX/estado** en Streamlit (`session_state`, tabs, rastreo).

---

### ✅ Avances implementados

#### 1) `insights_agent` mucho más flexible y útil para predicción
- Se relajó el prompt del LLM para aceptar insights de:
  - contexto institucional / off-field
  - partido anterior (resultado, sensaciones, polémicas)
  - presión mediática
  - incidentes disciplinarios / racismo
  - carga por torneos paralelos (ej: Libertadores, Champions, copa local)
- Se reforzó la instrucción de capturar **menciones indirectas** del equipo (DT, capitán, rueda de prensa, apodos, rival, etc.).
- Se amplió la taxonomía de `context_signals`:
  - `racism_incident`
  - `disciplinary_issue`
  - `media_pressure`
  - `multi_competition_load`
  - `previous_match_context`
  - etc.
- Si el LLM devuelve `context_signals` pero pocos bullets, ahora se transforman automáticamente en bullets visibles del `insight` (para que no se pierdan aguas abajo).

#### 2) Persistencia de insights/contexto por equipo mejorada
- `team_history.json` ya venía guardando contexto, pero se mejoró la utilidad:
  - se retiene más historial por equipo (`INSIGHTS_TEAM_HISTORY_MAX_ITEMS`, default 25)
  - se mantienen entradas `kind: "context_signal"` con `signal_type`, `confidence`
- Se agregó `as_of_date` a cada insight generado por `insights_agent` (fecha del payload del run).

#### 3) El Analista ahora recibe explícitamente el contexto estructurado
- Se detectó que el problema no era solo la UI:
  - el `analyst_agent` no incluía `context_signals` en `_format_insights_context(...)`.
- Se corrigió `agents/analyst_agent.py`:
  - ahora el prompt del analista sí incluye `context_signals` (tipo, señal, evidencia, confianza)
  - se aumentó el truncado del texto `insight` (de ~800 a ~2000 chars) para no perder contexto relevante.

#### 4) Fusión de historial persistente en `match_contexts` (normalizer)
- Hallazgo clave: `team_history.json` (historial acumulado) y `pipeline_match_contexts.json` (snapshot del run) podían desincronizarse.
- Se corrigió en `agents/normalizer_agent.py`:
  - al construir `match_contexts`, ahora fusiona contexto persistido de `team_history.json` dentro de `home.insights` / `away.insights`
  - agrega `context_signals` históricos faltantes (sin duplicados)
  - agrega bullets históricos al campo `insight` (prefijados como `Histórico` / `Contexto histórico`)
  - agrega fechas (`date`) en señales históricas fusionadas y `as_of_date` al payload resultante
- Impacto:
  - `Rastreo de Agentes` ahora puede mostrar también contexto histórico relevante que llega al analista.

#### 5) Ponderación temporal explícita en el prompt del analista
- Se agregó regla de **ponderación temporal** en `_build_analyst_prompt(...)`:
  - usar `as_of_date` y `context_signals[].date`
  - bajar peso a contexto antiguo
  - mantener peso si es estructural/persistente
  - mencionar contexto antiguo como riesgo/secundario si se usa
- Nueva variable de entorno opcional:
  - `ANALYST_STALE_CONTEXT_DAYS` (default `14`)

#### 6) Streamlit: Rastreo de Agentes muestra mejor lo que llega al Analista
- Se creó renderer más completo para insights en `Rastreo de Agentes`:
  - texto principal de `insight`
  - `insight_meta` (confianza + citas)
  - `context_signals` completos (tipo, señal, evidencia, confianza, fecha)
  - `as_of_date` del payload
  - expander con **payload JSON completo** entregado al analista
- Esto permite auditar si el problema está en:
  - extracción de insights
  - fusión de historial
  - formateo hacia el analista
  - o solo UI.

#### 7) Streamlit: nueva pestaña de “Insights Persistentes”
- Se agregó pestaña nueva para visualizar `data/knowledge/team_history.json`.
- Incluye filtros por:
  - equipo
  - competencia
  - tipo (`insight` / `context_signal`)
  - búsqueda libre
- Permite validar contexto acumulado y detectar señales históricas útiles.

#### 8) Streamlit: botón de pipeline parcial (desde periodista)
- Se implementó `run_pipeline_from_journalist.py` para ejecutar:
  - `insights_agent → normalizer_agent → gate_agent → analyst_agent → bettor_agent`
  - usando artefactos persistidos (`journalist_test_output.json`, `pipeline_odds.json`, `pipeline_stats.json`, etc.).
- Se agregó botón en Streamlit:
  - `⚡ EJECUTAR PARCIAL (DESDE PERIODISTA)`
- Muy útil para iterar rápido sin rerun completo.

#### 9) Noticias manuales del usuario → `insights_agent`
- Se agregó en Streamlit (sidebar) un bloque:
  - `📰 Noticias Manuales (Insights)` con `text_area`
  - botones `Guardar Noticias` / `Limpiar Noticias`
- Se persiste en:
  - `data/inputs/manual_news_input.json`
- `insights_agent` ahora lee ese archivo y lo pasa al prompt del LLM como:
  - `NOTICIAS MANUALES DEL USUARIO (opcional, usar solo si aplica)`
- Regla actual:
  - si aplica, debe incorporarse como contexto
  - marcar explícitamente que viene de noticia manual del usuario
  - asignar **confianza moderada a alta por defecto** (salvo texto ambiguo/contradictorio)

#### 10) Caché de `insights_agent` corregido para noticias manuales
- Bug detectado: noticias manuales no aparecían porque había `CACHE HIT`.
- Causa:
  - el cache key solo dependía de `videos + equipos`
  - no consideraba noticias manuales del usuario
- Se corrigió:
  - `manual_news_input.json` ahora entra en el cache key (hash por `updated_at + text`)
  - cambiar noticias manuales invalida cache y fuerza reproceso LLM.

#### 11) Bug de Streamlit corregido (`Limpiar Noticias`)
- Error:
  - `StreamlitAPIException: st.session_state.manual_news_text cannot be modified after the widget ... is instantiated`
- Causa:
  - se mutaba `session_state["manual_news_text"]` después de crear el widget en el mismo ciclo.
- Solución:
  - migrado a callbacks `on_click`:
    - `_on_save_manual_news()`
    - `_on_clear_manual_news()`
  - mensajes de estado temporales vía `session_state["manual_news_status"]`.

---

### 🔎 Descubrimientos / Diagnósticos clave (muy importantes)

1. **Historial persistente vs snapshot de run**
- `team_history.json` es acumulativo.
- `pipeline_match_contexts.json` es snapshot de un run específico.
- Por eso podían existir señales (ej. conflicto racial) en historial persistente pero no en `Rastreo`.
- El fix correcto fue fusionar historial en el `normalizer_agent` (no solo “mostrar más” en UI).

2. **El analista no estaba recibiendo `context_signals` aunque existieran**
- `Rastreo` inicialmente mostraba solo `insight` + `insight_meta`.
- Peor aún: el formatter del `analyst_agent` no serializaba `context_signals` al prompt.
- Resultado: contexto valioso existía pero no impactaba predicción.
- Corregido.

3. **Noticias manuales + caché = falsa sensación de bug**
- La noticia manual podía estar bien guardada, pero no aparecer porque no se re-ejecutaba el LLM (cache hit).
- Esto se resolvió metiendo noticias manuales en el cache key.

---

### 🧠 Aprendizajes (para próximas iteraciones)

- **No basta con extraer insights**: hay que verificar todo el camino:
  1. extracción (`insights_agent`)
  2. persistencia (`pipeline_insights.json`, `team_history.json`)
  3. consolidación (`match_contexts`)
  4. formateo al analista (`_format_insights_context`)
  5. visualización en `Rastreo`
- **La UI puede ocultar bugs reales de flujo**, pero también puede crear diagnósticos falsos si no muestra payload completo.
- **Los caches en agentes LLM deben incorporar todas las entradas semánticas**, no solo videos/URLs.

---

### 🧪 Hipótesis / áreas a seguir vigilando

1. **Sobreuso de historial persistente**
- Riesgo: que contexto histórico “contamine” demasiado el run actual si se acumula sin control.
- Mitigación ya iniciada:
  - fechas (`as_of_date`, `context_signals[].date`)
  - regla de ponderación temporal en analista
- Posible mejora:
  - score explícito de frescura por señal.

2. **Ambigüedad en noticias manuales**
- Si el usuario escribe noticias muy generales o mezcladas (varios equipos/torneos), el LLM puede distribuirlas mal.
- Posible mejora:
  - formato estructurado opcional por equipo/competencia (`JSON`/campos).

3. **Heurística del analista (sin LLM) aún no pondera temporalmente**
- La ponderación temporal quedó en el prompt LLM.
- Si cae a modo heurístico, el uso de contexto histórico sigue siendo más rudimentario.
- Pendiente deseable:
  - incorporar peso temporal también en fallback heurístico.

---

### 📌 Estado de agentes / componentes (actualizado)

- `journalist_agent`: ✅ operativo, muy mejorado (filtros, UCL, idiomas, fallback key, logs)
- `insights_agent`: ✅ operativo y enriquecido (contexto/off-field + noticias manuales + persistencia útil)
- `normalizer_agent`: ✅ operativo, ahora fusiona historial persistente en `match_contexts`
- `analyst_agent`: ✅ operativo, ahora consume `context_signals` + fechas
- `bettor_agent`: ✅ operativo
- `UEFA Adapter` (stats): 🔶 placeholder (sin datos reales)
- `FBref Adapter` (stats): 🔶 placeholder (sin datos reales)

---

### 🚀 Próximos pasos sugeridos (si seguimos esta línea)

1. **Ponderación temporal en heurística (sin LLM)**  
   Para que el fallback también use antigüedad de señales/contextos.

2. **Noticias manuales estructuradas**  
   Ej: campos `competencia`, `equipos`, `fecha`, `texto`, `prioridad`.

3. **Etiquetado en Rastreo: origen del insight**  
   Mostrar visualmente qué viene del run actual vs `team_history`.

4. **Control de frescura en historial**  
   Opcionalmente descartar o degradar automáticamente señales históricas demasiado antiguas (excepto estructurales).

---

## Sesión: Diseño e Implementación Inicial del Agente Web (24-Feb-2026, tarde) ✅

### 🎯 Objetivo
Crear un **nuevo agente standalone (`Agente Web`)** capaz de buscar en internet usando OpenAI `Responses + web_search`, entregar resultados estructurados/validables, y explorar cómo complementa al `insights_agent` (YouTube), **sin integrarlo aún al pipeline principal**.

---

### ✅ Avances implementados

#### 1) Nuevo módulo `Agente Web` standalone
- **Archivo nuevo:** `agents/web_agent.py`
- **Runner nuevo:** `run_web_agent.py`

Capacidades actuales:
- Usa OpenAI `Responses API` con tool `web_search` (configurable por env).
- Construye salida JSON estructurada por competencia/equipo:
  - `competitions[]`
  - `teams[]`
  - `web_insights`
  - `context_signals`
  - `sources`
  - `confidence`, `confidence_rationale`
- Incluye validación de salida (`_validate_web_output`).
- Incluye `raw_text` para auditoría.

#### 2) Pestaña Streamlit para ejecutar/visualizar el Agente Web
- Se agregó una pestaña nueva en `app.py`: **Agente Web**
- Permite:
  - editar prompt
  - ejecutar `run_web_agent.py` desde la UI
  - ver logs de la ejecución
  - ver `web_agent_output.json`
  - resumen por competencia / detalle por equipo / JSON completo

#### 3) Debugging de integración OpenAI web_search (hallazgo importante)
- `gpt-5 + web_search` en este entorno devolvía solo items:
  - `reasoning`
  - `web_search_call`
  - **sin `message` final**
- Resultado: `output_text == ""` y el agente parecía “no responder”.
- Se probó con modelos alternativos:
  - ✅ `gpt-4.1` respondió con `web_search_call + message`
  - ✅ `gpt-4.1-mini` también respondió (más básico)
- **Cambio aplicado:** modelo por defecto del Agente Web pasó a `gpt-4.1`.

#### 4) Reparación automática de JSON malformado
Problema recurrente:
- El modelo web devolvía JSON con errores (comas finales, texto extra, etc.)
- Rompía `json.loads(...)`

Solución implementada:
- Fallback de reparación:
  - si falla parseo JSON, se hace una segunda llamada (sin `web_search`) para **reparar formato JSON**
  - luego se reparsea
- Resultado:
  - varias corridas exitosas con `JSON reparado correctamente`

#### 5) Cobertura por competencia mejorada (iteraciones de diseño)
Se probaron varias estrategias:

**v1 - una sola llamada global (CHI1 + UCL)**
- Cobertura baja/inestable (ej. 3 equipos por comp)

**v2 - prompt reforzado con “8-10 equipos por competencia”**
- Mejora parcial, pero aún inestable

**v3 - equipos objetivo desde `pipeline_odds.json`**
- Se agregó lectura de `pipeline_odds.json` para extraer equipos objetivo por competencia
- Mejor alineación con partidos reales del run
- Pero una sola llamada seguía dejando vacía una competencia en algunas corridas

**v4 - sub-búsqueda por competencia (CHI1/UCL por separado)**
- Refactor del Agente Web para ejecutar 2 llamadas:
  - una para `CHI1`
  - una para `UCL`
- Resultado:
  - mejor estabilidad
  - mejor cobertura parcial (ej. CHI1 7 / UCL 4)

**v5 - segunda pasada automática por equipos faltantes**
- Si tras la primera pasada faltan equipos objetivo:
  - se ejecuta una **segunda pasada** enfocada en esos equipos
- Se hace merge sin duplicar por nombre de equipo (case-insensitive)
- Resultado:
  - mejora clara en cobertura

#### 6) Ventana temporal y fallback 7→14 días (con fecha)
Requerimiento del usuario:
- buscar en últimos 7 días, pero subir a 14 si no hay cobertura suficiente

Implementación:
- Prompt por competencia ahora incluye ventana temporal (`lookback`)
- Por defecto:
  - `WEB_AGENT_LOOKBACK_DAYS=7`
- Fallback automático por competencia:
  - si cobertura queda vacía o corta, reintenta con `WEB_AGENT_FALLBACK_LOOKBACK_DAYS=14`
- Se mantiene requerimiento de fecha en señales/contexto para ponderación futura

Metadatos agregados:
- `coverage_meta` por competencia (salida del Agente Web)
  - `lookback_used`
  - `fallback_applied`
  - `fallback_from_days`
  - conteo previo / nuevo (si aplica)

---

### 📊 Resultados de pruebas (corridas reales)

#### Prueba inicial con `gpt-4.1` (sin mejoras avanzadas)
- `CHI1: 3 equipos`
- `UCL: 3 equipos`
- Confirmó valor de extracción (ej. caso Everton y contexto UCL)

#### Con sub-búsqueda por competencia
- `CHI1: 7 equipos`
- `UCL: 4 equipos`
- Mejora parcial, aún insuficiente para UCL

#### Con segunda pasada + fallback temporal 7→14 días
- ✅ `CHI1: 17 equipos`
- ✅ `UCL: 9 equipos`
- Resultado considerado **muy bueno** para etapa standalone

---

### 🔎 Descubrimientos / Diagnósticos clave

1. **`gpt-5` no era el mejor modelo para este caso en este entorno**
- No devolvía mensaje final con `web_search` (solo reasoning/tool calls)
- `gpt-4.1` resultó más estable y usable

2. **El mayor problema práctico no era “inteligencia”, sino formato**
- JSON malformado fue una fuente principal de fallos
- El fallback de reparación fue clave para hacer usable el agente

3. **Cobertura requiere estrategia multi-paso**
- Un solo prompt global no garantiza cubrir ambas competencias
- Separar por competencia + segunda pasada por faltantes mejora mucho

4. **La ventana de 7 días puede dejar CHI1 sin datos recientes**
- El fallback a 14 días (manteniendo fecha) resolvió bien el tradeoff entre frescura y cobertura

---

### 🧠 Aprendizajes

- Para agentes web con `Responses + web_search`, la robustez requiere:
  - validación de schema
  - reparación JSON
  - sub-búsquedas por dominio/competencia
  - fallback temporal controlado
- “Más potente” no siempre significa “más usable”:
  - en este caso `gpt-4.1` superó a `gpt-5` en estabilidad práctica con `web_search`

---

### 🧪 Diseño acordado (siguiente fase): fusión con `insights_agent` sin duplicados

Decisión de diseño:
- La deduplicación/fusión **no** debería vivir principalmente en `normalizer_agent`.
- El mejor lugar es el **`insights_agent`** (o helper interno suyo), porque ahí ya existe lógica semántica de:
  - `context_signals`
  - confianza
  - alias de equipos
  - persistencia por equipo

Plan acordado (por etapas):
1. **Primer paso:** deduplicación/fusión `YouTube + Web` por `context_signals`
2. Luego extender a:
   - `manual_news`
   - `history` (persistido)

Idea de dedup (discutida):
- clave canónica por señal:
  - equipo canónico
  - `signal_type`
  - texto normalizado
  - fecha (si existe)
- merge por prioridad de fuente y preservando trazabilidad

---

### 🚀 Próximos pasos (siguiente sesión / continuación inmediata)

1. **Implementar primer paso de fusión en `insights_agent`**
   - merge `YouTube + Web` en `context_signals`
   - dedup básico por clave canónica

2. **(Luego) Extender dedup a manual/history**
   - conservar `provenance` y fechas

3. **Mejoras opcionales de UI para Agente Web**
   - mostrar `coverage_meta` en la pestaña
   - mostrar si hubo fallback 14d por competencia

---

## Sesión: Ajustes Profundos de YouTube, Normalización y UI (24-Feb-2026)

### 🎯 Objetivos Logrados
1.  **Fallback y Rotación de API Key YouTube**:
    -   Si la primera llamada devuelve 403, se cambia **permanentemente** a `YOUTUBE_API_KEY_ALTERNATIVA` para el resto de llamadas.
2.  **Periodista: Selección Más Robusta y Multi‑idioma**:
    -   Búsqueda multilenguaje configurable (`JOURNALIST_LANGUAGES`) y queries por idioma.
    -   Prefiltro de competencia + soft‑allow solo para whitelist.
    -   Forzado de inclusión por términos clave (ej: “pronósticos deportivos”, “champions league”, “16avos”).
    -   Logs enriquecidos del prefiltro (conteos, soft_allow, dropped).
    -   Caché del periodista deshabilitado y salida persistida en `journalist_test_output.json` para auditoría.
3.  **Insights: Traducción a Español**:
    -   Se fuerza traducción a español si la transcripción está en otro idioma.
    -   Prompt del Insight Agent ahora exige respuesta en español.
4.  **Normalización y Matching de Partidos**:
    -   Fuzzy match afinado: se evita confundir equipos por tokens ambiguos.
    -   `deportes` marcado como ruido para evitar Limache/Concepción.
5.  **UI: Normalización Consistente**:
    -   La UI usa `utils.normalizer.slugify` y `TeamNormalizer.clean` para comparar partidos/insights/predicciones.
6.  **Analyst: MatchContext por match_key**:
    -   El analista prioriza `match_key` y registra logs indicando si encontró por `match_key` o por nombres.

### 🧐 Hipótesis y Diagnóstico
1.  **Contexto Legacy en Analyst**:
    -   No encontraba `MatchContext` por nombres divergentes; migrado a `match_key`.
2.  **Selección pobre en UCL**:
    -   La API de YouTube agotada (403) forzaba fallback `yt‑dlp` y reducía cobertura.
    -   Filtros previos demasiado restrictivos dejaban fuera videos relevantes.
3.  **UI desfasada vs runtime**:
    -   Auditoría mostraba JSON viejo por falta de persistencia del output del periodista.

### 💡 Aprendizajes
-   **match_key** es la llave estable para atravesar el pipeline (evita mismatches por nombres).
-   La selección de videos mejora al **priorizar términos clave** y aplicar prefiltros antes del LLM.
-   Si la cuota está agotada, el fallback debe ser **más permisivo** y con menos filtros agresivos.

### 🚀 Próximos Pasos
1.  **Monitoreo de cuota**:
    -   Mostrar en UI cuándo la API cae a fallback y con qué key está operando.
2.  **Curaduría de Whitelist UCL**:
    -   Revisar canales blancos para aumentar fuentes de calidad.
3.  **Afinar scoring**:
    -   Exponer umbrales y pesos en `.env` y ajustar según cobertura.
4.  **Cobertura CHI1**:
    -   Investigar por qué no se están seleccionando videos del campeonato chileno y ajustar queries/whitelist.

### 🛠️ Cambios Técnicos
- **`utils/youtube_api.py`**: switch automático y persistente a key alternativa tras 403.
- **`agents/journalist_agent.py`**:
  - multi‑idioma, prefiltros, soft‑allow whitelist, must‑include terms,
  - logs enriquecidos,
  - sin caché, persistencia a `journalist_test_output.json`.
- **`agents/insights_agent.py`**: traducción a español + prompt en español.
- **`agents/normalizer_agent.py`**: ajuste de fuzzy match (`deportes` y tokens ambiguos).
- **`agents/analyst_agent.py`**: lookup por `match_key` + logging explícito.
- **`app.py`**: normalización consistente para predicciones/apuestas/odds.

### 📊 Métricas de Ejecución (run_journalist.py)
- **Timestamp**: 2026-02-24T04:45:30Z
- **Candidatos escaneados**: 34
- **UCL videos seleccionados**: 6
- **CHI1 videos seleccionados**: 0
- **Cache hit**: false
- **Notas de cuota**: “Quota exceeded? Used yt-dlp fallback.”

### 📝 Notas de Cierre
- El pipeline está operable aun con cuota agotada, pero la cobertura depende del fallback.
- La auditoría de Streamlit ahora refleja el output real del periodista.

## Sesión: Agente Periodista y Discovery Automático (23-Feb-2026)

### 🎯 Objetivos Logrados
1.  **Nacimiento del Agente Periodista**:
    -   Nuevo agente en `agents/journalist_agent.py` encargado de descubrir videos tácticos de alta calidad.
    -   Uso de **YouTube Data API v3** para búsquedas filtradas por recencia y relevancia.
2.  **Sistema de Scoring Multinivel**:
    -   `Relevancia`: Match de palabras clave (CHI1/UCL).
    -   `Reputación`: Criterios de Whitelist, Suscriptores (>200k) y Vistas (>2k).
3.  **Eficiencia de Cuota**:
    -   Implementación de `utils/cache.py` para evitar llamadas redundantes a la API de YouTube (ahorro masivo de cuota).
4.  **Validación de Ingeniería**:
    -   Creación de `run_journalist.py` (standalone) y tests unitarios en `tests/`.

## Sesión: Optimización de Cuota y Curaduría Premium (23-Feb-2026, Madrugada)

### 🧐 Hipótesis y Diagnóstico
1.  **Hipótesis de Cuota**: El error 403 se confirmó como un agotamiento de la cuota diaria (10,000 unidades). El método `search.list` consume 100 unidades por llamada, lo que lo hace insostenible para monitoreos frecuentes.
2.  **Fallo de Visibilidad**: ThonyBet no aparecía porque el Agente Periodista dependía de una "Whitelist" vacía para UCL y las queries de búsqueda eran demasiado restrictivas para los algoritmos de YouTube.

### 🎯 Tareas Completas
1.  **Implementación de "Playlist Mining"**:
    -   Se agregó el método `get_playlist_items` a `YouTubeAPI`, reduciendo el costo de 100 unidades a **1 unidad por consulta**.
    -   El sistema ahora apunta directamente a la playlist de "Uploads" de los canales en la Whitelist.
2.  **Whitelist de Élite**:
    -   Chile: `TNT Sports Chile` (TST).
    -   UCL: `ThonyBet` (Pionero en análisis táctico-estadístico).
3.  **Puente de Datos Robusto**:
    -   Mapeo explícito de `journalist_videos` -> `insights_sources` para asegurar flujo ininterrumpido al Agente de Insights.

### 💡 Enseñanzas (Lessons Learned)
-   **API Design**: Nunca usar `search` si se conoce el ID del canal; `playlistItems` es la vía profesional para ahorro de costos y velocidad.
-   **Whitelist > AI Search**: La inteligencia artificial es excelente para filtrar, pero los humanos (el usuario) saben mejor quiénes son los expertos dignos de confianza.

### 🚀 Próximos Pasos
-   **Monitoreo de Reset**: Verificar la reactivación automática del descubrimiento tras el reinicio de cuota de Google.
-   **Refinamiento de Prompts**: Ajustar el Prompt del Agente de Insights para que priorice específicamente los "Porcentajes de ThonyBet".
-   **Auditoría de Errores**: Implementar un sistema de alertas en la UI de Streamlit cuando la cuota de YouTube esté próxima a agotarse.

### 🛠️ Cambios Técnicos
-   **`utils/youtube_api.py` [NUEVO]**: Wrapper para endpoints de Search, Videos y Channels.
-   **`agents/journalist_agent.py` [NUEVO]**: Lógica de curaduría y nodo LangGraph.
-   **`state.py` [MODIFICADO]**: Agregado `journalist_videos` al estado compartido.

### 📝 Notas para el Próximo Desarrollador
-   El Agente Periodista debe configurarse con `YOUTUBE_API_KEY`.
-   Para agregar canales de confianza permanentes, usa las variables `JOURNALIST_CHANNEL_WHITELIST_CHILE/UCL`.
-   El output del periodista fluye directamente al Agente de Insights, automatizando la selección de fuentes.

## Sesión: Optimización de Discovery y Alineación (23-Feb-2026, Mañana) 🚀

### 🎯 Objetivos Logrados
1.  **Descubrimiento Dinámico**: El Agente Periodista ahora busca videos basados en los equipos de la jornada (ej: "Real Madrid vs Benfica analisis tactico").
2.  **Naming Correcto**: Liga chilena actualizada a "Liga de Primera Mercado Libre 2026" en todo el sistema.
3.  **Alineación Estratégica**: Nuevo prompt del LLM enfocado en "predicciones ganadoras" y ventajas competitivas.
4.  **Expansión de Whitelist**: Integrados canales de Campeones y ESPN Fans para la UCL.

### 🛠️ Cambios Técnicos
- **`journalist_agent.py`**: Lógica de búsqueda dinámica inyectada desde `odds_canonical`.
- **`.env`**: Whitelist de UCL expandida.
- **`pipeline_last_run.log`**: Registra la captura de múltiples fuentes dinámicas.

## Sesión: Resiliencia (YouTube Fallback) y Documentación (23-Feb-2026, Tarde) 🛡️

### 🎯 Objetivos Logrados
1.  **Resiliencia Total (Fallback Anti-Cuota)**: 
    -   Implementado sistema de respaldo basado en `yt-dlp` en `YouTubeAPI`.
    -   El pipeline ahora es **inmune al límite de 10,000 unidades** de YouTube; si la API falla, el sistema extrae los 2 últimos videos de la Whitelist automáticamente.
2.  **Documentación de Arquitectura**: 
    -   Creación de `agentes_flow.md`: Guía exhaustiva con diagramas Mermaid, ejemplos de I/O y herramientas por agente.
3.  **Filtros de Contenido Avanzados**:
    -   Implementados **filtros negativos** en el Journalist Agent para descartar videos de "Ascenso" y "Caixun", asegurando que CHI1 contenga solo primera división.
4.  **Estabilidad de Código**:
    -   Corregido `NameError` (`odds_list`) que detenía el funcionamiento del pipeline en Streamit.

### 🛠️ Cambios Técnicos
- **`youtube_api.py`**: Nuevo método `get_latest_videos_no_api`.
- **`journalist_agent.py`**: Lógica de fallback integrada y filtros de exclusión.
- **`agentes_flow.md` [NUEVO]**: La "Biblia" del flujo de datos del proyecto.
- **`team_history.json`**: Actualizado con registros masivos de la jornada UCL.

### 📝 Notas de Cierre
- El sistema se deja en un estado **estable y documentado**.
- La auditoría de Streamit ahora refleja correctamente el uso del fallback cuando la API no está disponible.
- Próxima sesión: Monitoreo de precisión de los nuevos insights tras el "playlist mining".

## Sesión: Arquitectura Modular de Stats y Gate Agent (23-Feb-2026, Tarde) 🏗️

### 🎯 Objetivos Logrados
1.  **Reestructuración Modular de Stats**:
    -   Implementación del patrón **Adapter** en `stats_agent.py`.
    -   Nuevos adaptadores operativos: `ESPNAdapter`, `FootballDataAdapter`, `UefaAdapter` (Alineaciones) y `FbrefAdapter` (Advanced xG).
2.  **Identificadores Deterministas (match_key)**:
    -   El `Odds Fetcher` ahora genera una clave única (`COMP:DATE:home:away`) que sincroniza todo el pipeline.
3.  **Validación con Pydantic**:
    -   Creación de `agents/schemas.py` para garantizar la integridad de los datos entre agentes y proteger el "Contrato Legado".
4.  **Nacimiento del Gate Agent (Agente #5.5)**:
    -   Nodo de seguridad que filtra partidos con bajo `data_quality_score` antes de llegar al Analista.

### 🛠️ Cambios Técnicos
- **`agents/stats_agent.py`**: Refactorizado a arquitectura de adaptadores y merge multi-fuente.
- **`app.py`**: Actualizado con Auditoría de xG/Alineaciones y visualización del Gate Agent.
- **`utils/normalizer.py`**: Mejorado con `TeamNormalizer` y soporte para `difflib`.
- **`graph_pipeline.py`**: Pipeline extendido a **8 agentes**.

### 🔴 Error Persistente: Duplicidad Visual UCL
A pesar de la de-duplicación por slugs en el agregador y por nombre en la UI, el equipo "Real Madrid CF" (y posiblemente otros) persiste en aparecer duplicado en el Dashboard (expansor con datos y lista de "no disponibles" simultáneamente).

#### 🧐 Hipótesis para el Próximo Desarrollador (Legado):
1. **Diferencias de Encoding/Espacios**: Es posible que existan caracteres invisibles o variaciones de espacios entre el nombre obtenido de ESPN y el de UEFA/FBref que evaden el `set()` de de-duplicación en `app.py`.
2. **Inconsistencia de Keys**: El Agregador mezcla datos basados en un slug, pero la UI renderiza usando el campo `team`. Si el merge no actualiza el `team` al nombre canónico, se mantienen llaves divergentes.
3. **Caché Persistente**: Streamlit podría estar recuperando estados de ejecución anteriores si no se realiza un reinicio completo del servidor tras cambios estructurales en el JSON de salida.

### 🚀 Próximos Pasos
- **Sanitización Agresiva**: Aplicar `.strip().replace('\xa0', ' ')` a todos los nombres de equipos antes del merge y del renderizado.
- **Implementar de-duplicación por `match_id`**: Migrar la visualización de Auditoría para que use el ID canónico en lugar del nombre del equipo.
- **Scraping Real**: Transicionar los adaptadores de UEFA y FBref de placeholders a extracción real.

## Sesión: Resolución de Duplicidad UCL y Auditoría de Fuentes (23-Feb-2026, Noche) ✅

### 🎯 Objetivos Logrados
1.  **BUG RESUELTO: Duplicidad Visual de Equipos (Real Madrid CF)**:
    -   **Raíz del problema**: Inconsistencia de nombres entre proveedores (`"Real Madrid CF"` vs `"Real Madrid"`) causaba duplicación en UI.
    -   **Solución de 3 capas**:
        1. ✅ Agregado campo `canonical_name` en `agents/schemas.py` 
        2. ✅ Normalización en cada adapter (ESPN, Football-Data, UEFA, FBref)
        3. ✅ De-duplicación en `app.py` usando `canonical_name` en lugar de `team`

2.  **Auditoría Completa de Fuentes de Datos**:
    -   Análisis detallado de qué trae cada proveedor en producción.
    -   Documentación de flujo real: ODDS → STATS → NORMALIZER → MATCH_CONTEXTS

### 📊 Estado Actual de las Fuentes

#### **THE ODDS API** (✅ Activo)
- **Función**: Fuente de Verdad Única para partidos y cuotas
- **Datos**: 16 eventos en 2 competiciones (UCL, CHI1)
- **Ejemplo UCL**: Atlético Madrid vs Club Brugge (24 bookmakers), Bayer Leverkusen vs Olympiakos (25 bookmakers)
- **Ejemplo CHI1**: Cobresal vs La Serena (19 libros), Union La Calera vs Audax (19 libros)

#### **ESPN** (✅ Activo)
- **Función**: Estadísticas primarias para CHI1
- **Qué trae**: Posiciones, puntos, forma, partidos jugados
- **Ejemplo**: `"Cobresal"` → Pos 3, 15 pts
- **Original → Normalizado**: `"Cobresal"` → `"cobresal"`

#### **FOOTBALL-DATA.ORG** (✅ Activo)
- **Función**: Fallback de estadísticas de tabla
- **Qué trae**: Posiciones, G-E-P, goles, diferencia de gol
- **Ejemplo UCL**: `"Real Madrid CF"` → Pos 9, 13 pts
- **Original → Normalizado**: `"Real Madrid CF"` → `"real madrid"`

#### **UEFA** (🔶 PLACEHOLDER - EN DESARROLLO)
- **Función**: Datos oficiales de Champions League
- **Qué debería traer**: Alineaciones, formación, match facts (goles, tarjetas)
- **Estado**: Solo retorna estructura dummy con `"Real Madrid"`
- **Prioridad**: ALTA - Complementa UCL con datos en tiempo real

#### **FBREF** (🔶 PLACEHOLDER - EN DESARROLLO)
- **Función**: Métricas avanzadas para UCL
- **Qué debería traer**: xG (Goles Esperados), xAG (Asistencias Esperadas), possession%, tiros
- **Estado**: Solo retorna placeholders (`xg: 2.45, xag: 1.20`)
- **Prioridad**: ALTA - Essential para análisis táctico profundo

### 🔄 Flujo Real: Ejemplo "Real Madrid"

```
[1] THE ODDS API
    → home_team: "Real Madrid" vs away_team: "Benfica" [UCL, 2026-02-25]

[2] FOOTBALL-DATA (Stats Fetcher)
    → Match: "Real Madrid" ≈ "Real Madrid CF" (fuzzy match)
    → Retorna: stats.team = "Real Madrid CF", position = 9, points = 13

[3] NORMALIZER (Enriquecimiento)
    → canonical_name = "real madrid" (normalizado)
    → Mantiene: stats.team = "Real Madrid CF" (original para auditoría)

[4] MATCH_CONTEXTS (Output)
    → home.canonical_name = "real madrid" ✅
    → home.stats.team = "Real Madrid CF" (trazabilidad)
    → home.stats.provider = "football-data"

[5] STREAMLIT UI (Auditoría)
    → Usa canonical_name para de-duplicación
    → Renderiza: UNA SOLA entrada para "Real Madrid" ✅
    → Sin duplicación con "Real Madrid CF"
```

### 🛠️ Cambios Técnicos Implementados
- **`agents/schemas.py`**: Agregado campo `canonical_name: Optional[str]`
- **`agents/stats_agent.py`**: 
  - ESPNAdapter normaliza nombres con `TeamNormalizer.clean()`
  - FootballDataAdapter normaliza nombres con `TeamNormalizer.clean()`
  - UefaAdapter agrega `canonical_name`
  - FbrefAdapter agrega `canonical_name`
- **`agents/normalizer_agent.py`**: Usa `canonical_name` de stats o normaliza nombres de odds
- **`app.py` [Auditoría]**: De-duplicación basada en `canonical_name` + `_local_slug()` 

### ✅ Validación
```
Real Madrid CF → "real madrid"   (Normalized)
Arsenal FC     → "arsenal"       (Normalized)
Bayern München → "bayern münchen" (Normalized)
FC Barcelona   → "barcelona"     (Normalized)
```

Test unitario `test_normalizer.py` confirma:
- ✅ Schema `TeamStatsCanonical` acepta `canonical_name`
- ✅ Normalización consistente entre proveedores
- ✅ De-duplicación en UI funcional

### 🚀 Próximo Paso: Desarrollo de UEFA y FBref

**Tareas para próxima sesión:**

1. **UEFA Adapter** (High Priority)
   - Implementar scraping real desde API oficial de UEFA (si existe)
   - O parser de datos desde UEFA.com
   - Objetivos:
     - Alineaciones (formation, starting XI, bench)
     - Match facts (goals, cards, substitutions por minuto)
     - Estadísticas en tiempo real durante el partido

2. **FBref Adapter** (High Priority)
   - Scraping de Football-Reference.com para xG/xAG
   - O integración con Understat (si disponible)
   - Objetivos:
     - Expected Goals (xG)
     - Expected Assists (xAG)
     - Possession %
     - Shots, Shots on Target

3. **Validación**
   - Testear que ambos adapters entregan `canonical_name` normalizado
   - Verificar no hay duplicación con datos de ESPN/Football-Data
   - Asegurar data_quality_score refleja completitud de datos

### 📝 Notas Técnicas
- La de-duplicación es **agnóstica al provider**: funciona porque normaliza TODOS los nombres
- `canonical_name` es persistido en JSONs para auditoría y trazabilidad
- Los datos originales (`team`) se conservan para debugging

---

### [2026-02-27] Corrección: Marcador Incorrecto Inter vs Bodø/Glimt (Evaluador)
- **Problema**: El evaluador mostraba 3-1 a favor del Inter para el partido del 24/02 (UCL), cuando el resultado real fue 1-2.
- **Causa**: Confusión con el partido de ida (18/02) y falta de alias para "Internazionale" en el evaluador, sumado a una lógica de local/visitante poco estricta que invertía marcadores ante nombres no idénticos.
- **Acciones**:
    - Se agregaron alias manuales ("Internazionale" -> "inter milan", etc.) en `agents/evaluator_agent.py`.
    - Se implementó `is_match` con intersección de tokens y fuzzy ratio (`difflib`).
    - Se endureció la validación: ahora requiere que AMBOS nombres de equipo coincidan (directo o invertido) para asignar el score.
- **Resultado**: El historial ahora muestra correctamente **1-2** para el Inter el 24/02.
## Sesión: Enhancements de UI, Métrica de Acierto de Marcador y Logging de Evaluador (26-Feb-2026, Tarde) 📈

### 🎯 Objetivos Logrados
1. **Nuevo KPI de Precisión de Marcador**:
   - Se implementó un algoritmo ponderado en `app.py` que calcula un porcentaje de certeza del marcador predecido vs. el score real (40% lado ganador, 30% a los goles del local, 30% a los goles del visitante).
   - Se expuso el **Promedio del KPI** en el Dashboard global y también de forma segregada en las sub-tablas Accuracy por Modelo y Accuracy por Liga.

2. **Estabilidad del Historial Legacy en UI**:
   - Streamlit ocultaba la columna `match_date` debido a registros antiguos nulos. Se agregó una lógica de extracción tri-fase (`match_date` explícito -> Regex del `prediction_id` -> `generated_at`).
   - Se corrigieron los remanentes dobles de Newcastle eliminando el resultado duplicado de ida.

3. **Identificación Efectiva del Modelo**:
   - Limpieza del placeholder `unknown` en los pipelines de historial JSON.
   - Ahora tanto `app.py` como `evaluator_agent.py` atribuyen los aciertos consolidados del sistema al modelo `gpt5`.

### 💡 Aprendizajes (Lessons Learned)
-   **Las columnas en Streamlit DataFrame** desaparecen de render si toda la lista viene vacía o con `None Type`, confundiendo la visualización.
-   **Atribuir modelos** desde un inicio permite a futuro hacer A/B Testing contra versiones como GPT-4.1 o Claude para entender qué LLM predice mejores cuotas y marcadores.

---
## Sesión: 2026-02-26 - Tarde (Contexto Psicológico & Predicción Secuencial)

### 🎯 Objetivos Logrados
1. **Contexto Psicológico y Geográfico (Web Agent)**:
   - Se entrenó al `web_agent.py` para detectar variables críticas en un lookback de 7 días: resultados de ida en UCL (`aggregate_score`), fatiga por torneos internacionales en CHI1 (`international_fatigue`, `heavy_rotation`) y localías extremas (`extreme_venue` como altura o desierto).
   - Estas señales se inyectan como etiquetas estructuradas al analista.

2. **Caducidad Inteligente (TTL) en Memoria**:
   - Implementación de `ttl_days` en `insights_agent.py`. Ahora las señales del historial tienen fecha de vencimiento:
     - *Fatiga*: 5 días.
     - *Rotación*: 4 días.
     - *Resultados de Ida*: 8 días.
     - *Lesiones*: 30 días.
   - Esto evita que el analista "recuerde" ruidos físicos que ya pasaron.

3. **Predicción Secuencial (Partido a Partido)**:
   - Refactoreo crítico de `analyst_agent.py`. Se eliminó el procesamiento en "batch" (bloque de liga) por uno secuencial.
   - **Beneficio**: Al predecir un solo partido, el LLM tiene atención total. Pudimos subir el límite de historial de 4 a **20 insights** por equipo sin saturar el contexto.
   - Se aumentó la calidad del `rationale` y la precisión estimada del marcador.

### 💡 Aprendizajes (Lessons Learned)
-   **Fatiga Acumulada**: En el fútbol chileno, los equipos con planteles cortos sufren caídas drásticas de rendimiento tras jugar Copa Libertadores/Sudamericana. Capturar esto mecánicamente mediante fechas (`datetime`) es más fiable que el análisis textual vago.
-   **Atención del LLM**: El rendimiento de GPT-5 (o cualquier modelo) se degrada cuando se le pide parsear 10 JSONs complejos en una sola respuesta. La inferencia secuencial es más lenta pero infinitamente más robusta.

### 🗓️ Sesión 2026-02-27 - Pattern Discovery & Web Check Force
**Objetivo**: Forzar búsqueda web en todos los partidos para identificar patrones de necesidad de información del Analista.

**Logros**:
- Implementado `ANALYST_WEB_CHECK_FORCE_ALL` y generador de consultas genéricas.
- Corregido bug de persistencia en `state.py` (añadido `analyst_web_checks`).
- Identificados patrones clave:
  - **Descarte de errores**: El analista detectó que Juan Cabal (expulsado en UCL) juega en Juventus y no en Galatasaray.
  - **Validación de dudas**: Seguimiento en tiempo real de lesiones de Tillman (Leverkusen) y Fabián Ruiz (PSG).
  - **Datos locales**: Rescate de sanciones históricas en CHI1 (Jorge Henríquez).
- Resiliencia: Activación exitosa de reparación de JSON automática ante fallos de formato del modelo de búsqueda.

**ESTADO DE LA SESIÓN:** Abierta. Forzado web activo.

### [2026-02-27] Regla Dura: Identidad de Concepción (PRO)
Se ha implementado una solución definitiva y robusta para evitar la confusión entre **Universidad de Concepción** y **Deportes Concepción**.

**Cambios Técnicos:**
1.  **Blacklist de Matching**: Nueva función `_is_blacklisted_match` que bloquea específicamente el par conflictivo.
2.  **Protección de Tokens Ambiguos**: La "Estrategia D" (tokens largos) ahora ignora palabras en `_AMBIGUOUS_TOKENS` (como "concepción" o "madrid").
3.  **Alias Extendidos**: Se agregaron variantes de "D. Concepcion" y "Univ de Concepcion" al normalizador global.

> [!IMPORTANT]
> Esta mejora previene colisiones futuras en equipos que compartan nombres de ciudades largos.

---

### [2026-02-27] Corrección de Marcador: Inter Milan vs Bodø/Glimt
- **Problema**: El sistema mostraba 3-1 para el Inter cuando el resultado real fue 1-2 (24/02).
- **Causa**: Confusión con el partido de ida (18/02) y matching inconsistente de nombres (Internazionale vs Inter Milan).
- **Solución**:
  - Implementado matching robusto con `difflib.SequenceMatcher` y tokens en `evaluator_agent.py`.
  - Añadidos alias manuales para equipos europeos.
  - Endurecida la validación de localía (ambos equipos deben coincidir).
- **Resultado**: El marcador en `predictions_history.json` ahora es correcto (**1-2**).

### [2026-02-27] Regla Dura: Identidad de Concepción (v2)
- **Bug**: El matching persistía en confundir U. de Concepción con Deportes Concepción por la longitud del token "concepcion" (Estrategia D).
- **Solución**:
  - Implementada `_is_blacklisted_match` para bloqueo explícito del par.
  - Refinada Estrategia D en `normalizer_agent.py` para ignorar tokens ambiguos.
  - Actualizado `manual_map` en `utils/normalizer.py` con alias de "Deportes Concepción".
- **Resultado**: Matching 100% preciso para ambos equipos.

---
### 🛠️ IMPLEMENTACIÓN: Contador de Tokens LLM (Incremental)
- **Fecha**: 2026-02-27
- **Objetivo**: Trackear el uso de tokens por modelo para control presupuestario.
- **Cambios Realizados**:
  - Creado `utils/token_tracker.py` para gestión persistente en `token_usage.json`.
  - Integrados callbacks de LangChain en `analyst`, `insights`, `journalist` y `evaluator`.
  - Implementado rastreo manual en `web_agent` y `analyst_web_check` (OpenAI SDK).
  - Añadida pestaña **💸 Presupuesto** en `app.py` con tabla de consumo y botón de reinicio.
- **Validación**: Script `/tmp/test_tokens.py` confirmó el correcto funcionamiento del contador.

---
**SESIÓN FINALIZADA.** Bitácora cerrada por Germán.
---
### Sesion 2026-02-28 - Bug Fixes and Auditoria Mejorada

**Objetivo**: Corregir bug de insights vacios y mejorar la pestana de Auditoria de APIs.

**Bugs Corregidos:**

#### Bug #1 - journalist_agent.py reemplazado por stub vacio
- **Causa**: Durante la integracion del contador de tokens, el nodo journalist_agent_node fue reemplazado accidentalmente por un stub que solo devolvia listas vacias de videos, sin poblar state['insights_sources'].
- **Sintoma**: La pestana Auditoria de APIs mostraba 'Sin datos' en YouTube (Insights tacticos).
- **Solucion**: Restauracion completa del journalist_agent.py con toda la logica original:
  - Busqueda en whitelist de canales (TNT Sports, ThonyBet, etc.)
  - Busquedas dinamicas por equipo de la jornada
  - Busquedas genericas de respaldo multiidioma (es, en, pt)
  - Scoring de relevancia y reputacion
  - Refinamiento con LLM
  - Poblado correcto de state['insights_sources'] (campo clave que lee el insights_agent)
- **Validacion**: Import sin errores confirmado.

#### Mejora - Pestana Auditoria de APIs: Cobertura Total del Pipeline
- **Antes**: 5 secciones (Odds, ESPN, Periodista, YouTube/Insights, MatchContext).
- **Ahora**: 10 secciones cubriendo todos los agentes del pipeline:
  1. Agente #1 - Odds API
  2. Agente #2 - ESPN Stats
  3. Agente #3 - Periodista (YouTube Discovery)
  4. Agente #4 - Insights (YouTube + LLM)
  5. Agente Web (contexto panoramico)
  6. Analyst Web Check (verificaciones on-demand)
  7. Gate Agent (auditoria de calidad con PASS/FAIL)
  8. Normalizador (MatchContext completo)
  9. Analista (predicciones con gaps)
  10. Apostador (value bets y combinadas)
- Metricas globales agregadas al tope de la pestana.

**ESTADO DE LA SESION:** Cerrada. Pipeline operativo.

---
**SESION FINALIZADA.** Bitacora cerrada por German.
---
### Sesion 2026-03-02 - Mejora de Precision del Pipeline

**Objetivo**: Subir el porcentaje de aciertos diagnosticando y corrigiendo los fallos del analista y del Bettor.

**Diagnostico (54 partidos evaluados):**
- Precision global: 25.9%
- Signo 1 (local): 12/29 = 41.4% -- el unico razonablemente bueno
- Signo X (empate): 1/16 = 6.2% -- casi nunca acierta
- Signo 2 (visitante): 1/9 = 11.1% -- casi nunca acierta
- Confianza media en correctos: 66.4% vs incorrectos: 64.0% -- no discrimina
- El modelo predecia local 54% del tiempo cuando la realidad es 40.7%

**Causas Raiz Identificadas:**
1. Prompt le decia al modelo 'NO sigas al mercado' -- eliminando la mejor senal disponible
2. Escala de confianza 50-95 no calibrada (no es probabilidad real)
3. Umbral del Bettor demasiado bajo (5% edge, 60% confianza)

**Cambios Implementados:**

1. agents/analyst_agent.py -- funcion _format_odds_context:
   - Ahora calcula probabilidades implicitas normalizadas de cada cuota
   - Muestra el FAVORITO DEL MERCADO con estrella en el prompt
   - El modelo recibe: Local=47.6% | Empate=29.4% | Visitante=31.2%

2. agents/analyst_agent.py -- funcion _build_analyst_prompt_single:
   - ANCLA BAYESIANA: las cuotas son el punto de partida obligatorio
   - Regla: si no hay evidencia concreta, seguir al favorito del mercado
   - Calibracion de confianza real (45-85, no 50-95)
   - Penalizaciones por datos pobres (pos=99: -12pts, forma vacia: -8pts)
   - Distribucion historica explicita: CHI1 40/27/33, UCL 45/24/31
   - Regla anti-sesgo local: localidad sola NO es suficiente para predecir victoria
   - Campo nuevo en output: market_prob_used (audit trail)

3. agents/bettor_agent.py:
   - MIN_CONFIDENCE subido de 60 -> 68
   - MIN_EDGE_PCT subido de 5% -> 8%
   - MIN_ODDS subido de 1.20 -> 1.30 (evitar cuotas de favoritos extremos)
   - Nueva proteccion contra-mercado: si pred va contra el mercado y conf < 72%, se marca con warning y stake se reduce 50%
   - Campo market_prob en el tip para auditoria

**Validacion:** py_compile OK en ambos archivos.

---

## Sesión: Mejora de Precisión + Sistema de Retroalimentación (02-Mar-2026)

### 🎯 Problema diagnosticado
- Precisión global: **25.9%** sobre 54 partidos evaluados
  - Signo 1 (local): 41.4% OK | Signo X (empate): 6.2% OK | Signo 2 (visitante): 11.1% OK
  - Confianza media correctos: 66.4% vs incorrectos: 64.0% → no discrimina
  - El modelo predecía local el 54% de las veces cuando la tasa real es 40.7%
- UCL: solo 18.2% de precisión (el más crítico)

### 📌 Correcciones al pipeline base (Gepeto)

**1. agents/analyst_agent.py — `_format_odds_context`**
- Calcula probabilidades implícitas normalizadas de cada cuota
- Muestra el favorito del mercado con ⭐ en el prompt (ej: `⭐ FAVORITO: LOCAL (1) con 47.8%`)

**2. agents/analyst_agent.py — `_build_analyst_prompt_single`**
- Ancla bayesiana obligatoria: las cuotas son el punto de partida, no un dato secundario
- Escala de confianza ajustada de 50-95 → **45-85** (más honesta)
- Penalizaciones explícitas: pos=99 → -12pts, forma vacía → -8pts, sin insights → -5pts
- Distribución histórica explícita en el prompt: CHI1 40/27/33%, UCL 45/24/31%
- Regla anti-sesgo local: "ser local NO es razón suficiente para predecir victoria"
- Campo nuevo en JSON de salida: `market_prob_used`

**3. agents/bettor_agent.py — Umbrales más estrictos**
- `MIN_CONFIDENCE`: 60 → **68**
- `MIN_EDGE_PCT`: 5% → **8%**
- `MIN_ODDS`: 1.20 → **1.30**
- Stake máximo: 5u → **4u**
- Protección contra-mercado: si pred va contra el mercado y conf < 72%, se añade `warning: contra_mercado_baja_conf` y el stake se reduce 50%
- Campo `market_prob` agregado al tip para auditoría

**Resultado del primer pipeline con mejoras:**
- Confianza media: **51.3%** (antes: 64%) → mucho más calibrada
- Distribución local/visitante: **37.5% / 62.5%** (antes: 54% local) → bias corregido
- Value bets: 0 (correcto: umbral más exigente)

---

### 🚀 Sistema de Retroalimentación y Mejora Continua (nuevo)

**Arquitectura implementada:** ciclo cerrado Pipeline → Post-Match → Feedback → Memoria → Pipeline

**4. agents/analyst_agent.py — Historial enriquecido**
- `_save_predictions_history` ahora guarda: `market_prob_used`, `home_pos`, `away_pos`, `home_form`, `away_form`, `had_youtube_insights`, `had_espn_stats`, `data_quality_flags`, `post_match_observation`

**5. agents/post_match_agent.py (NUEVO)**
- Evalúa predicciones pendientes (result=null) cuya fecha ya pasó
- Obtiene resultado real de ESPN (reutiliza lógica del evaluator_agent)
- Genera `post_match_observation` estructurada con tipos de error estandarizados:
  - `correct`, `draw_missed`, `home_bias`, `overconfident_wrong`
  - `market_divergence_loss`, `market_alignment_loss`, `data_poverty_miss`, `upset`
- Se ejecuta **asíncrono** desde la UI (botón "🔍 Ejecutar Agente Revisor")

**6. agents/feedback_agent.py (NUEVO)**
- Analiza estadísticas segmentadas por liga (CHI1 y UCL **separadas**)
- Usa **GPT-5** para generar lecciones concretas y accionables
- Genera `predictions/analyst_memory.json` con secciones por liga

**7. agents/analyst_agent.py — Inyección de lecciones**
- Funciones nuevas: `_load_analyst_memory()`, `_format_memory_section()`
- El prompt del analista ahora incluye sección `LECCIONES APRENDIDAS DE PARTIDOS PASADOS` con las lecciones específicas de la liga del partido

**8. app.py — Pestaña "🤖 Memoria del Analista" (NUEVA)**
- Botón `🔍 Ejecutar Agente Revisor` → corre Post-Match Agent + Feedback Agent en thread asíncrono
- Visualización de métricas, distribuciones, tipos de error y lecciones por liga
- Sub-tabs CHI1 y UCL con métricas independientes

### 📊 Primera Memoria del Analista generada (54 partidos)
- **CHI1** (32 partidos, 31.2%): errores principales → `draw_missed` (8), `market_alignment_loss` (9), `home_bias` (4)
- **UCL** (22 partidos, 18.2%): errores principales → `home_bias` (7 = más frecuente), `market_alignment_loss` (6), `draw_missed` (5)
- Lección GPT-5 para ambas ligas: *"Si la cuota de empate es ≤ 3.20, el empate es igualmente probable. No lo descartes sin evidencia."*

### ✅ Archivos modificados/creados
- `agents/analyst_agent.py` (modificado × 3 funciones)
- `agents/bettor_agent.py` (modificado × 2 constantes + `_analyze_value`)
- `agents/post_match_agent.py` (NUEVO)
- `agents/feedback_agent.py` (NUEVO)
- `app.py` (nueva pestaña)
- `predictions/analyst_memory.json` (GENERADO)

---

**9. Depuración de Trazabilidad y "Golden Mapping Table" (CHI1)**
- **Problema**: Triplicación de equipos en el selector de 'Rastreo de Agentes' (ej: "U Católica vs U Católica") y omisión de contextos críticos (ej: Palestino eliminando a la U).
- **Causa Raíz**: 
  1. **Fuzzy Matching Ambiguo**: "U de Chile" y "U de Concepción" se mapeaban por error a "U Católica" al usar solo el token "Universidad" como ancla.
  2. **Doble Renderizado**: Señales web se listaban en el análisis y se repetían abajo.
  3. **Falta de Trazabilidad Global**: El Agente Web solo mostraba datos si el equipo tenía partido hoy, perdiendo panorámicas de liga.
- **Solución Implementada**:
  - **Golden Mapping Table** (`utils/chi1_golden_mapping.json`): Tabla maestra con nombres oficiales y alias para CHI1. Prioridad absoluta sobre matching difuso.
  - **Normalizador Robusto**: Se añadió "universidad" a `_AMBIGUOUS_TOKENS`. `TeamNormalizer` ahora carga y prioriza el mapeo canónico.
  - **Deduplicación Semántica**: `insights_agent.py` ignora variaciones triviales ("recientemente", "hoy") para no duplicar señales.
  - **Sección "Panorámica Global"**: UI nueva en 'Rastreo' que permite ver noticias de TODOS los equipos usando `web_agent_output.json`.
  - **Optimización de Prompt**: El Agente Web ahora busca activamente eventos "rompe-esquemas" (crisis, eliminaciones, renuncias) de las últimas 72h.
- **Aprendizajes**:
  - El matching difuso requiere salvaguardas (tokens ambiguos) y tablas de verdad estáticas para ligas locales.
  - La persistencia web debe ser acumulativa para mantener el contexto histórico reciente.
  - La UI debe tener capas de seguridad (labels únicos) para detectar inconsistencias de datos de raíz.

### ✅ Archivos modificados/creados
- `app.py` (modificado: Implementación de flujo try/finally + taskkill + botón de parada)

**13. Botón de Parada (Stop Button)**
- **Causa**: Necesidad del usuario de interrumpir ejecuciones largas del pipeline si detecta errores o consume demasiados créditos.
- **Solución**: Se implementó una gestión de procesos mediante `st.session_state` para rastrear el PID. Se envolvió la ejecución en un `try...finally` que asegura el cierre del proceso (y sus hijos agentes) mediante `taskkill /F /T`.
- **Resultado**: Nuevo botón "🛑 DETENER" disponible en la barra lateral durante la ejecución.

**10. Mejora del Agente Periodista (Filtros)**
- **Problema**: El filtro negativo `"la liga"` causaba descartes de videos legítimos como "La Liga de Primera" (Chile).
- **Solución**: 
  - Se implementó un `has_priority` que detecta términos clave como "TST" o "Pizarra Táctica" y anula el filtro negativo.
  - Se refinaron términos genéricos como "la liga" usando expresiones regulares (`\bla liga\b`) para exigir coincidencia exacta de palabra.
- **Aprendizaje**: Los filtros negativos por substring son peligrosos en contextos donde el nombre de la liga es genérico. Se debe priorizar la presencia de términos de "autoridad" (como el nombre del programa) sobre palabras prohibidas.

---

## Sesión 2026-03-06 — Corrección estructural de nombres de equipos + Wishlist en Web Agent

### 14. Corrección Estructural: Confusión de Nombres de Equipos

- **Causa**: El pipeline confundía equipos con nombres similares (ej: "Deportes Concepción" con "Universidad de Concepción"), generando contexto contaminado para el analista. La revisión de código identificó **3 caminos de contaminación** y **4 colisiones confirmadas** por script de simulación real.
- **Colisiones detectadas (antes del fix)**:
  - `"la u"` → U. Católica (Jaccard 1.0 post-Golden Mapping)
  - `"u concepcion"` → Deportes Concepción (Jaccard 0.5 pasa Step C del matcher)
  - `"concepcion"` → Deportes Concepción (Substring antes del blacklist)
  - `"concepcion"` → U. de Concepción (Substring antes del blacklist)
- **Solución — 3 fixes estructurales**:
  - **Fix PRIMARIO** (`agents/normalizer_agent.py`): `_is_blacklisted_match` reescrita para evaluar **tanto slugs originales como canónicos** (post-Golden Mapping). Se llama ahora **ANTES** del check de substring en `_fuzzy_match`. Se añadieron 4 reglas cubriendo los 5 equipos conflictivos solicitados: U. de Concepción vs Deportes Concepción, aliases "conce/concepcion" vs universidades, todos los pares Universidad-vs-Universidad, y Deportes Limache vs Deportes Concepción. Guardia añadida también en `_find_team_history_entries`.
  - **Fix SECUNDARIO** (`agents/insights_agent.py`): Guardia `_is_blacklisted_match` en mapeo LLM→equipo.
  - **Fix TERCIARIO** (`agents/insights_agent.py`): `team_history.json` ahora se escribe siempre bajo `canonical_key = normalizer_tool.clean(team)`.
- **Golden Table** (`utils/chi1_golden_mapping.json`):
  - U. de Concepción ← `"la u de conce"`, `"el campanil"`, `"campaneros"`, `"udc"`.
  - Deportes Concepción ← `"conce"`, `"el conce"`, `"concepcion"`, `"dep concepcion"`.
- **Verificación**: **13/13 PASS** en suite de tests automatizados.

### 15. Limpieza de team_history.json

- **Causa**: Claves guardadas con nombres no canónicos (mayúsculas, alias) podían causar matches cruzados futuros.
- **Solución**: Script re-canonizó las 41 claves → 40 claves canónicas limpias. `"Everton"` y `"Everton de Viña del Mar"` fusionados correctamente en `"everton"`.
- **Archivo**: `data/knowledge/team_history.json`.

### 16. Integración Wishlist del Analista con Web Agent

- **Causa**: La wishlist del analista (`predictions/analyst_wishlist.json`) con necesidades específicas por partido (lesiones, XI, cuotas, stats) **no llegaba al Web Agent**. El agente buscaba información genérica sin responder las preguntas concretas.
- **Solución**: Nueva función `_build_wishlist_block(fixtures)` en `agents/web_agent.py`:
  1. Filtra necesidades de la wishlist por los equipos de cada partido de la jornada.
  2. Ordena por prioridad (alta → media → baja) con íconos de categoría.
  3. Inyecta el bloque al prompt del Web Agent como sección "PREGUNTAS ESPECÍFICAS DEL ANALISTA (Responder OBLIGATORIAMENTE)".
  4. Las respuestas fluyen como `context_signals` → Insights Agent → Analista, sin cambios en esos agentes.
- **Resultado**: El LLM del Web Agent ahora busca respuestas concretas: "¿Rivero está convocado?", "¿XI probable de O'Higgins?", etc.

### 17. Limpieza de Wishlist Contaminada + Ventana de Búsqueda

- **Causa**: La wishlist tenía una entrada donde se pedía info de Larrivey/Grillo (Deportes Concepción) asignada incorrectamente a `"Universidad de Concepción"` — contaminación generada antes del fix del normalizador.
- **Solución**:
  - Se eliminó la entrada contaminada de `predictions/analyst_wishlist.json`.
  - Ventana de búsqueda del Web Agent extendida de **48h/72h → 5 días** en el prompt.
- **Archivos**: `predictions/analyst_wishlist.json`, `agents/web_agent.py`.

### ✅ Archivos modificados esta sesión
- `agents/normalizer_agent.py`
- `agents/insights_agent.py`
- `utils/chi1_golden_mapping.json`
- `data/knowledge/team_history.json`
- `agents/web_agent.py`
- `predictions/analyst_wishlist.json`
