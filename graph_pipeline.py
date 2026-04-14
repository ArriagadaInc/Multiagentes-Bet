"""
LangGraph Pipeline Orchestration

Flujo:
    START → odds_fetcher → stats_agent → journalist_agent
          → web_agent → insights_agent → normalizer_agent
          → gate_agent → analyst_agent → bettor_agent → END

Data flow:
    - odds_fetcher  → state["odds_canonical"] (fuente de partidos + cuotas)
    - stats_agent   → state["stats_by_team"]
    - insights_agent→ state["insights"]
    - normalizer    → state["match_contexts"] (cruce consolidado)
    - analyst       → state["predictions"]
    - bettor        → state["betting_tips"]

Data flow:
    - Both agents read state["competitions"]
    - Fixtures agent populates: state["fixtures"], state["fixtures_raw"]
    - Odds agent populates: state["odds_canonical"], state["odds_raw"]
    - Both update: state["meta"] (shared metadata)
    - All add to: state["messages"] (audit trail)

Author: Senior Python Developer
Date: 2024
"""

import logging
import os
from typing import Any, Optional
from datetime import datetime, timedelta
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage

from state import AgentState
from agents.fixtures_agent import fixtures_fetcher_node
from agents.web_fixtures_agent import web_fixtures_fetcher_node, web_odds_fetcher_node
from agents.odds_agent import odds_fetcher_node
from agents.journalist_agent import journalist_agent_node
from agents.insights_agent import insights_agent_node
from agents.web_agent import web_agent_node
from agents.stats_agent import stats_agent_node
from agents.normalizer_agent import normalizer_agent_node
from agents.gate_agent import gate_agent_node
from agents.analyst_agent import analyst_agent_node
from agents.bettor_agent import bettor_agent_node

logger = logging.getLogger(__name__)



def prune_fixtures_node(state: AgentState) -> dict:
    """
    Guillotina Temprana (v14.14): Tras agotar los fallbacks de cuotas (API/OCR/Web), 
    descarta de state["fixtures"] a cualquier partido que matemáticamente
    carezca de cuotas. Esto previene que Agentes costosos (YouTube/Stats) se cobren
    investigación sobre partidos que no se pueden apostar.
    """
    from utils.normalizer import TeamNormalizer
    normalizer = TeamNormalizer()
    
    odds = state.get("odds_canonical") or []
    fixtures = state.get("fixtures") or []
    
    if not fixtures:
        return {"fixtures": []}
        
    if not odds:
        # No hay mercado total
        logger.warning(f"  🔪 CRIBADORA: Eliminados todos los {len(fixtures)} partidos por falta global de mercado.")
        return {"fixtures": []}
        
    odds_slugs = set()
    for o in odds:
        h = normalizer.clean(o.get("home_team", "")) or o.get("home_team", "").lower()
        a = normalizer.clean(o.get("away_team", "")) or o.get("away_team", "").lower()
        odds_slugs.add(f"{h} vs {a}")
        if o.get("match_key"):
            odds_slugs.add(o.get("match_key"))
            
    survivors = []
    dropped = 0
    
    for fix in fixtures:
        f_h = normalizer.clean(fix.get("home_team", "")) or fix.get("home_team", "").lower()
        f_a = normalizer.clean(fix.get("away_team", "")) or fix.get("away_team", "").lower()
        f_slug = f"{f_h} vs {f_a}"
        
        match_found = False
        if f_slug in odds_slugs:
            match_found = True
        else:
            # Reintento parcial fallback (subcadena de nombres ya normalizados)
            for slug in odds_slugs:
                if f_h in slug and f_a in slug:
                    match_found = True
                    break
                    
        if match_found:
            survivors.append(fix)
        else:
            short_name = f"{fix.get('home_team')} vs {fix.get('away_team')}"
            logger.info(f"    - Drop temprano (Sin Mercado): {short_name}")
            dropped += 1
            
    if dropped > 0:
        logger.warning(f"  🔪 CRIBADORA: {dropped} partidos purgados previo al Análisis profundo (Quedan: {len(survivors)}).")
        
    return {"fixtures": survivors}


