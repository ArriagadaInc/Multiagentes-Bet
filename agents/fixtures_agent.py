"""
Agente #1: Fixtures Fetcher

Fetches upcoming fixtures/matches from football-data.org API v4 for:
- UEFA Champions League (competition code: CL)
- Chilean Primera División (if available, or gracefully handles no coverage)

Output is normalized to a canonical format for downstream consumption by
Agente #2 (Odds Fetcher) and Agente #3 (Analyst).

Author: Senior Python Developer
Date: 2024
"""

import os
import logging
from typing import Optional, Any
from datetime import datetime, timedelta
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from state import AgentState
from utils.http import HTTPClient
from utils.cache import CacheManager

logger = logging.getLogger(__name__)


class FixturesFetcher:
    """
    Fetches and normalizes fixtures from football-data.org API v4.
    
    Attributes:
        api_key (str): Football Data API key (from env var FOOTBALL_DATA_API_KEY)
        base_url (str): API base URL (default: https://api.football-data.org)
        timeout_seconds (int): Request timeout
        retries (int): Number of retry attempts
        cache (CacheManager): Disk cache manager
        http_client (HTTPClient): Resilient HTTP client
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        retries: Optional[int] = None,
        cache_ttl_seconds: Optional[int] = None
    ):
        """
        Initialize Fixtures Fetcher.
        
        Reads configuration from environment variables if not explicitly provided:
        - FOOTBALL_DATA_API_KEY (mandatory): API authentication token
        - FOOTBALL_DATA_BASE_URL (opt): API base URL
        - FIXTURES_TIMEOUT_SECONDS (opt): Request timeout (default 20)
        - FIXTURES_RETRIES (opt): Retry attempts (default 2)
        - FIXTURES_CACHE_TTL_SECONDS (opt): Cache TTL in seconds (default 900)
        
        Args:
            api_key: Override env var FOOTBALL_DATA_API_KEY
            base_url: Override env var FOOTBALL_DATA_BASE_URL
            timeout_seconds: Override env var FIXTURES_TIMEOUT_SECONDS
            retries: Override env var FIXTURES_RETRIES
            cache_ttl_seconds: Override env var FIXTURES_CACHE_TTL_SECONDS
        
        Raises:
            ValueError: If FOOTBALL_DATA_API_KEY is not set and not provided
        """
        # Read API key
        self.api_key = api_key or os.getenv("FOOTBALL_DATA_API_KEY")
        if not self.api_key:
            raise ValueError(
                "FOOTBALL_DATA_API_KEY not set. "
                "Set env var or pass api_key= to constructor."
            )
        
        # Read configuration
        self.base_url = base_url or os.getenv(
            "FOOTBALL_DATA_BASE_URL", 
            "https://api.football-data.org"
        )
        self.timeout_seconds = timeout_seconds or int(
            os.getenv("FIXTURES_TIMEOUT_SECONDS", "20")
        )
        self.retries = retries or int(
            os.getenv("FIXTURES_RETRIES", "2")
        )
        cache_ttl_seconds = cache_ttl_seconds or int(
            os.getenv("FIXTURES_CACHE_TTL_SECONDS", "900")
        )
        
        # Initialize clients
        self.cache = CacheManager(default_ttl_seconds=cache_ttl_seconds)
        self.http_client = HTTPClient(
            timeout_seconds=self.timeout_seconds,
            max_retries=self.retries
        )
        # API-FOOTBALL config (optional, used for CHI1 when configured)
        self.api_football_base_url = os.getenv(
            "APIFOOTBALL_BASE_URL", "https://v3.football.api-sports.io"
        )
        self.api_football_key = os.getenv("APIFOOTBALL_API_KEY")
        
        logger.info(
            f"FixturesFetcher initialized: "
            f"base_url={self.base_url}, "
            f"timeout={self.timeout_seconds}s, "
            f"retries={self.retries}, "
            f"cache_ttl={cache_ttl_seconds}s"
        )
    
    def fetch_matches_for_competition(
        self,
        competition_code: str,
        status: str = "SCHEDULED",
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> dict[str, Any]:
        """
        Fetch matches from football-data API for a specific competition.
        
        Implements:
        1. Cache lookup (return if valid)
        2. API call with proper headers and query parameters
        3. Error handling and categorization
        4. Cache save for successful responses
        
        API Endpoint (v4):
        GET /v4/competitions/{competition_code}/matches?status=SCHEDULED&...
        
        Headers:
        - X-Auth-Token: <api_key> [Required]
        
        Query Parameters:
        - status: Match status filter (SCHEDULED, TIMED, LIVE, IN_PLAY, PAUSED, FINISHED, POSTPONED)
        - dateFrom: ISO 8601 date (YYYY-MM-DD) - optional
        - dateTo: ISO 8601 date (YYYY-MM-DD) - optional
        
        Args:
            competition_code: Football-data competition code (e.g., "CL", "SA", "PL")
            status: Match status filter (default: "SCHEDULED" - not yet played)
            date_from: Start date in ISO format (YYYY-MM-DD), optional
            date_to: End date in ISO format (YYYY-MM-DD), optional
        
        Returns:
            Dict with structure:
            {
                "success": bool,
                "status_code": int (0 if no response),
                "error": str or None,
                "data": {
                    "matches": [...],  # list of match objects from API
                    "competition": dict,
                    "count": int
                } or None,
                "cache_hit": bool
            }
        
        Example:
            >>> fetcher = FixturesFetcher()
            >>> result = fetcher.fetch_matches_for_competition("CL", status="SCHEDULED")
            >>> if result["success"]:
            ...     print(f"Got {result['data']['count']} matches")
        """
        logger.info(
            f"Fetching matches: competition={competition_code}, "
            f"status={status}, date_from={date_from}, date_to={date_to}"
        )
        
        # Try cache first
        cached = self.cache.load("fixtures", competition_code, status)
        if cached is not None:
            logger.debug(f"Cache hit for fixtures_{competition_code}_{status}")
            return {
                "success": True,
                "status_code": 200,
                "error": None,
                "data": cached,
                "cache_hit": True
            }
        
        # Build request
        url = f"{self.base_url}/v4/competitions/{competition_code}/matches"
        headers = {
            "X-Auth-Token": self.api_key,
            "Accept": "application/json"
        }
        params = {"status": status}
        
        if date_from:
            params["dateFrom"] = date_from
        if date_to:
            params["dateTo"] = date_to
        
        # Make request with retry logic
        data, status_code, error_msg = self.http_client.get(
            url, 
            headers=headers, 
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
        self.cache.save(data, "fixtures", competition_code, status)
        
        return {
            "success": True,
            "status_code": 200,
            "error": None,
            "data": data,
            "cache_hit": False
        }

    # ========================= API-FOOTBALL (CHI1) ========================= #
    def _api_football_get_league_and_season(
        self,
        country: str = "Chile",
        search: str = "Primera"
    ) -> dict[str, Any]:
        """
        Resolve Chilean Primera División league id and current season via API-FOOTBALL.

        Endpoint:
            GET {APIFOOTBALL_BASE_URL}/leagues?country=Chile&type=league&search=Primera

        Auth:
            Header "x-apisports-key: <APIFOOTBALL_API_KEY>"

        Returns:
            {"success": bool, "error": str|None, "league_id": int|None, "season": int|None}
        """
        if not self.api_football_key:
            return {"success": False, "error": "APIFOOTBALL_API_KEY not set", "league_id": None, "season": None}

        url = f"{self.api_football_base_url}/leagues"
        headers = {"x-apisports-key": self.api_football_key}
        # Fetch all leagues for country to robustly match top division name variants
        params = {"country": country, "type": "league"}

        data, status, err = self.http_client.get(url, headers=headers, params=params, allow_retries=True)
        if data is None or status != 200:
            return {"success": False, "error": err or f"HTTP {status}", "league_id": None, "season": None}

        resp = data.get("response", []) if isinstance(data, dict) else []
        # Heuristic: prefer top-tier names, avoid "Primera B"
        preferred_substrings = ["campeonato nacional", "primera division", "primera división", "primera" ]
        exclude_substrings = ["primera b", "segunda", "copa", "supercopa"]

        league_id = None
        season = None
        best_score = -1
        best_item = None
        for item in resp:
            lg = item.get("league", {})
            ctry = item.get("country", {})
            if ctry.get("name", "").lower() != country.lower():
                continue
            name = (lg.get("name") or "").lower()
            if any(x in name for x in exclude_substrings):
                continue
            score = 0
            for sub in preferred_substrings:
                if sub in name:
                    score += 1
            # small bonus for explicit "primera division"
            if "primera division" in name or "primera división" in name:
                score += 2
            if score > best_score:
                best_score = score
                best_item = item

        if best_item:
            lg = best_item.get("league", {})
            league_id = lg.get("id")
            # choose season: prefer current=True, else max year available
            seasons = best_item.get("seasons", [])
            cur = next((s for s in seasons if s.get("current")), None)
            if cur:
                season = cur.get("year")
            else:
                years = [s.get("year") for s in seasons if isinstance(s.get("year"), int)]
                season = max(years) if years else None

        if not league_id or not season:
            return {"success": False, "error": "Could not resolve league id/season for Chile Primera", "league_id": None, "season": None}

        return {"success": True, "error": None, "league_id": league_id, "season": season}

    def _api_football_fetch_fixtures(
        self,
        league_id: int,
        season: int,
        date_from: Optional[str],
        date_to: Optional[str],
        next_count: Optional[int] = None,
        include_status: bool = True
    ) -> dict[str, Any]:
        """
        Fetch fixtures from API-FOOTBALL by league + season within date range.

        Endpoint:
            GET {APIFOOTBALL_BASE_URL}/fixtures?league={id}&season={year}&from=YYYY-MM-DD&to=YYYY-MM-DD&status=NS

        Returns structure similar to fetch_matches_for_competition().
        """
        if not self.api_football_key:
            return {"success": False, "status_code": 0, "error": "APIFOOTBALL_API_KEY not set", "data": None, "cache_hit": False}

        # Cache key uses league id
        range_sig = f"{date_from}_{date_to}" if (date_from or date_to) else "none"
        mode = f"next{next_count}" if next_count else "range"
        cache_key = f"AF_{league_id}_{season}_{range_sig}_{mode}"
        status_key = "NS-PST-TBD"
        cached = self.cache.load("fixtures", cache_key, status_key)
        if cached is not None:
            return {"success": True, "status_code": 200, "error": None, "data": cached, "cache_hit": True}

        url = f"{self.api_football_base_url}/fixtures"
        headers = {"x-apisports-key": self.api_football_key}
        params = {"league": league_id, "season": season}
        if include_status:
            params["status"] = "NS-PST-TBD"
        if next_count:
            params["next"] = next_count
        else:
            if date_from:
                params["from"] = date_from
            if date_to:
                params["to"] = date_to

        data, status, err = self.http_client.get(url, headers=headers, params=params, allow_retries=True)
        if data is None or status != 200:
            return {"success": False, "status_code": status, "error": err or f"HTTP {status}", "data": None, "cache_hit": False}

        # Save to cache (store raw response)
        self.cache.save(data, "fixtures", cache_key, status_key)
        return {"success": True, "status_code": 200, "error": None, "data": data, "cache_hit": False}

    def _api_football_fetch_by_date(
        self,
        league_id: int,
        season: int,
        date_str: str,
        include_status: bool = True,
    ) -> dict[str, Any]:
        """
        Fetch fixtures for a single date using API-FOOTBALL `date` parameter.

        Caching key: AF_{league}_{season}_date_{date_str}
        """
        if not self.api_football_key:
            return {"success": False, "status_code": 0, "error": "APIFOOTBALL_API_KEY not set", "data": None, "cache_hit": False}

        cache_key = f"AF_{league_id}_{season}_date_{date_str}"
        status_key = "NS-PST-TBD"
        cached = self.cache.load("fixtures", cache_key, status_key)
        if cached is not None:
            return {"success": True, "status_code": 200, "error": None, "data": cached, "cache_hit": True}

        url = f"{self.api_football_base_url}/fixtures"
        headers = {"x-apisports-key": self.api_football_key}
        params = {"league": league_id, "season": season, "date": date_str}
        if include_status:
            params["status"] = "NS-PST-TBD"

        data, status, err = self.http_client.get(url, headers=headers, params=params, allow_retries=True)
        if data is None or status != 200:
            return {"success": False, "status_code": status, "error": err or f"HTTP {status}", "data": None, "cache_hit": False}

        self.cache.save(data, "fixtures", cache_key, status_key)
        return {"success": True, "status_code": 200, "error": None, "data": data, "cache_hit": False}

    def _api_football_fetch_full_season(
        self,
        league_id: int,
        season: int,
        include_status: bool = False,
    ) -> dict[str, Any]:
        """
        Fetch the entire season schedule for a league.

        Args:
            league_id: API-FOOTBALL league id (e.g., 265 for Chile Primera)
            season: Season year (e.g., 2026)
            include_status: If True, include status filter; default False to get all

        Returns standard dict like other fetchers, cached under AF_{league}_{season}_full.
        """
        if not self.api_football_key:
            return {"success": False, "status_code": 0, "error": "APIFOOTBALL_API_KEY not set", "data": None, "cache_hit": False}

        cache_key = f"AF_{league_id}_{season}_full"
        status_key = "ALL"
        cached = self.cache.load("fixtures", cache_key, status_key)
        if cached is not None:
            return {"success": True, "status_code": 200, "error": None, "data": cached, "cache_hit": True}

        url = f"{self.api_football_base_url}/fixtures"
        headers = {"x-apisports-key": self.api_football_key}
        params = {"league": league_id, "season": season}
        if include_status:
            params["status"] = "NS-PST-TBD"

        data, status, err = self.http_client.get(url, headers=headers, params=params, allow_retries=True)
        if data is None or status != 200:
            return {"success": False, "status_code": status, "error": err or f"HTTP {status}", "data": None, "cache_hit": False}

        self.cache.save(data, "fixtures", cache_key, status_key)
        return {"success": True, "status_code": 200, "error": None, "data": data, "cache_hit": False}

    def normalize_api_football(
        self,
        af_data: dict[str, Any],
        competition_label: str,
        competition_code: str | None
    ) -> list[dict[str, Any]]:
        """
        Normalize API-FOOTBALL fixtures to our canonical format.

        API-FOOTBALL response shape (simplified):
            {
              "response": [
                 {
                   "fixture": {"id": 123, "date": "2026-02-20T15:00:00+00:00", "status": {"short": "NS"}, "venue": {"name": "..."}},
                   "teams": {"home": {"name": "..."}, "away": {"name": "..."}},
                   "league": {"season": 2026}
                 }, ...
              ]
            }
        """
        normalized: list[dict[str, Any]] = []
        items = af_data.get("response", []) if isinstance(af_data, dict) else []
        for it in items:
            fx = it.get("fixture", {})
            tms = it.get("teams", {})
            lg = it.get("league", {})
            try:
                utc_iso = fx.get("date") or ""
                # normalize to Z if needed
                if utc_iso.endswith("+00:00"):
                    utc_iso = utc_iso.replace("+00:00", "Z")
                fixture = {
                    "competition": competition_label,
                    "provider": "api-football",
                    "competition_code": competition_code,
                    "fixture_id": str(fx.get("id", "")),
                    "utc_date": utc_iso,
                    "status": fx.get("status", {}).get("short", "UNKNOWN"),
                    "matchday": None,
                    "home_team": (tms.get("home") or {}).get("name", "Unknown"),
                    "away_team": (tms.get("away") or {}).get("name", "Unknown"),
                    "venue": (fx.get("venue") or {}).get("name"),
                    "season": lg.get("season")
                }
                normalized.append(fixture)
            except Exception as e:
                logger.warning(f"API-FOOTBALL normalize error: {e}")
                continue
        logger.info(f"Normalized {len(normalized)} fixtures for {competition_label} (api-football)")
        return normalized
    
    def normalize_fixtures(
        self,
        raw_matches: list[dict],
        competition_label: str,
        competition_code: str
    ) -> list[dict[str, Any]]:
        """
        Normalize raw football-data API matches to canonical fixture format.
        
        Input (from football-data API):
        {
            "id": 300...
            "utcDate": "2024-01-15T20:00:00Z",
            "status": "SCHEDULED",
            "matchday": 1,
            "stage": "GROUP_STAGE",
            "group": "Group A",
            "lastUpdated": "2024-01-10T...",
            "homeTeam": {"id": 101, "name": "Real Madrid", ...},
            "awayTeam": {"id": 205, "name": "AC Milan", ...},
            "score": {"winner": null, "duration": "REGULAR", ...},
            "odds": null,
            "referees": [...],
            "venue": "Estádio de Luz"
        }
        
        Output (canonical):
        {
            "competition": "UCL",
            "provider": "football-data",
            "competition_code": "CL",
            "fixture_id": "300...",
            "utc_date": "2024-01-15T20:00:00Z",
            "status": "SCHEDULED",
            "matchday": 1,
            "home_team": "Real Madrid",
            "away_team": "AC Milan",
            "venue": "Estádio de Luz",
            "season": 2023  # if available
        }
        
        Args:
            raw_matches: List of match dicts from API response["matches"]
            competition_label: Standardized label (e.g., "UCL", "CHI1")
            competition_code: API competition code (e.g., "CL")
        
        Returns:
            List of normalized fixture dicts
        """
        normalized = []
        
        for match in raw_matches:
            try:
                fixture = {
                    "competition": competition_label,
                    "provider": "football-data",
                    "competition_code": competition_code,
                    "fixture_id": str(match.get("id", "")),
                    "utc_date": match.get("utcDate", ""),
                    "status": match.get("status", "UNKNOWN"),
                    "matchday": match.get("matchday"),
                    "home_team": match.get("homeTeam", {}).get("name", "Unknown"),
                    "away_team": match.get("awayTeam", {}).get("name", "Unknown"),
                    "venue": match.get("venue"),
                    "season": match.get("season"),
                }
                normalized.append(fixture)
            except Exception as e:
                logger.warning(f"Error normalizing fixture: {e}")
                continue
        
        logger.info(f"Normalized {len(normalized)} fixtures for {competition_label}")
        return normalized


def fixtures_fetcher_node(state: AgentState) -> AgentState:
    """
    LangGraph node for fetching fixtures from football-data.org.
    
    This is the main entry point for Agente #1 within the multiagent pipeline.
    
    Process:
    1. Reads state["competitions"] - list of competitions to fetch
    2. For each competition:
       a. Try to fetch matches from API (or cache)
       b. If successful, normalize to canonical format
       c. If failed, record error in meta and continue
    3. Update state with:
       - state["fixtures"]: Combined normalized list
       - state["fixtures_raw"]: By-competition raw responses
       - state["meta"]: Execution stats and errors
       - state["messages"]: Audit trail
    
    Args:
        state: AgentState from LangGraph pipeline
    
    Returns:
        Updated AgentState with fixtures data populated
    
    Example in LangGraph:
        graph.add_node("fixtures_fetcher", fixtures_fetcher_node)
        graph.add_edge(START, "fixtures_fetcher")
        graph.add_edge("fixtures_fetcher", "odds_fetcher")
    """
    logger.info("=" * 60)
    logger.info("AGENTE #1: FIXTURES FETCHER (football-data.org)")
    logger.info("=" * 60)
    
    # Initialize fixtures fetcher
    try:
        fetcher = FixturesFetcher()
    except ValueError as e:
        error_msg = f"Configuration error: {str(e)}"
        logger.error(error_msg)
        state["messages"].append(
            SystemMessage(content=f"Fixtures Fetcher Error: {error_msg}")
        )
        state["meta"]["errors"]["fixtures"] = {"init": error_msg}
        return state
    
    # Initialize containers
    state["fixtures"] = []
    state["fixtures_raw"] = {}
    state["meta"]["fixtures_counts"] = {}
    state["meta"]["errors"]["fixtures"] = {}
    state["meta"]["cache_hits"]["fixtures"] = 0
    
    start_time = datetime.now()
    
    # Get date range from state (if provided)
    date_from = state.get("fixtures_date_from")
    date_to = state.get("fixtures_date_to")
    
    if date_from or date_to:
        logger.info(f"Date range filter: {date_from} to {date_to}")
    
    # Fetch for each competition
    for comp in state.get("competitions", []):
        comp_label = comp.get("competition", "?")
        comp_code = comp.get("competition_code")
        logger.info(f"\n>>> Fetching {comp_label} (code={comp_code})...")

        provider = (comp.get("fixtures_provider") or "football-data").lower()
        if comp_label == "CHI1" and provider == "api-football":
            # Explicit override or automatic resolution
            league_id = comp.get("api_football_league_id")
            season = comp.get("api_football_season")
            if not league_id or not season:
                res = fetcher._api_football_get_league_and_season(country="Chile", search="Primera")
                if not res.get("success"):
                    err = res.get("error") or "league/season resolution failed"
                    logger.error(f"Error resolving CHI1 league via API-FOOTBALL: {err}")
                    state["meta"]["errors"]["fixtures"][comp_label] = err
                    state["meta"]["fixtures_counts"][comp_label] = 0
                    continue
                league_id = res["league_id"]
                season = res["season"]

            # Try range first
            fetch = fetcher._api_football_fetch_fixtures(league_id, season, date_from, date_to)
            if not fetch.get("success"):
                err = fetch.get("error") or "API-FOOTBALL fetch failed"
                logger.error(f"Error fetching CHI1 fixtures: {err}")
                state["meta"]["errors"]["fixtures"][comp_label] = err
                state["meta"]["fixtures_counts"][comp_label] = 0
                continue
            if fetch.get("cache_hit"):
                state["meta"]["cache_hits"]["fixtures"] += 1

            state["fixtures_raw"][comp_label] = fetch["data"]
            normalized = fetcher.normalize_api_football(fetch["data"], comp_label, comp_code)

            # Fallback to next=N when range empty
            if not normalized:
                next_count = comp.get("api_football_next") or 20
                logger.info(f"No CHI1 fixtures in range, trying next={next_count}")
                fetch2 = fetcher._api_football_fetch_fixtures(league_id, season, None, None, next_count=next_count)
                if fetch2.get("success"):
                    state["fixtures_raw"][comp_label] = fetch2["data"]
                    normalized = fetcher.normalize_api_football(fetch2["data"], comp_label, comp_code)

            # Ultimate fallback: next=50 without status filter (some plans/leagues)
            if not normalized:
                logger.info("No CHI1 fixtures after next fallback, trying next=50 without status filter")
                fetch3 = fetcher._api_football_fetch_fixtures(league_id, season, None, None, next_count=50, include_status=False)
                if fetch3.get("success"):
                    state["fixtures_raw"][comp_label] = fetch3["data"]
                    normalized = fetcher.normalize_api_football(fetch3["data"], comp_label, comp_code)

            # Final attempt: query each day in window individually
            if not normalized and date_from and date_to:
                try:
                    start_dt = datetime.fromisoformat(f"{date_from}T00:00:00")
                    end_dt = datetime.fromisoformat(f"{date_to}T00:00:00")
                    days = (end_dt - start_dt).days + 1
                    logger.info(f"No CHI1 fixtures yet, probing per-day for {days} days")
                    combined = {"response": []}
                    for i in range(max(1, min(days, 7))):
                        d = (start_dt + timedelta(days=i)).date().isoformat()
                        day_fetch = fetcher._api_football_fetch_by_date(league_id, season, d, include_status=True)
                        if day_fetch.get("success") and isinstance(day_fetch.get("data"), dict):
                            part = day_fetch["data"].get("response", [])
                            combined["response"].extend(part)
                    if combined["response"]:
                        state["fixtures_raw"][comp_label] = combined
                        normalized = fetcher.normalize_api_football(combined, comp_label, comp_code)
                except Exception as e:
                    logger.warning(f"Per-day probe failed: {e}")

            # Full-season fetch and local filter as a final robust path
            if not normalized:
                logger.info("No CHI1 fixtures found; fetching full season and filtering locally")
                full_fetch = fetcher._api_football_fetch_full_season(league_id, season, include_status=False)
                if full_fetch.get("success") and isinstance(full_fetch.get("data"), dict):
                    full_raw = full_fetch["data"]
                    all_norm = fetcher.normalize_api_football(full_raw, comp_label, comp_code)
                    if date_from and date_to:
                        try:
                            start = datetime.fromisoformat(f"{date_from}T00:00:00+00:00")
                            end = datetime.fromisoformat(f"{date_to}T23:59:59+00:00")
                            def in_window(iso):
                                try:
                                    return start <= datetime.fromisoformat(iso.replace('Z','+00:00')) <= end
                                except Exception:
                                    return False
                            filtered = [e for e in all_norm if in_window(e.get("utc_date",""))]
                            state["fixtures_raw"][comp_label] = full_raw
                            normalized = filtered
                        except Exception as e:
                            logger.warning(f"Full-season filter failed: {e}")

            state["fixtures"].extend(normalized)
            state["meta"]["fixtures_counts"][comp_label] = len(normalized)
            logger.info(f"✓ {comp_label}: {len(normalized)} fixtures (api-football)")
            continue

        # Default: football-data.org
        if not comp_code:
            msg = "No competition code available (may not be in free tier)"
            logger.warning(f"Skipping {comp_label}: {msg}")
            state["meta"]["errors"]["fixtures"][comp_label] = msg
            state["meta"]["fixtures_counts"][comp_label] = 0
            continue

        result = fetcher.fetch_matches_for_competition(
            comp_code,
            status=os.getenv("FIXTURES_STATUS", "SCHEDULED"),
            date_from=date_from,
            date_to=date_to,
        )
        if not result["success"]:
            err = result["error"] or "Unknown error"
            logger.error(f"Error fetching {comp_label}: {err}")
            state["meta"]["errors"]["fixtures"][comp_label] = err
            state["meta"]["fixtures_counts"][comp_label] = 0
            continue

        state["fixtures_raw"][comp_label] = result["data"]
        raw_matches = result["data"].get("matches", [])
        normalized = fetcher.normalize_fixtures(raw_matches, comp_label, comp_code)
        state["fixtures"].extend(normalized)
        state["meta"]["fixtures_counts"][comp_label] = len(normalized)
        logger.info(f"✓ {comp_label}: {len(normalized)} fixtures")
    
    # Update metadata
    state["meta"]["total_fixtures"] = len(state["fixtures"])
    state["meta"]["processing_time_seconds"] = (
        datetime.now() - start_time
    ).total_seconds()
    
    # Add audit message
    audit_msg = (
        f"Fetched fixtures for competitions: {list(state['meta']['fixtures_counts'].keys())}. "
        f"Total: {state['meta']['total_fixtures']} fixtures. "
        f"Cache hits: {state['meta']['cache_hits'].get('fixtures', 0)}"
    )
    state["messages"].append(HumanMessage(content=audit_msg))
    
    logger.info("\n" + "=" * 60)
    logger.info(f"FIXTURES AGENT COMPLETE: {state['meta']['total_fixtures']} fixtures")
    logger.info("=" * 60)
    
    return state
