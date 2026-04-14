#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tournament Research Agent v2.1 - Implementación Completa con gpt-5.1

✅ IMPLEMENTACIÓN REALIZADA:

1. ✅ utils/llm_factory.py
   - Nuevo perfil "tournament_research_gpt51"
   - Hardcoded a gpt-5.1 (ignora EXPENSIVE_MODE)
   - Temperature 0.2 (investigación determinística)
   - Sin límite de tokens (investigación profunda)
   - Callbacks automáticos: TokenTrackingCallbackHandler

2. ✅ agents/web_agent.py
   - Función _get_web_llm() actualizada para usar tournament_research_gpt51
   - WEB_AGENT_MODEL = "gpt-5.1" (hardcoded)
   - Prompt _build_tournament_prompt() EXTENDIDO con:
     ├─ Validaciones críticas (Año 2026, Género, DT 2026, Equipos fantasma)
     ├─ Extracción de datos del torneo:
     │  ├─ match_day (número de fecha)
     │  ├─ league_table (tabla completa con forma reciente)
     │  ├─ top_scorers (goleadores del torneo)
     │  ├─ key_figures (figuras por equipo)
     │  ├─ trends (on_fire, in_crisis, recovery)
     │  └─ head_to_head (si están jugando)
     └─ Estructura JSON v2.1 extendida

═══════════════════════════════════════════════════════════════════════════════

📋 ESTRUCTURA JSON v2.1 (Nueva)

{
  "match_day": 8,
  "tournament_context": {
    "league_table": [
      { 
        "position": 1, 
        "team": "Colo-Colo", 
        "played": 7, 
        "wins": 5, 
        "draws": 1, 
        "losses": 1, 
        "for": 14, 
        "against": 6, 
        "gd": 8, 
        "points": 16, 
        "recent_form": "WWWDL" 
      }
    ],
    "top_scorers": [
      { 
        "rank": 1, 
        "player": "Solari", 
        "team": "Colo-Colo", 
        "goals": 5, 
        "assists": 1 
      }
    ],
    "key_figures": {
      "Colo-Colo": ["Solari (5G)", "Brayan Cortés (GK)", "..."]
    },
    "trends": {
      "on_fire": ["Colo-Colo (3W)", "..."],
      "in_crisis": ["Palestino (4L)", "..."],
      "recovery": ["U. Católica (trend+)", "..."]
    },
    "head_to_head": {
      "Colo-Colo vs Audax": {
        "cc_wins": 2,
        "audax_wins": 0,
        "draws": 1,
        "last_result": "CC 2-1",
        "h2h_form": "Colo-Colo favorito"
      }
    }
  },
  
  "contexto_campeonato": { ... },
  "team_research": [ ... ],
  "match_relevant_facts": [ ... ],
  ... (resto igual a v2.0)
}

═══════════════════════════════════════════════════════════════════════════════

🧪 VALIDACIÓN Y PRUEBA

Paso 1: Verificar que el perfil está registrado
────────────────────────────────────────────────────────────────────────────────
$ python -c "from utils.llm_factory import get_llm; llm = get_llm(profile='tournament_research_gpt51'); print(f'✓ LLM: {llm.model_name}')"

Paso 2: Correr el Web Agent standalone
────────────────────────────────────────────────────────────────────────────────
# Limpiar cache anterior
Remove-Item web_agent_output.json -ErrorAction SilentlyContinue
Remove-Item token_usage.json -ErrorAction SilentlyContinue

# Ejecutar
python run_web_agent.py --mode node --competition CHI1 --verbose

