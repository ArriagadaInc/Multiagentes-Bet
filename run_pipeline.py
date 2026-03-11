"""
Pipeline Execution Script

Orchestrates the complete multiagent pipeline.
Supports per-league execution via --liga argument or PIPELINE_LIGA env var.

Usage:
    python run_pipeline.py                 # CHI1 + UCL (default)
    python run_pipeline.py --liga CHI1     # Solo Chile
    python run_pipeline.py --liga UCL      # Solo Champions
    python run_pipeline.py --liga CHI1 UCL # Ambas explícito
"""

import os
import sys
import io
import argparse

# Force UTF-8 encoding for stdout/stderr to handle emojis on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
import json
import logging
import asyncio
from datetime import datetime
from dotenv import load_dotenv

from graph_pipeline import PipelineExecutor, create_initial_state

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


def validate_environment():
    """
    Validate required environment variables.
    
    Returns:
        Tuple (is_valid: bool, errors: list[str])
    """
    errors = []
    
    if not os.getenv("FOOTBALL_DATA_API_KEY"):
        errors.append("Missing FOOTBALL_DATA_API_KEY")
    
    if not os.getenv("ODDS_API_KEY"):
        errors.append("Missing ODDS_API_KEY")
    
    return len(errors) == 0, errors


def print_header(text: str, width: int = 80):
    """Print formatted section header."""
    print("\n" + "=" * width)
    print(f"  {text}".ljust(width - 2))
    print("=" * width)


def print_metadata(meta: dict, width: int = 80):
    """Print execution metadata in readable format."""
    print(f"\n📊 EXECUTION METADATA")
    print(f"  Started at: {meta.get('started_at', 'N/A')}")
    print(f"  Completed at: {meta.get('completed_at', 'N/A')}")
    print(f"  Processing time: {meta.get('processing_time_seconds', 0):.2f}s")
    print()
    print(f"📋 COLLECTIONS")
    print(f"  Total Fixtures: {meta.get('total_fixtures', 0)}")
    print(f"  Total Odds Events: {meta.get('total_odds', 0)}")
    print()
    print(f"📈 COUNTS BY COMPETITION")
    
    fixtures_counts = meta.get("fixtures_counts", {})
    for comp, count in fixtures_counts.items():
        print(f"  Fixtures - {comp}: {count}")
    
    odds_counts = meta.get("odds_counts", {})
    for comp, count in odds_counts.items():
        print(f"  Odds - {comp}: {count}")
    print()
    
    print(f"💾 CACHE PERFORMANCE")
    cache_hits = meta.get("cache_hits", {})
    print(f"  Fixtures cache hits: {cache_hits.get('fixtures', 0)}")
    print(f"  Odds cache hits: {cache_hits.get('odds', 0)}")
    print()
    
    # Show errors if any
    errors = meta.get("errors", {})
    if errors:
        fixtures_errors = errors.get("fixtures", {})
        odds_errors = errors.get("odds", {})
        
        if fixtures_errors or odds_errors:
            print(f"⚠️  ERRORS")
            for comp, error in fixtures_errors.items():
                print(f"  Fixtures - {comp}: {error}")
            for comp, error in odds_errors.items():
                print(f"  Odds - {comp}: {error}")
            print()


def print_fixture_sample(fixtures: list[dict], count: int = 3):
    """Print sample fixtures."""
    if not fixtures:
        print("  (No fixtures)")
        return
    
    sample = fixtures[:count]
    for i, fixture in enumerate(sample, 1):
        print(f"\n  [{i}] {fixture.get('home_team', '?')} vs {fixture.get('away_team', '?')}")
        print(f"      Competition: {fixture.get('competition')}")
        print(f"      Date: {fixture.get('utc_date')}")
        print(f"      Status: {fixture.get('status')}")
        print(f"      Matchday: {fixture.get('matchday')}")


def print_odds_sample(odds: list[dict], count: int = 3):
    """Print sample odds events."""
    if not odds:
        print("  (No odds)")
        return
    
    sample = odds[:count]
    for i, event in enumerate(sample, 1):
        print(f"\n  [{i}] {event.get('home_team', '?')} vs {event.get('away_team', '?')}")
        print(f"      Competition: {event.get('competition')}")
        print(f"      Bookmakers: {event.get('bookmakers_count')}")
        print(f"      Commence: {event.get('commence_time')}")


