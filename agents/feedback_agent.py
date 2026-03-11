"""
Feedback Agent: análisis de patrones de error y generación de memoria del analista.

Corre después del Post-Match Agent.
Usa GPT-5 para generar lecciones concretas y accionables por liga.

Salida: predictions/analyst_memory.json (lecciones separadas por CHI1 y UCL)
"""

import json
import logging
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

PREDICTIONS_FILE     = os.path.join("predictions", "predictions_history.json")
ANALYST_MEMORY_FILE  = os.path.join("predictions", "analyst_memory.json")

FEEDBACK_MODEL = "gpt-5-2025-08-07"   # GPT-5 como solicitó Álvaro


# ─── Estadísticas por liga ────────────────────────────────────────────────────

def _compute_league_stats(evaluated: List[Dict]) -> Dict:
    """Calcula estadísticas detalladas segmentadas por liga."""
    leagues: Dict[str, List[Dict]] = defaultdict(list)
    for p in evaluated:
        comp = p.get("competition", "?")
        leagues[comp].append(p)

    result = {}
    for comp, preds in leagues.items():
        correct = [p for p in preds if p.get("correct")]
        wrong   = [p for p in preds if not p.get("correct")]

        # Distribución de signos predichos vs reales
        pred_dist  = Counter(p.get("prediction") for p in preds)
        real_dist  = Counter(p.get("result") for p in preds)

        # Precisión por signo
        accuracy_by_sign = {}
        for sign in ("1", "X", "2"):
            sign_preds = [p for p in preds if p.get("prediction") == sign]
            sign_ok    = [p for p in sign_preds if p.get("correct")]
            if sign_preds:
                accuracy_by_sign[sign] = {
                    "predicted": len(sign_preds),
                    "correct":   len(sign_ok),
                    "accuracy":  round(len(sign_ok) / len(sign_preds) * 100, 1),
                }

        # Calcular error_type retroactivamente si no hay observation
        error_counts: Counter = Counter()
        for p in preds:
            obs = p.get("post_match_observation")
            if obs and isinstance(obs, dict):
                error_counts[obs.get("error_type", "unknown")] += 1
            elif p.get("correct") is True:
                error_counts["correct"] += 1
            elif p.get("correct") is False:
                actual = p.get("result", "?")
                if actual != "?":
                    # Clasificar inline sin import dinámico para evitar problemas de path
                    pred_sign = p.get("prediction","")
                    conf      = p.get("confidence", 0) or 0
                    flags     = p.get("data_quality_flags") or []
                    if actual == "X" and pred_sign in ("1","2"):
                        error_counts["draw_missed"] += 1
                    elif pred_sign == "1" and actual == "2":
                        error_counts["home_bias"] += 1
                    elif conf > 65:
                        error_counts["overconfident_wrong"] += 1
                    elif any(f in flags for f in ("home_pos_99","away_pos_99","no_espn_stats")):
                        error_counts["data_poverty_miss"] += 1
                    else:
                        error_counts["market_alignment_loss"] += 1

        # Análisis de datos de calidad
        pos_99_preds  = [p for p in wrong if "home_pos_99" in (p.get("data_quality_flags") or [])
                         or "away_pos_99" in (p.get("data_quality_flags") or [])]
        no_yt_preds   = [p for p in wrong if "no_youtube_insights" in (p.get("data_quality_flags") or [])]

        # Confianza global y calibración
        confs_ok  = [p.get("confidence", 0) for p in correct if p.get("confidence")]
        confs_bad = [p.get("confidence", 0) for p in wrong   if p.get("confidence")]
        avg_conf_ok  = round(sum(confs_ok)  / len(confs_ok),  1) if confs_ok  else None
        avg_conf_bad = round(sum(confs_bad) / len(confs_bad), 1) if confs_bad else None

        result[comp] = {
            "total":   len(preds),
            "correct": len(correct),
            "wrong":   len(wrong),
            "accuracy": round(len(correct) / len(preds) * 100, 1) if preds else 0,
            "pred_distribution": dict(pred_dist),
            "real_distribution": dict(real_dist),
            "accuracy_by_sign":  accuracy_by_sign,
            "error_counts":      dict(error_counts),
            "data_poverty_wrong": len(pos_99_preds),
            "no_insights_wrong":  len(no_yt_preds),
            "avg_confidence_correct":   avg_conf_ok,
            "avg_confidence_incorrect": avg_conf_bad,
        }

    return result


