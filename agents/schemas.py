from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class MatchStats(BaseModel):
    possession_pct: Optional[float] = None
    shots: Optional[int] = None
    shots_on_target: Optional[int] = None
    corners: Optional[int] = None
    fouls: Optional[int] = None

class RecentMatch(BaseModel):
    date: str
    opponent: str
    home_away: str
    score: str
    status: str
    venue: Optional[str] = None
    headline: Optional[str] = None
    goals: List[Dict[str, Any]] = []
    goals_against: List[Dict[str, Any]] = []
    cards: List[Dict[str, Any]] = []

class TopScorer(BaseModel):
    player: str
    goals: int
    assists: Optional[int] = 0
    position: Optional[str] = "?"

class LineupPlayer(BaseModel):
    name: str
    number: Optional[int] = None
    position: Optional[str] = None
    is_captain: bool = False

class Lineup(BaseModel):
    starting_xi: List[LineupPlayer] = []
    bench: List[LineupPlayer] = []
    coach: Optional[str] = None

class MatchFact(BaseModel):
    type: str  # goal, card, substitution
    minute: int
    player: str
    detail: Optional[str] = None

class TeamStatsLegacy(BaseModel):
    """Contrato legado para compatibilidad con Analyst Agent"""
    position: Optional[int] = None
    played: int = 0
    won: int = 0
    draw: int = 0
    lost: int = 0
    goals_for: int = 0
    goals_against: int = 0
    goal_difference: int = 0
    points: int = 0
    form: Optional[str] = ""
    match_stats: Optional[MatchStats] = None

class TeamStatsCanonical(BaseModel):
    """Esquema canónico para estadísticas de equipo enriquecidas"""
    team: str
    competition: str
    provider: str
    stats: TeamStatsLegacy
    top_scorers: List[TopScorer] = []
    recent_match: Optional[RecentMatch] = None
    lineup: Optional[Lineup] = None
    match_facts: List[MatchFact] = []
    
    # Metadatos de calidad sugeridos para el pipeline
    data_quality_score: float = Field(default=1.0, ge=0.0, le=1.0)
    quality_notes: List[str] = []
    
    # Campos avanzados para UCL (FBref/Understat)
    advanced_stats: Dict[str, Any] = {}


class CanonicalSignal(BaseModel):
    """Contrato canónico para señales contextuales consumibles por el pipeline."""
    team: str
    competition: str
    type: str
    signal: str
    evidence: Optional[str] = ""
    date: Optional[str] = None
    confidence: float = Field(default=0.4, ge=0.0, le=1.0)
    is_rumor: bool = False
    provenance: List[str] = []
    source_urls: List[str] = []

    subject_type: str = "unknown"
    epistemic_status: str = "HECHO"
    impact_axis: str = "general"
    impact_level: str = "medio"
    source_type: str = "unknown"
    source_quality: float = Field(default=0.5, ge=0.0, le=1.0)
    time_horizon: str = "short_term"
    relevance_to_match: str = "direct"
    relevance_to_1x2: str = "medium"
    freshness_score: float = Field(default=0.5, ge=0.0, le=1.0)
    trust_score: float = Field(default=0.5, ge=0.0, le=1.0)
    conflict_score: float = Field(default=0.0, ge=0.0, le=1.0)
    final_signal_score: float = Field(default=0.5, ge=0.0, le=1.0)
    resolution_status: str = "active"
    raw_excerpt: str = ""
    reasoning_note: str = ""
    impact_note: str = ""
