
import os
import logging
import json
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Set up logging to a file and stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("diagnose_chi1.log", mode='w', encoding='utf-8')
    ],
    force=True
)
logger = logging.getLogger("diagnose_chi1")

# Load environment
load_dotenv()

from agents.fixtures_agent import FixturesFetcher
from agents.odds_agent import OddsFetcher

async def diagnose():
    logger.info("Starting CHI1 Diagnosis...")
    
    # 1. Config
    comp = {
        "competition": "CHI1",
        "fixtures_provider": "api-football",
        "api_football_league_id": 265,
        "api_football_season": 2026,
        "api_football_next": 20,
        "espn_slug": "chi.1"
    }
    
    today = datetime.now()
    date_from = today.strftime("%Y-%m-%d")
    date_to = (today + timedelta(days=7)).strftime("%Y-%m-%d")
    logger.info(f"Target Window: {date_from} to {date_to}")

    # 2. Fetch Fixtures
    logger.info("\nChecking API-Football Fixtures (League 265)...")
    try:
        fetcher = FixturesFetcher()
        league_id = comp["api_football_league_id"]
        season = comp["api_football_season"]
        
        res = fetcher._api_football_fetch_fixtures(league_id, season, date_from, date_to)
        if res["success"]:
            raw_fixtures = res["data"].get("response", [])
            logger.info(f"✓ Found {len(raw_fixtures)} raw fixtures in API-Football")
            for f in raw_fixtures:
                fixture = f.get("fixture", {})
                teams = f.get("teams", {})
                logger.info(f"  - [{fixture.get('date')}] {teams.get('home', {}).get('name')} vs {teams.get('away', {}).get('name')}")
        else:
            logger.error(f"✗ Failed to fetch fixtures: {res.get('error')}")
            raw_fixtures = []
    except Exception as e:
        logger.error(f"Error in Fixtures: {e}")
        raw_fixtures = []

    # 3. Fetch Odds (The Odds API)
    logger.info("\nChecking The Odds API Odds...")
    try:
        odds_fetcher = OddsFetcher()
        odds_res = odds_fetcher.fetch_odds_for_competition("CHI1")
        if odds_res["success"]:
            raw_odds = odds_res["data"]
            logger.info(f"✓ Found {len(raw_odds)} raw odds events in The Odds API")
            
            # Filter by window
            filtered_odds = []
            for o in raw_odds:
                commence_time = o.get("commence_time")
                if commence_time:
                    o_dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
                    # Naive match check
                    if today.date() <= o_dt.date() <= (today + timedelta(days=7)).date():
                        filtered_odds.append(o)
            
            logger.info(f"✓ {len(filtered_odds)} odds events in the 7-day window")
            for o in filtered_odds:
                logger.info(f"  - [{o.get('commence_time')}] {o.get('home_team')} vs {o.get('away_team')}")
        else:
            logger.error(f"✗ Failed to fetch odds from API: {odds_res.get('error')}")
    except Exception as e:
        logger.error(f"Error in Odds API: {e}")

    # 4. Check Web Odds Fallback
    logger.info("\nChecking Web Odds Scraper (Coolbet/Betano)...")
    try:
        from agents.web_fixtures_agent import web_odds_fetcher_node
        from state import AgentState
        mock_state = AgentState(
            messages=[],
            competitions=[comp],
            fixtures=[],
            fixtures_raw={},
            odds_raw={},
            odds_canonical=[],
            fixtures_date_from=date_from,
            fixtures_date_to=date_to,
            meta={"errors": {"odds": {}}, "cache_hits": {"odds": 0}, "odds_counts": {}}
        )
        
        if raw_fixtures:
            mock_state["fixtures"] = fetcher.normalize_api_football({"response": raw_fixtures}, "CHI1", None)
            
        final_state = web_odds_fetcher_node(mock_state)
        logger.info(f"✓ Web Odds Fetcher finished. Canonical Odds count: {len(final_state.get('odds_canonical', []))}")
        for o in final_state.get('odds_canonical', []):
             logger.info(f"  - {o.get('home_team')} vs {o.get('away_team')} ({o.get('provider')})")
             
    except Exception as e:
        logger.error(f"✗ Web Odds Fetcher failed: {e}")

    logger.info("\nDiagnosis Complete.")

if __name__ == "__main__":
    asyncio.run(diagnose())
