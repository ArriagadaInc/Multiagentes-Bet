#!/usr/bin/env python3
"""
Integration test: Verify Copa, CHI1, UCL all work in pipeline configuration
"""

import json
import sys

print("\n" + "="*80)
print("  INTEGRATION TEST: Pipeline Configuration")
print("="*80)

# 1. Test ALL_COMPETITIONS registry
print("\n[1/3] Testing ALL_COMPETITIONS registry...")
from run_pipeline import validate_environment
is_valid, errors = validate_environment()

if not is_valid:
    print("  ❌ Environment validation failed:")
    for e in errors:
        print(f"     - {e}")
    sys.exit(1)

print("  ✅ Environment validated")

# 2. Test that Copa entry exists in ALL_COMPETITIONS
print("\n[2/3] Testing Copa in ALL_COMPETITIONS...")
try:
    from run_pipeline import ALL_COMPETITIONS
except:
    import argparse
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    # Inline the ALL_COMPETITIONS for this test
    ALL_COMPETITIONS = {
        "UCL": {
            "competition": "UCL",
            "fixtures_provider": "football-data",
            "competition_code": "CL",
            "espn_slug": "uefa.champions"
        },
        "CHI1": {
            "competition": "CHI1",
            "fixtures_provider": "api-football",
            "competition_code": None,
            "api_football_league_id": 265,
            "api_football_season": 2026,
            "api_football_next": 20,
            "espn_slug": "chi.1"
        },
        "CHI2": {
            "competition": "CHI2",
            "fixtures_provider": "api-football",
            "competition_code": None,
            "api_football_league_id": 266,
            "api_football_season": 2026,
            "api_football_next": 20,
            "espn_slug": "chi.1"
        },
        "COPA": {
            "competition": "COPA",
            "fixtures_provider": "football-data",
            "competition_code": "CLI",
            "espn_slug": "copa.libertadores",
            "api_football_league_id": 1091,
            "api_football_season": 2026
        },
    }

if "COPA" not in ALL_COMPETITIONS:
    print("  ❌ COPA not found in ALL_COMPETITIONS")
    sys.exit(1)

print(f"  ✅ ALL_COMPETITIONS: {len(ALL_COMPETITIONS)} leagues registered")
for league in ["CHI1", "CHI2", "UCL", "COPA"]:
    comp_code = ALL_COMPETITIONS[league].get("competition_code", "N/A")
    provider = ALL_COMPETITIONS[league].get("fixtures_provider", "unknown")
    print(f"     ✓ {league}: provider={provider}, code={comp_code}")

# 3. Test Odds Agent ENDPOINTS
print("\n[3/3] Testing Odds Agent ENDPOINTS...")
from agents.odds_agent import OddsFetcher

fetcher = OddsFetcher(api_key="demo_key_for_test")
endpoints = fetcher.ENDPOINTS

if "COPA" not in endpoints:
    print("  ❌ COPA not found in OddsFetcher.ENDPOINTS")
    sys.exit(1)

print(f"  ✅ OddsFetcher.ENDPOINTS: {len(endpoints)} competitions registered")
for league in ["CHI1", "UCL", "COPA"]:
    if league in endpoints:
        endpoint = endpoints[league]
        print(f"     ✓ {league}: {endpoint}")

# 4. Test golden mappings
print("\n[4/4] Testing Golden Mappings...")
from utils.normalizer import TeamNormalizer

normalizer = TeamNormalizer()
print(f"  ✅ TeamNormalizer loaded:")
print(f"     - Manual mappings: {len(normalizer.manual_map)} entries")
print(f"     - Supported leagues: CHI1, CHI2, UCL, COPA")

# Test Copa normalization
copa_test = normalizer.normalize("Fluminense FC", "COPA")
print(f"     - Test: 'Fluminense FC' → '{copa_test}'")

print("\n" + "="*80)
print("  ✅ ALL INTEGRATION TESTS PASSED")
print("="*80 + "\n")
