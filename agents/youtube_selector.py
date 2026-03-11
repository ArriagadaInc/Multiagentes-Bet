"""
YouTube Selector Agent

Obtiene listas de videos desde canales de YouTube usando yt_dlp y coloca
en el estado los URLs a analizar por el Agente #3.

Reglas actuales:
- CHI1: del canal https://www.youtube.com/@TNTSportsCL los 3 últimos
  videos cuyo título contenga 'todos somos técnicos' (case-insensitive).
- UCL: del canal https://www.youtube.com/@pronosticosdeportivos.thonybet
  los 2 últimos videos cuyo título contenga 'CHAMPIONS LEAGUE'.

Salida en state:
  insights_sources = { 'CHI1': [url1, url2, url3], 'UCL': [urlA, urlB] }
  meta['insights_sources_counts']
  meta['errors']['insights_sources']
"""

from __future__ import annotations

import logging
from typing import Any, List, Dict

from state import AgentState

logger = logging.getLogger(__name__)


def _fetch_channel_videos(channel_url: str) -> List[Dict[str, Any]]:
    try:
        import yt_dlp
    except ImportError:
        logger.error("yt-dlp not installed; youtube selector cannot run")
        return []

    # extraer lista de videos en plano (sin descargar)
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
    }
    url = channel_url.rstrip('/') + "/videos"
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        entries = info.get('entries') or []
        out = []
        for e in entries:
            vid = e.get('id') or e.get('url')
            if not vid:
                continue
            watch = f"https://www.youtube.com/watch?v={vid}" if 'http' not in vid else vid
            out.append({
                'id': vid,
                'title': (e.get('title') or '').strip(),
                'url': watch,
                'upload_date': e.get('upload_date'),
                'timestamp': e.get('timestamp'),
            })
        return out
    except Exception as e:
        logger.error(f"yt-dlp extraction error for {channel_url}: {e}")
        return []


def youtube_selector_node(state: AgentState) -> AgentState:
    logger.info("=" * 60)
    logger.info("YOUTUBE SELECTOR: building sources for insights")
    logger.info("=" * 60)

    state.setdefault('insights_sources', {})
    state['meta'].setdefault('errors', {}).setdefault('insights_sources', {})
    counts = state['meta'].setdefault('insights_sources_counts', {})

    # Config canales y filtros
    rules = {
        'CHI1': {
            'channel': 'https://www.youtube.com/@TNTSportsCL',
            'contains': ['todos somos técnicos'],
            'limit': 3
        },
        'UCL': {
            'channel': 'https://www.youtube.com/@pronosticosdeportivos.thonybet',
            'contains': ['champions league'],
            'limit': 2
        }
    }

    for comp in state.get('competitions', []):
        label = comp.get('competition')
        rule = rules.get(label)
        if not rule:
            continue
        vids = _fetch_channel_videos(rule['channel'])
        if not vids:
            state['meta']['errors']['insights_sources'][label] = 'no videos found or yt-dlp missing'
            counts[label] = 0
            continue
        # filtro por título
        patterns = [s.lower() for s in rule['contains']]
        filtered = [v for v in vids if any(p in (v.get('title','').lower()) for p in patterns)]
        # ordenar por upload_date o timestamp desc
        def _key(v):
            ts = v.get('timestamp') or 0
            ud = v.get('upload_date') or ''
            # usar (ud,ts) para priorizar fecha
            return (ud, ts)
        filtered.sort(key=_key, reverse=True)
        selected = filtered[: rule['limit']]
        urls = [v['url'] for v in selected]
        state['insights_sources'][label] = urls
        counts[label] = len(urls)
        logger.info(f"Selected {len(urls)} videos for {label}")

    return state