def should_continue(state: AgentState) -> str:
    """
    Router que decide continuar o abortar el pipeline.
    Nueva regla v13.7: si NO hay cuotas (odds) tras los fetchers iniciales,
    se DETIENE el pipeline para evitar predicciones sin mercado.
    """
    has_odds = state.get("odds_canonical") and len(state["odds_canonical"]) > 0
    has_fixtures = state.get("fixtures") and len(state["fixtures"]) > 0

    logger.info(
        f"PIPELINE CHECK: Fixtures count={len(state.get('fixtures') or [])} | Odds count={len(state.get('odds_canonical') or [])}"
    )

    # Abort total si no hay ni fixtures ni odds
    if not has_odds and not has_fixtures:
        logger.warning("\n" + "!" * 80)
        logger.warning("PIPELINE ABORTED: No matches found in any competition.")
        logger.warning(
            "Tried: [Agente #1 API-Football, Agente #1.1 Web Scraper, Agente #2 The Odds API, Agente #2.1 Web Odds]"
        )
        logger.warning("!" * 80 + "\n")
        return END

    # v13.7: Abortar si no hay odds (aunque existan fixtures)
    if not has_odds:
        logger.warning("\n" + "!" * 80)
        logger.warning("PIPELINE ABORTED: No market odds available after initial agents.")
        logger.warning("Regla v13.7: sin cuotas → no hay predicciones ni etapas posteriores.")
        logger.warning("!" * 80 + "\n")
        return END

    return "stats_agent"


def build_pipeline() -> StateGraph:
    """
    Build and return the LangGraph StateGraph for the multiagent pipeline.
    
    Topology:
    - START -> odds_fetcher (Agente #1)
    - odds_fetcher -> should_continue (router)
    - should_continue -> stats_agent (if matches) OR END (if empty)
    - stats_agent onwards (linear flow until END)
    
    Returns:
        StateGraph object ready to compile and invoke
    """
    
    # Create state graph
    graph = StateGraph(AgentState)

    # ── Nodos ─────────────────────────────────────────────────────────────────
    graph.add_node("fixtures_fetcher", fixtures_fetcher_node)  # Agente #1: fixtures oficiales
    graph.add_node("web_fixtures_fetcher", web_fixtures_fetcher_node) # Agente #1.1: respaldo web
    graph.add_node("odds_fetcher",     odds_fetcher_node)      # Agente #2: partidos + cuotas
    graph.add_node("web_odds_fetcher", web_odds_fetcher_node)  # Agente #2.1: respaldo web de cuotas
    graph.add_node("prune_fixtures", prune_fixtures_node)    # Agente Guardián: Guillotina de Fixtures
    graph.add_node("stats_agent",      stats_agent_node)       # Agente #2: estadísticas ESPN
    graph.add_node("journalist_agent", journalist_agent_node)  # Agente #3: descubrimiento YouTube
    graph.add_node("web_agent",        web_agent_node)         # Agente #3.5: contexto web por torneo
    graph.add_node("insights_agent",   insights_agent_node)    # Agente #4: insights YouTube/LLM
    graph.add_node("normalizer_agent", normalizer_agent_node)  # Agente #5: cruce y consolidación
    graph.add_node("gate_agent",       gate_agent_node)        # Agente #5.5: filtro de calidad
    graph.add_node("analyst_agent",    analyst_agent_node)     # Agente #6: predicciones
    graph.add_node("bettor_agent",     bettor_agent_node)      # Agente #7: tips de apuesta

    # ── Aristas y Router ───────────────────────────────────────────────────────
    graph.add_edge(START,               "fixtures_fetcher")
    graph.add_edge("fixtures_fetcher",  "web_fixtures_fetcher")
    graph.add_edge("web_fixtures_fetcher", "odds_fetcher")
    graph.add_edge("odds_fetcher",     "web_odds_fetcher")
    
    graph.add_edge("web_odds_fetcher", "prune_fixtures")
    
    # Router después de fetcher/poda para abortar si no nos quedan partidos apostables
    graph.add_conditional_edges(
        "prune_fixtures",
        should_continue,
        {
            "stats_agent": "stats_agent",
            END: END
        }
    )
    
    graph.add_edge("stats_agent",       "journalist_agent")
    graph.add_edge("journalist_agent",  "web_agent")
    graph.add_edge("web_agent",         "insights_agent")
    graph.add_edge("insights_agent",    "normalizer_agent")
    graph.add_edge("normalizer_agent",  "gate_agent")
    graph.add_edge("gate_agent",        "analyst_agent")
    graph.add_edge("analyst_agent",     "bettor_agent")
    graph.add_edge("bettor_agent",      END)

    logger.info(
        "Pipeline: START → odds → [router] → stats → journalist → web_agent → insights → normalizer → gate → analyst → bettor → END"
    )

    return graph


