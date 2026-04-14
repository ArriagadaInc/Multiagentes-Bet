import json
import os

CACHE_DIR = "cache"

def list_cached_scoreboards():
    if not os.path.exists(CACHE_DIR):
        print("No cache dir")
        return
    
    files = [f for f in os.listdir(CACHE_DIR) if f.startswith("odds") or f.startswith("scoreboard") or f.startswith("cache_")]
    # ResultEvaluator uses self.cache.load("odds", ...) or similar
    # Actually, the CacheManager uses a specific naming convention.
    
    # Let's check the code of CacheManager to see where it saves things.
    # It seems it's in c:\desarrollos\apuestas\Futbol\cache
    
    for f in os.listdir(CACHE_DIR):
        if "chi.1" in f or "chi.2" in f or "chi.copa_chi" in f:
            print(f"Cache file: {f}")

if __name__ == "__main__":
    list_cached_scoreboards()
