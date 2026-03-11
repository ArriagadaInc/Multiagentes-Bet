"""
Shared state for multiagent LangGraph pipeline.

Defines the AgentState TypedDict that manages communication between:
- Agente #1 (Fixtures Fetcher - football-data.org)
- Agente #2 (Odds Fetcher - The Odds API)
- Future Agente #3 (Analyst)
"""

from typing import TypedDict, Optional, Any
from langchain_core.messages import BaseMessage


class AgentState(TypedDict, total=False):
    """
    Shared state dictionary for multiagent pipeline.
    
    Fields:
        messages: List of LangChain BaseMessages for audit trail and inter-agent communication.
        
        fixtures: Normalized list of fixture objects from Agente #1.
                 Format: [{"competition": "UCL", "fixture_id": "...", ...}, ...]
        
        fixtures_raw: Raw response from football-data API, grouped by competition.
                      Format: {
                          "UCL": {"matches": [...], "count": N, "source": "football-data"},
                          "CHI1": {...}
                      }
        
        odds_raw: Raw response from The Odds API, grouped by competition.
                 Reserved for Agente #2.
        
        odds_canonical: Normalized odds output from Agente #2.
                       Format: [{"competition": "UCL", "odds": {...}, ...}, ...]
        
        competitions: Configuration list of competitions to fetch data for.
                     Format: [
                         {"competition": "UCL", "fixtures_provider": "football-data", "competition_code": "CL"},
                         {"competition": "CHI1", "fixtures_provider": "football-data", "competition_code": None}
                     ]
        
        meta: Metadata dict tracking pipeline execution.
             Example: {
                 "generated_at": "2024-01-15T10:30:00Z",
                 "total_fixtures": 123,
                 "total_odds": 456,
                 "fixtures_counts": {"UCL": 50, "CHI1": 0},
                 "odds_counts": {"UCL": 200, "CHI1": 256},
                 "cache_hits": {"fixtures": 1, "odds": 1},
                 "errors": {
                     "fixtures": {"CHI1": "No coverage available in free tier"},
                     "odds": {}
                 },
                 "rate_limit_info": {"remaining": 98, "reset_at": "..."},
                 "processing_time_seconds": 2.45
             }
    """
    
    # Audit trail
    messages: list[BaseMessage]
    
    # Agente #1 (Fixtures) outputs
    fixtures: Optional[list[dict[str, Any]]]
    fixtures_raw: Optional[dict[str, Any]]
    
    # Agente #2 (Odds) outputs
    odds_raw: Optional[dict[str, Any]]
    odds_canonical: Optional[list[dict[str, Any]]]
    
    # Configuration
    competitions: list[dict[str, Any]]
    fixtures_date_from: Optional[str]
    fixtures_date_to: Optional[str]
    
    # Metadata
    meta: dict[str, Any]

    # Agente #3 (Insights) outputs
    insights: Optional[list[dict[str, Any]]]
    insights_sources: Optional[dict[str, list[str]]]

    # Agente #4 (Stats) outputs
    stats_by_team: Optional[list[dict[str, Any]]]

    # Agente Normalizador outputs
    match_contexts: Optional[list[dict[str, Any]]]
    """
    Format: [
        {
            "match_id": "UCL_2026-02-25_home_away",
            "match_key": "deterministic_key",
            "data_quality": {
                "score": 0.85,
                "reasons": [...],
                "source_hierarchy": [...]
            },
            ...
        }
    ]
    """

    # Agente #5 (Analyst) outputs
    predictions: Optional[list[dict[str, Any]]]
    
    # Agente #6 (Bettor) outputs
    betting_tips: Optional[list[dict[str, Any]]]

    # Agente Periodista outputs
    journalist_videos: Optional[dict[str, Any]]

    # Analyst Web Checks output (auditoría de búsquedas en tiempo real)
    analyst_web_checks: Optional[list[dict[str, Any]]]

