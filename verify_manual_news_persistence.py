#!/usr/bin/env python3
"""
Verificar que las noticias manuales se persisten en memoria física
y que el analista puede acceder a ellas
"""

import os
import json

print("=" * 80)
print("VERIFICACION: Persistencia de Noticias Manuales (v13.6)")
print("=" * 80)

# 1. Verificar archivo de noticias manuales
manual_file = 'data/inputs/manual_news_input.json'
print(f'\n[1/4] Archivo persistente: {manual_file}')
if os.path.exists(manual_file):
    with open(manual_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print(f'✅ EXISTE')
    text_len = len(data.get("text", ""))
    comp = data.get("competition", "NONE")
    print(f'   - Text length: {text_len} caracteres')
    print(f'   - Competition: {comp}')
    print(f'   - Updated: {data.get("updated_at", "NONE")[:19]}')
    print(f'   - Preview: {data.get("text", "")[:80]}...')
else:
    print(f'❌ NO EXISTE (se creará al guardar en Streamlit)')

# 2. Verificar que insights_agent lo carga
print(f'\n[2/4] Función: _load_manual_news_payload() en insights_agent')
try:
    from agents.insights_agent import _load_manual_news_payload
    payload = _load_manual_news_payload()
    print(f'✅ CARGABLE desde insights_agent')
    print(f'   - Payload keys: {list(payload.keys())}')
    print(f'   - Has text: {bool(payload.get("text"))}')
    print(f'   - Has competition: {bool(payload.get("competition"))}')
    if payload.get("text"):
        print(f'   - Text preview: {payload.get("text")[:80]}...')
except Exception as e:
    print(f'❌ ERROR cargando: {e}')

# 3. Verificar pipeline_insights.json
print(f'\n[3/4] Archivo intermediate: pipeline_insights.json')
insights_file = 'pipeline_insights.json'
if os.path.exists(insights_file):
    with open(insights_file, 'r', encoding='utf-8') as f:
        insights = json.load(f)
    
    # Buscar señales con provenance='manual'
    manual_signals = []
    total_insights = len(insights) if isinstance(insights, list) else 1
    
    for insight in (insights if isinstance(insights, list) else [insights]):
        if isinstance(insight, dict):
            comp = insight.get('competition', 'N/A')
            team = insight.get('team', 'N/A')
            signals = insight.get('context_signals', [])
            for sig in signals:
                prov = sig.get('provenance') or []
                if 'manual' in prov:
                    manual_signals.append({
                        'team': team,
                        'competition': comp,
                        'signal': sig.get('signal', '')[:100],
                        'confidence': sig.get('confidence', 0),
                        'type': sig.get('type', 'N/A')
                    })
    
    print(f'✅ EXISTE ({total_insights} registros)')
    print(f'   - Manual signals encontradas: {len(manual_signals)}')
    if manual_signals:
        for sig in manual_signals[:5]:
            print(f'     • {sig["team"]:20} ({sig["competition"]:5}): conf={sig["confidence"]:.2f} type={sig["type"]}')
            print(f'       → {sig["signal"][:70]}...')
else:
    print(f'⚠️  No existe aún (se genera al correr pipeline)')

# 4. Verificar pipeline_result.json
print(f'\n[4/4] Archivo final: pipeline_result.json')
result_file = 'pipeline_result.json'
if os.path.exists(result_file):
    try:
        with open(result_file, 'r', encoding='utf-8') as f:
            result = json.load(f)
        
        # Buscar en match_contexts si hay señales manuales
        contexts = result.get('match_contexts', {})
        print(f'✅ EXISTE')
        print(f'   - Match contexts: {len(contexts)} partidos')
        
        # Verificar un ejemplo
        manual_found = False
        for match_key, match_data in list(contexts.items())[:3]:
            home_data = match_data.get('home', {})
            away_data = match_data.get('away', {})
            
            home_signals = home_data.get('context_signals', [])
            away_signals = away_data.get('context_signals', [])
            
            manual_home = [s for s in home_signals if 'manual' in (s.get('provenance') or [])]
            manual_away = [s for s in away_signals if 'manual' in (s.get('provenance') or [])]
            
            if manual_home or manual_away:
                manual_found = True
                if manual_home:
                    print(f'   ✅ Señales MANUALES en HOME ({home_data.get("canonical_name")}):')
                    for sig in manual_home[:2]:
                        print(f'      - {sig.get("signal", "")[:70]}')
                if manual_away:
                    print(f'   ✅ Señales MANUALES en AWAY ({away_data.get("canonical_name")}):')
                    for sig in manual_away[:2]:
                        print(f'      - {sig.get("signal", "")[:70]}')
        
        if not manual_found:
            print(f'   ℹ️  Sin señales manuales en los primeros 3 match_contexts')
    except Exception as e:
        print(f'⚠️  Error leyendo: {e}')
else:
    print(f'⚠️  No existe aún (se genera al final del pipeline)')

print('\n' + "=" * 80)
print("FLUJO DE PERSISTENCIA:")
print("=" * 80)
print("""
  1. data/inputs/manual_news_input.json (Usuario guarda en Streamlit)
     {
       "text": "...",
       "competition": "COPA",
       "updated_at": "2026-04-08T..."
     }
  
  2. insights_agent.py carga _load_manual_news_payload()
     ├─ Lee el JSON
     ├─ Filtra por competition si aplica
     └─ Genera context_signals para equipos mencionados
  
  3. pipeline_insights.json (Intermediate output)
     └─ Contiene signals con "provenance": ["manual"]
        y "confidence": 0.85 (automático para noticias)
  
  4. match_contexts (en pipeline_result.json)
     ├─ home.context_signals (incluye manual signals)
     ├─ away.context_signals (incluye manual signals)
     └─ Disponible para analyst_agent
  
  5. analyst_agent.py consume match_contexts
     └─ Usa context_signals para tomar decisiones

✅ ACCESO DEL ANALISTA:
   - Archivo: pipeline_result.json
   - Path: result["match_contexts"][match_key]["home/away"]["context_signals"]
   - Filter: [s for s in signals if "manual" in s.get("provenance", [])]
""")
print("=" * 80)
