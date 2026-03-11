
import requests
import logging
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

class ESPNAPI:
    """Utilidad para interactuar con la API de ESPN Sports Data."""
    
    BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer"
    WEB_BASE_URL = "https://site.web.api.espn.com/apis/site/v2/sports/soccer"

    @staticmethod
    def get_scoreboard(league: str, date_yyyymmdd: str) -> Optional[Dict]:
        """
        Obtiene el scoreboard para una liga y fecha específica.
        URL: site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard?dates=YYYYMMDD
        """
        url = f"{ESPNAPI.BASE_URL}/{league}/scoreboard"
        params = {"dates": date_yyyymmdd}
        
        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching ESPN scoreboard ({league}, {date_yyyymmdd}): {e}")
            return None

    @staticmethod
    def get_summary(league: str, event_id: str) -> Optional[Dict]:
        """
        Obtiene el resumen detallado de un partido.
        URL: site.web.api.espn.com/apis/site/v2/sports/soccer/{league}/summary?event={eventId}
        """
        url = f"{ESPNAPI.WEB_BASE_URL}/{league}/summary"
        params = {"event": event_id}
        
        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching ESPN summary ({league}, {event_id}): {e}")
            return None
