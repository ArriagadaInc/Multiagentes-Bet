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
    
    # Nombre canónico normalizado (sin variaciones de proveedores)
    canonical_name: Optional[str] = None
    
    # Metadatos de calidad sugeridos por Gepeto
    data_quality_score: float = Field(default=1.0, ge=0.0, le=1.0)
    quality_notes: List[str] = []
    
    # Campos avanzados para UCL (FBref/Understat)
    advanced_stats: Dict[str, Any] = {}
