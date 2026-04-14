"""
Scraper directo de cuotas web (best effort).

Objetivo:
- Intentar encontrar una línea 1X2 real sin pasar por LLM.
- Útil sobre todo para CHI2, donde el mercado puede aparecer en agregadores
  antes o en lugar de APIs estructuradas.

Estrategia:
1. Buscar URLs candidatas con DDGS.
2. Priorizar dominios de odds/agregadores.
3. Descargar HTML y extraer texto visible.
4. Parsear patrones comunes de 1X2.

No pretende ser perfecto. Es una capa previa de resiliencia.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover
    BeautifulSoup = None  # type: ignore

try:
    from duckduckgo_search import DDGS
except Exception:  # pragma: no cover
    DDGS = None  # type: ignore


ODDS_DOMAINS = (
    "oddspedia.com",
    "oddsportal.com",
    "betarena.com",
    "fctables.com",
)


def _clean_text(text: str) -> str:
    t = (text or "").replace("\xa0", " ")
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _domain_rank(url: str) -> int:
    u = (url or "").lower()
    for idx, domain in enumerate(ODDS_DOMAINS):
        if domain in u:
            return len(ODDS_DOMAINS) - idx
    return 0


def _build_queries(home: str, away: str, competition: str) -> list[str]:
    base = [
        f'"{home}" "{away}" odds',
        f'"{home}" "{away}" 1x2 odds',
    ]
    if competition == "CHI2":
        base.extend([
            f'"{home}" "{away}" "Primera B" odds',
            f'"{home}" "{away}" site:oddspedia.com',
            f'"{home}" "{away}" site:oddsportal.com',
        ])
    return base


def _search_candidate_results(home: str, away: str, competition: str, max_results_per_query: int = 5) -> list[dict[str, Any]]:
    if DDGS is None:
        return []

    seen = set()
    out: list[dict[str, Any]] = []
    queries = _build_queries(home, away, competition)

    with DDGS() as ddgs:
        for query in queries:
            try:
                results = list(ddgs.text(query, max_results=max_results_per_query))
            except Exception as e:
                logger.debug("WEB ODDS SCRAPER: search failed for query %s: %s", query, e)
                continue

            for r in results:
                url = str(r.get("href") or r.get("url") or "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                out.append(
                    {
                        "title": str(r.get("title") or "").strip(),
                        "url": url,
                        "body": str(r.get("body") or "").strip(),
                        "rank": _domain_rank(url),
                    }
                )

    out.sort(key=lambda x: x.get("rank", 0), reverse=True)
    return out


def _fetch_page_text(url: str, timeout: int = 12) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    html = resp.text
    if BeautifulSoup is None:
        return _clean_text(html)

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.extract()
    return _clean_text(soup.get_text(" ", strip=True))


def _extract_triplet_from_text(text: str) -> Optional[tuple[float, float, float]]:
    """
    Busca patrones razonables de 1X2 en texto visible.
    """
    if not text:
        return None

    tx = text.replace(",", ".")

    # Caso más fiable: 1 / X / 2 etiquetado.
    pat = re.search(
        r"(?:^|[\s|,;])1\s*[:=]?\s*(\d+(?:\.\d+)?)"
        r".{0,50}?"
        r"(?:X|Empate|Draw)\s*[:=]?\s*(\d+(?:\.\d+)?)"
        r".{0,50}?"
        r"(?:2)\s*[:=]?\s*(\d+(?:\.\d+)?)",
        tx,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if pat:
        try:
            return float(pat.group(1)), float(pat.group(2)), float(pat.group(3))
        except Exception:
            pass

    # Fallback: bloque cerca de "1x2" o "full time result".
    for marker in ["1x2", "full time result", "match result", "h2h"]:
        idx = tx.lower().find(marker)
        if idx >= 0:
            window = tx[idx : idx + 400]
            nums = re.findall(r"(\d+(?:\.\d{1,2}))", window)
            vals = []
            for n in nums:
                try:
                    v = float(n)
                except Exception:
                    continue
                if 1.05 < v < 20.0:
                    vals.append(v)
            if len(vals) >= 3:
                return vals[0], vals[1], vals[2]

    return None


def _valid_overround(h: float, d: float, a: float) -> bool:
    try:
        overround = (1 / h) + (1 / d) + (1 / a)
    except Exception:
        return False
    return 1.0 < overround < 1.40


def fetch_direct_web_odds(home: str, away: str, competition: str) -> Optional[dict[str, Any]]:
    """
    Intenta obtener una línea 1X2 directa desde páginas web públicas.
    """
    candidates = _search_candidate_results(home, away, competition)
    if not candidates:
        logger.info("WEB ODDS SCRAPER: sin resultados de búsqueda para %s vs %s", home, away)
        return None

    # Probar pocos candidatos para mantener el costo/latencia bajo.
    for cand in candidates[:6]:
        url = cand.get("url") or ""
        body = cand.get("body") or ""

        # 1. Intentar extraer desde snippet del buscador.
        triplet = _extract_triplet_from_text(body)
        if triplet and _valid_overround(*triplet):
            h, d, a = triplet
            logger.info("WEB ODDS SCRAPER: cuotas detectadas desde snippet (%s)", url)
            return {
                "home": h,
                "draw": d,
                "away": a,
                "source_url": url,
                "odds_source_type": "web_search_snippet",
                "odds_source_name": "direct_web_odds_scraper",
                "captured_at": None,
                "extraction_method": "ddgs_snippet_parse",
                "extraction_confidence": 0.65,
                "market_data_quality": "low",
            }

        # 2. Intentar extraer desde HTML real.
        try:
            page_text = _fetch_page_text(url)
        except Exception as e:
            logger.debug("WEB ODDS SCRAPER: fetch failed for %s: %s", url, e)
            continue

        triplet = _extract_triplet_from_text(page_text)
        if triplet and _valid_overround(*triplet):
            h, d, a = triplet
            logger.info("WEB ODDS SCRAPER: cuotas detectadas desde HTML (%s)", url)
            return {
                "home": h,
                "draw": d,
                "away": a,
                "source_url": url,
                "odds_source_type": "web_scraped_direct",
                "odds_source_name": "direct_web_odds_scraper",
                "captured_at": None,
                "extraction_method": "direct_html_parse",
                "extraction_confidence": 0.72,
                "market_data_quality": "low",
            }

    logger.info("WEB ODDS SCRAPER: sin cuotas parseables para %s vs %s", home, away)
    return None

