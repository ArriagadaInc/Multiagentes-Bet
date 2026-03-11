#!/usr/bin/env python3
"""Test para verificar que la normalización de nombres funciona correctamente"""

from utils.normalizer import TeamNormalizer

n = TeamNormalizer()

test_cases = [
    "Real Madrid CF",
    "Real Madrid",
    "Arsenal FC",
    "FC Bayern München",
    "Paris Saint Germain",
    "PSG",
    "Barcelona",
    "FC Barcelona"
]

print("=" * 50)
print("TEST: Normalización de nombres de equipo")
print("=" * 50)

for team_name in test_cases:
    normalized = n.clean(team_name)
    print(f"{team_name:30} -> {normalized}")

print("\n" + "=" * 50)
print("TEST: Verificar schema")
print("=" * 50)

from agents.schemas import TeamStatsCanonical, TeamStatsLegacy

# Test creating a TeamStatsCanonical with canonical_name
try:
    stats = TeamStatsCanonical(
        team="Real Madrid CF",
        competition="UCL",
        provider="test",
        canonical_name=n.clean("Real Madrid CF"),
        stats=TeamStatsLegacy(position=1, played=8, won=5, draw=0, lost=3, 
                              goals_for=15, goals_against=8, goal_difference=7, points=15)
    )
    print(f"✓ TeamStatsCanonical creado correctamente")
    print(f"  - team: {stats.team}")
    print(f"  - canonical_name: {stats.canonical_name}")
    print(f"  - competition: {stats.competition}")
except Exception as e:
    print(f"✗ Error al crear TeamStatsCanonical: {e}")

print("\n" + "=" * 50)
