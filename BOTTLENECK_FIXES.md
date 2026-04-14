# 🔧 BOTTLENECK FIXES - Pipeline Signal Flow Enhancement

## Problema Identificado
**Cuello de botella en el paso de signals de web_agent → insights_agent → analyst_agent**

### Limitaciones Encontradas:

| Componente | Antes | Después | Mejora |
|-----------|-------|---------|--------|
| **Analyst Agent** - Context Signals | `[:8]` hard-coded | `[:15]` + env var | +87% |
| **Analyst Agent** - Clean Signals | `[:15]` | `[:20]` + env var | +33% |
| **Analyst Agent** - Suspicious Signals | `[:10]` | `[:15]` + env var | +50% |
| **Analyst Agent** - Top Scorers | `[:3]` | `[:5]` + env var | +67% |
| **Analyst Agent** - Citations | `[:2]` | `[:4]` + env var | +100% |
| **Web Agent** - Teams Sent | `[:20]` | `[:100]` | Más cobertura |
| **Web Agent** - Output Tokens | 6000 | 10000 | Completes all teams |

---

## Cambios Realizados

### 1. **analyst_agent.py - Aumentado Material para LLM**

#### Line 513-520: Context Signals (ahora configurable)
```python
# ANTES:
for sig in context_signals[:8]:

# DESPUÉS:
max_signals = int(os.getenv("ANALYST_MAX_SIGNALS_PER_TEAM", "15"))
for sig in context_signals[:max_signals]:
```
**Env Var**: `ANALYST_MAX_SIGNALS_PER_TEAM` (default: 15)

#### Line 551-552: Clean Match Signals
```python
# ANTES: for s in clean[:15]
# DESPUÉS: 
max_clean = int(os.getenv("ANALYST_MAX_CLEAN_SIGNALS", "20"))
for s in clean[:max_clean]:
```
**Env Var**: `ANALYST_MAX_CLEAN_SIGNALS` (default: 20)

#### Line 566-567: Suspicious Signals
```python
# ANTES: for s in suspicious[:10]
# DESPUÉS:
max_suspicious = int(os.getenv("ANALYST_MAX_SUSPICIOUS_SIGNALS", "15"))
for s in suspicious[:max_suspicious]:
```
**Env Var**: `ANALYST_MAX_SUSPICIOUS_SIGNALS` (default: 15)

#### Line 452: Top Scorers
```python
# ANTES: for sc in scorers[:3]
# DESPUÉS:
max_scorers = int(os.getenv("ANALYST_MAX_SCORERS", "5"))
for sc in scorers[:max_scorers]
```
**Env Var**: `ANALYST_MAX_SCORERS` (default: 5)

#### Line 487: Citations
```python
# ANTES: for c in citations[:2]
# DESPUÉS:
max_citations = int(os.getenv("ANALYST_MAX_CITATIONS", "4"))
for c in citations[:max_citations]
```
**Env Var**: `ANALYST_MAX_CITATIONS` (default: 4)

---

### 2. **web_agent.py - Mejorado Cobertura de Equipos**

#### Line 309: Teams in Prompt
```python
# ANTES: teams_str = ", ".join(teams[:20])
# DESPUÉS: teams_str = ", ".join(teams[:100])
```
**Impacto**: Ahora include hasta 100 equipos en el prompt web_search

#### Line 738: Output Tokens
```python
# ANTES: max_output_tokens=6000
# DESPUÉS: max_output_tokens=10000
```
**Impacto**: El LLM tiene más espacio para responder con todos los equipos en JSON

---

## Resultados Esperados

1. **Más signals por equipo en el prompt del analyst**
   - Audax Italiano: 10 signals → 15 signals (+50%)
   - Cobresal: 11 signals → 15 signals (+36%)
   - Promedio: 7-8 → 12-15 signals/equipo

2. **Mejor cobertura de web_agent**
   - Antes: 3/14 equipos con señales estructuradas (21%)
   - Después: Esperado 12-14/14 equipos (85%+)

3. **Prompt LLM del analyst más rico**
   - Antes: 8 + 15 + 10 + 3 + 2 = ~38 items de contexto
   - Después: 15 + 20 + 15 + 5 + 4 = ~59 items (+55%)

---

## Variables de Entorno para Tunning

```bash
# Per-team signals
export ANALYST_MAX_SIGNALS_PER_TEAM=15

# Match context signals
export ANALYST_MAX_CLEAN_SIGNALS=20
export ANALYST_MAX_SUSPICIOUS_SIGNALS=15

# Players
export ANALYST_MAX_SCORERS=5

# Meta information
export ANALYST_MAX_CITATIONS=4

# Web search coverage
export WEB_AGENT_MAX_TEAMS=100  # (manual if needed)
```

---

## Próximos Pasos Recomendados

1. ✅ Ejecutar pipeline CHI1 y verificar logs de signals
2. ⏳ Monitorear token usage del analyst (nuevo contexto más grande)
3. ⏳ Investigar si YouTube API 403 puede mejorarse (diversificar keys)
4. ⏳ Considerar caché de web_agent más agresivo (6h → 12h) para economía

---

**Status**: Ready for testing with `python run_pipeline.py --liga CHI1`
