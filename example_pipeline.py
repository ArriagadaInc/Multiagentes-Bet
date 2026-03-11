#!/usr/bin/env python
"""
Example: Running the Fixtures Agent (Agente #1)

Demonstrates how to use the FixturesFetcher in standalone mode
and within the full multiagent pipeline.
"""

import os
import logging
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Load environment
load_dotenv()


def example_1_standalone_fixtures_fetcher():
    """Example 1: Use FixturesFetcher standalone (no pipeline)"""
    
    print("\n" + "=" * 70)
    print("EXAMPLE 1: Standalone Fixtures Fetcher")
    print("=" * 70)
    
    from agents.fixtures_agent import FixturesFetcher
    
    try:
        # Initialize fetcher
        fetcher = FixturesFetcher()
        
        # Fetch Champions League matches
        print("\n📌 Fetching Champions League fixtures...")
        result = fetcher.fetch_matches_for_competition(
            "CL", 
            status="SCHEDULED"
        )
        
        if result["success"]:
            raw_matches = result["data"].get("matches", [])
            print(f"   ✓ Got {len(raw_matches)} raw matches from API")
            print(f"   Cache hit: {result['cache_hit']}")
            
            # Normalize
            normalized = fetcher.normalize_fixtures(raw_matches, "UCL", "CL")
            print(f"   ✓ Normalized to {len(normalized)} fixtures\n")
            
            # Show sample
            for i, fixture in enumerate(normalized[:2], 1):
                print(f"   [{i}] {fixture['home_team']} vs {fixture['away_team']}")
                print(f"       Date: {fixture['utc_date']}")
                print(f"       Status: {fixture['status']}\n")
        else:
            print(f"   ✗ Error: {result['error']}")
    
    except Exception as e:
        logger.error(f"Failed: {e}")


def example_2_full_pipeline():
    """Example 2: Execute full multiagent pipeline"""
    
    print("\n" + "=" * 70)
    print("EXAMPLE 2: Full Multiagent Pipeline (Fixtures + Odds)")
    print("=" * 70)
    
    from graph_pipeline import PipelineExecutor, create_initial_state
    
    try:
        # Define competitions
        competitions = [
            {
                "competition": "UCL",
                "fixtures_provider": "football-data",
                "competition_code": "CL"
            },
            {
                "competition": "CHI1",
                "fixtures_provider": "football-data",
                "competition_code": None  # Not in free tier
            }
        ]
        
        # Create initial state
        print("\n🔧 Initializing pipeline state...")
        initial_state = create_initial_state(competitions)
        
        # Execute pipeline
        print("🚀 Executing pipeline (Fixtures → Odds)...\n")
        executor = PipelineExecutor()
        result = executor.execute(initial_state)
        
        # Display results
        print("\n" + "=" * 70)
        print("📊 RESULTS")
        print("=" * 70)
        
        meta = result["meta"]
        print(f"\n📈 Statistics:")
        print(f"   Total Fixtures: {meta.get('total_fixtures', 0)}")
        print(f"   Total Odds Events: {meta.get('total_odds', 0)}")
        print(f"   Processing time: {meta.get('processing_time_seconds', 0):.2f}s")
        
        print(f"\n📋 Counts by competition:")
        for comp, count in meta.get("fixtures_counts", {}).items():
            print(f"   Fixtures - {comp}: {count}")
        
        for comp, count in meta.get("odds_counts", {}).items():
            print(f"   Odds - {comp}: {count}")
        
        # Show sample fixtures
        fixtures = result.get("fixtures", [])
        if fixtures:
            print(f"\n📌 Sample Fixtures ({len(fixtures)} total):")
            for i, fix in enumerate(fixtures[:2], 1):
                print(f"   [{i}] {fix['home_team']} vs {fix['away_team']}")
                print(f"       Competition: {fix['competition']}, Status: {fix['status']}")
        
        # Show sample odds
        odds = result.get("odds_canonical", [])
        if odds:
            print(f"\n💰 Sample Odds Events ({len(odds)} total):")
            for i, odd in enumerate(odds[:2], 1):
                print(f"   [{i}] {odd['home_team']} vs {odd['away_team']}")
                print(f"       Competition: {odd['competition']}, Bookmakers: {odd['bookmakers_count']}")
        
        # Show any errors
        errors = meta.get("errors", {})
        if errors.get("fixtures") or errors.get("odds"):
            print(f"\n⚠️  Errors encountered:")
            for comp, error in errors.get("fixtures", {}).items():
                print(f"   Fixtures - {comp}: {error}")
            for comp, error in errors.get("odds", {}).items():
                print(f"   Odds - {comp}: {error}")
    
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)


