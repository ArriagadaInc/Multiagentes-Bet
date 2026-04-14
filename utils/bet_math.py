"""
Utilidades matemáticas para evaluación de apuestas y staking.
"""

from __future__ import annotations

from math import prod


def implied_probability(odds_decimal: float) -> float:
    """Retorna probabilidad implícita en rango 0-1."""
    if odds_decimal <= 1.0:
        return 1.0
    return 1.0 / float(odds_decimal)


def expected_value(probability: float, odds_decimal: float) -> float:
    """
    EV por unidad apostada.

    EV = p * (odds - 1) - (1 - p)
    """
    p = max(0.0, min(1.0, float(probability)))
    o = float(odds_decimal)
    return (p * (o - 1.0)) - (1.0 - p)


def kelly_fraction(probability: float, odds_decimal: float) -> float:
    """Fracción Kelly teórica en rango [0, +inf)."""
    p = max(0.0, min(1.0, float(probability)))
    o = float(odds_decimal)
    if o <= 1.0:
        return 0.0
    b = o - 1.0
    q = 1.0 - p
    frac = ((b * p) - q) / b
    return max(0.0, frac)


def fractional_kelly(probability: float, odds_decimal: float, fraction: float = 0.25) -> float:
    """Kelly reducido para control de volatilidad."""
    return max(0.0, kelly_fraction(probability, odds_decimal) * max(0.0, float(fraction)))


def combo_probability(probabilities: list[float], correlation_penalty: float = 0.90) -> float:
    """Probabilidad aproximada de combinada con penalización conservadora."""
    if not probabilities:
        return 0.0
    clean = [max(0.0, min(1.0, float(p))) for p in probabilities]
    return max(0.0, min(1.0, prod(clean) * max(0.0, min(1.0, float(correlation_penalty)))))


def combo_odds(odds_values: list[float]) -> float:
    """Cuota decimal total de una combinada."""
    if not odds_values:
        return 0.0
    return float(prod(float(o) for o in odds_values))
