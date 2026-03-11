"""
Post-Match Agent: evaluación asíncrona post-partido.

Corre de forma INDEPENDIENTE del pipeline principal.
Se gatilla desde la UI con el botón "Ejecutar Agente Revisor".

Proceso:
1. Lee predictions_history.json
2. Filtra predicciones sin resultado (result=null) cuya match_date ya pasó
3. Consulta ESPN para obtener el resultado real
4. Clasifica el error con un tipo estandarizado
5. Genera post_match_observation estructurada
6. Actualiza predictions_history.json

Tipos de error:
- correct              → Predicción correcta ✅
- draw_missed          → Predijo 1 o 2, fue empate
- home_bias            → Predijo local (1) sin razón, ganó visitante (2)
- overconfident_wrong  → Confianza > 65%, resultado incorrecto
- market_divergence_loss → Se apartó del favorito del mercado y perdió
- market_alignment_loss  → Siguió al mercado y aun así perdió
- data_poverty_miss    → Falló con datos de baja calidad (pos=99, sin insights)
- upset               → Favorito del mercado perdió (resultado sorpresa)
"""

import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()

from utils.espn_api import ESPNAPI
from utils.normalizer import TeamNormalizer

logger = logging.getLogger(__name__)

PREDICTIONS_FILE = os.path.join("predictions", "predictions_history.json")
EVALUATION_SUMMARY_FILE = os.path.join("predictions", "evaluation_summary.json")

COMPETITION_MAP = {
    "CHI1": "chi.1",
    "UCL":  "uefa.champions",
}

# ─── Errores estandarizados ──────────────────────────────────────────────────

ERROR_TYPES = [
    "correct",
    "draw_missed",
    "home_bias",
    "overconfident_wrong",
    "market_divergence_loss",
    "market_alignment_loss",
    "data_poverty_miss",
    "upset",
]


