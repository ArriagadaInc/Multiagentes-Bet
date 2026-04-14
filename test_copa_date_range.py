"""
Test: Verificar que Agentes 1 & 2 (Fixtures/Odds) usan 7 días
       y Agente Web usa 10 días de lookback
Ref: bitacora.md - Ventanas Temporales Diferenciadas por Agente (v13.5)
"""
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

# Cargar .env
load_dotenv()

# Agentes 1 & 2: Fixtures/Odds
FIXTURES_DAYS_AHEAD = int(os.getenv("FIXTURES_DAYS_AHEAD", "7"))

# Agente Web: Análisis/Contexto (puede mirar más atrás)
WEB_LOOKBACK_DAYS = int(os.getenv("ANALYST_WEB_CHECK_LOOKBACK_DAYS", "10"))

print("=" * 70)
print("TEST: Ventanas Temporales por Agente")
print("=" * 70)

print("\n📋 Configuración:\n")
print(f"✅ Agentes 1 & 2 (Fixtures/Odds): {FIXTURES_DAYS_AHEAD} días")
print(f"   └─ Solo eventos próximos con mercado abierto")
print(f"\n✅ Agente Web (Análisis/Contexto): {WEB_LOOKBACK_DAYS} días")
print(f"   └─ Puede buscar información histórica más atrás")

print("\n" + "=" * 70)
print("VALIDACIÓN:")
print("=" * 70)

# Validaciones
pass_count = 0
fail_count = 0

# Test 1: Fixtures 7 días
if FIXTURES_DAYS_AHEAD == 7:
    print("✅ [1] Agentes 1 & 2 usan 7 días")
    pass_count += 1
else:
    print(f"❌ [1] Agentes 1 & 2 deberían ser 7 días, pero son {FIXTURES_DAYS_AHEAD}")
    fail_count += 1

# Test 2: Web 10 días
if WEB_LOOKBACK_DAYS == 10:
    print("✅ [2] Agente Web usa 10 días")
    pass_count += 1
else:
    print(f"❌ [2] Agente Web debería ser 10 días, pero es {WEB_LOOKBACK_DAYS}")
    fail_count += 1

print("\n" + "=" * 70)

# Mostrar rangos
today = datetime.now()
fixtures_from = today.strftime("%Y-%m-%d")
fixtures_to = (today + timedelta(days=FIXTURES_DAYS_AHEAD)).strftime("%Y-%m-%d")
web_from = (today - timedelta(days=WEB_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
web_to = today.strftime("%Y-%m-%d")

print(f"\n📆 Rango de fechas:\n")
print(f"Agentes 1 & 2 (Fixtures/Odds):")
print(f"   Desde: {fixtures_from}")
print(f"   Hasta: {fixtures_to}")
print(f"   Ventana: {FIXTURES_DAYS_AHEAD} días hacia ADELANTE")

print(f"\nAgente Web (Búsqueda de contexto):")
print(f"   Desde: {web_from}")
print(f"   Hasta: {web_to}")
print(f"   Ventana: {WEB_LOOKBACK_DAYS} días hacia ATRÁS")

print("\n" + "=" * 70)
if fail_count == 0:
    print("✅ TODOS LOS TESTS PASARON")
    print("Ventanas temporales correctamente diferenciadas")
else:
    print(f"❌ {fail_count} test(s) fallaron")
print("=" * 70)


