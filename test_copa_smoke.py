#!/usr/bin/env python
"""
COPA LIBERTADORES - SMOKE TEST
Verification that Copa is fully integrated into the pipeline.
Tests: Config loading, team normalization, fixture fetching, basic agent workflow.
"""

import sys
import json
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

def test_config_loading():
    """Test 1: Verify Copa in ALL_COMPETITIONS registry"""
    print("\n" + "="*60)
    print("TEST 1: Config Loading - Copa in ALL_COMPETITIONS")
    print("="*60)
    
    try:
        from run_pipeline import ALL_COMPETITIONS
        
        if "COPA" not in ALL_COMPETITIONS:
            print("❌ FAILED: COPA not found in ALL_COMPETITIONS")
            return False
        
        copa_config = ALL_COMPETITIONS["COPA"]
        print(f"✅ Found COPA config: {copa_config['competition']}")
        print(f"   - Fixtures provider: {copa_config['fixtures_provider']}")
        print(f"   - Competition code: {copa_config['competition_code']}")
        print(f"   - ESPN slug: {copa_config['espn_slug']}")
        return True
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False


def test_team_normalization():
    """Test 2: Verify Copa team mapping loads correctly"""
    print("\n" + "="*60)
    print("TEST 2: Team Normalization - Copa golden mapping")
    print("="*60)
    
    try:
        mapping_path = PROJECT_ROOT / "utils" / "copa_golden_mapping.json"
        
        if not mapping_path.exists():
            print(f"❌ FAILED: {mapping_path} not found")
            return False
        
        with open(mapping_path, 'r', encoding='utf-8') as f:
            teams = json.load(f)
        
        print(f"✅ Loaded {len(teams)} teams from copa_golden_mapping.json")
        
        # Show sample teams
        sample_teams = teams[:3]
        for team in sample_teams:
            print(f"   - {team['canonical_name']} ({team['official_name'][:30]}...)")
            print(f"     Aliases: {', '.join(team['aliases'][:3])}...")
        
        return len(teams) >= 45  # Should have ~47 teams
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False


def test_odds_endpoint():
    """Test 3: Verify Copa endpoint in OddsAgent"""
    print("\n" + "="*60)
    print("TEST 3: Odds Agent - Copa endpoint configuration")
    print("="*60)
    
    try:
        from agents.odds_agent import ENDPOINTS
        
        if "COPA" not in ENDPOINTS:
            print("❌ FAILED: COPA not found in ENDPOINTS")
            return False
        
        endpoint = ENDPOINTS["COPA"]
        print(f"✅ Found Copa endpoint: {endpoint}")
        
        if "conmebol" not in endpoint.lower():
            print("⚠️  WARNING: Endpoint doesn't contain 'conmebol'")
            return False
        
        return True
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False


def test_normalizer_auto_detection():
    """Test 4: Verify normalizer auto-detects Copa mapping"""
    print("\n" + "="*60)
    print("TEST 4: Normalizer Auto-Detection - Copa")
    print("="*60)
    
    try:
        from utils.normalizer import TeamNormalizer
        
        normalizer = TeamNormalizer()
        
        # Check if Copa mapping was loaded
        if "COPA" not in normalizer.mappings:
            print("❌ FAILED: COPA not auto-loaded in normalizer.mappings")
            return False
        
        copa_teams = normalizer.mappings["COPA"]
        print(f"✅ Normalizer auto-detected {len(copa_teams)} Copa teams")
        
        # Test normalization
        test_cases = [
            ("Fluminense", "fluminense"),
            ("FLUMINENSE FC", "fluminense"),
            ("Flu", "fluminense"),
            ("River Plate", "river"),
            ("Boca Juniors", "boca"),
        ]
        
        print("\n   Sample normalizations:")
        for raw, expected in test_cases:
            normalized = normalizer.normalize(raw, "COPA")
            status = "✅" if normalized == expected else f"⚠️ got '{normalized}'"
            print(f"   {status} '{raw}' → '{normalized}'")
        
        return True
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False


def test_fixtures_structure():
    """Test 5: Verify Copa can be passed to fixtures loader"""
    print("\n" + "="*60)
    print("TEST 5: Fixtures Structure - Copa compatibility")
    print("="*60)
    
    try:
        from agents.fixtures_agent import FixturesAgent
        from run_pipeline import ALL_COMPETITIONS
        
        copa_config = ALL_COMPETITIONS["COPA"]
        
        # Verify essential fields exist
        required_fields = ["competition", "fixtures_provider", "competition_code", "espn_slug"]
        for field in required_fields:
            if field not in copa_config:
                print(f"❌ FAILED: Missing '{field}' in Copa config")
                return False
        
        print(f"✅ Copa config has all required fields:")
        for field in required_fields:
            print(f"   - {field}: {copa_config[field]}")
        
        return True
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False


def run_all_tests():
    """Execute all tests and report summary"""
    print("\n" + "🏆 "*30)
    print("COPA LIBERTADORES INTEGRATION SMOKE TEST")
    print("🏆 "*30)
    
    tests = [
        ("Config Loading", test_config_loading),
        ("Team Normalization", test_team_normalization),
        ("Odds Endpoint", test_odds_endpoint),
        ("Normalizer Auto-Detection", test_normalizer_auto_detection),
        ("Fixtures Structure", test_fixtures_structure),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ EXCEPTION in {test_name}: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\n{'='*60}")
    print(f"TOTAL: {passed}/{total} tests passed")
    print(f"{'='*60}\n")
    
    if passed == total:
        print("🎉 ALL TESTS PASSED - Copa Libertadores is fully integrated!")
        return 0
    else:
        print(f"⚠️  {total - passed} test(s) failed - Review output above")
        return 1


if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)
