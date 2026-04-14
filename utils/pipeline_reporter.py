"""
utils/pipeline_reporter.py
Módulo de Observabilidad Operativa (Tarea 5 - Plan de Acción V2)

Genera un resumen ASCII claro al final de cada corrida del pipeline, mostrando:
- Cuántos partidos entraron al Gate y cuántos pasaron.
- Motivo exacto de descarte de cada partido bloqueado.
- Cuántos están en modo degradado / observación.
- Cuántas apuestas generó el Bettor y qué compuestos descartó.
- Sub-rutinas on-demand disparadas (web checks).
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ─── Constantes visuales ──────────────────────────────────────────────────────
_SEP = "═" * 72
_SEP_THIN = "─" * 72
_STATUS_ICONS = {
    "clean": "✅ LIMPIO   ",
    "degraded": "🟡 DEGRADADO",
    "observation": "⚠️ OBSERV.  ",
    "dropped": "❌ BLOQUEADO",
}
_REASON_LABELS = {
    "low_overall_quality": "Calidad global insuficiente",
    "no_stats_both_teams": "Sin stats ESPN (ambos equipos)",
    "high_risk_severe": "Riesgo alto con anomalía severa",
    None: "-",
}


def _fmt_drop(reason: Optional[str]) -> str:
    return _REASON_LABELS.get(reason, reason or "-")


def _fmt_score(val: Optional[float]) -> str:
    return f"{val:.2f}" if val is not None else "  -  "


# ─── Sección: Gate ────────────────────────────────────────────────────────────

def _render_gate_section(gate_summary: Dict) -> List[str]:
    lines = [
        _SEP,
        "  📊  RESUMEN DEL GATE (Data Completeness Gate)",
        _SEP_THIN,
        f"  Entrada: {gate_summary.get('total_input', 0)} partidos → "
        f"Pasaron: {gate_summary.get('total_passed', 0)}  |  "
        f"Bloqueados: {gate_summary.get('total_dropped', 0)}",
        f"  Estado: ✅ Limpios={gate_summary.get('count_clean', 0)}  "
        f"🟡 Degradados={gate_summary.get('count_degraded', 0)}  "
        f"⚠️  Observación={gate_summary.get('count_observation', 0)}",
        _SEP_THIN,
    ]

    events = gate_summary.get("events", [])
    if not events:
        lines.append("  (Sin eventos registrados)")
        return lines

    for ev in events:
        icon = _STATUS_ICONS.get(ev.get("gate_status", "dropped"), "❓")
        match_label = f"{ev.get('home', '?')} vs {ev.get('away', '?')}"
        score_str = _fmt_score(ev.get("overall_score"))
        risk = ev.get("risk_level", "?")
        reason = _fmt_drop(ev.get("drop_reason"))
        line = f"  {icon}  {match_label:<40} Score={score_str}  Risk={risk}"
        if ev.get("drop_reason"):
            line += f"  → {reason}"
        lines.append(line)

    return lines


# ─── Sección: YouTube Selector ───────────────────────────────────────────────

def _render_yt_section(meta: Dict) -> List[str]:
    statuses = meta.get("insights_sources_status", {})
    counts = meta.get("insights_sources_counts", {})
    if not statuses and not counts:
        return []
    lines = [
        _SEP,
        "  📺  YOUTUBE SELECTOR (Estado de Muestreo)",
        _SEP_THIN,
    ]
    for comp, status in statuses.items():
        icon = "✅" if status != "degraded" else "⚠️ "
        n = counts.get(comp, 0)
        lines.append(f"  {icon}  {comp:<8}  {n} video(s)  →  {status}")
    return lines


# ─── Sección: Bettor ──────────────────────────────────────────────────────────

def _render_bettor_section(betting_tips: List[Dict]) -> List[str]:
    lines = [
        _SEP,
        "  💰  RESUMEN DEL BETTOR (Tips generados)",
        _SEP_THIN,
    ]

    if not betting_tips:
        lines.append("  Sin tips generados en esta corrida.")
        return lines

    active = [t for t in betting_tips if t.get("action") not in ("Skip / No Value", "Skip / No Apuestable") and not str(t.get("type", "")).startswith("combo")]
    skipped = [t for t in betting_tips if t.get("action") in ("Skip / No Value", "Skip / No Apuestable")]
    combos = [t for t in betting_tips if str(t.get("type", "")).startswith("combo")]

    lines.append(f"  Total tips: {len(betting_tips)}  |  Singles activas: {len(active)}  |  Salteadas: {len(skipped)}  |  Combinadas: {len(combos)}")
    lines.append(_SEP_THIN)

    for tip in active:
        match = tip.get("match", "?")
        pick = tip.get("pick", "?")
        odds = tip.get("odds", 0)
        edge = tip.get("edge_pct", 0)
        stake = tip.get("stake_units_final", tip.get("stake_units", 0))
        gate_st = tip.get("gate_status", "clean")
        icon = "🟡" if gate_st == "degraded" else "✅"
        adj = " [DEGRADADO]" if gate_st == "degraded" else ""
        lines.append(f"  {icon}  {match:<40}  {pick}  @{odds:.2f}  edge={edge:.1f}%  stake={stake:.1f}u{adj}")

    if skipped:
        lines.append(_SEP_THIN)
        lines.append(f"  ⛔  {len(skipped)} tip(s) salteados por Gate (no apuestables):")
        for tip in skipped:
            lines.append(f"       · {tip.get('match', '?')}  → {tip.get('skip_reason', '?')}")

    if combos:
        lines.append(_SEP_THIN)
        lines.append(f"  🔗  {len(combos)} apuesta(s) combinada(s) generadas")

    return lines


# ─── Sección: Web Checks ──────────────────────────────────────────────────────

def _render_webchecks_section(analyst_web_checks: List[Dict]) -> List[str]:
    if not analyst_web_checks:
        return []
    lines = [
        _SEP,
        "  🔎  SUBRUTINAS ON-DEMAND (Analyst Web Checks)",
        _SEP_THIN,
        f"  Disparados: {len(analyst_web_checks)} web check(s)",
        _SEP_THIN,
    ]
    for wc in analyst_web_checks:
        match_str = f"{wc.get('home_team','?')} vs {wc.get('away_team','?')}"
        team = wc.get("target_team", "?")
        ok = "✅" if wc.get("result", {}).get("ok") else "❌"
        lines.append(f"  {ok}  {match_str:<40}  → Equipo consultado: {team}")
    return lines


# ─── Reporte principal ────────────────────────────────────────────────────────

def print_pipeline_report(state: Dict[str, Any]) -> None:
    """
    Genera y loguea el resumen operativo completo de la corrida del pipeline.
    Debe llamarse al final de run_graph o equivalente.
    """
    lines = [
        "",
        _SEP,
        "  🏟️   REPORTE OPERATIVO DEL PIPELINE",
        _SEP,
    ]

    # YT Selector
    meta = state.get("meta", {})
    yt_lines = _render_yt_section(meta)
    if yt_lines:
        lines.extend(yt_lines)

    # Gate
    gate_summary = state.get("gate_summary")
    if gate_summary:
        lines.extend(_render_gate_section(gate_summary))
    else:
        lines.extend([_SEP, "  ⚠️  Sin datos del Gate (gate_summary no encontrado en el estado)"])

    # Bettor
    betting_tips = state.get("betting_tips") or []
    lines.extend(_render_bettor_section(betting_tips))

    # Web Checks
    analyst_web_checks = state.get("analyst_web_checks") or []
    lines.extend(_render_webchecks_section(analyst_web_checks))

    lines.append(_SEP)
    lines.append("")

    report_text = "\n".join(lines)
    # Loguear todo de una vez para que aparezca compacto en el log
    logger.info(report_text)
    # También imprimir en stdout para visibilidad inmediata en terminal
    print(report_text)