# ─── Generación de lecciones con GPT-5 ───────────────────────────────────────

def _generate_lessons_llm(comp: str, stats: Dict) -> Dict[str, Any]:
    """
    Usa GPT-5 para generar lecciones concretas y accionables basándose
    en las estadísticas de una liga específica.
    Retorna dict con lessons, top_lesson y calibration_note.
    """
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        acc_by_sign_text = "\n".join([
            f"  - Signo '{s}': {v['predicted']} predicciones, {v['correct']} correctas ({v['accuracy']}%)"
            for s, v in stats.get("accuracy_by_sign", {}).items()
        ])

        error_text = "\n".join([
            f"  - {etype}: {cnt} casos ({round(cnt/stats['total']*100,1)}%)"
            for etype, cnt in sorted(stats.get("error_counts", {}).items(), key=lambda x: -x[1])
        ])

        prompt = f"""Eres un experto en análisis estadístico de apuestas deportivas.
Analiza estas estadísticas de predicciones para la liga {comp} y genera lecciones CONCRETAS y ACCIONABLES.

ESTADÍSTICAS:
- Total predicciones evaluadas: {stats['total']}
- Precisión global: {stats['accuracy']}%
- Distribución predicciones: {stats['pred_distribution']}
- Distribución resultados reales: {stats['real_distribution']}
- Confianza media en correctos: {stats.get('avg_confidence_correct')}%
- Confianza media en incorrectos: {stats.get('avg_confidence_incorrect')}%

PRECISIÓN POR SIGNO PREDICHO:
{acc_by_sign_text}

TIPOS DE ERROR:
{error_text}

DATOS DE CALIDAD:
- Errores con datos pobres (pos=99): {stats.get('data_poverty_wrong')} casos
- Errores sin insights YouTube: {stats.get('no_insights_wrong')} casos

Genera un JSON con esta estructura EXACTA (sin markdown):
{{
  "lessons": [
    {{
      "pattern": "nombre del patrón (ej: draw_missed)",
      "severity": "alta/media/baja",
      "description": "descripción del problema en 1 línea",
      "lesson": "regla concreta y accionable para el analista en 2-3 líneas. Debe ser específica para {comp}."
    }}
  ],
  "calibration_note": "nota concreta sobre calibración de confianza para {comp} en 1-2 líneas",
  "top_lesson": "la lección más importante de todas, en 1-2 oraciones directas al analista"
}}

Crea entre 3 y 6 lecciones, ordenadas por severidad (alta primero).
Sé muy específico con la liga {comp}. Las lecciones deben ser directamente usables en el prompt de predicción.
"""

        response = client.chat.completions.create(
            model=FEEDBACK_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )

        content = response.choices[0].message.content.strip()
        # Limpiar markdown si existe
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        result = json.loads(content)
        logger.info(f"Feedback Agent: {len(result.get('lessons', []))} lecciones generadas para {comp}")
        return result

    except Exception as e:
        logger.error(f"Error generando lecciones con LLM para {comp}: {e}")
        # Fallback: lecciones básicas hardcodeadas basadas en las stats
        return _generate_lessons_fallback(comp, stats)