def example_3_cache_management():
    """Example 3: Manage and inspect cache"""
    
    print("\n" + "=" * 70)
    print("EXAMPLE 3: Cache Management")
    print("=" * 70)
    
    from utils.cache import CacheManager
    
    cache = CacheManager()
    
    # Get cache info
    info = cache.get_cache_info()
    print(f"\n📁 Cache Directory: {info['cache_dir']}")
    print(f"   Total files: {info['total_files']}")
    
    if info['files']:
        print(f"\n   Cached files:")
        for file in info['files']:
            print(f"     - {file['name']}: {file['size_kb']:.1f}KB (age: {file['age_seconds']:.0f}s)")
    else:
        print(f"\n   No cached files yet")


def example_4_http_client_retry_logic():
    """Example 4: Demonstrate HTTP client retry logic"""
    
    print("\n" + "=" * 70)
    print("EXAMPLE 4: HTTP Client (Retries & Backoff)")
    print("=" * 70)
    
    from utils.http import HTTPClient
    
    client = HTTPClient(
        timeout_seconds=20,
        max_retries=2,
        backoff_factors=[1.0, 2.0]
    )
    
    print("\n📡 HTTP Client Features:")
    print("   ✓ Retry on connection errors")
    print("   ✓ Exponential backoff (1s, 2s)")
    print("   ✓ Timeout enforcement (20s)")
    print("   ✓ No retry on 401/403/404 errors")
    print("   ✓ Automatic retry on 429/5xx errors")
    
    print("\n💡 Usage:")
    print("""
    data, status, error = client.get(
        "https://api.example.com/data",
        headers={"X-Auth-Token": "key"},
        params={"status": "active"}
    )
    
    if data:
        print(f"Success: {len(data)} items")
    else:
        print(f"Error {status}: {error}")
    """)


def main():
    """Run all examples"""
    
    print("\n" + "=" * 70)
    print("🎯 AGENTE #1 (FIXTURES FETCHER) - EXAMPLES")
    print("=" * 70)
    
    # Check environment
    if not os.getenv("FOOTBALL_DATA_API_KEY") or \
       os.getenv("FOOTBALL_DATA_API_KEY") == "YOUR_FOOTBALL_DATA_API_KEY_HERE":
        print("\n⚠️  WARNING: FOOTBALL_DATA_API_KEY not properly configured")
        print("   Add your API key to .env to run examples 1 & 2")
    
    if not os.getenv("ODDS_API_KEY"):
        print("\n⚠️  WARNING: ODDS_API_KEY not configured")
        print("   Add your API key to .env to run example 2")
    
    print("\n\nRunning examples:\n")
    
    try:
        # Example 1: Standalone
        if os.getenv("FOOTBALL_DATA_API_KEY") and \
           os.getenv("FOOTBALL_DATA_API_KEY") != "YOUR_FOOTBALL_DATA_API_KEY_HERE":
            example_1_standalone_fixtures_fetcher()
        
        # Example 2: Full pipeline
        if os.getenv("FOOTBALL_DATA_API_KEY") and \
           os.getenv("ODDS_API_KEY") and \
           os.getenv("FOOTBALL_DATA_API_KEY") != "YOUR_FOOTBALL_DATA_API_KEY_HERE":
            example_2_full_pipeline()
        
        # Example 3: Cache management (always works)
        example_3_cache_management()
        
        # Example 4: HTTP client (always works)
        example_4_http_client_retry_logic()
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")


if __name__ == "__main__":
    main()
