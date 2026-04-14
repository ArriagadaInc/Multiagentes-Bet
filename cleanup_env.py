#!/usr/bin/env python3
"""Remove .env duplication and fix Copa URL"""

with open('c:\\desarrollos\\apuestas\\Futbol\\.env', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the duplication point (line 114 is where second config starts)
# Keep only the first section + the CHI2 section at the end
cleaned_lines = []
skip_mode = False

for i, line in enumerate(lines, 1):
    # Skip the duplicate section (lines 114 onwards that are identical to earlier)
    if i == 114:
        # We've hit the duplicate header, skip everything until the end
        skip_mode = True
        continue
    
    if skip_mode:
        # Only keep lines that are NEW/UNIQUE after duplication (CHI2 section, GEMINI config)
        if 'CHI2 FUENTES' in line or 'GEMINI' in line or 'USE_FOOTYSTATS' in line or 'USE_PRIMERABCHILE' in line:
            skip_mode = False
            cleaned_lines.append(line)
        continue
    
    # Fix the malformed Copa line
    if '`nYT_URL_COPA=' in line:
        cleaned_lines.append('YT_URL_UCL=https://www.youtube.com/watch?v=5pj4YdUnETU\n')
        cleaned_lines.append('YT_URL_COPA=https://www.youtube.com/watch?v=5c3E7pJ9aXU\n')
        continue
    
    cleaned_lines.append(line)

# Write back
with open('c:\\desarrollos\\apuestas\\Futbol\\.env', 'w', encoding='utf-8') as f:
    f.writelines(cleaned_lines)

print("✅ Fixed .env - removed duplication and fixed Copa URL entries")
