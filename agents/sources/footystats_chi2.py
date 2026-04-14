"""
FootyStats CHI2 Scraper
=======================
Scraper HTML estático para obtener fixtures de la Primera B de Chile (CHI2)
desde https://footystats.org/chile/primera-b/fixtures

Usa BeautifulSoup para extraer datos directamente de los <a> tags, evitando
el ruido del texto plano.

Retorna lista compatible con state["fixtures"]:
    [{
        "fixture_id": "web_CHI2_...",
        "competition": "CHI2",
        "provider": "footystats",
        "utc_date": "2026-03-27T21:00:00Z",
        "status": "NS",
        "home_team": "...",
        "away_team": "...",
        "season": 2026,
        "source_url": "https://footystats.org/chile/primera-b/fixtures",
        "captured_at": "...",
        "extraction_method": "html_scrape_bs4",
        "source_name": "footystats"
    }]
"""

from __future__ import annotations

import logging
import re
import os
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)

FOOTYSTATS_FIXTURES_URL = "https://footystats.org/chile/primera-b" # Homepage es más real que /fixtures
SOURCE_NAME = "footystats"
COMPETITION = "CHI2"

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_DAY_ABBR = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


def _parse_footystats_datetime(day_str: str, time_str: str) -> str | None:
    """Convierte "Fri 27" y "6:00pm" a ISO."""
    now = datetime.now(timezone.utc)
    try:
        # Extraer día
        day_m = re.search(r"(\d{1,2})", day_str)
        if not day_m: return None
        day_num = int(day_m.group(1))

        # Heurística de mes: hoy es Mar 26. Fri 27 es Mar 27. Tue 1 es Apr 1.
        # Si el día es mayor o igual a hoy - 1, asumimos mes actual. 
        # Si el día es mucho menor (ej: 1 vs 26), es el mes siguiente.
        if day_num >= now.day - 1:
            ref_month = now.month
            ref_year = now.year
        else:
            ref_month = now.month + 1 if now.month < 12 else 1
            ref_year = now.year if ref_month > 1 else now.year + 1
        
        # Validar mes (si es Feb y pedimos 30, saltar a Mar)
        try:
            candidate = datetime(ref_year, ref_month, day_num, tzinfo=timezone.utc)
        except ValueError:
            ref_month = ref_month + 1 if ref_month < 12 else 1
            ref_year = ref_year if ref_month > 1 else now.year + 1
            candidate = datetime(ref_year, ref_month, day_num, tzinfo=timezone.utc)

        # Parsear hora
        h_m = re.match(r"(\d{1,2}):(\d{2})(am|pm)", time_str.lower().strip())
        hour, minute = (int(h_m.group(1)), int(h_m.group(2))) if h_m else (0, 0)
        if h_m and h_m.group(3) == "pm" and hour != 12: hour += 12
        if h_m and h_m.group(3) == "am" and hour == 12: hour = 0

        return candidate.replace(hour=hour, minute=minute).strftime("%Y-%m-%dT%H:%M:%SZ")
    except: return None


def _clean_team_name(href: str) -> str:
    """Extrae el nombre limpio desde el slug del URL de FootyStats."""
    # href ej: "/clubs/deportes-recoleta-2207" o "deportes-recoleta"
    slug = href.split("/")[-1]
    # Remover ID numérico final: "-2207"
    slug = re.sub(r"-\d+$", "", slug)
    # Reemplazar guiones por espacios y capitalizar
    name = slug.replace("-", " ").title()
    # Limpiar prefijos comunes
    name = re.sub(r"^(Cd|Csd|Club|Deportes|Santiago|Universidad De|Provincial|Uni[óo]n)\s+", "", name, flags=re.IGNORECASE).strip()
    # Mapeos específicos
    mapp = {
        "Union San Felipe": "Unión San Felipe",
        "Union Espanola": "Unión Española",
        "Curico Unido": "Curicó Unido",
        "Concepcion": "Concepción",
        "Magallanes": "Magallanes",
        "Iquique": "Deportes Iquique",
        "Temuco": "Deportes Temuco",
        "San Marcos De Arica": "San Marcos de Arica"
    }
    return mapp.get(name, name)


