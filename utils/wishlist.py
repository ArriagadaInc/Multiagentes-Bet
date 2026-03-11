import os
import json
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

ANALYST_WISHLIST_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "predictions", "analyst_wishlist.json"
)

def load_analyst_wishlist() -> List[Dict[str, Any]]:
    """Carga la bitácora del analista desde el archivo JSON."""
    if not os.path.exists(ANALYST_WISHLIST_FILE):
        return []
    try:
        with open(ANALYST_WISHLIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Error cargando analyst_wishlist.json: {e}")
        return []

def save_analyst_wishlist(items: List[Dict[str, Any]]) -> bool:
    """Guarda la bitácora del analista en el archivo JSON."""
    try:
        with open(ANALYST_WISHLIST_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error guardando analyst_wishlist.json: {e}")
        return False

def get_wishlist_for_teams(teams: List[str]) -> List[Dict[str, Any]]:
    """
    Obtiene los items de la wishlist relevantes para una lista de equipos.
    Ahora soporta la estructura PLANA y PERSISTENTE.
    - Los items con 'teams_affected' vacío son GLOBALES (se aplican a todo partido).
    - Los items con equipos se filtran si el equipo está en 'teams'.
    """
    items = load_analyst_wishlist()
    relevant_items = []
    
    seen_needs = set()
    teams_lower = [t.lower().strip() for t in teams]
    
    # Recorrer items de la wishlist plana
    for item in items:
        affected = [t.lower().strip() for t in item.get("teams_affected", [])]
        
        # Un item es relevante si:
        # 1. No tiene equipos afectados (es un interés GLOBAL del analista)
        # 2. Alguno de sus equipos afectados está en el partido actual
        is_global = len(affected) == 0
        matches_team = any(t in teams_lower for t in affected)
        
        if is_global or matches_team:
            need = item.get("need", "").strip()
            if need and need not in seen_needs:
                relevant_items.append(item)
                seen_needs.add(need)
                    
    # Retornar los top 10 (puedes ajustar este límite)
    return relevant_items[:12]

def get_wishlist_context_str(teams: List[str]) -> str:
    """Retorna un string formateado con las necesidades del analista para el prompt."""
    items = get_wishlist_for_teams(teams)
    if not items:
        return ""
    
    lines = ["\n### NECESIDADES ESPECÍFICAS DEL ANALISTA (Priorizar en la búsqueda):"]
    for item in items:
        priority = item.get("priority", "media").upper()
        category = item.get("category", "info").upper()
        need = item.get("need", "")
        affected = ", ".join(item.get("teams_affected", []))
        lines.append(f"- [{priority}][{category}] Para {affected}: {need}")
    
    return "\n".join(lines)