def create_initial_state(
    competitions: list[dict[str, Any]],
    include_fixtures: bool = True,
    include_odds: bool = True,
    fixtures_days_ahead: int = 7
) -> AgentState:
    """
    Create initial state for pipeline execution.
    
    Args:
        competitions: List of competition configurations.
                     Example:
                     [
                         {"competition": "UCL", "fixtures_provider": "football-data", "competition_code": "CL"},
                         {"competition": "CHI1", "fixtures_provider": "football-data", "competition_code": None}
                     ]
        include_fixtures: Whether to enable fixtures agent (default: True)
        include_odds: Whether to enable odds agent (default: True)
        fixtures_days_ahead: Number of days ahead to fetch fixtures for (default: 7)
    
    Returns:
        AgentState ready for pipeline.invoke()
    
    State structure initialized with:
    - messages: Empty list for audit trail
    - fixtures: None (populated by Agente #1)
    - fixtures_raw: None (populated by Agente #1)
    - odds_raw: None (populated by Agente #2)
    - odds_canonical: None (populated by Agente #2)
    - competitions: Configuration list
    - fixtures_date_from: Today (ISO 8601)
    - fixtures_date_to: Today + fixtures_days_ahead (ISO 8601)
    - meta: Execution metadata (timestamps, counts, errors)
    """
    
    # Calculate date range for fixtures (today to N days ahead)
    today = datetime.now()
    date_from = today.strftime("%Y-%m-%d")
    date_to = (today + timedelta(days=fixtures_days_ahead)).strftime("%Y-%m-%d")
    
    return AgentState(
        messages=[
            AIMessage(
                content=(
                    f"Pipeline initialized with {len(competitions)} competitions. "
                    f"Fixtures: {include_fixtures} (dates {date_from} to {date_to}), "
                    f"Odds: {include_odds}"
                )
            )
        ],
        fixtures=None,
        fixtures_raw=None,
        odds_raw=None,
        odds_canonical=None,
        competitions=competitions,
        fixtures_date_from=date_from,
        fixtures_date_to=date_to,
        meta={
            "started_at": datetime.now().isoformat(),
            "include_fixtures": include_fixtures,
            "include_odds": include_odds,
            "fixtures_date_range": f"{date_from} to {date_to}",
            "total_fixtures": 0,
            "total_odds": 0,
            "fixtures_counts": {},
            "odds_counts": {},
            "cache_hits": {
                "fixtures": 0,
                "odds": 0
            },
            "errors": {
                "fixtures": {},
                "odds": {}
            },
            "rate_limit_info": {},
            "processing_time_seconds": 0.0
        }
    )


class PipelineExecutor:
    """
    Executes the multiagent pipeline with proper error handling and reporting.
    
    Attributes:
        graph (StateGraph): The compiled LangGraph
    """
    
    def __init__(self):
        """Initialize pipeline executor."""
        self.graph = build_pipeline()
        self.compiled = self.graph.compile()
        logger.info("Pipeline executor initialized")
    
    def execute(
        self,
        initial_state: AgentState,
        verbose: bool = False
    ) -> AgentState:
        """
        Execute the pipeline with the given initial state.
        
        Args:
            initial_state: AgentState from create_initial_state()
            verbose: If True, log detailed node execution
        
        Returns:
            Final AgentState with all data populated
        
        Raises:
            Exception: If critical errors occur (though pipeline tries to be resilient)
        """
        logger.info("=" * 80)
        logger.info("STARTING MULTIAGENT PIPELINE")
        logger.info("=" * 80)
        
        try:
            result = self.compiled.invoke(initial_state)
            
            # Final metadata
            result["meta"]["completed_at"] = datetime.now().isoformat()
            
            logger.info("=" * 80)
            logger.info("PIPELINE EXECUTION COMPLETE")
            logger.info("=" * 80)
            
            return result
        
        except Exception as e:
            logger.error(f"Pipeline execution failed: {str(e)}", exc_info=True)
            raise


# Convenience function for pipeline execution
async def run_pipeline(
    competitions: list[dict[str, Any]],
    include_fixtures: bool = True,
    include_odds: bool = True,
    fixtures_days_ahead: int = 7,
    verbose: bool = False
) -> AgentState:
    """
    Quick start: Create and execute pipeline in one call.
    
    Args:
        competitions: Competition configurations
        include_fixtures: Include Agente #1 (default: True)
        include_odds: Include Agente #2 (default: True)
        fixtures_days_ahead: Days ahead to fetch fixtures for (default: 7)
        verbose: Verbose logging (default: False)
    
    Returns:
        Final AgentState with all results
    
    Example:
        >>> competitions = [
        ...     {"competition": "UCL", "fixtures_provider": "football-data", "competition_code": "CL"},
        ... ]
        >>> result = await run_pipeline(competitions, fixtures_days_ahead=7)
        >>> print(f"Got {result['meta']['total_fixtures']} fixtures")
    """
    
    executor = PipelineExecutor()
    initial_state = create_initial_state(
        competitions,
        include_fixtures=include_fixtures,
        include_odds=include_odds,
        fixtures_days_ahead=fixtures_days_ahead
    )
    
    return executor.execute(initial_state, verbose=verbose)
