#!/usr/bin/env python
"""Quick test of pipeline imports and initialization"""

import sys
import os

# Test imports
print("Testing module imports...")

try:
    from state import AgentState
    print("  ✓ state.py")
except Exception as e:
    print(f"  ✗ state.py: {e}")
    sys.exit(1)

try:
    from utils.cache import CacheManager
    print("  ✓ utils.cache")
except Exception as e:
    print(f"  ✗ utils.cache: {e}")
    sys.exit(1)

try:
    from utils.http import HTTPClient
    print("  ✓ utils.http")
except Exception as e:
    print(f"  ✗ utils.http: {e}")
    sys.exit(1)

try:
    from agents.fixtures_agent import FixturesFetcher, fixtures_fetcher_node
    print("  ✓ agents.fixtures_agent")
except Exception as e:
    print(f"  ✗ agents.fixtures_agent: {e}")
    sys.exit(1)

try:
    from agents.odds_agent import OddsFetcher, odds_fetcher_node
    print("  ✓ agents.odds_agent")
except Exception as e:
    print(f"  ✗ agents.odds_agent: {e}")
    sys.exit(1)

try:
    from graph_pipeline import build_pipeline, create_initial_state, PipelineExecutor
    print("  ✓ graph_pipeline")
except Exception as e:
    print(f"  ✗ graph_pipeline: {e}")
    sys.exit(1)

print("\nTesting state initialization...")

try:
    competitions = [
        {"competition": "UCL", "fixtures_provider": "football-data", "competition_code": "CL"},
        {"competition": "CHI1", "fixtures_provider": "football-data", "competition_code": None}
    ]
    
    initial_state = create_initial_state(competitions)
    
    print(f"  ✓ Initial state created")
    print(f"    - Competitions: {len(initial_state['competitions'])}")
    print(f"    - Messages: {len(initial_state['messages'])}")
    print(f"    - Meta keys: {list(initial_state['meta'].keys())}")
    
except Exception as e:
    print(f"  ✗ State initialization failed: {e}")
    sys.exit(1)

print("\nTesting graph construction...")

try:
    executor = PipelineExecutor()
    print("  ✓ PipelineExecutor created")
    print("  ✓ Graph compiled successfully")
except Exception as e:
    print(f"  ✗ Graph construction failed: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("✅ ALL TESTS PASSED - Pipeline is ready to use!")
print("=" * 60)
