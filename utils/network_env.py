"""
Utilidades para sanear configuración de red heredada del entorno.

Problema observado:
- Algunos procesos heredan proxies "sinkhole" como http://127.0.0.1:9
- Eso rompe toda salida HTTP del pipeline (API-Football, FootyStats, DDG, etc.)

La estrategia aquí es conservadora:
- Solo removemos proxies claramente inválidos/locales de descarte.
- No tocamos proxies corporativos/reales.
"""

from __future__ import annotations

import logging
import os
from typing import Iterable

logger = logging.getLogger(__name__)

_PROXY_KEYS: tuple[str, ...] = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "GIT_HTTP_PROXY",
    "GIT_HTTPS_PROXY",
)


def _looks_like_invalid_local_proxy(value: str) -> bool:
    v = (value or "").strip().lower()
    if not v:
        return False

    invalid_markers = (
        "127.0.0.1:9",
        "localhost:9",
        "127.0.0.1:0",
        "localhost:0",
    )
    return any(marker in v for marker in invalid_markers)


def sanitize_process_proxy_env(keys: Iterable[str] = _PROXY_KEYS) -> list[str]:
    """
    Elimina del proceso actual proxies locales inválidos heredados del entorno.

    Returns:
        Lista de variables removidas.
    """
    removed: list[str] = []
    for key in keys:
        value = os.environ.get(key)
        if value and _looks_like_invalid_local_proxy(value):
            removed.append(f"{key}={value}")
            os.environ.pop(key, None)

    if removed:
        logger.warning(
            "Proxy inválido detectado y removido del proceso: %s",
            ", ".join(removed),
        )

    return removed

