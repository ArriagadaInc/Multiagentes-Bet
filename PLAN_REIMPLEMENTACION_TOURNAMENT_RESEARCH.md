# 🎯 Plan de Reimplementación: Tournament Research Agent v2.0

**Fecha:** 2026-04-02  
**Basado en:** Bitácora (31-Mar-2026 — Tournament Research Agent, Costeo y Control de Gastos)  
**Objetivo:** Convertir el Web Agent en un "Tournament Research Agent" con:
- JSON estricto v2 (nuevos campos de investigación + mantenimiento de compatibilidad)
- Control de costos (perfil LLM dedicado con tope de tokens)
- Medición exhaustiva de costos (USD → CLP)

---

## 📋 FASE 1: Análisis de Estado Actual

### Estado del Código (2026-04-02)
- ✅ `agents/web_agent.py`: Arquitectura base presente, pero falta:
  - Campos v2 nuevos (`contexto_campeonato`, `team_research`, `match_relevant_facts`, etc.)
  - Validación de DT 2026 para detectar noticias antiguas
  - Filtro de género explícito en código
  - Salida JSON v2 pura (ahora mezcla v2 + legacy)
  
- ✅ `utils/llm_factory.py`: Existe perfil `web_research_forced`, pero necesita:
  - Validación de que resuelve modelo por `WEB_RESEARCH_MODEL`
  - Validación de que aplica tope `WEB_RESEARCH_MAX_TOKENS`
  - Confirmación de callbacks conectados a `TokenTrackingCallbackHandler`

- ⚠️ `utils/token_tracker.py`: Existe, pero necesita:
  - Verificar que persiste tokens en `token_usage.json`
  - Verificar que consolida por nombre canónico de modelo

- ✅ `pricing.json`: Actualizado a USD/1M (ver CORRECCIONES_AUDIT.md)

- ✅ `utils/costing.py`: Reescrito con `/1_000_000` y consolidación correcta

- ✅ Tests: `test_costing.py` valida todas las correcciones (5/5 PASS)

### Problemas Identificados en la Bitácora
1. **Costo Alto**: Web Agent con `gpt-5.1` genera ~131 USD por corrida (sin control)
2. **Doble Conteo de Modelos**: `gpt-4.1-2025-04-14` vs `gpt-4.1` se reportaban como 2 entradas
3. **JSON Incompleto**: Salida actual no genera v2 completo, mezcla con legacy
4. **Noticias Anacrónicas**: Falta validación de año/DT para descartar noticias viejas
5. **Género Confundido**: No hay filtro explícito para evitar mezclar femenino/masculino

---

## 🔧 FASE 2: Especificación del Tournament Research Agent v2.0

### 2.1 Cambios en `agents/web_agent.py`

#### **Objetivo Operativo**
```
1 llamada por torneo (CHI1 + UCL máximo = 2 llamadas)
 ↓
Respuesta JSON v2 PURA con validación temporal y de género
 ↓
Compatibilidad con insights_agent (mantiene campos legacy: competition_summary, teams)
 ↓
Persistencia en web_agent_output.json (con TTL)
 ↓
Cache por firma (torneo + fecha + equipos + wishlist hash)
```

#### **Función Principal: `run_tournament_research(state: dict) -> dict`**

**Firma de Cache (determinista):**
```python
def _cache_signature(competition: str, fixtures: list[dict], wishlist: dict) -> str:
    """
    Hash de: competition + fixture_ids + wishlist_hash
    Si la firma no cambió, reutilizar resultado sin reinvocar LLM (costo = 0)
    """
    fixture_str = "|".join([f"{f['home_team']}_{f['away_team']}" for f in fixtures])
    wishlist_str = json.dumps(wishlist, sort_keys=True)
    combined = f"{competition}_{fixture_str}_{wishlist_str}"
    return hashlib.sha256(combined.encode()).hexdigest()[:16]
```

**Búsqueda Web Segura:**
```python
def _validate_temporal_sanity(snippet: str, year: int = 2026) -> bool:
    """
    Filtros heurísticos para descartar noticias anacrónicas:
    
    1. Texto debe mencionar explícitamente el año 2026 (o estar en noticia reciente)
    2. NO permitir equipos "fantasma" (Fortaleza, Concepción, San Lorenzo si no están en CHI1 2026)
    3. DT mencionado debe coincidir con el vigente en 2026 (validar si es posible)
    4. NO mezclar géneros: si dice "Femenino" o menciona a equipos con sufijo "F", rechazar
    """
    # Checks
    has_2026 = "2026" in snippet or "2025" in snippet or "este año" in snippet
    has_female = any(x in snippet.lower() for x in ["femenino", " f ", "women", "damas"])
    has_ghost_team = any(x in snippet for x in ["Fortaleza", "Concepción", "San Lorenzo", "Gremio"])
    
    if has_female or (has_ghost_team and not has_2026):
        return False
    return has_2026 or _is_recent_snippet(snippet)

def _validate_coach_2026(coach_name: str, team: str) -> bool:
    """
    Valida que el DT mencionado esté efectivamente activo en 2026.
    Ejemplos:
    - "Gustavo Lema en Audax" → True (activo en 2026)
    - "Arrué en Colo-Colo" → False (Arrué salió en 2024)
    """
    VALID_COACHES_2026 = {
        "Colo-Colo": ["Gustavo Quinteros"],  # Se valida contra fuentes actuales
        "Audax": ["Gustavo Lema"],
        "O'Higgins": ["Lucas Bovaglio"],
        # ... más equipos
    }
    return coach_name in VALID_COACHES_2026.get(team, [])
```

