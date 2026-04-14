"""
Costing system with corrected USD/1M pricing units and proper model consolidation.

UNITS CLARIFICATION:
  - pricing.json now uses USD per 1M tokens (OpenAI standard)
  - Internal: all conversions divide by 1_000_000
  - Output: USD and CLP for auditor review
"""

import os
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
import re

PRICING_FILE = "pricing.json"
TOKEN_USAGE_FILE = "token_usage.json"
COST_HISTORY_DIR = Path("cost_history")
COST_HISTORY_DIR.mkdir(exist_ok=True)

DEFAULT_EXCHANGE = float(os.getenv("EXCHANGE_RATE_CLP_PER_USD", "900"))

DEFAULT_PRICING = {
    "gpt-4.1-mini": {
        "prompt_per_1m_usd": 0.40,
        "completion_per_1m_usd": 1.60,
        "web_search_input_per_1m_usd": 0.40
    },
    "gemini-flash-latest": {
        "prompt_per_1m_usd": 0.035,
        "completion_per_1m_usd": 0.30,
        "web_search_input_per_1m_usd": 0.035
    }
}


def load_pricing() -> Dict[str, Dict[str, float]]:
    """Load pricing from pricing.json (USD per 1M tokens)."""
    if os.path.exists(PRICING_FILE):
        try:
            with open(PRICING_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    # Filter out comment fields
                    return {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} 
                            for k, v in data.items() if isinstance(v, dict)}
        except Exception as e:
            print(f"[WARN] Error loading pricing.json: {e}")
    return DEFAULT_PRICING


