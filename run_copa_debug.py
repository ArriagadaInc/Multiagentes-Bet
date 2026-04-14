#!/usr/bin/env python
"""
COPA Pipeline Execution with Full Debug Capture
"""

import subprocess
import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path.cwd()
LOG_FILE = PROJECT_ROOT / "copa_debug_run.log"

print("\n" + "="*80)
print("COPA LIBERTADORES - PIPELINE DEBUG RUN")
print("="*80)
print(f"\nStarting: {datetime.now().isoformat()}\n")

cmd = [sys.executable, "run_pipeline.py", "--liga", "COPA"]

try:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(PROJECT_ROOT),
        encoding='utf-8',
        errors='replace'
    )
    
    # Write to log file
    with open(LOG_FILE, 'w', encoding='utf-8', errors='replace') as f:
        f.write("="*80 + "\n")
        f.write("COPA PIPELINE DEBUG RUN\n")
        f.write("="*80 + "\n\n")
        
        f.write(f"Command: {' '.join(cmd)}\n")
        f.write(f"Exit Code: {result.returncode}\n")
        f.write(f"Timestamp: {datetime.now().isoformat()}\n\n")
        
        f.write("--- STDOUT ---\n")
        f.write(result.stdout)
        f.write("\n\n--- STDERR ---\n")
        f.write(result.stderr)
    
    # Console summary
    print(f"Exit Code: {result.returncode}\n")
    
    # Extract key lines
    print("KEY OUTPUT LINES:")
    print("-" * 80)
    
    for line in result.stdout.split('\n'):
        # Show important lines
        if any(x in line.lower() for x in ['copa', 'error', 'failed', 'complete', 'fixture', 'prediction', 'agent', '✓', '[info', '[error']):
            if line.strip():
                print(line[:100])
    
    print("\n" + "="*80)
    print(f"Full log saved to: {LOG_FILE}")
    print("="*80 + "\n")
    
    # Check output files
    print("\nOUTPUT FILES:")
    for fname in ["pipeline_fixtures.json", "pipeline_odds.json", "pipeline_predictions.json", "pipeline_result.json"]:
        fpath = PROJECT_ROOT / fname
        if fpath.exists():
            size = fpath.stat().st_size
            print(f"  OK: {fname} ({size:,} bytes)")
        else:
            print(f"  -- {fname} (not found)")
    
except subprocess.TimeoutExpired:
    print("[TIMEOUT] Pipeline took too long (>180s)")
except Exception as e:
    print(f"[ERROR] {e}")
