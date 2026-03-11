import unittest
import os
import time
import json
from utils.cache import load_cache, save_cache, CACHE_DIR

class TestJournalistCache(unittest.TestCase):
    
    def setUp(self):
        self.comp = "TEST_COMP"
        if not os.path.exists(CACHE_DIR):
            os.makedirs(CACHE_DIR)

    def test_save_and_load_cache(self):
        data = {"test": "data"}
        save_cache(self.comp, data)
        
        # Cargar inmediatamente (debe funcionar)
        loaded = load_cache(self.comp, ttl_seconds=60)
        self.assertEqual(loaded, data)

    def test_cache_ttl_expired(self):
        data = {"test": "expired"}
        save_cache(self.comp, data)
        
        # Simular que el archivo es viejo (cambiando su mtime)
        path = os.path.join(CACHE_DIR, f"journalist_{self.comp}_{time.strftime('%Y-%m-%d')}.json")
        past_time = time.time() - 5000
        os.utime(path, (past_time, past_time))
        
        # Cargar con TTL corto (debe fallar)
        loaded = load_cache(self.comp, ttl_seconds=3600)
        self.assertIsNone(loaded)

if __name__ == "__main__":
    unittest.main()
