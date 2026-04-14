# 📋 Checklist de Implementación: Tournament Research Agent v2.0

**Última actualización:** 2026-04-02

---

## ✅ FASE 0: Validaciones Previas (Pre-Requisitos)

- [x] **Costo system corregido**
  - [x] pricing.json: USD/1M ✅
  - [x] utils/costing.py: ÷1_000_000 ✅
  - [x] test_costing.py: 5/5 PASS ✅
  - [x] audit_report.py: Regenerado con costos correctos (~$0.0038 USD) ✅

- [x] **Infraestructura de token tracking**
  - [x] utils/token_tracker.py: Existe y funciona
  - [x] token_usage.json: Archivo persistente presente
  - [x] TokenTrackingCallbackHandler: Conectado

- [x] **Bitácora y especificaciones**
  - [x] bitacora.md: Leído y analizado
  - [x] agentes_flow.md: Leído (Tour Research Agent en agente #3.5)
  - [x] PLAN_REIMPLEMENTACION.md: Creado

---

## 📝 FASE 1: Reescritura Core de `agents/web_agent.py`

### Subtarea 1.1: Función principal `run_tournament_research()`
- [ ] Reemplazar o refactorizar función actual para:
  - [ ] Cargar wishlist del analista
  - [ ] Calcular firma de cache (torneo + fixtures + wishlist hash)
  - [ ] Verificar si existe en web_agent_output.json (check TTL)
  - [ ] Si fresco: reutilizar (retornar con cache_hit=true)
  - [ ] Si no fresco: generar nuevo JSON v2
- [ ] **Tiempo estimado:** 90 minutos
- [ ] **Archivo:** `agents/web_agent.py` líneas ~200-300

### Subtarea 1.2: Validadores de sanidad temporal
- [ ] Implementar `_validate_temporal_sanity(snippet: str, year: int = 2026) -> bool`
  - [ ] Check 1: Menciona año 2026 OR es reciente
  - [ ] Check 2: NO es género femenino
  - [ ] Check 3: NO equipos "fantasma" sin contexto 2026
  - [ ] Check 4: DT vigente (si aplica)
- [ ] Implementar `_validate_coach_2026(coach_name: str, team: str) -> bool`
- [ ] Implementar `_is_recent_snippet(snippet: str) -> bool` (helper)
- [ ] **Tiempo estimado:** 45 minutos
- [ ] **Archivo:** `agents/web_agent.py` líneas ~50-100

### Subtarea 1.3: Prompt Tournament v2.0
- [ ] Actualizar `_build_tournament_prompt()` con:
  - [ ] "Guillotina Temporal": Prohibir explícitamente noticias sin 2026
  - [ ] "Filtro de Género": NO mezclar Femenino/Masculino
  - [ ] "Validación de DT": Verificar vigencia en 2026
  - [ ] "Tabla de Posiciones": Obtener líder, colista, situación actual
  - [ ] "Todos los equipos": Obligar a incluir 100% de los equipos (no omitir)
- [ ] **Tiempo estimado:** 30 minutos
- [ ] **Archivo:** `agents/web_agent.py` líneas ~180-220

### Subtarea 1.4: Parseo y validación de JSON v2
- [ ] Función `_parse_tournament_research_json(response: str) -> dict`
  - [ ] Validar estructura v2 (19+ campos requeridos)
  - [ ] Preservar campos legacy para compatibilidad
  - [ ] Detectar contradicciones lógicas (flags contradictory señales)
  - [ ] Anotar stale_signals_detected si hay noticias anacrónicas
- [ ] **Tiempo estimado:** 45 minutos
- [ ] **Archivo:** `agents/web_agent.py` líneas ~320-380

### Subtarea 1.5: Persistencia con firma de cache
- [ ] Función `_save_to_cache(competition, signature, data)`
  - [ ] Estructura: `{ "signature": "abc123", "generated_at": "iso8601", "data": {...} }`
  - [ ] TTL por competencia (CHI1/CHI2/UCL configurable en .env)
- [ ] Función `_load_from_cache(competition, signature) -> Optional[dict]`
  - [ ] Validar TTL (¿generado hace < X horas?)
- [ ] **Tiempo estimado:** 30 minutos
- [ ] **Archivo:** `agents/web_agent.py` líneas ~80-120

---

## 🔧 FASE 2: Validación de Infraestructura

### Subtarea 2.1: Validar `utils/llm_factory.py` perfil web_research_forced
- [ ] Verificar que existe perfil "web_research_forced"
- [ ] Verificar que resuelve modelo por `WEB_RESEARCH_MODEL` env var
- [ ] Verificar que aplica tope `WEB_RESEARCH_MAX_TOKENS`
- [ ] Verificar que conecta `TokenTrackingCallbackHandler`
- [ ] Verificar que retorna ChatOpenAI (no Gemini)
- [ ] **Tiempo estimado:** 20 minutos
- [ ] **Archivo:** `utils/llm_factory.py` líneas ~50-100

### Subtarea 2.2: Validar `utils/token_tracker.py`
- [ ] Verificar que `track_tokens()` persiste en token_usage.json
- [ ] Verificar estructura: model → {prompt_tokens, completion_tokens, total, calls, last_updated}
- [ ] Verificar que se llama automáticamente desde callbacks
- [ ] **Tiempo estimado:** 15 minutos
- [ ] **Archivo:** `utils/token_tracker.py` líneas ~20-60

### Subtarea 2.3: Validar `pricing.json` y `.env`
- [ ] Confirmar pricing.json: `*_per_1m_usd` (no `*_per_1k_usd`)
- [ ] Confirmar tarifas gpt-4.1-mini: 0.40 (input), 1.60 (output)
- [ ] Confirmar .env tiene:
  - [ ] `WEB_RESEARCH_MODEL=gpt-4.1-mini`
  - [ ] `WEB_RESEARCH_MAX_TOKENS=2000`
  - [ ] `EXCHANGE_RATE_CLP_PER_USD=900`
  - [ ] `WEB_AGENT_CACHE_TTL_HOURS=6`
- [ ] **Tiempo estimado:** 10 minutos
- [ ] **Archivo:** pricing.json, .env

---

## 🧪 FASE 3: Pruebas Unitarias y de Integración

### Test 3.1: Cache Hit
- [ ] Crear test `test_web_agent_cache_hit()`
  - [ ] Correr `run_tournament_research()` 1ra vez (1° fixture)
  - [ ] Correr `run_tournament_research()` 2da vez (mismo fixture)
  - [ ] Validar: `coverage_meta.cache_hit == true` en 2da
  - [ ] Validar: `coverage_meta.cost_usd == 0` en 2da
  - [ ] Validar: ambas respuestas tienen mismo signature
- [ ] **Tiempo estimado:** 30 minutos
- [ ] **Archivo:** `tests/test_web_agent_v2.py`

### Test 3.2: Temporal Sanity (Noticias Anacrónicas)
- [ ] Crear test `test_web_agent_detects_stale_signals()`
  - [ ] Inyectar snippet con "Palermo como técnico en O'Higgins" (falso)
  - [ ] Validar: `stale_signals_detected` lo incluye
  - [ ] Validar: señal está marcada con `status="stale"`
- [ ] **Tiempo estimado:** 25 minutos
- [ ] **Archivo:** `tests/test_web_agent_v2.py`

### Test 3.3: Género Confundido
- [ ] Crear test `test_web_agent_rejects_female_content()`
  - [ ] Inyectar resultado de "U. de Chile Femenino"
  - [ ] Validar: `_validate_temporal_sanity()` retorna False
  - [ ] Validar: NO aparece en team_research
- [ ] **Tiempo estimado:** 20 minutos
- [ ] **Archivo:** `tests/test_web_agent_v2.py`

### Test 3.4: JSON v2 Completo
- [ ] Crear test `test_web_agent_json_v2_structure()`
  - [ ] Validar 19+ campos nuevos presentes
  - [ ] Validar campos legacy presentes (competition_summary, teams)
  - [ ] Validar cada equipo en team_research tiene todos los required fields
- [ ] **Tiempo estimado:** 25 minutos
- [ ] **Archivo:** `tests/test_web_agent_v2.py`

### Test 3.5: Costeo Correcto
- [ ] Crear test `test_web_agent_costing_accuracy()`
  - [ ] Correr Tournament Research Agent
  - [ ] Validar `coverage_meta.cost_usd < 0.01` (< 1 centavo USD)
  - [ ] Validar `coverage_meta.cost_clp < 10` (< 10 CLP)
  - [ ] Validar tokens consolidados por modelo (no duplicados)
- [ ] **Tiempo estimado:** 25 minutos
- [ ] **Archivo:** `tests/test_web_agent_v2.py`

---

## 🚀 FASE 4: Integración en Pipeline

### Subtarea 4.1: Runner standalone
- [ ] Crear/actualizar `run_web_agent.py`
  - [ ] Argumento `--mode`: "node" (standalone) O "integrated" (pipeline)
  - [ ] Argumento `--competition`: CHI1, CHI2, UCL (default all)
  - [ ] LOG completo del JSON generado
  - [ ] Reporte de costos por corrida
- [ ] **Tiempo estimado:** 30 minutos
- [ ] **Archivo:** `run_web_agent.py` (NEW or UPDATE)

### Subtarea 4.2: Integración en `run_pipeline.py`
- [ ] Verificar que run_pipeline invoca run_tournament_research() en el lugar correcto
- [ ] Verificar que pasa fixtures y state correctamente
- [ ] Verificar que LOG muestra el JSON v2 generado (auditoría)
- [ ] **Tiempo estimado:** 15 minutos
- [ ] **Archivo:** `run_pipeline.py`

---

## 📊 FASE 5: Validación de Costeo y Benchmarking

### Benchmark 5.1: Costo 1ra Corrida
- [ ] Ejecutar: `python run_web_agent.py --mode node --competition CHI1`
- [ ] Validar: `coverage_meta.cache_hit = false`
- [ ] Validar: `coverage_meta.cost_usd < 0.01` USD
- [ ] Validar: `coverage_meta.cost_clp < 10` CLP
- [ ] Captura de screenshot o log
- [ ] **Tiempo estimado:** 10 minutos

### Benchmark 5.2: Costo 2da Corrida (Cache Hit)
- [ ] Ejecutar NUEVAMENTE (mismos parámetros): `python run_web_agent.py --mode node --competition CHI1`
- [ ] Validar: `coverage_meta.cache_hit = true`
- [ ] Validar: `coverage_meta.cost_usd == 0` USD
- [ ] Validar: `coverage_meta.cost_clp == 0` CLP
- [ ] Captura de screenshot o log
- [ ] **Tiempo estimado:** 10 minutos

### Benchmark 5.3: Costeo Histórico
- [ ] Ejecutar: `python audit_report.py`
- [ ] Validar: TOTAL USD ≈ $0.003-0.005 (no $23+)
- [ ] Validar: TOTAL CLP ≈ 3-5 CLP (no 21,000+ CLP)
- [ ] Captura de screenshot
- [ ] **Tiempo estimado:** 5 minutos

### Benchmark 5.4: Pipeline Completo CHI1
- [ ] Ejecutar: `python run_pipeline.py --liga CHI1 2>&1 | Tee pipeline_chi1_final.log`
- [ ] Validar: Web Agent JSON visible en logs (FASE 4 Auditoría)
- [ ] Validar: Insights Agent procesa correctamente el JSON v2
- [ ] Validar: No hay errores por campos faltantes
- [ ] Validar: Predicciones se generan sin crash
- [ ] **Tiempo estimado:** 15 minutos

---

## 📚 DOCUMENTACIÓN y Entrega

### Doc 6.1: README_TOURNAMENT_RESEARCH_AGENT_v2.md
- [ ] Explicar cambios principales vs v1
- [ ] Listar ejemplo de JSON v2 completo
- [ ] Explicar validadores (temporal, género, DT)
- [ ] Listar costos esperados por modelo
- [ ] Instruir cómo ajustar .env para pruebas
- [ ] **Tiempo estimado:** 30 minutos
- [ ] **Archivo:** `README_TOURNAMENT_RESEARCH_AGENT_v2.md` (NEW)

### Doc 6.2: Actualizar bitacora.md
- [ ] Agregar entrada con resumen de reimplementación v2.0
- [ ] Listar tickets completados
- [ ] Listar benchmarks alcanzados
- [ ] Notas operativas
- [ ] **Tiempo estimado:** 15 minutos
- [ ] **Archivo:** `bitacora.md` (APPEND)

---

## 📈 Resumen de Tareas por Tiempo

| FASE | Subtarea | Tiempo Est. | Status |
|------|----------|------------|--------|
| 1 | 1.1 - run_tournament_research() | 90 min | ⬜ |
| 1 | 1.2 - Validadores temporales | 45 min | ⬜ |
| 1 | 1.3 - Prompt v2.0 | 30 min | ⬜ |
| 1 | 1.4 - Parseo JSON v2 | 45 min | ⬜ |
| 1 | 1.5 - Persistencia cache | 30 min | ⬜ |
| **1** | **SUBTOTAL** | **240 min** | ⬜ |
| 2 | 2.1 - Validar llm_factory | 20 min | ⬜ |
| 2 | 2.2 - Validar token_tracker | 15 min | ⬜ |
| 2 | 2.3 - Validar pricing/.env | 10 min | ⬜ |
| **2** | **SUBTOTAL** | **45 min** | ⬜ |
| 3 | 3.1-3.5 - Tests unitarios | 125 min | ⬜ |
| **3** | **SUBTOTAL** | **125 min** | ⬜ |
| 4 | 4.1 - Runner standalone | 30 min | ⬜ |
| 4 | 4.2 - Integración pipeline | 15 min | ⬜ |
| **4** | **SUBTOTAL** | **45 min** | ⬜ |
| 5 | 5.1-5.4 - Benchmarking | 40 min | ⬜ |
| **5** | **SUBTOTAL** | **40 min** | ⬜ |
| 6 | 6.1-6.2 - Documentación | 45 min | ⬜ |
| **6** | **SUBTOTAL** | **45 min** | ⬜ |
| | **TOTAL ESTIMADO** | **~540 min** ≈ **9 horas** | ⬜ |

---

## 🎯 Criterios de Aceptación (Definition of Done)

✅ **Código**
- [ ] `agents/web_agent.py`: 5 funciones nuevas (run_tournament_research, validadores x3, cache)
- [ ] JSON v2 se genera 100% completo (19 campos + legacy)
- [ ] Campos legacy presentes, insights_agent NO rompe
- [ ] Costo 1ra corrida < $0.01 USD
- [ ] Costo 2da corrida = $0 USD (cache hit)

✅ **Tests**
- [ ] 5 test cases en test_web_agent_v2.py
- [ ] Cobertura: cache, temporal, género, json, costing
- [ ] 5/5 tests PASS

✅ **Documentación**
- [ ] README_TOURNAMENT_RESEARCH_AGENT_v2.md (completo)
- [ ] Entrada en bitacora.md (resumen)
- [ ] Ejemplos de .env y pricing.json actualizados

✅ **Operación**
- [ ] run_web_agent.py funciona (standalone o integrated)
- [ ] Pipeline CHI1 completo sin errores
- [ ] Audit report muestra costos correctos USD/CLP

---

**Estado Inicial:** Todas las tareas ⬜ (Not Started)  
**Siguiente paso:** Comenzar FASE 1.1 (Reescritura de run_tournament_research)