def print_stats_sample(stats: list[dict], count: int = 5):
    """Print sample team statistics."""
    if not stats:
        print("  (No stats)")
        return
    sample = stats[:count]
    for i, st in enumerate(sample, 1):
        team = st.get('team', '?')
        comp = st.get('competition', '?')
        s = st.get('stats', {})
        pos = s.get('position', '?')
        pts = s.get('points', 0)
        gf = s.get('goals_for', 0)
        ga = s.get('goals_against', 0)
        form = s.get('form', 'N/D')
        w = s.get('won', 0)
        d = s.get('draw', 0)
        l = s.get('lost', 0)
        print(f"\n  [{i}] {comp} - {team} (pos: {pos})")
        print(f"      PTS={pts} | PJ={s.get('played',0)} | G={w} E={d} P={l} | GF={gf} GC={ga} DG={s.get('goal_difference',0)}")
        print(f"      Forma: {form}")
        cs = s.get('clean_sheets')
        if cs is not None:
            print(f"      Clean sheets: {cs} | Amarillas: {s.get('cards_yellow',0)} | Rojas: {s.get('cards_red',0)}")
        scorers = st.get('top_scorers', [])
        if scorers:
            sc_str = ', '.join([f"{x['player']}({x['goals']}g)" for x in scorers[:3]])
            print(f"      Goleadores: {sc_str}")


def print_insights_sample(insights: list[dict], count: int = 5):
    """Print sample insights."""
    if not insights:
        print("  (No insights)")
        return
    sample = insights[:count]
    for i, ins in enumerate(sample, 1):
        team = ins.get('team', '?')
        comp = ins.get('competition', '?')
        nm = ins.get('next_match') or {}
        opp = nm.get('opponent', 'N/D')
        date = nm.get('date', 'N/D')
        print(f"\n  [{i}] {comp} - {team}")
        print(f"      Próximo: {team} vs {opp} | {date}")
        fc = ins.get('forecast') or {}
        fc_line = ""
        if fc:
            fc_line = f"      Pronóstico: {fc.get('outcome','N/D')} (conf {fc.get('confidence','N/D')}) | {fc.get('rationale','')}"
            print(fc_line)
        ents = ins.get('entities') or {}
        if ents:
            inj = len(ents.get('injuries') or [])
            sus = len(ents.get('suspensions') or [])
            absn = len(ents.get('absences') or [])
            print(f"      Entidades: injuries={inj}, suspensions={sus}, absences={absn}")
        text = ins.get('insight', '')
        preview = (text[:280] + '...') if len(text) > 280 else text
        for line in preview.splitlines():
            print(f"      {line}")


def print_predictions_sample(predictions: list[dict], count: int = 10):
    """Print sample predictions."""
    if not predictions:
        print("  No predictions generated.")
        return

    for pred in predictions[:count]:
        home = pred.get("home_team", "?")
        away = pred.get("away_team", "?")
        p = pred.get("prediction", "?")
        conf = pred.get("confidence", "?")
        score = pred.get("score_prediction", "?")
        comp = pred.get("competition", "?")

        emoji = "🏠" if p == "1" else "🤝" if p == "X" else "✈️"

        print(f"  {emoji} {comp:4} | {home:25} vs {away:25} | {p} ({conf}%) | Score: {score}")

        rationale = pred.get("rationale", "")
        if rationale:
            print(f"         💡 {rationale[:100]}")
        print()


def print_betting_tips_sample(tips: list[dict], count: int = 10):
    """Print sample betting tips."""
    if not tips:
        print("  No betting tips generated.")
        return

    for tip in tips[:count]:
        tipo = tip.get("type", "?")
        if tipo == "value_bet":
            match = tip.get("match", "?")
            pick = tip.get("pick", "?")
            odds = tip.get("odds", 0.0)
            edge = tip.get("edge_pct", 0.0)
            stake = tip.get("stake_units", 0.0)
            
            emoji = "💎"
            print(f"  {emoji} {match:30} | Pick: {pick} @ {odds} | Edge: {edge}% | Stake: {stake}u")
            
        elif tipo.startswith("combo"):
            sel_count = len(tip.get("legs", []))
            total_odds = tip.get("total_odds", 0.0)
            stake = tip.get("stake_units", 0.0)
            
            emoji = "🚀"
            print(f"  {emoji} COMBINADA ({sel_count} legs) | Cuota Total: {total_odds} | Stake: {stake}u")
            for leg in tip.get("legs", []):
                print(f"      - {leg['match']} ({leg['pick']} @ {leg['odds']})")
                
        rationale = tip.get("rationale", "")
        if rationale:
            print(f"         💡 {rationale[:100]}")
        print()


