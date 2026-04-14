"""
PrimeraBChile CHI2 Scraper
==========================
Extrae señales editoriales de la Primera B de Chile desde primerabchile.cl

Fuentes usadas:
    - /primera-b-chile/  → noticias de categoría (señales más relevantes)
    - /videos-primera-b-tv/  → videos (si está disponible)

Retorna lista de señales:
    [{
        "title": "Rangers lamenta un nuevo golpe: delantero habría sufrido delicada lesión",
        "url": "https://primerabchile.cl/...",
        "published_at": "2026-03-26",
        "teams": ["Rangers"],
        "signal_type": "lesion",
        "snippet": "...",
        "source_name": "primerabchile",
        "captured_at": "2026-03-26T..."
    }]
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

PRIMERAB_BASE = "https://primerabchile.cl"
PRIMERAB_CATEGORY_URL = PRIMERAB_BASE  # La homepage tiene todos los artículos recientes
SOURCE_NAME = "primerabchile"

# Palabras clave para clasificar señales automáticamente
_SIGNAL_KEYWORDS: list[tuple[str, str]] = [
    # (tipo_señal, palabras_clave)
    ("lesion",      r"lesi[oó]n|lesionado|baja|baj[aó]|dudoso|parte m[eé]dico|m[eé]dico"),
    ("sancion",     r"sanci[oó]n|suspendido|expulsado|tarjeta|castigo|informe|fallo"),
    ("tecnico",     r"\bdt\b|t[eé]cnico|entrenador|director t[eé]cnico|ponce|partida del dt"),
    ("fichaje",     r"fichaje|refuerzo|contrato|llega|arriba|incorpora|firma|mercado"),
    ("crisis",      r"crisis|descenso|preocupa|peligra|derrota|caos|problema"),
    ("programacion", r"programaci[oó]n|horario|tv|canal|tnt|chilevisi[oó]n|transmite"),
    ("ambiente",    r"ambiente|barrista|hincha|afici[oó]n|estadio|localía"),
]

# Equipos de CHI2 conocidos (2026) — para detección rápida
_CHI2_TEAMS = [
    "Cobreloa", "Unión Española", "Deportes Antofagasta", "Antofagasta", "Deportes Iquique", "Iquique",
    "Curicó Unido", "Magallanes", "Rangers", "Rangers de Talca", "Santiago Wanderers",
    "San Marcos de Arica", "San Marcos", "San Luis de Quillota", "San Luis", "Puerto Montt", 
    "Deportes Recoleta", "Recoleta", "Deportes Temuco", "Temuco", "Unión San Felipe", 
    "Deportes Copiapó", "Copiapó", "Deportes Santa Cruz", "Deportes Melipilla",
    "Santiago Morning", "A.C. Barnechea", "Barnechea", "Limache", "Deportes Limache",
    "Universidad de Concepción", "U. de Concepción", "U Conce", "U de Conce"
]
_CHI2_TEAM_PATTERN = re.compile(
    "|".join(re.escape(t) for t in _CHI2_TEAMS),
    re.IGNORECASE,
)


def _classify_signal(text: str) -> str:
    """Clasifica el tipo de señal basándose en palabras clave del título/snippet."""
    text_lower = text.lower()
    for signal_type, pattern in _SIGNAL_KEYWORDS:
        if re.search(pattern, text_lower):
            return signal_type
    return "otro"


def _extract_teams_mentioned(text: str) -> list[str]:
    """Detecta equipos CHI2 mencionados en el texto."""
    found = _CHI2_TEAM_PATTERN.findall(text)
    # Normalizar y deduplicar
    seen: set[str] = set()
    result = []
    for t in found:
        norm = t.strip().title()
        if norm not in seen:
            seen.add(norm)
            result.append(norm)
    return result


def fetch_primerabchile_signals(
    max_articles: int = 15,
) -> list[dict[str, Any]]:
    """
    Scrape de primerabchile.cl para obtener señales editoriales CHI2.

    Returns:
        Lista de señales con provenance completo.
    """
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError as e:
        logger.error(f"PrimeraBChile scraper: falta dependencia → {e}")
        return []

    captured_at = datetime.now(timezone.utc).isoformat()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "es-CL,es;q=0.9",
    }

    signals: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    urls_to_scrape = [PRIMERAB_CATEGORY_URL]

    for page_url in urls_to_scrape:
        try:
            resp = requests.get(page_url, headers=headers, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            logger.info(f"PrimeraBChile: descargados {len(resp.text):,} bytes desde {page_url}")
        except Exception as e:
            logger.error(f"PrimeraBChile: error HTTP en {page_url} → {e}")
            continue

        # Buscar artículos por encabezados (h2, h3) con links a artículos noticiosos reales
        # En primerabchile.cl los artículos están dentro de <h2 class="...">
        # Usamos h2>a y h3>a para obtener los títulos con sus링 URLs
        article_headings = soup.find_all(["h2", "h3"])
        article_links = []
        for heading in article_headings:
            a = heading.find("a", href=re.compile(r"^https?://primerabchile\.cl/"))
            if a:
                article_links.append(a)

        for link in article_links:
            url = link.get("href", "").strip()
            if not url or url in seen_urls:
                continue
            # Excluir páginas de sección, autor, tags, estadísticas, etc.
            skip_patterns = [
                "/author/", "/tag/", "/categoria/", "/page/",
                "/polideportivo/", "/tercer-tiempo/", "/estadisticas",
                "/tabla-de-posiciones", "/apuestas", "/videos-primera-b",
                "/primera-b-chile/$",  # la categoría raíz misma
                "primerabchile.cl/2022/", "primerabchile.cl/2023/",
                "primerabchile.cl/2024/", "primerabchile.cl/2025/",
            ]
            if any(p in url for p in skip_patterns):
                continue
            # Solo aceptar artículos (URLs con slug descriptivo, no solo section)
            slug = url.rstrip("/").split("/")[-1]
            if not slug or len(slug) < 10:
                continue
            seen_urls.add(url)

            # Obtener texto del link (título del artículo)
            title = link.get_text(" ", strip=True)
            if not title or len(title) < 10:
                # Intentar subir en el DOM para encontrar título
                parent = link.find_parent(["h2", "h3", "article"])
                if parent:
                    title = parent.get_text(" ", strip=True)[:200]

            if not title or len(title) < 10:
                continue

            # Snippet: texto extra del card si existe
            card = link.find_parent("article") or link.find_parent("div")
            snippet = ""
            if card:
                p = card.find("p")
                if p:
                    snippet = p.get_text(" ", strip=True)[:300]

            # Clasificar señal
            full_text = f"{title} {snippet}"
            signal_type = _classify_signal(full_text)
            teams = _extract_teams_mentioned(full_text)

            # Fecha: buscar en elemento time o meta cerca del artículo
            published_at = None
            time_tag = card.find("time") if card else None
            if time_tag:
                dt_attr = time_tag.get("datetime", "")
                if dt_attr:
                    published_at = dt_attr[:10]  # YYYY-MM-DD

            signals.append({
                "title": title[:200],
                "url": url,
                "published_at": published_at or captured_at[:10],
                "teams": teams,
                "signal_type": signal_type,
                "snippet": snippet,
                "source_name": SOURCE_NAME,
                "captured_at": captured_at,
                "source_url": page_url,
            })

            if len(signals) >= max_articles:
                break

    if signals:
        logger.info(f"PrimeraBChile: {len(signals)} señal(es) extraídas")
        for s in signals[:5]:
            logger.info(f"  [{s['signal_type']}] {s['title'][:60]}...")
    else:
        logger.warning("PrimeraBChile: 0 señales encontradas. Revisar selectores HTML.")

    return signals


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    results = fetch_primerabchile_signals()
    print(f"\n{'='*60}")
    print(f"Señales CHI2 extraídas: {len(results)}")
    print(json.dumps(results, indent=2, ensure_ascii=False))
