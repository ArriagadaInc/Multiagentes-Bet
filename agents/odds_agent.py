"""
Agente #2: Odds Fetcher

Fetches real-time betting odds from The Odds API v4 for:
- UEFA Champions League
- Chilean Campeonato

Output is normalized to a canonical format that includes:
- Multiple bookmakers per event
- Match details
- Odds in decimal format

Author: Senior Python Developer
Date: 2024
"""

import os
import logging
from typing import Optional, Any
from datetime import datetime
from difflib import SequenceMatcher
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from state import AgentState
from utils.http import HTTPClient
from utils.cache import CacheManager
from utils.normalizer import slugify

logger = logging.getLogger(__name__)


class OddsFetcher:
    """
    Fetches and normalizes odds from The Odds API v4.
    
    Attributes:
        api_key (str): The Odds API key (from env var ODDS_API_KEY)
        base_url (str): API base URL (default: https://api.odds.to)
        timeout_seconds (int): Request timeout
        retries (int): Number of retry attempts
        cache (CacheManager): Disk cache manager
        http_client (HTTPClient): Resilient HTTP client
    """
    
    # Mapping: competition label -> API endpoint
    ENDPOINTS = {
        "UCL": "soccer_uefa_champs_league",
        "CHI1": "soccer_chile_campeonato"
    }
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        retries: Optional[int] = None,
        cache_ttl_seconds: Optional[int] = None
    ):
        """
        Initialize Odds Fetcher.
        
        Reads configuration from environment variables if not explicitly provided:
        - ODDS_API_KEY (mandatory): API authentication key
        - ODDS_BASE_URL (opt): API base URL
        - ODDS_TIMEOUT_SECONDS (opt): Request timeout (default 20)
        - ODDS_RETRIES (opt): Retry attempts (default 2)
        - ODDS_CACHE_TTL_SECONDS (opt): Cache TTL in seconds (default 600)
        
        Args:
            api_key: Override env var ODDS_API_KEY
            base_url: Override env var ODDS_BASE_URL
            timeout_seconds: Override env var ODDS_TIMEOUT_SECONDS
            retries: Override env var ODDS_RETRIES
            cache_ttl_seconds: Override env var ODDS_CACHE_TTL_SECONDS
        
        Raises:
            ValueError: If ODDS_API_KEY is not set and not provided
        """
        # Read API key
        self.api_key = api_key or os.getenv("ODDS_API_KEY")
        if not self.api_key:
            raise ValueError(
                "ODDS_API_KEY not set. "
                "Set env var or pass api_key= to constructor."
            )
        
        # Read configuration
        self.base_url = base_url or os.getenv(
            "ODDS_BASE_URL",
            "https://api.odds.to"
        )
        self.timeout_seconds = timeout_seconds or int(
            os.getenv("ODDS_TIMEOUT_SECONDS", "20")
        )
        self.retries = retries or int(
            os.getenv("ODDS_RETRIES", "2")
        )
        
        cache_ttl_seconds = cache_ttl_seconds or int(
            os.getenv("ODDS_CACHE_TTL_SECONDS", "600")
        )
        
        # Initialize clients
        self.cache = CacheManager(default_ttl_seconds=cache_ttl_seconds)
        self.http_client = HTTPClient(
            timeout_seconds=self.timeout_seconds,
            max_retries=self.retries
        )
        
        logger.info(
            f"OddsFetcher initialized: "
            f"base_url={self.base_url}, "
            f"timeout={self.timeout_seconds}s, "
            f"retries={self.retries}, "
            f"cache_ttl={cache_ttl_seconds}s"
        )
    
    def fetch_odds_for_competition(
        self,
        competition_label: str,
        regions: str = "eu",
        markets: str = "h2h"
    ) -> dict[str, Any]:
        """
        Fetch odds from The Odds API for a specific competition.
        
        API Endpoint (v4):
        GET /v4/sports/{sport_key}/odds?apiKey=...&regions=...&markets=...
        
        Query Parameters:
        - apiKey: API key for authentication
        - regions: Comma-separated region codes (e.g., "eu,uk,us")
        - markets: Comma-separated market types (e.g., "h2h" for 1X2 odds)
        
        Args:
            competition_label: Competition key (e.g., "UCL", "CHI1")
            regions: Region filter (default: "eu")
            markets: Market type filter (default: "h2h")
        
        Returns:
            Dict with structure:
            {
                "success": bool,
                "status_code": int (0 if no response),
                "error": str or None,
                "data": [...],  # list of odds events from API or None
                "cache_hit": bool
            }
        """
        endpoint_key = self.ENDPOINTS.get(competition_label)
        if not endpoint_key:
            return {
                "success": False,
                "status_code": 0,
                "error": f"Unknown competition: {competition_label}",
                "data": None,
                "cache_hit": False
            }
        
        logger.info(
            f"Fetching odds: competition={competition_label}, "
            f"endpoint={endpoint_key}, regions={regions}, markets={markets}"
        )
        
        # Try cache first
        cached = self.cache.load("odds", competition_label, markets)
        if cached is not None:
            logger.debug(f"Cache hit for odds_{competition_label}_{markets}")
            return {
                "success": True,
                "status_code": 200,
                "error": None,
                "data": cached,
                "cache_hit": True
            }
        
        # Build request
        url = f"{self.base_url}/v4/sports/{endpoint_key}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": regions,
            "markets": markets
        }
        
        # Make request
        data, status_code, error_msg = self.http_client.get(
            url,
            params=params,
            allow_retries=True
        )
        
        # Handle errors
        if data is None:
            logger.error(f"API error: {error_msg}")
            return {
                "success": False,
                "status_code": status_code,
                "error": error_msg,
                "data": None,
                "cache_hit": False
            }
        
        # Save to cache
        self.cache.save(data, "odds", competition_label, markets)
        
        return {
            "success": True,
            "status_code": 200,
            "error": None,
            "data": data,
            "cache_hit": False
        }
    
    def normalize_odds(
        self,
        raw_odds: list[dict],
        competition_label: str
    ) -> list[dict[str, Any]]:
        """
        Normalize raw The Odds API response to canonical odds format.
        
        Input (from The Odds API):
        {
            "id": "event_id",
            "sport_key": "soccer_uefa_champs_league",
            "sport_title": "UEFA Champs League",
            "commence_time": "2024-01-15T20:00:00Z",
            "home_team": "Real Madrid",
            "away_team": "AC Milan",
            "bookmakers": [
                {
                    "key": "bet365",
                    "title": "Bet365",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Real Madrid", "price": 2.50},
                                {"name": "Draw", "price": 3.20},
                                {"name": "AC Milan", "price": 1.90}
                            ]
                        }
                    ]
                },
                ...
            ]
        }
        
        Output (canonical):
        {
            "competition": "UCL",
            "provider": "the_odds_api",
            "event_id": "event_id",
            "sport_key": "soccer_uefa_champs_league",
            "commence_time": "2024-01-15T20:00:00Z",
            "home_team": "Real Madrid",
            "away_team": "AC Milan",
            "bookmakers_count": 50,
            "bookmakers": [
                {
                    "key": "bet365",
                    "title": "Bet365",
                    "home_odds": 2.50,
                    "draw_odds": 3.20,
                    "away_odds": 1.90
                },
                ...
            ]
        }
        
        Args:
            raw_odds: List of odds event dicts from API
            competition_label: Standardized label (e.g., "UCL", "CHI1")
        
        Returns:
            List of normalized odds dicts
        """
        normalized = []
        
        for event in raw_odds:
            try:
                # Extract bookmakers with h2h odds
                bookmakers_normalized = []
                for bm in event.get("bookmakers", []):
                    markets = bm.get("markets", [])
                    h2h_market = next(
                        (m for m in markets if m.get("key") == "h2h"),
                        None
                    )
                    
                    if not h2h_market:
                        continue
                    
                    outcomes = h2h_market.get("outcomes", [])
                    if len(outcomes) < 3:
                        continue
                    
                    for outcome in outcomes:
                        name = outcome.get("name")
                        price = outcome.get("price")
                        if name == event.get("home_team"):
                            home_outcome = outcome
                        elif name == event.get("away_team"):
                            away_outcome = outcome
                        elif name == "Draw":
                            draw_outcome = outcome
                            
                    # Validación: si no encontramos por nombre exacto, intentar fallback posicional solo si es seguro?
                    # No, mejor ser estrictos para evitar datos basura.
                    # Pero The Odds API a veces usa nombres ligeramente distintos? 
                    # En la misma respuesta de API, los names de outcomes suelen coincidir con home_team/away_team del evento.
                    # El script debug mostró coincidencia exacta: Name: 'Inter Milan' vs Event: 'Inter Milan'
                    
                    if not home_outcome or not away_outcome or not draw_outcome:
                         # Fallback leve si falla exact match (sanity check)
                         # Ojo: el script mostró coincidencia perfecta string a string.
                         continue

                    bm_norm = {
                        "key": bm.get("key", "unknown"),
                        "title": bm.get("title", "Unknown"),
                        "home_odds": home_outcome.get("price"),
                        "draw_odds": draw_outcome.get("price"),
                        "away_odds": away_outcome.get("price"),
                    }
                    bookmakers_normalized.append(bm_norm)
                
                # Create normalized event
                home_slug = slugify(event.get("home_team", "Unknown"))
                away_slug = slugify(event.get("away_team", "Unknown"))
                date_part = str(event.get("commence_time") or "nodate")[:10]
                match_key = f"{competition_label}:{date_part}:{home_slug}:{away_slug}"

                normalized_event = {
                    "competition": competition_label,
                    "provider": "the_odds_api",
                    "event_id": event.get("id", ""),
                    "match_key": match_key,
                    "sport_key": event.get("sport_key", ""),
                    "commence_time": event.get("commence_time", ""),
                    "home_team": event.get("home_team", "Unknown"),
                    "away_team": event.get("away_team", "Unknown"),
                    "bookmakers_count": len(bookmakers_normalized),
                    "bookmakers": bookmakers_normalized,
                }
                
                normalized.append(normalized_event)
            
            except Exception as e:
                logger.warning(f"Error normalizing odds event: {e}")
                continue
        
        logger.info(f"Normalized {len(normalized)} odds events for {competition_label}")
        return normalized
    
    def fuzzy_match_fixtures_to_odds(
        self,
        fixtures: list[dict],
        odds: list[dict],
        threshold: float = 0.8
    ) -> list[dict]:
        """
        Optionally match fixtures to odds events using fuzzy team name matching.
        
        This is useful for:
        - Enriching odds with fixture metadata (venue, matchday, etc.)
        - Validating that odds exist for scheduled fixtures
        
        OPTIONAL: Can be used in future enhanced analysis.
        Currently not required for MVP.
        
        Args:
            fixtures: List of normalized fixture dicts
            odds: List of normalized odds dicts
            threshold: Similarity threshold for fuzzy matching (0-1)
        
        Returns:
            List of matched pairs with both fixture and odds data
        """
        matches = []
        
        for fix in fixtures:
            fix_home = fix.get("home_team", "").lower()
            fix_away = fix.get("away_team", "").lower()
            fix_key = f"{fix_home} vs {fix_away}"
            
            for odd in odds:
                odd_home = odd.get("home_team", "").lower()
                odd_away = odd.get("away_team", "").lower()
                odd_key = f"{odd_home} vs {odd_away}"
                
                similarity = SequenceMatcher(None, fix_key, odd_key).ratio()
                
                if similarity >= threshold:
                    matches.append({
                        "fixture": fix,
                        "odds": odd,
                        "similarity": similarity
                    })
                    break
        
        logger.info(f"Matched {len(matches)} fixtures to odds events")
        return matches


