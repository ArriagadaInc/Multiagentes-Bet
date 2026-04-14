"""
agents/youtube_selector.py

Obtiene listas de videos desde canales de YouTube usando yt_dlp y coloca
en el estado los URLs a analizar por el Agente #3 (Insights Agent).

Reglas actuales:
- CHI1: del canal @TNTSportsCL los 3 últimos videos con 'todos somos técnicos'.
- UCL: del canal @pronosticosdeportivos.thonybet los 2 últimos con 'champions league'.

Cadena de fallback (P1.6):
  1. yt_dlp con URL /videos (modo rápido, sin descarga)  → modo normal
  2. yt_dlp con URL /videos + extrae_flat=False (más lento pero más metadata)
  3. Modo degradado explícito: estado marcado como 'degraded_no_videos'.
     El pipeline continúa con lista vacía y el Gate lo sabrá.

Salida en state:
  insights_sources = { 'CHI1': [url1, url2, url3], 'UCL': [urlA, urlB] }
  meta['insights_sources_counts']
  meta['insights_sources_status']    ← nuevo: 'ok' | 'degraded' | 'unavailable'
  meta['errors']['insights_sources']
"""

from __future__ import annotations

import logging
import time
from typing import Any, List, Dict, Optional

from state import AgentState

logger = logging.getLogger(__name__)

# ─── Constantes ───────────────────────────────────────────────────────────────
_YT_DLP_TIMEOUT_SECS = 30  # Timeout razonable para una petición de canal
_YT_DLP_RETRY_ATTEMPTS = 2  # Intentos antes de marcar degradado


def _fetch_channel_videos_attempt(channel_url: str, flat: bool = True) -> List[Dict[str, Any]]:
    """
    Intenta obtener la lista de videos de un canal con yt_dlp.
    
    Args:
        channel_url: URL del canal de YouTube (sin /videos al final).
        flat: Si True usa extract_flat=True (rápido). Si False va sin él (más metadata).
    
    Returns:
        Lista de dicts con campos 'id', 'title', 'url', 'upload_date', 'timestamp'.
        Devuelve [] si falla.
    """
    try:
        import yt_dlp
    except ImportError:
        logger.error("yt-dlp no está instalado. Instala con: pip install yt-dlp")
        return []

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "socket_timeout": _YT_DLP_TIMEOUT_SECS,
    }
    if flat:
        ydl_opts["extract_flat"] = True

    url = channel_url.rstrip("/") + "/videos"
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        entries = info.get("entries") or []
        out = []
        for e in entries:
            vid = e.get("id") or e.get("url") or ""
            if not vid:
                continue
            watch = f"https://www.youtube.com/watch?v={vid}" if "http" not in vid else vid
            out.append({
                "id": vid,
                "title": (e.get("title") or "").strip(),
                "url": watch,
                "upload_date": e.get("upload_date"),
                "timestamp": e.get("timestamp"),
            })
        return out
    except Exception as exc:
        logger.warning(f"yt-dlp fallo (flat={flat}) para {channel_url}: {exc!r}")
        return []


def _fetch_channel_videos_with_fallback(channel_url: str) -> tuple[List[Dict], str]:
    """
    Cadena de fallback con dos intentos para obtener videos de un canal.

    Returns:
        (videos, source_status) donde source_status puede ser:
          'yt_dlp_flat'   → éxito con modo rápido
          'yt_dlp_full'   → éxito con modo completo (fallback)
          'degraded'      → vacío pero el pipeline puede continuar
    """
    # Intento 1: modo rápido (extract_flat)
    videos = _fetch_channel_videos_attempt(channel_url, flat=True)
    if videos:
        return videos, "yt_dlp_flat"

    logger.warning(f"Intento 1 fallido para {channel_url}. Reintentando sin extract_flat...")
    time.sleep(1)  # Pequeña espera antes del reintento

    # Intento 2: modo completo (más lento pero extrae más metadata)
    videos = _fetch_channel_videos_attempt(channel_url, flat=False)
    if videos:
        return videos, "yt_dlp_full"

    logger.error(
        f"Ambos intentos fallaron para {channel_url}. "
        "El selector entra en modo degradado para esta competencia."
    )
    return [], "degraded"


def youtube_selector_node(state: AgentState) -> AgentState:
    """
    Nodo del YouTube Selector. Lee canales configurados por competencia,
    aplica filtros de título y devuelve URLs aptas para el Insights Agent.

    Con fallback P1.6: registra estado explícito de éxito/degradación.
    """
    logger.info("=" * 60)
    logger.info("YOUTUBE SELECTOR: building sources for insights")
    logger.info("=" * 60)

    state.setdefault("insights_sources", {})
    meta = state.setdefault("meta", {})
    meta.setdefault("errors", {}).setdefault("insights_sources", {})
    counts = meta.setdefault("insights_sources_counts", {})
    statuses = meta.setdefault("insights_sources_status", {})  # ← nuevo

    # Reglas de canales por competencia
    rules: Dict[str, Dict] = {
        "CHI1": {
            "channel": "https://www.youtube.com/@TNTSportsCL",
            "contains": ["todos somos técnicos"],
            "limit": 3,
        },
        "UCL": {
            "channel": "https://www.youtube.com/@pronosticosdeportivos.thonybet",
            "contains": ["champions league"],
            "limit": 2,
        },
    }

    for comp in state.get("competitions", []):
        label = comp.get("competition")
        rule = rules.get(label)
        if not rule:
            logger.debug(f"Sin regla de selector para competencia '{label}'. Saltando.")
            continue

        channel_url = rule["channel"]
        logger.info(f"  [{label}] Consultando canal: {channel_url}")

        vids, source_status = _fetch_channel_videos_with_fallback(channel_url)

        if not vids:
            # Modo degradado explícito: el pipeline continúa sin videos para esta liga.
            statuses[label] = "degraded"
            counts[label] = 0
            state["insights_sources"][label] = []
            meta["errors"]["insights_sources"][label] = (
                f"youtube_selector_degraded: no se pudo obtener videos de {channel_url}"
            )
            logger.warning(f"  [{label}] ⚠️  DEGRADED: sin videos disponibles. Pipeline continúa sin insights de YouTube.")
            continue

        # Filtro por título
        patterns = [p.lower() for p in rule["contains"]]
        filtered = [v for v in vids if any(p in (v.get("title", "")).lower() for p in patterns)]

        # Ordenar por fecha desc
        def _sort_key(v: Dict) -> tuple:
            return (v.get("upload_date") or "", v.get("timestamp") or 0)

        filtered.sort(key=_sort_key, reverse=True)
        selected = filtered[: rule["limit"]]
        urls = [v["url"] for v in selected]

        state["insights_sources"][label] = urls
        counts[label] = len(urls)
        statuses[label] = source_status

        logger.info(
            f"  [{label}] ✅  {len(urls)} video(s) seleccionados "
            f"(de {len(vids)} totales, {len(filtered)} coincidencias) "
            f"vía {source_status}"
        )
        for v in selected:
            logger.info(f"    · {v.get('title', '?')} — {v.get('url')}")

    # Resumen global
    total_ok = sum(1 for s in statuses.values() if s != "degraded")
    total_degraded = sum(1 for s in statuses.values() if s == "degraded")
    logger.info(
        f"YOUTUBE SELECTOR DONE: {total_ok} liga(s) OK, {total_degraded} degradada(s)"
    )

    return state