def load_token_usage() -> Dict[str, Any]:
    """Load token usage from token_usage.json (raw callback data)."""
    if os.path.exists(TOKEN_USAGE_FILE):
        try:
            with open(TOKEN_USAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def _canonical_model_name(name: str) -> str:
    """
    Normalize model names by removing version date suffixes.
    
    Examples:
      - gpt-4.1-mini-2025-04-14 -> gpt-4.1-mini
      - gpt-4.1-mini -> gpt-4.1-mini
      - gpt-4o-mini -> gpt-4o-mini
    
    Regex: ^(.*?)(?:-\d{4}-\d{2}-\d{2}.*)?$
      - Captures: everything before -YYYY-MM-DD suffix (if present)
      - Handles: all model naming patterns (gpt-4.1, gpt-4o, gpt-4-turbo, etc.)
    """
    if not name:
        return "unknown"
    # Match: everything before -YYYY-MM-DD suffix and ignore trailing date
    m = re.match(r"^(.*?)(?:-\d{4}-\d{2}-\d{2}.*)?$", name)
    if m:
        return m.group(1)
    # Fallback: return as-is
    return name


def compute_costs(usage: Dict[str, Any], pricing: Dict[str, Dict[str, float]], 
                 clp_per_usd: float = DEFAULT_EXCHANGE, 
                 web_search_tokens: int = 0) -> Dict[str, Any]:
    """
    Compute costs with proper consolidation and USD/1M pricing.
    
    Args:
      usage: raw token_usage.json data {model: {prompt_tokens, completion_tokens, calls}}
      pricing: pricing.json data {model: {prompt_per_1m_usd, completion_per_1m_usd, ...}}
      clp_per_usd: exchange rate (default 900)
      web_search_tokens: if >0, add web search cost (input tokens treated as search content)
    
    Returns:
      {
        "models": {
          "gpt-4.1-mini": {
            "prompt_tokens": 1589,
            "completion_tokens": 2000,
            "calls": 1,
            "cost_breakdown": {
              "llm_prompt_usd": 0.0006356,
              "llm_completion_usd": 0.0032,
              "web_search_usd": 0.0,
              "total_usd": 0.0038356
            },
            "cost_clp": 3452
          }
        },
        "totals": {
          "llm_prompt_usd": 0.0006356,
          "llm_completion_usd": 0.0032,
          "web_search_usd": 0.0,
          "total_usd": 0.0038356,
          "total_clp": 3452
        }
      }
    """
    
    # === STEP 1: Consolidate by canonical model name ===
    consolidated: Dict[str, Dict[str, Any]] = {}
    
    for model_alias, u in usage.items():
        canonical = _canonical_model_name(model_alias)
        prompt = float(u.get("prompt_tokens", 0))
        completion = float(u.get("completion_tokens", 0))
        calls = int(u.get("calls", 1))
        
        if canonical not in consolidated:
            consolidated[canonical] = {
                "prompt": prompt,
                "completion": completion,
                "calls": calls,
                "aliases": [model_alias]
            }
        else:
            # CRITICAL: Take MAX to avoid double-counting same LLM call with different aliases
            old_p = consolidated[canonical]["prompt"]
            old_c = consolidated[canonical]["completion"]
            
            consolidated[canonical]["prompt"] = max(old_p, prompt)
            consolidated[canonical]["completion"] = max(old_c, completion)
            consolidated[canonical]["calls"] = max(consolidated[canonical]["calls"], calls)
            consolidated[canonical]["aliases"].append(model_alias)
    
    # === STEP 2: Calculate costs (USD per 1M tokens) ===
    report = {
        "models": {},
        "totals": {
            "llm_prompt_usd": 0.0,
            "llm_completion_usd": 0.0,
            "web_search_usd": 0.0,
            "total_usd": 0.0,
            "total_clp": 0.0
        },
        "consolidation_note": "Model aliases consolidated via MAX() to avoid double-counting",
        "unit": "USD per 1M tokens (NOT per 1K)"
    }
    
    for canonical, data in consolidated.items():
        prompt_tokens = int(data["prompt"])
        completion_tokens = int(data["completion"])
        calls = int(data["calls"])
        
        # Get pricing for this model
        model_pricing = pricing.get(canonical)
        if not model_pricing:
            # Model not found in pricing - treat as $0
            report["models"][canonical] = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "calls": calls,
                "cost_breakdown": {
                    "llm_prompt_usd": 0.0,
                    "llm_completion_usd": 0.0,
                    "web_search_usd": 0.0,
                    "total_usd": 0.0
                },
                "cost_clp": 0,
                "aliases": data["aliases"],
                "warning": f"Model '{canonical}' not in pricing.json"
            }
            continue
        
        # === Cost calculation: USD per 1M ===
        prompt_rate_per_1m = model_pricing.get("prompt_per_1m_usd", 0.0)
        completion_rate_per_1m = model_pricing.get("completion_per_1m_usd", 0.0)
        web_search_rate_per_1m = model_pricing.get("web_search_input_per_1m_usd", 0.0)
        
        # Divide by 1_000_000 (not 1000!)
        llm_prompt_usd = (prompt_tokens / 1_000_000.0) * prompt_rate_per_1m
        llm_completion_usd = (completion_tokens / 1_000_000.0) * completion_rate_per_1m
        web_search_usd = (web_search_tokens / 1_000_000.0) * web_search_rate_per_1m if web_search_tokens > 0 else 0.0
        
        total_usd = llm_prompt_usd + llm_completion_usd + web_search_usd
        total_clp = total_usd * clp_per_usd
        
        # === Record per-model breakdown ===
        report["models"][canonical] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "calls": calls,
            "cost_breakdown": {
                "llm_prompt_usd": round(llm_prompt_usd, 8),
                "llm_completion_usd": round(llm_completion_usd, 8),
                "web_search_usd": round(web_search_usd, 8),
                "total_usd": round(total_usd, 8)
            },
            "cost_clp": int(round(total_clp, 0)),
            "aliases": data["aliases"]
        }
        
        # === Accumulate totals ===
        report["totals"]["llm_prompt_usd"] += llm_prompt_usd
        report["totals"]["llm_completion_usd"] += llm_completion_usd
        report["totals"]["web_search_usd"] += web_search_usd
        report["totals"]["total_usd"] += total_usd
        report["totals"]["total_clp"] += total_clp
    
    # === Round totals ===
    report["totals"]["llm_prompt_usd"] = round(report["totals"]["llm_prompt_usd"], 8)
    report["totals"]["llm_completion_usd"] = round(report["totals"]["llm_completion_usd"], 8)
    report["totals"]["web_search_usd"] = round(report["totals"]["web_search_usd"], 8)
    report["totals"]["total_usd"] = round(report["totals"]["total_usd"], 8)
    report["totals"]["total_clp"] = int(round(report["totals"]["total_clp"], 0))
    
    return report


def save_cost_snapshot(report: Dict[str, Any], liga: str = "CHI1") -> Path:
    """Save cost snapshot to cost_history/ with timestamp."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = COST_HISTORY_DIR / f"cost_{liga}_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return path
