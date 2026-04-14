#!/usr/bin/env python3
"""Fix .env file - replace malformed Copa entries with proper newlines"""

with open('c:\\desarrollos\\apuestas\\Futbol\\.env', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the malformed entries with backtick-n
content = content.replace(
    'YT_URL_UCL=https://www.youtube.com/watch?v=5pj4YdUnETU`nYT_URL_COPA=https://www.youtube.com/watch?v=5c3E7pJ9aXU',
    'YT_URL_UCL=https://www.youtube.com/watch?v=5pj4YdUnETU\nYT_URL_COPA=https://www.youtube.com/watch?v=5c3E7pJ9aXU'
)

with open('c:\\desarrollos\\apuestas\\Futbol\\.env', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Fixed .env file - proper newlines inserted for YT_URL_COPA")
