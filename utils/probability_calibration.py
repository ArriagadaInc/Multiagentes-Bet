"""
Calibración simple de probabilidad a partir de la confianza del analista.

Primera versión:
- Conservadora
- Penaliza calidad degradada y flags de datos faltantes
- No asume que confidence == probabilidad real
"""

from __future__ import annotations


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def calibrate_prediction_probability(
    pick: str,
    confidence: float,
    gate_status: str = "clean",
    data_quality_flags: list[str] | None = None,
    had_youtube_insights: bool | None = None,
    had_espn_stats: bool | None = None,
) -> float:
    """
    Convierte confianza del analista en probabilidad utilizable para staking.

    Notas:
    - Conservadora por diseño.
    - Usa castigos suaves por deterioro de calidad.
    - Mantiene un suelo para que no colapse por falta parcial de datos.
    """
    p = _clamp(float(confidence) / 100.0, 0.05, 0.95)
    flags = [str(x or "").strip().lower() for x in (data_quality_flags or []) if str(x or "").strip()]

    gate = str(gate_status or "clean").strip().lower()
    if gate == "degraded":
        p -= 0.05
    elif gate == "observation":
        p -= 0.10
    elif gate == "blocked":
        p -= 0.20

    if had_youtube_insights is False:
        p -= 0.03
    if had_espn_stats is False:
        p -= 0.04

    for flag in flags:
        if "youtube" in flag:
            p -= 0.02
        elif "odds" in flag:
            p -= 0.01
        elif "stats" in flag:
            p -= 0.03
        else:
            p -= 0.01

    # Penalización ligera adicional para picks X por mayor varianza estructural.
    if str(pick or "").upper() == "X":
        p -= 0.01

    return _clamp(p, 0.05, 0.90)