def _parse_iso_utc(dt_str: str) -> Optional[datetime]:
    """
    Parse ISO8601 string potentially ending with 'Z' to timezone-aware datetime.
    Returns None if parsing fails.
    """
    try:
        if not dt_str:
            return None
        return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
    except Exception:
        return None


def _in_window(commence_iso: str, date_from: str, date_to: str) -> bool:
    """
    Check if commence_iso (ISO8601) is within [date_from, date_to] inclusive.
    date_from/date_to are YYYY-MM-DD strings assumed to be in UTC.
    """
    dt = _parse_iso_utc(commence_iso)
    if not dt:
        return False
    start = datetime.fromisoformat(f"{date_from}T00:00:00+00:00")
    end = datetime.fromisoformat(f"{date_to}T23:59:59+00:00")
    return start <= dt <= end


def odds_fetcher_node(state: AgentState) -> AgentState:
    """
    LangGraph node for fetching odds from The Odds API.
    
    This is the main entry point for Agente #2 within the multiagent pipeline.
    
    Process:
    1. Reads state["competitions"] - list of competitions to fetch
    2. For each competition:
       a. Try to fetch odds from API (or cache)
       b. If successful, normalize to canonical format
       c. If failed, record error in meta and continue
    3. Update state with:
       - state["odds_canonical"]: Combined normalized list
       - state["odds_raw"]: By-competition raw responses
       - state["meta"]: Execution stats and errors
       - state["messages"]: Audit trail
    
    Args:
        state: AgentState from LangGraph pipeline
    
    Returns:
        Updated AgentState with odds data populated
    """
    logger.info("=" * 60)
    logger.info("AGENTE #2: ODDS FETCHER (The Odds API)")
    logger.info("=" * 60)
    
    # Initialize odds fetcher
    try:
        fetcher = OddsFetcher()
    except ValueError as e:
        error_msg = f"Configuration error: {str(e)}"
        logger.error(error_msg)
        state["messages"].append(
            SystemMessage(content=f"Odds Fetcher Error: {error_msg}")
        )
        state["meta"]["errors"]["odds"] = {"init": error_msg}
        return state
    
    # Initialize containers
    state["odds_canonical"] = []
    state["odds_raw"] = {}
    state["meta"]["odds_counts"] = {}
    state["meta"]["errors"]["odds"] = {}
    state["meta"]["cache_hits"]["odds"] = 0
    
    start_time = datetime.now()
    
    # Date window (aligned with fixtures agent)
    date_from = state.get("fixtures_date_from")
    date_to = state.get("fixtures_date_to")
    if date_from and date_to:
        logger.info(f"Applying odds date filter: {date_from} to {date_to}")
    
    # Fetch for each competition
    for comp in state.get("competitions", []):
        comp_label = comp.get("competition", "?")
        
        logger.info(f"\n>>> Fetching odds for {comp_label}...")
        
        # Fetch odds
        result = fetcher.fetch_odds_for_competition(
            comp_label,
            regions=os.getenv("ODDS_REGIONS", "eu"),
            markets=os.getenv("ODDS_MARKETS", "h2h")
        )
        
        # Handle errors
        if not result["success"]:
            error_msg = result["error"] or "Unknown error"
            logger.error(f"Error fetching odds for {comp_label}: {error_msg}")
            state["meta"]["errors"]["odds"][comp_label] = error_msg
            state["meta"]["odds_counts"][comp_label] = 0
            continue
        
        # Track cache hit
        if result.get("cache_hit"):
            state["meta"]["cache_hits"]["odds"] += 1
        
        # Store raw response
        state["odds_raw"][comp_label] = result["data"]
        
        # Normalize odds
        raw_odds = result["data"] if isinstance(result["data"], list) else []
        normalized = fetcher.normalize_odds(raw_odds, comp_label)
        
        # Optional: filter by date window (today -> +7 days)
        if date_from and date_to:
            before = len(normalized)
            normalized = [
                e for e in normalized
                if _in_window(e.get("commence_time", ""), date_from, date_to)
            ]
            logger.info(
                f"Applied odds date filter: {before} -> {len(normalized)} events in window"
            )
        
        # Add to combined list
        state["odds_canonical"].extend(normalized)
        state["meta"]["odds_counts"][comp_label] = len(normalized)
        
        logger.info(f"✓ {comp_label}: {len(normalized)} odds events")
    
    # Update metadata
    state["meta"]["total_odds"] = len(state["odds_canonical"])
    
    # Add audit message
    audit_msg = (
        f"Fetched odds for competitions: {list(state['meta']['odds_counts'].keys())}. "
        f"Total: {state['meta']['total_odds']} odds events. "
        f"Cache hits: {state['meta']['cache_hits'].get('odds', 0)}"
    )
    state["messages"].append(HumanMessage(content=audit_msg))
    
    logger.info("\n" + "=" * 60)
    logger.info(f"ODDS AGENT COMPLETE: {state['meta']['total_odds']} odds events")
    logger.info("=" * 60)
    
    return state