#### **Estructura JSON v2 (Salida Pura)**

```json
{
  "generated_at": "2026-04-02",
  "competition_key": "CHI1",
  "competition_name": "Primera División de Chile",
  "as_of_date": "2026-04-02",
  
  "contexto_campeonato": {
    "punteros": [
      { "position": 1, "team": "Colo-Colo", "points": 24, "gd": "+8" },
      { "position": 2, "team": "Universidad Católica", "points": 22, "gd": "+6" }
    ],
    "tendencias": [
      "Colo-Colo en racha de 3 victorias consecutivas",
      "Audax Italiano sorprende con 5 puntos en 2 jornadas"
    ],
    "rachas": {
      "Colo-Colo": "WWWDL",
      "Audax": "WWW",
      "Palestino": "LLLLW"
    ],
    "clima_deportivo": "Inicio equilibrado; todavía es pronto para definiciones.",
    "alertas_competencia": [
      "O'Higgins: cambio de DT en semana (Lucas Bovaglio desde ACF Fiorentina)",
      "Temuco: sigue sin puntos (0 PTS en 4 J)"
    ]
  },

  "team_research": [
    {
      "team": "Colo-Colo",
      "position_in_table": 1,
      "points": 24,
      "played": 7,
      "gd": 8,
      "form": "WWWDL",
      "last_result": {
        "match": "Colo-Colo 3-1 Palestino",
        "date": "2026-03-31",
        "competition": "CHI1",
        "highlights": ["Solari 2G", "Falcón 1G"]
      },
      "signals": [
        {
          "type": "form",
          "text": "Racha de 3 victorias consecutivas; superó esperativas de especialistas.",
          "fact_date": "2026-04-01",
          "confidence": 0.95,
          "status": "confirmed",
          "sources": ["espn.com.ar", "estadio.cl"]
        },
        {
          "type": "injury_news",
          "text": "Pavez: duda para el próximo partido (sobrecarga muscular). Médico evalúa disponibilidad.",
          "fact_date": "2026-04-01",
          "confidence": 0.8,
          "status": "likely",
          "sources": ["emolfutbol.cl"]
        }
      ],
      "coached_by_2026": "Gustavo Quinteros",
      "coached_validity": true,
      "coverage_notes": "Información fresca del 31/03 y posteriores. DT validado activo 2026."
    }
  ],

  "match_relevant_facts": [
    {
      "home": "Colo-Colo",
      "away": "Audax",
      "facts": [
        "Colo-Colo llega con 3 victorias; Audax en sorpresa con 2G en 2J.",
        "Duelo de ritmos: esperado vs emergente.",
        "Pavez (Colo) es duda; Rodríguez (Audax) está suspendido."
      ],
      "sources": ["estadio.cl", "emol.com"]
    }
  ],

  "wishlist_resolution": [
    {
      "need": "¿Recuperaciones de lesionados en Colo-Colo?",
      "answer": "Medina regresa de suspensión. Pavez está en duda (sobrecarga).",
      "confidence": 0.85,
      "sources": ["emolfutbol.cl"]
    }
  ],

  "contradictions": [
    "Reportaje A dice que Pavez está Out; Reportaje B dice 'En duda'. => Validado: en evaluación, no descartado aún."
  ],

  "stale_signals_detected": [
    "Mención a 'Palermo como técnico en O'Higgins' (falso; es Lucas Bovaglio desde ciclo 2026)."
  ],

  "coverage_meta": {
    "queries": 12,
    "sources": 8,
    "cache_hit": false,
    "model_used": "gpt-4.1-mini",
    "tokens_prompt": 2100,
    "tokens_completion": 1800,
    "tokens_total": 3900,
    "cost_usd": 0.00208,
    "cost_clp": 1.87
  },

  "_v2_notes": "Estructura v2 completa con validación temporal y de género. Compatibilidad legacy a continuación.",

  "competition": "CHI1",
  "competition_summary": "[Legacy] Inicio equilibrado; líderes consolidados.",
  "teams": [
    {
      "team": "Colo-Colo",
      "position_in_table": 1,
      "points": 24,
      "last_result": "Colo-Colo 3-1 Palestino",
      "figures": ["Solari (2G)", "Falcón (1G)"],
      "injuries": ["Pavez (duda)"],
      "form": "WWWDL",
      "context_signals": [
        { "type": "form", "signal": "3 victorias consecutivas", "confidence": 0.95 }
      ],
      "raw_context": "En racha; sorprendieron positivamente a especialistas."
    }
  ]
}
```