Paso 3: Validar JSON v2.1 generado
────────────────────────────────────────────────────────────────────────────────
$ python -c "
import json
with open('web_agent_output.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
    
# Verificar campos nuevos
assert 'match_day' in data, 'Falta match_day'
assert 'tournament_context' in data, 'Falta tournament_context'
assert 'league_table' in data.get('tournament_context', {}), 'Falta league_table'
assert 'top_scorers' in data.get('tournament_context', {}), 'Falta top_scorers'
assert 'key_figures' in data.get('tournament_context', {}), 'Falta key_figures'
assert 'trends' in data.get('tournament_context', {}), 'Falta trends'

# Verificar datos
league_table = data['tournament_context']['league_table']
print(f'✓ Tabla de posiciones: {len(league_table)} equipos')
print(f'  Puntero: {league_table[0][\"team\"]} ({league_table[0][\"points\"]} pts)')

scorers = data['tournament_context']['top_scorers']
print(f'✓ Goleadores: {len(scorers)} registrados')
print(f'  Top scorer: {scorers[0][\"player\"]} ({scorers[0][\"goals\"]} goles)')

# Verificar compatibility
assert 'competition' in data, 'Falta competition (legacy)'
assert 'teams' in data, 'Falta teams (legacy)'
print(f'✓ Compatibilidad legacy: OK')

print('\\n✅ JSON v2.1 VÁLIDO')
"

Paso 4: Validar Costos
────────────────────────────────────────────────────────────────────────────────
$ python audit_report.py

Esperado:
- TOTAL USD: ~$0.04-0.08 USD (investigación profunda con gpt-5.1)
- TOTAL CLP: ~36-72 CLP (a 900 rate)
- Model: gpt-5.1 confirmado en coverage_meta

Paso 5: Correr 2da vez (validar cache)
────────────────────────────────────────────────────────────────────────────────
$ python run_web_agent.py --mode node --competition CHI1

Esperado:
- coverage_meta.cache_hit = true
- cost_usd = 0
- cost_clp = 0

═══════════════════════════════════════════════════════════════════════════════

📊 BENCHMARKS ESPERADOS

Parámetro               | Valor Esperado    | Observaciones
─────────────────────────────────────────────────────────────────────────────
Model                  | gpt-5.1           | SIEMPRE gpt-5.1 (hardcoded)
Temperature            | 0.2               | Determinística
Max Tokens             | None              | Sin límite (investigación profunda)
Tokens Prompt (promedio)     | 4200-4500     | Prompt detallado
Tokens Completion (promedio) | 3500-4000     | Respuesta con tabla, goleadores, etc.
Tokens Total           | 7500-8500         | Investigación profunda
Costo 1ra corrida      | $0.04-0.08 USD    | ~36-72 CLP
Costo 2da corrida      | $0 USD            | Cache hit
Tiempo de respuesta    | 45-90 seg         | Network + LLM latency
Cache TTL              | 6 horas (default) | Configurable en .env

═══════════════════════════════════════════════════════════════════════════════

🔧 CONFIGURACIÓN .env

```bash
# LLM Factory (no necesita cambios para Tournament Research)
EXPENSIVE_MODE=false                  # Irrelevante (bypass)
OPENAI_API_KEY=sk-...                 # Requerido
OPENAI_MODEL=gpt-5.1                  # Backup (no usada)

# Web Agent (deprecated para Tournament Research)
WEB_RESEARCH_MODEL=gpt-4.1-mini       # Ignorado (bypass)
WEB_RESEARCH_MAX_TOKENS=2000          # Ignorado (bypass)

# Cache
WEB_AGENT_CACHE_TTL_HOURS=6           # Configurable

# Costos
EXCHANGE_RATE_CLP_PER_USD=900         # Actualizar con tipo real

# Tracking
TRACK_TOKENS=true                     # Automático
```

═══════════════════════════════════════════════════════════════════════════════

⚠️ NOTAS IMPORTANTES

1. gpt-5.1 SIEMPRE se usa (hardcoded en llm_factory)
   - No se puede cambiar a otro modelo
   - El toggle EXPENSIVE_MODE es ignorado
   - El env var WEB_RESEARCH_MODEL es ignorado

2. Sin límite de tokens por diseño
   - Investigación profunda requiere respuestas largas
   - Tabla completa (18+ equipos)
   - Top 5-10 goleadores
   - Análisis de tendencias y H2H

3. Costo ~ $0.04-0.08 por corrida
   - Más alto que versión económica (gpt-4.1-mini ~$0.002)
   - Justificado por calidad de investigación
   - Cache reutiliza resultados (costo 0 en reuso)

4. JSON v2.1 es backward compatible
   - Campos legacy presentes (competition, teams, etc.)
   - Insights Agent no rompe
   - Nuevos campos en tournament_context

═══════════════════════════════════════════════════════════════════════════════

✅ CHECKLIST DE IMPLEMENTACIÓN

Código:
  [x] Perfil tournament_research_gpt51 en llm_factory.py
  [x] _get_web_llm() actualizado
  [x] WEB_AGENT_MODEL = "gpt-5.1"
  [x] Prompt extendido con validaciones críticas
  [x] Estructura JSON v2.1 completa
  [x] Campos tournament_context
  [x] Compatibilidad legacy

Validación:
  [ ] Test: JSON v2.1 estructura completa
  [ ] Test: Tabla de posiciones extraída
  [ ] Test: Goleadores presentes (rank, goals, assists)
  [ ] Test: Figuras clave por equipo
  [ ] Test: Trends (on_fire, in_crisis, recovery)
  [ ] Test: Head-to-head si aplica
  [ ] Test: Cache hit en 2da corrida (cost=$0)
  [ ] Test: Costos correctos (~$0.04-0.08 USD)

Documentación:
  [x] IMPL_TOURNAMENT_RESEARCH_GPT51.md (este archivo)
  [ ] README actualizado
  [ ] Bitácora actualizada

═══════════════════════════════════════════════════════════════════════════════

🚀 EJECUCIÓN RECOMENDADA

# 1. Validar instalación
python -c "from utils.llm_factory import get_llm; get_llm(profile='tournament_research_gpt51')"

# 2. Ejecutar investigación del torneo
Remove-Item web_agent_output.json -ErrorAction SilentlyContinue
python run_web_agent.py --mode node --competition CHI1

# 3. Validar estructura JSON
python -c "import json; d=json.load(open('web_agent_output.json')); print('match_day:', d.get('match_day')); print('table:', len(d.get('tournament_context',{}).get('league_table',[]))); print('scorers:', len(d.get('tournament_context',{}).get('top_scorers',[])))"

# 4. Ver costos
python audit_report.py

# 5. Integrar en pipeline
python run_pipeline.py --liga CHI1

═══════════════════════════════════════════════════════════════════════════════

ESTADO: ✅ IMPLEMENTACIÓN COMPLETA Y LISTA PARA VALIDACIÓN
"""