def _normalize(name: str) -> str:
    """Normalización básica de nombre de equipo."""
    if not name:
        return ""
    n = name.lower()
    manual = {
        "internazionale": "inter milan",
        "fc internazionale milano": "inter milan",
        "inter milano": "inter milan",
        "bayer 04 leverkusen": "bayer leverkusen",
        "sport lisboa e benfica": "benfica",
        "sl benfica": "benfica",
        "club brugge kv": "club brugge",
        "atletico de madrid": "atletico madrid",
        "club atletico de madrid": "atletico madrid",
        "paris saint germain fc": "psg",
        "paris saint germain": "psg",
        "as monaco fc": "monaco",
        "sporting cp": "sporting lisbon",
        "fk bodo glimt": "bodo glimt",
        "bodo/glimt": "bodo glimt",
    }
    for k, v in manual.items():
        if k in n:
            n = n.replace(k, v)
            break
    n = re.sub(r'[áàäâă]', 'a', n)
    n = re.sub(r'[éèëê]', 'e', n)
    n = re.sub(r'[íìïî]', 'i', n)
    n = re.sub(r'[óòöôø]', 'o', n)
    n = re.sub(r'[úùüû]', 'u', n)
    n = n.replace('ñ', 'n')
    n = re.sub(r'\b(fc|cf|cd|club|sd|fk|kv|afc|utd|united|city|real|deportivo|deportes|atletico|as|us|sc)\b', '', n)
    n = re.sub(r'[^a-z0-9\s]+', ' ', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def _teams_match(a: str, b: str) -> bool:
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    import difflib
    return difflib.SequenceMatcher(None, na, nb).ratio() > 0.75


# ─── Clasificación de errores ─────────────────────────────────────────────────

def _classify_error(pred: Dict, actual_result: str) -> str:
    """
    Clasifica el tipo de error/acierto dado el resultado real.
    Devuelve un string del tipo de error estandarizado.
    """
    prediction = pred.get("prediction")
    confidence = pred.get("confidence", 0) or 0
    data_flags  = pred.get("data_quality_flags") or []

    if prediction == actual_result:
        return "correct"

    # Draw missed
    if actual_result == "X" and prediction in ("1", "2"):
        return "draw_missed"

    # Home bias: predijo local sin razón, ganó el visitante
    if prediction == "1" and actual_result == "2":
        if not pred.get("had_youtube_insights") or "home_pos_99" in data_flags:
            return "home_bias"
        return "home_bias"

    # Overconfident wrong
    if confidence > 65:
        return "overconfident_wrong"

    # Data poverty miss
    if any(f in data_flags for f in ("home_pos_99", "away_pos_99", "no_espn_stats")):
        return "data_poverty_miss"

    # Market divergence: se apartó del favorito del mercado y perdió
    mkt_prob = pred.get("market_prob_used")
    if mkt_prob and float(mkt_prob) > 50 and confidence < 60:
        return "market_alignment_loss"
    if mkt_prob and float(mkt_prob) < 40:
        return "market_divergence_loss"

    return "market_alignment_loss"


def _build_observation(pred: Dict, actual_result: str, actual_score: str) -> Dict:
    """Construye el dict post_match_observation para una predicción."""
    prediction = pred.get("prediction")
    confidence = pred.get("confidence", 0) or 0
    mkt_prob = pred.get("market_prob_used")
    error_type = _classify_error(pred, actual_result)

    market_expected = None
    if mkt_prob is not None:
        try:
            mp = float(mkt_prob)
            # El mercado esperaba el signo con mayor prob implícita
            # Usamos market_prob_used como proxy del signo elegido
            market_expected = prediction  # si siguió al mercado
        except Exception:
            pass

    obs = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "was_correct": prediction == actual_result,
        "predicted": prediction,
        "actual": actual_result,
        "actual_score": actual_score,
        "error_type": error_type,
        "confidence_at_prediction": confidence,
        "market_prob_at_prediction": mkt_prob,
        "data_quality_flags": pred.get("data_quality_flags") or [],
        "had_youtube_insights": pred.get("had_youtube_insights"),
        "had_espn_stats": pred.get("had_espn_stats"),
    }
    return obs


# ─── Obtención de resultado real de ESPN ─────────────────────────────────────