### 2.2 Cambios en `utils/llm_factory.py`

**Verificación de Perfil `web_research_forced`:**
```python
def get_llm(profile: str = "default", *args, **kwargs):
    """
    Perfiles soportados:
    - "default": Resuelve EXPENSIVE_MODE, fallback a Gemini si aplica
    - "web_research_forced": 
        • SIEMPRE OpenAI (ignora EXPENSIVE_MODE)
        • Modelo: WEB_RESEARCH_MODEL (default: gpt-4.1-mini)
        • Max tokens: WEB_RESEARCH_MAX_TOKENS (default: 2000)
        • Callbacks: TokenTrackingCallbackHandler conectado
    """
    if profile == "web_research_forced":
        model = os.getenv("WEB_RESEARCH_MODEL", "gpt-4.1-mini")
        max_tokens = int(os.getenv("WEB_RESEARCH_MAX_TOKENS", "2000"))
        
        llm = ChatOpenAI(
            model=model,
            max_tokens=max_tokens,
            temperature=0.3,  # Más determinístico para investigación
            callbacks=[TokenTrackingCallbackHandler()],  # ← Tracking automático
            api_key=os.getenv("OPENAI_API_KEY")
        )
        return llm
    # ... resto de perfiles
```

**Validación de `.env`:**
```bash
# .env requerido
WEB_RESEARCH_MODEL=gpt-4.1-mini          # Modelo económico
WEB_RESEARCH_MAX_TOKENS=2000               # Cap de tokens para completion
EXCHANGE_RATE_CLP_PER_USD=900              # Tipo de cambio (ajustar a real)
```

### 2.3 Cambios en `utils/token_tracker.py`

**Persistencia en `token_usage.json`:**
```python
def track_tokens(model: str, prompt_tokens: int, completion_tokens: int):
    """
    Registra tokens por modelo LLM.
    
    Estructura en token_usage.json:
    {
      "model_name": {
        "prompt_tokens": 2100,
        "completion_tokens": 1800,
        "total_tokens": 3900,
        "calls": 1,
        "last_updated": "2026-04-02T14:30:00Z"
      }
    }
    """
    if not model:
        return
    
    data = _load_token_usage()
    if model not in data:
        data[model] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "calls": 0,
            "last_updated": None
        }
    
    data[model]["prompt_tokens"] += prompt_tokens
    data[model]["completion_tokens"] += completion_tokens
    data[model]["total_tokens"] += prompt_tokens + completion_tokens
    data[model]["calls"] += 1
    data[model]["last_updated"] = datetime.now(timezone.utc).isoformat()
    
    _save_token_usage(data)
```

---

## 🛠️ FASE 3: Implementación Detallada

### Tarea 3.1: Reescribir `run_tournament_research()` completo
- **Entrada:** `state["fixtures"]`, `state["competitions"]`
- **Validaciones:**
  1. Cargar wishlist (necesidades del analista)
  2. Computar firma de cache (torneo + fixtures + wishlist)
  3. Verificar si existe en web_agent_output.json y es fresco (< 6 horas)
  4. Si es fresco: reutilizar (costo = 0) ✅ cache hit
  5. Si NO es fresco: 
     a. Invocar `get_llm(profile="web_research_forced")`
     b. Generar prompt con validación temporal
     c. Hacer 1 llamada al LLM
     d. Parsear respuesta JSON v2
     e. Registrar tokens en `token_usage.json` (automático via callbacks)
     f. Guardar en web_agent_output.json con timestamp
- **Salida:** JSON v2 completo + campos legacy para compatibilidad

### Tarea 3.2: Implementar validaciones de sanidad temporal
- Función `_validate_temporal_sanity(snippet, year=2026)` con 4 checks:
  1. Año 2026 explícito O noticia reciente
  2. NO género femenino
  3. NO equipos "fantasma" sin contexto 2026
  4. DT vigente (si es aplicable)

### Tarea 3.3: Mejorar prompt de `_build_tournament_prompt()`
- Agregar "Guillotina Temporal": "Si encuentras un resultado que NO mencione 2026, DEBES ignorarlo"
- Agregar "Filtro de Género": "NO mezcles Fútbol Femenino con Masculino"
- Validación de DT: "Asegúrate de que el DT coincida con el vigente en 2026"