def fetch_footystats_fixtures(
    url: str = FOOTYSTATS_FIXTURES_URL,
    max_days_ahead: int = 14,
) -> list[dict[str, Any]]:
    """
    Scrape HTML de FootyStats para obtener fixtures futuros de CHI2.

    Returns:
        Lista de fixtures en el formato canónico del pipeline.
    """
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError as e:
        logger.error(f"FootyStats scraper: falta dependencia → {e}")
        return []

    captured_at = datetime.now(timezone.utc).isoformat()
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(days=max_days_ahead)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=12)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        logger.info(f"FootyStats CHI2: Scrapeando {url}")
    except Exception as e:
        logger.error(f"Error HTTP FootyStats: {e}"); return []

    fixtures = []
    seen = set()
    now_utc = datetime.now(timezone.utc)

    # Buscar el widget de Fixtures por texto
    # FootyStats suele envolver estos bloques en <li> o <div class="match-item">
    # Buscamos todos los links de Stats que son los que definen las filas del widget
    h2h_pattern = re.compile(r"/chile/.*-vs-.*-h2h-stats")
    stats_links = soup.find_all("a", href=h2h_pattern)

    for link in stats_links:
        # En el widget del home, la estructura suele ser:
        # [Day Time] [Home] [Score/Stats] [Away]
        parent = link.find_parent(["li", "tr", "div", "ul"])
        if not parent: continue
        
        row_text = parent.get_text(" ", strip=True)
        # Regex para capturar: "Fri 27, 6:00pm"
        dt_m = re.search(r"([A-Z][a-z]{2}\s+\d{1,2}),?\s+(\d{1,2}:\d{2}(?:am|pm))", row_text)
        if not dt_m: continue
        date_raw, time_raw = dt_m.group(1), dt_m.group(2)
        
        # Equipos: Buscamos links de clubes únicamente DENTRO del contenedor de la fila
        row_clubs = []
        seen_hrefs = set()
        for a in parent.find_all("a", href=re.compile(r"/clubs/")):
            h = a["href"]
            if h not in seen_hrefs:
                row_clubs.append(a)
                seen_hrefs.add(h)
        
        if len(row_clubs) >= 2:
            home_tx = _clean_team_name(row_clubs[0]["href"])
            away_tx = _clean_team_name(row_clubs[1]["href"])
        else:
            # Fallback al slug del URL si no hay links claros en la fila
            h2h_m = re.search(r"/chile/(.*)-vs-(.*)-h2h-stats", link["href"])
            if h2h_m:
                home_tx = _clean_team_name(h2h_m.group(1))
                away_tx = _clean_team_name(h2h_m.group(2))
            else: continue
        
        # Limpieza final de nombres
        home_tx = re.sub(r"^(Cd|Csd|Club|Deportes)\s+", "", home_tx, flags=re.IGNORECASE).strip()
        away_tx = re.sub(r"^(Cd|Csd|Club|Deportes)\s+", "", away_tx, flags=re.IGNORECASE).strip()
        # Mapeos especiales de normalización rápida
        for old, new in [("Uni N", "Unión"), ("Uniã³N", "Unión"), ("Concepci N", "Concepción"), ("Espanola", "Española"), ("Uni N", "Unión")]:
            home_tx = home_tx.replace(old, new)
            away_tx = away_tx.replace(old, new)
        
        # FILTRO DE LIGA (v12.9.3): Evitar capturar partidos de Copa Chile entre CHI1 y CHI2
        # Solo permitimos partidos si al menos uno de los equipos es claramente de CHI2
        # (Opcional: cargar el golden mapping para ser estrictos)
        chi2_canonical_teams = {
            "recoleta", "temuco", "magallanes", "rangers", "la serena", "limache", "curico unido", 
            "san marcos de arica", "antofagasta", "santiago morning", "universidad de concepcion", 
            "santa cruz", "barnechea", "san luis de quillota", "union san felipe", "santiago wanderers"
        }
        
        from utils.normalizer import slugify
        if slugify(home_tx) not in chi2_canonical_teams and slugify(away_tx) not in chi2_canonical_teams:
            logger.debug(f"FootyStats CHI2: Saltando partido no-CHI2: {home_tx} vs {away_tx}")
            continue

        iso_date = _parse_footystats_datetime(date_raw, time_raw)
        if not iso_date: continue
        
        # Filtro de seguridad: no partidos pasados (salvo muy recientes)
        match_dt = datetime.strptime(iso_date, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if match_dt < now_utc - timedelta(hours=3): continue

        key = f"{iso_date}|{home_tx}|{away_tx}"
        if key in seen: continue
        seen.add(key)

        fixtures.append({
            "fixture_id": f"web_CHI2_{re.sub(r'[^a-z0-9]', '_', home_tx.lower())}_{re.sub(r'[^a-z0-9]', '_', away_tx.lower())}",
            "competition": COMPETITION,
            "provider": SOURCE_NAME,
            "utc_date": iso_date,
            "status": "NS",
            "home_team": home_tx,
            "away_team": away_tx,
            "season": now_utc.year,
            "source_url": url,
            "captured_at": now_utc.isoformat(),
            "extraction_method": "html_scrape_bs4_homepage",
            "source_name": SOURCE_NAME,
        })

    fixtures.sort(key=lambda x: x["utc_date"])

    if fixtures:
        logger.info(f"FootyStats CHI2: {len(fixtures)} fixture(s) extraídos")
        for f in fixtures:
            logger.info(f"  → {f['utc_date']} | {f['home_team']} vs {f['away_team']}")
    else:
        logger.warning("FootyStats CHI2: 0 fixtures encontrados. Revisar selectores HTML.")

    return fixtures


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    results = fetch_footystats_fixtures()
    print(f"\n{'='*60}")
    print(f"Fixtures CHI2 extraídos: {len(results)}")
    print(json.dumps(results, indent=2, ensure_ascii=False))