def save_results(result, output_prefix: str = "pipeline"):
    """
    Save pipeline results to JSON files.
    
    Creates:
    - {output_prefix}_result.json: Complete state
    - {output_prefix}_metadata.json: Metadata only
    - {output_prefix}_fixtures.json: Normalized fixtures
    - {output_prefix}_odds.json: Normalized odds
    """
    
    # Main result file
    main_file = f"{output_prefix}_result.json"
    with open(main_file, "w", encoding="utf-8") as f:
        # Convert to JSON-serializable format
        save_obj = {
            "meta": result.get("meta", {}),
            "fixtures": result.get("fixtures", []),
            "odds_canonical": result.get("odds_canonical", []),
        }
        json.dump(save_obj, f, indent=2)
    logger.info(f"✓ Results saved to {main_file}")
    
    # Metadata file
    meta_file = f"{output_prefix}_metadata.json"
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(result.get("meta", {}), f, indent=2)
    logger.info(f"✓ Metadata saved to {meta_file}")
    
    # Fixtures file
    fixtures_file = f"{output_prefix}_fixtures.json"
    with open(fixtures_file, "w", encoding="utf-8") as f:
        json.dump(result.get("fixtures", []), f, indent=2)
    logger.info(f"✓ Fixtures saved to {fixtures_file}")
    
    # Odds file
    odds_file = f"{output_prefix}_odds.json"
    with open(odds_file, "w", encoding="utf-8") as f:
        json.dump(result.get("odds_canonical", []), f, indent=2)
    logger.info(f"✓ Odds saved to {odds_file}")

    # Insights file
    insights_file = f"{output_prefix}_insights.json"
    with open(insights_file, "w", encoding="utf-8") as f:
        json.dump(result.get("insights", []), f, indent=2)
    logger.info(f"✓ Insights saved to {insights_file}")

    # Stats file
    stats_file = f"{output_prefix}_stats.json"
    with open(stats_file, "w", encoding="utf-8") as f:
        json.dump(result.get("stats_by_team", []), f, indent=2)
    logger.info(f"✓ Stats saved to {stats_file}")

    # Predictions file
    predictions_file = f"{output_prefix}_predictions.json"
    with open(predictions_file, "w", encoding="utf-8") as f:
        json.dump(result.get("predictions", []), f, indent=2, ensure_ascii=False)
    logger.info(f"✓ Predictions saved to {predictions_file}")

    # Betting tips file
    bets_file = f"{output_prefix}_bets.json"
    with open(bets_file, "w", encoding="utf-8") as f:
        json.dump(result.get("betting_tips", []), f, indent=2, ensure_ascii=False)
    logger.info(f"✓ Betting tips saved to {bets_file}")

    # Analyst Web Checks file (opcional)
    analyst_web_checks_file = f"{output_prefix}_analyst_web_checks.json"
    with open(analyst_web_checks_file, "w", encoding="utf-8") as f:
        json.dump(result.get("analyst_web_checks", []), f, indent=2, ensure_ascii=False)
    logger.info(f"✓ Analyst Web Checks saved to {analyst_web_checks_file}")


