"""
Test rápido de la validación crítica de Odds en el Gate Agent
Verifica que partidos sin cuotas son eliminados ANTES del Analista
"""
import json
from agents.gate_agent import gate_agent_node
from state import AgentState

def test_gate_agent_eliminates_partidos_sin_odds():
    """Test que verifica que sin odds = partido eliminado"""
    
    # Mock state con 3 partidos: 1 con odds, 1 SIN ODDS, 1 con odds
    state = AgentState()
    
    match_contexts = [
        {
            "match_id": "COPA_001",
            "home": {"canonical_name": "Palmeiras", "stats": {"matches": 5}},
            "away": {"canonical_name": "River", "stats": {"matches": 6}},
            "odds": {"1": 2.5, "X": 3.0, "2": 2.8},  # CON ODDS
            "data_quality": {
                "score": 0.8,
                "overall_quality_score": 0.8,
                "signal_risk_level": "low",
                "has_severe_signal_issues": False,
            },
            "competition": "COPA"
        },
        {
            "match_id": "COPA_002",
            "home": {"canonical_name": "Boca", "stats": {"matches": 5}},
            "away": {"canonical_name": "Cruzeiro", "stats": {"matches": 6}},
            "odds": None,  # ⚠️ SIN ODDS - DEBE SER ELIMINADO
            "data_quality": {
                "score": 0.8,
                "overall_quality_score": 0.8,
                "signal_risk_level": "low",
                "has_severe_signal_issues": False,
            },
            "competition": "COPA"
        },
        {
            "match_id": "COPA_003",
            "home": {"canonical_name": "Fluminense", "stats": {"matches": 5}},
            "away": {"canonical_name": "Barcelona", "stats": {"matches": 6}},
            "odds": {"1": 2.1, "X": 3.5, "2": 3.2},  # CON ODDS
            "data_quality": {
                "score": 0.75,
                "overall_quality_score": 0.75,
                "signal_risk_level": "low",
                "has_severe_signal_issues": False,
            },
            "competition": "COPA"
        }
    ]
    
    state["match_contexts"] = match_contexts
    
    # Ejecutar Gate Agent
    result = gate_agent_node(state)
    
    # Validaciones
    passed_contexts = result.get("match_contexts", [])
    gate_summary = result.get("gate_summary", {})
    
    print("=" * 70)
    print("TEST: Gate Agent - Validación Crítica de Odds")
    print("=" * 70)
    print(f"\n✅ Partidos entrados: {len(match_contexts)}")
    print(f"✅ Partidos pasados: {len(passed_contexts)}")
    print(f"❌ Partidos eliminados: {gate_summary.get('total_dropped', 0)}")
    print(f"\n📊 Resumen del Gate:")
    print(f"  - Clean: {gate_summary.get('count_clean', 0)}")
    print(f"  - Degraded: {gate_summary.get('count_degraded', 0)}")
    print(f"  - Observation: {gate_summary.get('count_observation', 0)}")
    print(f"  - Dropped: {gate_summary.get('total_dropped', 0)}")
    
    print(f"\n🔎 Eventos del Gate:")
    for event in gate_summary.get("events", []):
        if event["gate_status"] == "dropped":
            print(f"  ❌ {event['match_id']}: {event.get('drop_reason', 'unknown')}")
            if event.get("message"):
                print(f"     Razón: {event['message']}")
        else:
            print(f"  ✅ {event['match_id']}: {event['gate_status']}")
    
    # Validación crítica
    print("\n" + "=" * 70)
    print("VALIDACIÓN CRÍTICA:")
    print("=" * 70)
    
    # Debe haber 1 partido eliminado (el que no tiene odds)
    assert gate_summary.get('total_dropped') == 1, f"❌ Esperaba 1 partido eliminado, pero {gate_summary.get('total_dropped')} fueron eliminados"
    print("✅ PASO 1: Exactamente 1 partido fue eliminado")
    
    # El partido sin odds debe ser COPA_002
    dropped_matches = [e for e in gate_summary.get("events", []) if e["gate_status"] == "dropped"]
    copa_002_dropped = any(m["match_id"] == "COPA_002" for m in dropped_matches)
    assert copa_002_dropped, "❌ COPA_002 (sin odds) no fue eliminado"
    print("✅ PASO 2: COPA_002 (sin odds) fue correctamente eliminado")
    
    # La razón debe ser 'no_market_odds'
    copa_002_reason = next((m.get("drop_reason") for m in dropped_matches if m["match_id"] == "COPA_002"), None)
    assert copa_002_reason == "no_market_odds", f"❌ Razón incorrecta: {copa_002_reason}"
    print("✅ PASO 3: Razón de eliminación correcta: 'no_market_odds'")
    
    # Deben quedar 2 partidos (los que sí tienen odds)
    assert len(passed_contexts) == 2, f"❌ Esperaba 2 partidos pasados, pero {len(passed_contexts)} pasaron"
    print("✅ PASO 4: Los 2 partidos con odds pasaron el Gate")
    
    print("\n" + "=" * 70)
    print("✅ TODOS LOS TESTS PASARON")
    print("La validación crítica de odds está funcionando correctamente")
    print("=" * 70)

if __name__ == "__main__":
    test_gate_agent_eliminates_partidos_sin_odds()
