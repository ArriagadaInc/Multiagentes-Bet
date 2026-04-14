#!/usr/bin/env python
"""
Direct test: Execute running Copa pipeline
Captures all output and status
"""

import subprocess
import sys
import json
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path.cwd()
OUTPUT_FILE = PROJECT_ROOT / "test_copa_exec_log.txt"

def run_pipeline_copa():
    """Execute: python run_pipeline.py --liga COPA"""
    
    print(f"[{datetime.now().isoformat()}] Starting Copa pipeline test...")
    
    cmd = [sys.executable, "run_pipeline.py", "--liga", "COPA", "--verbose"]
    
    try:
        # Capture output in subprocess
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(PROJECT_ROOT)
        )
        
        # Write all output to file
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            f.write("="*70 + "\n")
            f.write("COPA PIPELINE EXECUTION TEST\n")
            f.write("="*70 + "\n\n")
            
            f.write("COMMAND:\n")
            f.write(f"  {' '.join(cmd)}\n\n")
            
            f.write("EXIT CODE:\n")
            f.write(f"  {result.returncode}\n\n")
            
            f.write("STDOUT:\n")
            f.write(result.stdout[:5000] if result.stdout else "(no output)")
            f.write("\n\n")
            
            f.write("STDERR:\n")
            f.write(result.stderr[:5000] if result.stderr else "(no errors)")
            f.write("\n\n")
            
            f.write("="*70 + "\n")
        
        # Print summary to console
        print(f"\n✅ Pipeline execution completed")
        print(f"   Exit Code: {result.returncode}")
        print(f"   Output written to: {OUTPUT_FILE}")
        
        # Print first lines of stdout
        if result.stdout:
            lines = result.stdout.split('\n')[:10]
            print(f"\n   First output lines:")
            for line in lines:
                if line.strip():
                    print(f"   {line}")
        
        return result.returncode == 0
        
    except subprocess.TimeoutExpired:
        print("❌ Pipeline execution timed out (>120s)")
        return False
    except Exception as e:
        print(f"❌ Error executing pipeline: {e}")
        return False

def check_output_files():
    """Check if pipeline generated expected output files"""
    print("\n" + "="*70)
    print("CHECKING OUTPUT FILES")
    print("="*70)
    
    expected_files = [
        "pipeline_fixtures.json",
        "pipeline_odds.json",
        "pipeline_predictions.json",
        "pipeline_result.json",
    ]
    
    found = []
    for fname in expected_files:
        fpath = PROJECT_ROOT / fname
        if fpath.exists():
            size = fpath.stat().st_size
            found.append(f"✅ {fname} ({size} bytes)")
        else:
            found.append(f"❌ {fname} (not found)")
    
    for line in found:
        print(f"   {line}")
    
    return len([f for f in found if f.startswith("✅")])

if __name__ == "__main__":
    print("\n" + "🏆 "*30)
    print("COPA PIPELINE - FULL EXECUTION TEST")
    print("🏆 "*30 + "\n")
    
    success = run_pipeline_copa()
    num_files = check_output_files()
    
    print("\n" + "="*70)
    if success:
        print(f"✅ TEST PASSED - Pipeline executed successfully ({num_files} output files found)")
    else:
        print(f"❌ TEST FAILED - See {OUTPUT_FILE} for details")
    print("="*70 + "\n")
    
    sys.exit(0 if success else 1)
