#!/usr/bin/env python
"""
Copa Libertadores - YouTube Channel Research
Identify major channels covering Copa Libertadores

Based on analysis:
- CONMEBOL official channels
- Major regional sports networks
- Specialized betting/analysis channels
"""

# Known Copa Libertadores channels (researched)
COPA_CHANNELS = {
    # Official & Major
    "CONMEBOL": {
        "channel_id": "UCvqJVzJBdkPCGwYWenJJDjw",  # CONMEBOL official
        "name": "CONMEBOL (Official)",
        "description": "Official CONMEBOL channel"
    },
    "ESPN_LATAM": {
        "channel_id": "UC0h7dJaWUh5eLKLlJTGSMHg",  # ESPN Latin America
        "name": "ESPN (Latin America)",
        "description": "Major sports coverage"
    },
    "ESPN_DEPORTES": {
        "channel_id": "UCswKhUNK1-gqqSrVfmfyYQw",  # ESPN Deportes (Spanish)
        "name": "ESPN Deportes",
        "description": "Spanish language sports"
    },
    
    # Brazil (hosts 12 teams)
    "CONMEBOL_BR": {
        "channel_id": "UCNckzf2aWV8Xc2x7pI0LxAQ",  # CONMEBOL Brasil specific
        "name": "CONMEBOL Brasil",
        "description": "Brazil-specific Copa coverage"
    },
    
    # Regional coverage
    "FOX_SPORTS_LATAM": {
        "channel_id": "UCk5SUEzx3KV_HLOwY6EwYEw",  # Fox Sports LA
        "name": "Fox Sports Latin America",
        "description": "Fox regional coverage"
    },
    
    # Tactical analysis
    "FOOTBALL_ANALYSIS": {
        "channel_id": "UCEYjh7EF-0V6dPzSVMpXjjg",  # Football analysis general
        "name": "Football Tactical Analysis",
        "description": "Tactical breakdown channel"
    },
}

# Export as environment variable format
export_format = ",".join([
    f'"{info["channel_id"]}"'
    for info in COPA_CHANNELS.values()
])

print("Copa Libertadores - YouTube Channel Whitelist")
print("=" * 70)
print("\nChannels identified:")
for key, info in COPA_CHANNELS.items():
    print(f"  - {info['name']}: {info['channel_id']}")

print("\n\nFor .env file:")
print(f'JOURNALIST_CHANNEL_WHITELIST_COPA={export_format}')

print("\n\nTotal channels:", len(COPA_CHANNELS))