def _generate_lessons_fallback(comp: str, stats: Dict) -> Dict[str, Any]:
    """Genera lecciones básicas sin LLM como fallback."""
    lessons = []
    error_counts = stats.get("error_counts", {})

    if error_counts.get("draw_missed", 0) > 3:
        lessons.append({
            "pattern": "draw_missed",
            "severity": "alta",
            "description": "El modelo predice 1 o 2 cuando el resultado es empate",
            "lesson": f"En {comp}, los empates representan ~27% de los resultados. Si la cuota de empate es <= 3.20, el empate es igualmente probable. No lo descartes sin evidencia concreta."
        })
    if error_counts.get("home_bias", 0) > 2:
        lessons.append({
            "pattern": "home_bias",
            "severity": "alta",
            "description": "Sesgo al equipo local sin evidencia suficiente",
            "lesson": f"En {comp}, el local gana solo ~40% del tiempo. Ser local NO es razón suficiente para predecir victoria."
        })
    if stats.get("data_poverty_wrong", 0) > 2:
        lessons.append({
            "pattern": "data_poverty_miss",
            "severity": "alta",
            "description": "Errores cuando no hay datos ESPN (pos=99)",
            "lesson": "Cuando los datos de ESPN no están disponibles (pos=99), sigue ciegamente al favorito del mercado sin ajustar."
        })

    top = lessons[0]["lesson"] if lessons else "Seguir al favorito del mercado cuando no hay datos concretos."
    return {
        "lessons": lessons,
        "calibration_note": f"La confianza media en correctos ({stats.get('avg_confidence_correct')}%) es apenas superior a la de incorrectos ({stats.get('avg_confidence_incorrect')}%). No uses confianza > 65% sin evidencia concreta.",
        "top_lesson": top,
    }


# ─── Nodo principal ───────────────────────────────────────────────────────────

def run_feedback_agent(progress_callback=None) -> Dict:
    """
    Analiza el historial de predicciones evaluadas, segmenta por liga,
    genera lecciones con GPT-5 y guarda analyst_memory.json.
    """
    if not os.path.exists(PREDICTIONS_FILE):
        return {"error": "No existe predictions_history.json"}

    with open(PREDICTIONS_FILE, "r", encoding="utf-8") as f:
        predictions = json.load(f)

    evaluated = [
        p for p in predictions
        if p.get("evaluation_status") == "OK" and p.get("correct") is not None
    ]

    if not evaluated:
        return {"error": "No hay predicciones evaluadas en el historial"}

    if progress_callback:
        progress_callback(f"Analizando {len(evaluated)} predicciones evaluadas...")

    # Estadísticas globales
    total_correct = sum(1 for p in evaluated if p.get("correct"))
    accuracy_overall = round(total_correct / len(evaluated) * 100, 1)

    # Estadísticas por liga
    league_stats = _compute_league_stats(evaluated)

    # Generar lecciones con GPT-5 por liga
    lessons_by_league: Dict[str, Any] = {}
    for comp, stats in league_stats.items():
        if progress_callback:
            progress_callback(f"Generando lecciones para {comp} con GPT-5...")
        logger.info(f"Generando lecciones para {comp}...")
        lessons_by_league[comp] = _generate_lessons_llm(comp, stats)

    # Construir memoria del analista
    memory = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_evaluated": len(evaluated),
        "accuracy_overall": accuracy_overall,
        "by_league": {},
    }

    for comp, stats in league_stats.items():
        lessons_data = lessons_by_league.get(comp, {})
        memory["by_league"][comp] = {
            "stats": {
                "total":    stats["total"],
                "correct":  stats["correct"],
                "accuracy": stats["accuracy"],
                "accuracy_by_sign": stats["accuracy_by_sign"],
                "pred_distribution": stats["pred_distribution"],
                "real_distribution": stats["real_distribution"],
                "error_counts":      stats["error_counts"],
                "avg_confidence_correct":   stats.get("avg_confidence_correct"),
                "avg_confidence_incorrect": stats.get("avg_confidence_incorrect"),
            },
            "lessons":          lessons_data.get("lessons", []),
            "calibration_note": lessons_data.get("calibration_note", ""),
            "top_lesson":       lessons_data.get("top_lesson", ""),
        }

    # Guardar
    os.makedirs("predictions", exist_ok=True)
    with open(ANALYST_MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2, ensure_ascii=False)

    logger.info(f"Analyst memory guardada: {ANALYST_MEMORY_FILE}")
    if progress_callback:
        progress_callback(f"✅ Memoria del analista actualizada con lecciones de {', '.join(league_stats.keys())}")

    return {
        "total_evaluated": len(evaluated),
        "accuracy_overall": accuracy_overall,
        "leagues": list(league_stats.keys()),
        "memory_file": ANALYST_MEMORY_FILE,
    }


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s")
    result = run_feedback_agent(progress_callback=lambda msg: print(msg))
    print(f"\nResumen: {result}")
