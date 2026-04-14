#!/usr/bin/env python3
"""Integration test - writes results to file"""

import json
import sys
import traceback

output = []

def log(msg):
    output.append(msg)
    print(msg)

try:
    log("\n" + "="*80)
    log("  INTEGRATION TEST: Copa Libertadores Pipeline Config")
    log("="*80)
    
    # 1. Load config
    log("\n[1] Loading ALL_COMPETITIONS registry...")
    from run_pipeline import ALL_COMPETITIONS
    
    if "COPA" in ALL_COMPETITIONS:
        log("  ✅ COPA found in registry")
        copa_config = ALL_COMPETITIONS["COPA"]
        log(f"     - Provider: {copa_config.get('fixtures_provider')}")
        log(f"     - Code: {copa_config.get('competition_code')}")
    else:
        log("  ❌ COPA NOT FOUND in registry")
        sys.exit(1)
    
    # 2. Test odds agent
    log("\n[2] Testing Odds Agent ENDPOINTS...")
    from agents.odds_agent import OddsFetcher
    fetcher = OddsFetcher(api_key="demo")
    
    if "COPA" in fetcher.ENDPOINTS:
        log(f"  ✅ COPA in ENDPOINTS: {fetcher.ENDPOINTS['COPA']}")
    else:
        log("  ❌ COPA NOT in ENDPOINTS")
        sys.exit(1)
    
    # 3. Test golden mapping
    log("\n[3] Testing Copa Golden Mapping...")
    import os
    if os.path.exists("utils/copa_golden_mapping.json"):
        with open("utils/copa_golden_mapping.json", "r") as f:
            teams = json.load(f)
        log(f"  ✅ Copa mapping loaded: {len(teams)} teams")
    else:
        log("  ❌ Copa golden mapping NOT FOUND")
        sys.exit(1)
    
    log("\n" + "="*80)
    log("  ✅ ALL TESTS PASSED - COPA READY")
    log("="*80)
    
except Exception as e:
    log(f"\n  ❌ ERROR: {e}")
    log(traceback.format_exc())
    sys.exit(1)

# Write to file
with open("test_copa_integration_results.txt", "w") as f:
    f.write("\n".join(output))

print("\n✅ Results saved to test_copa_integration_results.txt")
