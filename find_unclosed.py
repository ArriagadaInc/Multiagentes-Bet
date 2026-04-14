#!/usr/bin/env python
# Find the exact line with the unclosed triple-quote

with open('agents/web_agent.py', 'rb') as f:
    content = f.read()

# Convert to string, bypassing encoding issues for now
text = content.decode('utf-8', errors='replace')
lines = text.split('\n')

# Find lines 840-860
print("Lines 840-860:")
for i in range(839, min(860, len(lines))):
    line = lines[i]
    quote_count = line.count('"""')
    if quote_count > 0:
        print(f"{i+1}: [{quote_count}x quotes] {line[:80]}")
    else:
        print(f"{i+1}: {line[:80]}")

print("\n" + "="*60)
print("Finding unclosed triple-quote...")

# Track state
in_string = False
string_start = 0

for i, line in enumerate(lines, 1):
    if '"""' in line:
        count = line.count('"""')
        if count == 1:
            if in_string:
                print(f"CLOSES: Line {i}")
                in_string = False
            else:
                print(f"OPENS: Line {i}")
                string_start = i
                in_string = True
        elif count == 2:
            print(f"COMPLETE (open+close): Line {i}")

if in_string:
    print(f"\n❌ UNCLOSED: Opened at line {string_start}, never closed!")
