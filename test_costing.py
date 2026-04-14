#!/usr/bin/env python3
"""
Unit tests for costing.py with corrected USD/1M pricing.

Test cases verify:
1. Correct USD/1M conversion (divide by 1_000_000)
2. Model alias consolidation using MAX()
3. Web search cost separation
4. CLP conversion
"""

import sys
sys.path.insert(0, ".")

from utils.costing import (
    _canonical_model_name,
    compute_costs
)


def test_canonical_model_name():
    """Test regex-based model name canonicalization."""
    print("\n[TEST] canonical_model_name()")
    
    cases = [
        ("gpt-4.1-mini-2025-04-14", "gpt-4.1-mini"),
        ("gpt-4.1-mini", "gpt-4.1-mini"),
        ("gpt-4o-mini-2025-04-14", "gpt-4o-mini"),
        ("gpt-5-turbo", "gpt-5-turbo"),
        ("gemini-flash-latest", "gemini-flash-latest"),
    ]
    
    for input_name, expected in cases:
        result = _canonical_model_name(input_name)
        status = "PASS" if result == expected else "FAIL"
        print(f"  [{status}] {input_name!r} -> {result!r} (expected {expected!r})")
        assert result == expected, f"Mismatch: {result} != {expected}"


def test_consolidation_max():
    """Test that MAX() consolidation prevents double-counting."""
    print("\n[TEST] consolidation with MAX()")
    
    usage = {
        "gpt-4.1-mini-2025-04-14": {
            "prompt_tokens": 1589,
            "completion_tokens": 2000,
            "calls": 1
        },
        "gpt-4.1-mini": {
            "prompt_tokens": 1541,
            "completion_tokens": 1736,
            "calls": 1
        }
    }
    
    pricing = {
        "gpt-4.1-mini": {
            "prompt_per_1m_usd": 0.40,
            "completion_per_1m_usd": 1.60
        }
    }
    
    report = compute_costs(usage, pricing)
    
    # After consolidation, should have 1 model entry (not 2)
    assert len(report["models"]) == 1, f"Expected 1 model, got {len(report['models'])}"
    
    model_entry = report["models"]["gpt-4.1-mini"]
    
    # Verify MAX was applied
    assert model_entry["prompt_tokens"] == 1589, f"Prompt: expected 1589, got {model_entry['prompt_tokens']}"
    assert model_entry["completion_tokens"] == 2000, f"Completion: expected 2000, got {model_entry['completion_tokens']}"
    assert len(model_entry["aliases"]) == 2, f"Expected 2 aliases, got {len(model_entry['aliases'])}"
    
    print(f"  [PASS] Consolidated {len(model_entry['aliases'])} aliases into 1 entry (MAX applied)")
    print(f"    Aliases: {model_entry['aliases']}")
    print(f"    Tokens: {model_entry['prompt_tokens']} prompt, {model_entry['completion_tokens']} completion")


def test_usd_1m_conversion():
    """Test correct USD per 1M token conversion."""
    print("\n[TEST] USD/1M conversion (divide by 1_000_000)")
    
    usage = {
        "gpt-4.1-mini": {
            "prompt_tokens": 1589,
            "completion_tokens": 2000,
            "calls": 1
        }
    }
    
    pricing = {
        "gpt-4.1-mini": {
            "prompt_per_1m_usd": 0.40,
            "completion_per_1m_usd": 1.60
        }
    }
    
    report = compute_costs(usage, pricing, clp_per_usd=900)
    
    breakdown = report["models"]["gpt-4.1-mini"]["cost_breakdown"]
    
    # Expected calculations:
    # Prompt: 1589 / 1_000_000 * 0.40 = 0.0006356
    # Completion: 2000 / 1_000_000 * 1.60 = 0.0032
    # Total: 0.0038356
    
    expected_prompt = 1589 / 1_000_000.0 * 0.40
    expected_completion = 2000 / 1_000_000.0 * 1.60
    expected_total = expected_prompt + expected_completion
    
    print(f"  Expected prompt:     {expected_prompt:.8f} USD")
    print(f"  Calculated prompt:   {breakdown['llm_prompt_usd']:.8f} USD")
    assert abs(breakdown["llm_prompt_usd"] - expected_prompt) < 1e-9, "Prompt mismatch"
    
    print(f"  Expected completion: {expected_completion:.8f} USD")
    print(f"  Calculated completion: {breakdown['llm_completion_usd']:.8f} USD")
    assert abs(breakdown["llm_completion_usd"] - expected_completion) < 1e-9, "Completion mismatch"
    
    print(f"  Expected total:      {expected_total:.8f} USD")
    print(f"  Calculated total:    {breakdown['total_usd']:.8f} USD")
    assert abs(breakdown["total_usd"] - expected_total) < 1e-9, "Total mismatch"
    
    print(f"  [PASS] USD/1M conversion correct (~{breakdown['total_usd']:.6f} USD)")


