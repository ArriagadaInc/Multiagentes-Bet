import json
import os
import time
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)

CACHE_DIR = "./cache"

class CacheManager:
    """
    Gestor de caché en disco para el pipeline multiagente.
    Soporta TTL (Time To Live) por archivo.
    """
    def __init__(self, default_ttl_seconds: int = 3600):
        self.default_ttl_seconds = default_ttl_seconds
        if not os.path.exists(CACHE_DIR):
            os.makedirs(CACHE_DIR, exist_ok=True)

    def _get_path(self, prefix: str, key: str, status: str) -> str:
        """Construye una ruta de archivo estandarizada: {prefix}_{key}_{status}.json"""
        # Sanitizar nombres para evitar problemas con caracteres especiales en Windows
        safe_key = str(key).replace("/", "_").replace("\\", "_").replace(":", "_")
        safe_status = str(status).replace("/", "_").replace("\\", "_").replace(":", "_")
        return os.path.join(CACHE_DIR, f"{prefix}_{safe_key}_{safe_status}.json")

    def load(self, prefix: str, key: str, status: str, ttl_seconds: Optional[int] = None) -> Optional[Any]:
        """Carga datos del caché si existen y no han expirado."""
        path = self._get_path(prefix, key, status)
        if not os.path.exists(path):
            return None
        
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        
        try:
            mtime = os.path.getmtime(path)
            if (time.time() - mtime) > ttl:
                logger.debug(f"Caché expirado para {path}")
                return None
                
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error cargando caché de {path}: {e}")
            return None

    def save(self, data: Any, prefix: str, key: str, status: str) -> None:
        """Guarda datos en un archivo JSON serializable."""
        path = self._get_path(prefix, key, status)
        try:
            # Asegurar que el directorio de caché existe justo antes de guardar
            if not os.path.exists(CACHE_DIR):
                os.makedirs(CACHE_DIR, exist_ok=True)
                
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"Caché guardado en {path}")
        except Exception as e:
            logger.warning(f"Error guardando caché en {path}: {e}")

# --- Funciones de compatibilidad para Agentes que no usan la clase ---

def load_cache(competition: str, ttl_seconds: int = 3600) -> Optional[Any]:
    """Carga caché usando el formato específico del Agente Periodista."""
    manager = CacheManager(default_ttl_seconds=ttl_seconds)
    date_str = time.strftime("%Y-%m-%d")
    return manager.load("journalist", competition, date_str)

def save_cache(competition: str, data: Any) -> None:
    """Guarda caché usando el formato específico del Agente Periodista."""
    manager = CacheManager()
    date_str = time.strftime("%Y-%m-%d")
    manager.save(data, "journalist", competition, date_str)
