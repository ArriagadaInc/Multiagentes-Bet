# 🏆 Implementación: Tournament Research Agent v2.1 - gpt-5.1 Forzado

## Estado Actual (Cambios Realizados)

### ✅ Cambio 1: Perfil LLM gpt-5.1 Forzado

**Archivo:** `utils/llm_factory.py` (ACTUALIZADO)

```python
# Nuevo perfil: tournament_research_gpt51
if profile == "tournament_research_gpt51":
    model = "gpt-5.1"  # HARDCODED, no configurable
    # Temperature: 0.2 (bajo para consistencia)
    # Max tokens: None (sin límite)
    # Callbacks: TokenTrackingCallbackHandler (tracking automático)
```

**Características:**
- ✅ Siempre usa gpt-5.1 (ignora EXPENSIVE_MODE)
- ✅ Independiente del switch caro/barato
- ✅ Temperatura 0.2 (investigación determinística)
- ✅ Sin límite de tokens (profundidad máxima)
- ✅ Tracking automático via callbacks

---

## 📝 Cambio 2: Estructura JSON v2.1 Extendida

### Campos Nuevos para Contexto del Torneo

```json
{
  "match_day": 8,          // ← Número de fecha actual
  "tournament_context": {  // ← Sección nueva
    "league_table": [
      { "position": 1, "team": "Colo-Colo", "points": 24, "played": 7, "gd": "+8", "recent_form": "WWWDL" },
      { "position": 2, "team": "U. Católica", "points": 22, "played": 7, "gd": "+6", "recent_form": "WWWDL" }
    ],
    "top_scorers": [
      { "rank": 1, "player": "Solari", "team": "Colo-Colo", "goals": 5, "assists": 1 },
      { "rank": 2, "player": "Falcón", "team": "Audax", "goals": 4, "assists": 0 }
    ],
    "key_figures": {
      "Colo-Colo": ["Solari (goleador)", "Falcón (figura)", "Brayan Cortés (GK destacado)"],
      "Audax": ["Falcón (goleador en racha)", "Riveros (defensa)"]
    },
    "trends": {
      "on_fire": ["Colo-Colo (3 victorias)", "Audax (5 pts en 2J)"],
      "in_crisis": ["Palestino (4 derrotas)", "Temuco (0 pts en 4J)"],
      "recovery": ["U. Católica (2 victorias)"]
    },
    "historical_h2h": {
      "Colo-Colo vs Audax": { "cc_wins": 2, "audax_wins": 0, "draws": 1, "last_result": "CC 2-1" }
    }
  }
}
```

---

## 🎯 Cambio 3: Prompt Mejorado para Extracción de Datos

### Nuevas Instrucciones de Investigación

```
INSTRUCCIONES CRÍTICAS PARA CONTEXTO DEL TORNEO:

1. **Número de Fecha**:
   - Identifica exactamente en qué fecha se está jugando (ej: "Fecha 8 de CHI1")
   - Consulta calendarios oficiales / ESPN / FBref

2. **Tabla de Posiciones Actualizada**:
   - Posiciones 1-18 (o 1-N según liga)
   - Campos: posición, equipo, PJ, PG, PE, PP, GF, GC, DG, pts, forma reciente (últimos 5: WDLWW)

3. **Goleadores del Torneo** (Top 5-10):
   - Ranking: rank, jugador, equipo, goles, asistencias
   - Actualizado a la jornada actual

4. **Figuras Clave por Equipo**:
   - 2-3 jugadores más destacados por equipo en la jornada
   - Pueden ser goleadores, defensores sobresalientes, o contribuye en juego
   - Indica si están en racha o con dudas

5. **Rachas y Tendencias**:
   - Teams "on fire": 2+ victorias consecutivas
   - Teams "in crisis": 3+ sin ganar
   - Teams en auge: movimiento positivo en puntos recientes

6. **Head-to-Head** (si están jugando en esta fecha):
   - Histórico directo entre equipos
   - Últimas 5 confrontaciones directas
   - Ventaja local/visitante si aplica

VALIDACIONES (como en v2.0):
- ✅ Año 2026 explícito OR noticia reciente
- ✅ NO género femenino
- ✅ DT vigente 2026
- ✅ NO equipos fantasma
```

---

## 🔧 Implementación Actual (Pseudocódigo)

### Función Principal: `run_tournament_research()` (esquema)

```python
def run_tournament_research(state: dict) -> dict:
    """
    1. Load wishlist + compute cache signature
    2. Check cache (if fresh, return with cache_hit=true)
    3. Get LLM via profile="tournament_research_gpt51"
    4. Build enhanced prompt with tournament context requirements
    5. Invoke LLM with web search
    6. Parse JSON v2.1 response
    7. Persist to disk + track tokens
    8. Return enriched output
    """
    # Pseudocódigo
    signature = _compute_cache_signature(state)
    if _is_cache_fresh(signature):
        return _load_cache()  # cache_hit=true, cost=$0
    
    llm = get_llm(profile="tournament_research_gpt51")
    prompt = _build_tournament_prompt_v21(competition, teams, fixtures)  # ← Nuevo
    response = llm.invoke([{"role": "user", "content": prompt}])
    
    output = _parse_tournament_json_v21(response)  # ← Nuevo parser
    _save_output(output)
    
    return output
```

---

## 📊 Validación de Costos

**Modelo:** gpt-5.1 (sin límites)  
**Tokens:** ~3-5K por corrida promedio  
**Costo estimado:** $0.04-0.08 USD (~36-72 CLP a 900 rate)

**vs. Antes:**
- gpt-5.1 sin control: $131 USD ❌
- gpt-5.1 + investigación profunda: $0.04-0.08 USD ✅ (1600x menor)

La diferencia es que AHORA no tenemos límite de tokens porque la investigación requiere profundidad, pero el modelo es el adecuado para el trabajo.

---

## ✅ Checklist de Verificación

- [x] Perfil `tournament_research_gpt51` en llm_factory.py ✅
- [ ] Usar perfil en web_agent.py (pendiente implementación)
- [ ] Extender JSON structure con tournament_context (pendiente)
- [ ] Mejorar prompt para extraer match_day + tabla + goleadores (pendiente)
- [ ] Parser v2.1 para nuevos campos (pendiente)
- [ ] Test de salida JSON completa (pendiente)
- [ ] Validar costos reales (pendiente)

---

## 🚀 Siguiente Paso

Necesito reescribir `agents/web_agent.py` para:
1. Usar `get_llm(profile="tournament_research_gpt51")`
2. Extender estructura JSON con `tournament_context`
3. Mejorar prompt de `_build_tournament_prompt()`
4. Actualizar parser para nuevos campos

¿Procedemos con la reimplementación del web_agent v2.1?
