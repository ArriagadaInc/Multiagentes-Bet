import re
import os
import difflib
import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

def slugify(text: str) -> str:
    """Convierte un nombre de equipo a slug ASCII simple."""
    if not text:
        return ""
    text = str(text).lower().strip()
    # Caracteres latinos con diacríticos
    text = re.sub(r"[áàäâă]", "a", text)
    text = re.sub(r"[éèëê]", "e", text)
    text = re.sub(r"[íìïîı]", "i", text)   # ı = dotless i (turco)
    text = re.sub(r"[óòöô]", "o", text)
    text = re.sub(r"[úùüû]", "u", text)
    text = re.sub(r"[ñ]", "n", text)
    # Caracteres turcos adicionales
    text = re.sub(r"[ğ]", "g", text)   # ğ (g con cedilla)
    text = re.sub(r"[ş]", "s", text)   # ş (s con cedilla)
    text = re.sub(r"[ç]", "c", text)   # ç (c con cedilla)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text

class TeamNormalizer:
    """
    Normalizador de nombres de equipos utilizando fuzzy matching.
    Permite cruzar nombres de diferentes fuentes (ESPN vs Odds API).
    """

    def __init__(self, mapping_files: Optional[List[str]] = None):
        # Mapeos manuales base
        self.manual_map = {
            "sport lisboa e benfica": "benfica",
            "sl benfica": "benfica",
            "psg": "paris saint germain",
            "paris sg": "paris saint germain",
            "genoa cfc": "genoa",
            "real madrid cf": "real madrid",
            "fc barcelona": "barcelona",
            "atletico madrid": "atletico de madrid",
            "club atletico de madrid": "atletico de madrid",
            "bayer 04 leverkusen": "bayer leverkusen",
            "sporting cp": "sporting lisbon",
            "sporting clube de portugal": "sporting lisbon",
            "sporting club de portugal": "sporting lisbon",
        }

        # Asegurar que los nombres canónicos (valores) también se resuelvan a sí mismos
        # Esto previene que una entrada como "paris saint-germain" (que el slugifier procesa como "paris saint germain") 
        # devuelva un "miss" en el diccionario manual.
        for alias, canonical in list(self.manual_map.items()):
            if canonical not in self.manual_map:
                self.manual_map[canonical] = canonical
        
        # Si no se proveen archivos, buscar todos los golden_mapping en utils/
        if mapping_files is None:
            mapping_files = []
            utils_dir = "utils"
            if os.path.exists(utils_dir):
                for f in os.listdir(utils_dir):
                    if f.endswith("_golden_mapping.json"):
                        mapping_files.append(os.path.join(utils_dir, f))
        
        # Cargar cada archivo de mapeo
        for mf in mapping_files:
            if os.path.exists(mf):
                try:
                    import json
                    with open(mf, "r", encoding="utf-8") as f:
                        golden_data = json.load(f)
                        for entry in golden_data:
                            canonical = entry.get("canonical_name")
                            official = entry.get("official_name")
                            aliases = entry.get("aliases") or []
                            
                            if canonical:
                                # El nombre canónico se mapea a sí mismo
                                self.manual_map[self.clean_simple(canonical)] = canonical
                                if official:
                                    self.manual_map[self.clean_simple(official)] = canonical
                                for alias in aliases:
                                    self.manual_map[self.clean_simple(alias)] = canonical
                    logger.info(f"TeamNormalizer: {len(golden_data)} equipos cargados desde {mf}")
                except Exception as e:
                    logger.error(f"Error cargando Golden Mapping {mf}: {e}")

    def clean_simple(self, name: str) -> str:
        """Limpieza mínima para el mapeo (slugify-like)"""
        if not name: return ""
        # Usar slugify para que el match sea robusto a diacríticos y espacios
        return slugify(name).replace("-", " ")

    def clean(self, name: str) -> str:
        """Limpieza básica de strings"""
        if not name:
            return ""
        
        # Lowercase y strip
        name = name.lower().strip()
        
        # Eliminar sufijos/prefijos comunes de clubes
        replacements = [
            " cf", " fc", " sc", " cd", " ca", " ac", 
            "sad", "s.a.d.", "united", "city", "deportivo", "club"
        ]
        
        # Nota: Eliminar "united" o "city" puede ser peligroso (Manchester), 
        # pero para matching difuso a veces ayuda si el otro lado no lo tiene.
        # Por seguridad, solo quitamos FC/CF/CD genéricos al final o inicio.
        
        tokens = name.split()
        clean_tokens = [t for t in tokens if t not in ["cf", "fc", "cd", "ca"]]
        
        cleaned = " ".join(clean_tokens)
        
        # Mapeo manual directo pasándolo por clean_simple primero
        return self.manual_map.get(self.clean_simple(cleaned), cleaned)

    def find_match(self, team_name: str, candidates: List[str], threshold: float = 0.6) -> Optional[str]:
        """
        Busca el candidate mas parecido a team_name.
        Retorna el nombre encontrado en candidates o None.
        """
        if not team_name or not candidates:
            return None
            
        clean_team = self.clean(team_name)
        
        # 1. Match exacto post-limpieza
        # Pre-calcular limpieza de candidatos para eficiencia
        clean_candidates = {self.clean(c): c for c in candidates}
        
        if clean_team in clean_candidates:
            return clean_candidates[clean_team]
            
        # 2. Fuzzy match con difflib
        # get_close_matches retorna los mejores matches ordenados por score
        matches = difflib.get_close_matches(clean_team, clean_candidates.keys(), n=1, cutoff=threshold)
        
        if matches:
            best_match_clean = matches[0]
            original_candidate = clean_candidates[best_match_clean]
            
            # Loguear para depuración si el score no es perfecto
            score = difflib.SequenceMatcher(None, clean_team, best_match_clean).ratio()
            if score < 1.0:
                logger.debug(f"Fuzzy match: '{team_name}' ({clean_team}) -> '{original_candidate}' (score: {score:.2f})")
                
            return original_candidate
            
        return None
