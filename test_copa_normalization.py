#!/usr/bin/env python3
"""
Quick test: Verify Copa golden mapping loads and normalizer works
"""

import json
import sys
sys.path.insert(0, '.')

from utils.normalizer import normalize_team_name

print("\n" + "="*80)
print("  QUICK TEST: Copa Team Normalization")
print("="*80)

# Load Copa mapping
with open('utils/copa_golden_mapping.json', 'r', encoding='utf-8') as f:
    copa_teams = json.load(f)

print(f"\n✅ Loaded {len(copa_teams)} Copa teams from mapping")

# Test some normalization cases
test_cases = [
    ("fluminense", "fluminense"),
    ("FLU", "fluminense"),
    ("Palmeiras SP", "palmeiras"),
    ("VERDÃO", "palmeiras"),
    ("River Plate", "river plate"),
    ("Boca", "boca juniors"),
    ("colo colo", "colo-colo"),
    ("Universitario Peru", "universitario"),
    ("The Strongest Bolivia", "the strongest"),
]

print("\n🧪 Testing normalization:")
print("-" * 80)

for raw_name, expected_canonical in test_cases:
    result = normalize_team_name(raw_name, "COPA")
    status = "✅" if result == expected_canonical else "⚠️ "
    print(f"  {status} '{raw_name}' → '{result}' (expected: '{expected_canonical}')")

print("\n" + "="*80)
print("  ✅ QUICK TEST COMPLETED")
print("="*80 + "\n")