class PostMatchAgent:
    def __init__(self):
        self.espn = ESPNAPI()
        self._scoreboard_cache: Dict[str, Any] = {}

    def _get_scoreboard(self, league: str, date_str: str) -> Optional[Dict]:
        """Obtiene el scoreboard de ESPN para una liga y fecha."""
        key = f"{league}_{date_str}"
        if key in self._scoreboard_cache:
            return self._scoreboard_cache[key]
        try:
            data = self.espn.get_scoreboard(league, date_str)
            self._scoreboard_cache[key] = data
            return data
        except Exception as e:
            logger.warning(f"Error obteniendo scoreboard {league} {date_str}: {e}")
            return None

    def _find_event(self, pred: Dict, scoreboard: Dict) -> Optional[Dict]:
        """Busca el evento del partido en el scoreboard de ESPN."""
        events = scoreboard.get("events", [])
        home_t = pred.get("home_team", "")
        away_t = pred.get("away_team", "")

        for ev in events:
            comp = ev.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])
            if len(competitors) < 2:
                continue
            e_home, e_away = "", ""
            for c in competitors:
                if c.get("homeAway") == "home":
                    e_home = c.get("team", {}).get("name", "")
                elif c.get("homeAway") == "away":
                    e_away = c.get("team", {}).get("name", "")
            if _teams_match(home_t, e_home) and _teams_match(away_t, e_away):
                return ev
            if _teams_match(home_t, e_away) and _teams_match(away_t, e_home):
                return ev
        return None

    def _extract_result(self, event: Dict) -> Optional[Dict]:
        """Extrae el resultado final del evento ESPN."""
        try:
            comp = event.get("competitions", [{}])[0]
            status = comp.get("status", {}).get("type", {})
            if status.get("state") != "post":
                return None  # Partido no terminado

            competitors = comp.get("competitors", [])
            home_score = away_score = None
            for c in competitors:
                if c.get("homeAway") == "home":
                    home_score = int(c.get("score", 0))
                elif c.get("homeAway") == "away":
                    away_score = int(c.get("score", 0))

            if home_score is None or away_score is None:
                return None

            actual_score = f"{home_score}-{away_score}"
            if home_score > away_score:
                result = "1"
            elif home_score < away_score:
                result = "2"
            else:
                result = "X"

            return {"result": result, "actual_score": actual_score}
        except Exception as e:
            logger.warning(f"Error extrayendo resultado: {e}")
            return None

    def _parse_match_date(self, pred: Dict) -> Optional[str]:
        """Extrae la fecha del partido en formato YYYYMMDD."""
        # Priorizar match_date (fecha real del partido) sobre generated_at (fecha de la predicción)
        match_date = pred.get("match_date") or pred.get("generated_at")
        if not match_date:
            # Intentar extraer la fecha del prediction_id como último recurso
            pid = pred.get("prediction_id", "")
            m = re.search(r"(\d{4}-\d{2}-\d{2})", pid)
            if m:
                return m.group(1).replace("-", "")
            return None

        # Limpiar strings tipo "2026-03-05T00:00:00Z" o "2026-03-05"
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
            try:
                # Tomar solo la parte de fecha/hora básica para evitar problemas con offsets complejos
                clean_str = match_date[:19] if "T" in match_date else match_date[:10]
                dt = datetime.strptime(clean_str, fmt[:len(clean_str)])
                return dt.strftime("%Y%m%d")
            except Exception:
                pass
        
        return None

    def run(self, progress_callback=None) -> Dict:
        """
        Evalúa todas las predicciones pendientes (result=None) cuya fecha ya pasó.
        Retorna resumen de lo procesado.
        """
        if not os.path.exists(PREDICTIONS_FILE):
            return {"error": "No existe predictions_history.json"}

        with open(PREDICTIONS_FILE, "r", encoding="utf-8") as f:
            predictions = json.load(f)

        now = datetime.now(timezone.utc)
        pending = [
            p for p in predictions
            if p.get("result") is None and p.get("evaluation_status") != "OK"
        ]

        logger.info(f"Post-Match Agent: {len(pending)} predicciones pendientes de evaluar")
        if progress_callback:
            progress_callback(f"Evaluando {len(pending)} predicciones pendientes...")

        evaluated = 0
        not_found = 0
        skipped = 0

        for pred in pending:
            competition = pred.get("competition", "")
            league = COMPETITION_MAP.get(competition)
            if not league:
                skipped += 1
                continue

            date_str = self._parse_match_date(pred)
            if not date_str:
                skipped += 1
                continue

            # Verificar que la fecha ya pasó
            try:
                # Si match_date tiene solo fecha, asumimos el inicio del día
                # Le damos margen: si es hoy, esperamos al menos 4 horas después del inicio teórico
                match_dt = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
                if match_dt.date() > now.date():
                    skipped += 1
                    continue
                
                # Si es hoy, permitir evaluar si ya pasaron unas horas (proxy de fin de partido)
                # O simplemente confiar en el estado 'post' de ESPN que se chequea después
                if match_dt.date() == now.date() and match_dt + timedelta(hours=4) > now:
                    # Si no tenemos hora exacta, pecamos de conservadores
                    # Pero si ESPN dice que terminó, lo tomaremos igual más adelante
                    pass 
            except Exception:
                pass

            scoreboard = self._get_scoreboard(league, date_str)
            if not scoreboard:
                not_found += 1
                continue

            event = self._find_event(pred, scoreboard)
            if not event:
                logger.warning(f"Evento no encontrado: {pred.get('home_team')} vs {pred.get('away_team')} ({date_str})")
                not_found += 1
                continue

            result_data = self._extract_result(event)
            if not result_data:
                logger.info(f"Partido no terminado aún: {pred.get('home_team')} vs {pred.get('away_team')}")
                skipped += 1
                continue

            actual_result = result_data["result"]
            actual_score  = result_data["actual_score"]

            # Actualizar predicción en el historial
            pred["result"]       = actual_result
            pred["actual_score"] = actual_score
            pred["correct"]      = pred.get("prediction") == actual_result
            pred["evaluated_at"] = now.isoformat()
            pred["evaluation_status"] = "OK"
            pred["event_id"]     = event.get("id")
            pred["post_match_observation"] = _build_observation(pred, actual_result, actual_score)

            evaluated += 1
            status_msg = "✅" if pred["correct"] else "❌"
            logger.info(
                f"{status_msg} [{competition}] {pred.get('home_team')} vs {pred.get('away_team')}: "
                f"pred={pred.get('prediction')} real={actual_result} ({actual_score})"
            )
            if progress_callback:
                progress_callback(
                    f"{status_msg} {pred.get('home_team')} vs {pred.get('away_team')}: "
                    f"pred={pred.get('prediction')} real={actual_result}"
                )

        # Guardar historial actualizado
        with open(PREDICTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(predictions, f, indent=2, ensure_ascii=False)

        # Actualizar evaluation_summary.json
        _update_evaluation_summary(predictions)

        summary = {
            "evaluated": evaluated,
            "not_found": not_found,
            "skipped": skipped,
            "total_pending": len(pending),
        }
        logger.info(f"Post-Match Agent completado: {summary}")
        return summary


def _update_evaluation_summary(predictions: List[Dict]) -> None:
    """Actualiza el resumen de evaluación con los datos más recientes."""
    evaluated = [p for p in predictions if p.get("evaluation_status") == "OK" and "correct" in p and p["correct"] is not None]
    correct   = [p for p in evaluated if p.get("correct")]

    by_league: Dict[str, Dict] = {}
    for p in evaluated:
        comp = p.get("competition", "?")
        if comp not in by_league:
            by_league[comp] = {"total": 0, "correct": 0}
        by_league[comp]["total"] += 1
        if p.get("correct"):
            by_league[comp]["correct"] += 1

    by_model: Dict[str, Dict] = {}
    for p in evaluated:
        model = p.get("analyst_model_id", "?")
        if model not in by_model:
            by_model[model] = {"total": 0, "correct": 0}
        by_model[model]["total"] += 1
        if p.get("correct"):
            by_model[model]["correct"] += 1

    status_counts = {}
    for p in predictions:
        s = p.get("evaluation_status", "PENDING")
        status_counts[s] = status_counts.get(s, 0) + 1

    summary = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "total_evaluated": len(evaluated),
        "total_correct": len(correct),
        "overall_accuracy_pct": round(len(correct) / len(evaluated) * 100, 2) if evaluated else 0,
        "by_league": {
            comp: {
                "total": d["total"],
                "correct": d["correct"],
                "accuracy": round(d["correct"] / d["total"] * 100, 2) if d["total"] else 0,
            }
            for comp, d in by_league.items()
        },
        "by_model": {
            model: {
                "total": d["total"],
                "correct": d["correct"],
                "accuracy": round(d["correct"] / d["total"] * 100, 2) if d["total"] else 0,
            }
            for model, d in by_model.items()
        },
        "status_counts": status_counts,
    }

    os.makedirs("predictions", exist_ok=True)
    with open(EVALUATION_SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    logger.info(f"Evaluation summary actualizado: {summary['total_evaluated']} evaluadas, {summary['overall_accuracy_pct']}% precisión")


# ─── Entry point standalone ──────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s")
    agent = PostMatchAgent()
    result = agent.run(progress_callback=lambda msg: print(msg))
    print(f"\nResumen: {result}")