### Tarea 3.4: Auditar costing
- Verificar `utils/costing.py` consolida por nombre canónico ✅ (revisado, corregido)
- Verificar `pricing.json` usa USD/1M ✅ (revisado, corregido)
- Ejecutar `test_costing.py` y confirmar 5/5 PASS ✅ (ya hecho)

### Tarea 3.5: Crear script `run_web_agent.py`
```bash
python run_web_agent.py --mode node --Competition CHI1
# O integrado en pipeline:
python run_pipeline.py --liga CHI1
```

---

## 📊 FASE 4: Validación y Costeo

### Pruebas Funcionales
1. **Test 1: Cache Hit**
   - Correr `run_tournament_research()` 2 veces con mismos parámetros
   - Esperado: covenge_meta.cache_hit = true en 2da corrida
   - Costo USD: 0 en 2da corrida

2. **Test 2: Temporal Sanity**
   - Inyectar noticias antiguas (2023-2025) en búsqueda simulada
   - Esperado: filtro `_validate_temporal_sanity()` las rechaza
   - Verificar en stale_signals_detected

3. **Test 3: Género Confundido**
   - Inyectar resultado de femenino
   - Esperado: validador rechaza (has_female = true)

4. **Test 4: DT Anacrónico**
   - Inyectar "Palermo como técnico en O'Higgins" (Palermo ≠ 2026)
   - Esperado: contradiction detectada, señal marcada status=stale

### Costeo Esperado (vs. Antes)
```
ANTES (gpt-5.1, sin cap, 1 corrida):
  Tokens: ~9,768 prompt/completion
  Costo:  ~$131 USD = $117,999 CLP ❌ ALTO

DESPUÉS (gpt-4.1-mini, 2000 max_tokens, 1 corrida):
  Tokens: ~2,100 prompt + 1,800 completion
  Costo:  ~$0.002 USD = $1.80 CLP ✅ BAJO
  
Con cache (si firma no cambia):
  Cache hit: Costo = $0 USD = $0 CLP ✅✅ ÓPTIMO
```

---

## 🚀 FASE 5: Despliegue y Operativo

### Orden de Ejecución
1. ✅ Repasar cambios del costeo (correcciones ya aplicadas)
2. 📝 Reescribir `agents/web_agent.py` (tasks 3.1-3.3)
3. 📝 Validar `utils/llm_factory.py` perfil web_research_forced (task 3.2)
4. 📝 Validar `utils/token_tracker.py` (task 3.4)
5. 🧪 Tests de cache, temporal, género, costing (FASE 4)
6. 🧪 Correr pipeline CHI1 completo y validar logs
7. 📊 Costeo y snapshot en `cost_history/`

### Flags de Éxito
- [ ] Regex canónico normaliza `gpt-4.1-mini-2025-04-14` → `gpt-4.1-mini` ✅
- [ ] Consolidación usa MAX(), no SUM() ✅
- [ ] JSON v2 se genera completo (19 campos nuevos)
- [ ] Campos legacy presentes para compatibilidad insights_agent
- [ ] Cache signature determinista (mismo hash si parámetros iguales)
- [ ] Wishlist resolution incluye respuestas a necesidades del analista
- [ ] stale_signals_detected captura noticias anacrónicas
- [ ] coverage_meta incluye model_used, tokens, cost_usd, cost_clp
- [ ] Costo por corrida 1ra vez: < $1 USD (vs $131 antes)
- [ ] Costo por corrida 2da vez (cache): $0 USD

### Flujo de Operación Post-Reimplementación
```powershell
# 1. Limpiar para corrida fresca
Remove-Item web_agent_output.json -ErrorAction SilentlyContinue
Remove-Item token_usage.json -ErrorAction SilentlyContinue

# 2. Correr web agent standalone
python run_web_agent.py --mode node --competition CHI1

# 3. Ver resultado y costos
type web_agent_output.json | ConvertFrom-Json
python audit_report.py  # Ver costos USD/CLP

# 4. Correr pipeline completo
python run_pipeline.py --liga CHI1

# 5. Correr nuevamente (debe usar cache)
python run_web_agent.py --mode node --competition CHI1
# Esperado: coverage_meta.cache_hit = true, costo = 0
```

---

## 📎 Referencias

- **Bitácora (31-Mar)**: Especificación original del Tournament Research Agent
- **CORRECCIONES_AUDIT.md**: Fixes de costeo (USD/1M, consolidación, tests)
- **agentes_flow.md**: Arquitectura completa del pipeline
- **pricing.json**: Tarifas corrected (USD/1M, no USD/1K)
- **utils/costing.py**: Consolidación y cálculo (rewritten, 5/5 tests PASS)

---

**Estado General:** Fundaciones en lugar. Listo para reimplementación v2.0.