def test_clp_conversion():
    """Test CLP conversion at 900 CLP/USD."""
    print("\n[TEST] CLP conversion (900 CLP/USD)")
    
    usage = {
        "gpt-4.1-mini": {
            "prompt_tokens": 1589,
            "completion_tokens": 2000,
            "calls": 1
        }
    }
    
    pricing = {
        "gpt-4.1-mini": {
            "prompt_per_1m_usd": 0.40,
            "completion_per_1m_usd": 1.60
        }
    }
    
    report = compute_costs(usage, pricing, clp_per_usd=900)
    
    usd_total = report["totals"]["total_usd"]
    clp_total = report["totals"]["total_clp"]
    
    expected_clp = int(round(usd_total * 900, 0))
    
    print(f"  USD total: {usd_total:.8f}")
    print(f"  Expected CLP: {expected_clp}")
    print(f"  Calculated CLP: {clp_total}")
    assert clp_total == expected_clp, f"CLP mismatch: {clp_total} != {expected_clp}"
    
    print(f"  [PASS] CLP conversion correct ({clp_total} CLP)")


def test_web_search_cost():
    """Test web search cost as separate line item."""
    print("\n[TEST] Web search cost (8000 input tokens)")
    
    usage = {
        "gpt-4.1-mini": {
            "prompt_tokens": 1589,
            "completion_tokens": 2000,
            "calls": 1
        }
    }
    
    pricing = {
        "gpt-4.1-mini": {
            "prompt_per_1m_usd": 0.40,
            "completion_per_1m_usd": 1.60,
            "web_search_input_per_1m_usd": 0.40
        }
    }
    
    # With 8000 tokens of web search content
    report = compute_costs(usage, pricing, clp_per_usd=900, web_search_tokens=8000)
    
    breakdown = report["models"]["gpt-4.1-mini"]["cost_breakdown"]
    
    # Web search: 8000 / 1_000_000 * 0.40 = 0.0032
    expected_web_search = 8000 / 1_000_000.0 * 0.40
    
    print(f"  LLM prompt:   {breakdown['llm_prompt_usd']:.8f}")
    print(f"  LLM completion: {breakdown['llm_completion_usd']:.8f}")
    print(f"  Web search:   {breakdown['web_search_usd']:.8f}")
    print(f"  Total:        {breakdown['total_usd']:.8f}")
    
    assert abs(breakdown["web_search_usd"] - expected_web_search) < 1e-9, "Web search cost mismatch"
    
    print(f"  [PASS] Web search cost correct ({breakdown['web_search_usd']:.8f} USD for 8K tokens)")


if __name__ == "__main__":
    print("\n" + "="*80)
    print("  UNIT TESTS: Costing System (USD/1M, Consolidation, Web Search)")
    print("="*80)
    
    try:
        test_canonical_model_name()
        test_consolidation_max()
        test_usd_1m_conversion()
        test_clp_conversion()
        test_web_search_cost()
        
        print("\n" + "="*80)
        print("  [OK] ALL TESTS PASSED")
        print("="*80 + "\n")
    except AssertionError as e:
        print(f"\n[FAIL] {e}")
        sys.exit(1)