def main():
    """Main execution entry point."""

    print_header("SPORTS BETTING ANALYSIS - MULTIAGENT PIPELINE")

    # Load environment
    print("\n📝 Loading environment configuration...")
    load_dotenv()

    # Validate environment
    is_valid, errors = validate_environment()
    if not is_valid:
        print_header("⚠️  CONFIGURATION ERROR", 80)
        for error in errors:
            print(f"  ✗ {error}")
        print()
        sys.exit(1)

    print("  ✓ All required environment variables are set")

    # ── Catálogo completo de ligas disponibles ────────────────────────────────
    ALL_COMPETITIONS = {
        "UCL": {
            "competition": "UCL",
            "fixtures_provider": "football-data",
            "competition_code": "CL",
            "espn_slug": "uefa.champions"
        },
        "CHI1": {
            "competition": "CHI1",
            "fixtures_provider": "api-football",
            "competition_code": None,
            "api_football_league_id": 265,
            "api_football_season": 2026,
            "api_football_next": 20,
            "espn_slug": "chi.1"
        },
    }

    # ── Selección de ligas: CLI > entorno > default (ambas) ───────────────────
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--liga", nargs="+",
        choices=["CHI1", "UCL", "chi1", "ucl"],
        default=None,
        help="Liga(s) a ejecutar: CHI1, UCL o ambas"
    )
    args, _ = parser.parse_known_args()

    liga_env = os.getenv("PIPELINE_LIGA", "").strip()

    if args.liga:
        selected = [l.upper() for l in args.liga]
    elif liga_env:
        selected = [l.strip().upper() for l in liga_env.split(",") if l.strip()]
    else:
        selected = list(ALL_COMPETITIONS.keys())   # CHI1 + UCL (comportamiento actual)

    competitions = [ALL_COMPETITIONS[l] for l in selected if l in ALL_COMPETITIONS]

    if not competitions:
        print(f"  ✗ Ninguna liga válida seleccionada. Opciones: {list(ALL_COMPETITIONS.keys())}")
        sys.exit(1)

    ligas_str = " + ".join([c["competition"] for c in competitions])
    print(f"  ⚽ Ligas seleccionadas: {ligas_str}")
    logger.info(f"Competitions activas: {[c['competition'] for c in competitions]}")

    # Create initial state
    print("\n🔧 Initializing pipeline state...")
    print(f"   Fetching fixtures from today up to 30 days ahead...")
    initial_state = create_initial_state(competitions, fixtures_days_ahead=30)
    logger.info("✓ Initial state created")

    # Execute pipeline
    print("\n🚀 Executing multiagent pipeline...")
    executor = PipelineExecutor()

    try:
        result = executor.execute(initial_state, verbose=False)
    except Exception as e:
        print_header("❌ PIPELINE FAILED", 80)
        print(f"  Error: {str(e)}")
        print()
        sys.exit(1)

    # Display results
    print_header("RESULTS", 80)
    print_metadata(result.get("meta", {}))

    print_header("FIXTURE SAMPLES", 80)
    print(f"\n📌 Showing first 3 fixtures:\n")
    print_fixture_sample(result.get("fixtures", []), count=3)

    print_header("ODDS SAMPLES", 80)
    print(f"\n📌 Showing first 3 odds events:\n")
    print_odds_sample(result.get("odds_canonical", []), count=3)

    print_header("STATS SAMPLES", 80)
    print(f"\n📊 Showing first 5 team stats:\n")
    print_stats_sample(result.get("stats_by_team", []), count=5)

    print_header("INSIGHTS SAMPLES", 80)
    print(f"\n📌 Showing first 5 insights:\n")
    print_insights_sample(result.get("insights", []), count=5)

    print_header("PREDICTIONS", 80)
    preds = result.get("predictions", [])
    print(f"\n🧠 {len(preds)} predicciones generadas:\n")
    print_predictions_sample(preds, count=10)

    print_header("BETTING TIPS", 80)
    tips = result.get("betting_tips", [])
    print(f"\n💰 {len(tips)} apuestas sugeridas:\n")
    print_betting_tips_sample(tips, count=10)

    # Save results
    print_header("SAVING RESULTS", 80)
    save_results(result)
    print()

    # Success message
    print_header("✅ PIPELINE EXECUTION SUCCESSFUL", 80)
    print(f"  Summary:")
    print(f"    - Ligas: {ligas_str}")
    print(f"    - Fixtures collected: {result['meta'].get('total_fixtures', 0)}")
    print(f"    - Odds events collected: {result['meta'].get('total_odds', 0)}")
    stats_count = len(result.get('stats_by_team', []))
    print(f"    - Team stats collected: {stats_count}")
    print(f"    - Insights generated: {len(result.get('insights', []))}")
    print(f"    - Predictions generated: {len(result.get('predictions', []))}")
    print(f"    - Betting tips generated: {len(result.get('betting_tips', []))}")
    print(f"    - Processing time: {result['meta'].get('processing_time_seconds', 0):.2f}s")
    print()


if __name__ == "__main__":
    main()
