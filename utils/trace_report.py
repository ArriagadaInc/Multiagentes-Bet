from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from utils.normalizer import TeamNormalizer, slugify


normalizer = TeamNormalizer()


def _safe_date(value: Any) -> str:
    return str(value or "")[:10]


def _pair_key(competition: str, match_date: str, home: str, away: str) -> str:
    return f"{competition}|{match_date}|{slugify(home)}|{slugify(away)}"


def _base_trace() -> dict[str, Any]:
    return {
        "fixtures_agent": {},
        "web_fixtures_agent": {},
        "odds_agent": {},
        "stats_agent": {},
        "journalist_agent": {},
        "web_agent": {},
        "insights_agent": {},
        "normalizer_agent": {},
        "gate_agent": {},
        "analyst_agent": {},
        "bettor_agent": {},
    }


def _ensure_record(index: dict[str, dict], competition: str, match_date: str, home: str, away: str, match_id: str | None = None) -> dict:
    key = _pair_key(competition, match_date, home, away)
    if key not in index:
        index[key] = {
            "match_id": match_id or "",
            "competition": competition,
            "match_date": match_date,
            "home_team": home,
            "away_team": away,
            "match_label": f"{home} vs {away}",
            "trace": _base_trace(),
        }
    else:
        rec = index[key]
        if match_id and not rec.get("match_id"):
            rec["match_id"] = match_id
        if competition and not rec.get("competition"):
            rec["competition"] = competition
        if match_date and not rec.get("match_date"):
            rec["match_date"] = match_date
    return index[key]


def _find_record(
    index: dict[str, dict],
    competition: str = "",
    match_date: str = "",
    home: str = "",
    away: str = "",
    match_id: str = "",
) -> dict | None:
    if match_id:
        for rec in index.values():
            if rec.get("match_id") == match_id:
                return rec
    if competition and match_date and home and away:
        rec = index.get(_pair_key(competition, match_date, home, away))
        if rec:
            return rec
    if home and away:
        home_slug = slugify(home)
        away_slug = slugify(away)
        for rec in index.values():
            if slugify(rec.get("home_team")) == home_slug and slugify(rec.get("away_team")) == away_slug:
                if competition and rec.get("competition") and rec.get("competition") != competition:
                    continue
                return rec
    return None


def _find_team_stats(team: str, stats_data: list[dict], competition: str = "") -> dict | None:
    team_clean = normalizer.clean(team)
    for st in stats_data or []:
        if competition and (st.get("competition") or "") != competition:
            continue
        if normalizer.clean(st.get("team") or "") == team_clean:
            return st
    return None


def _find_team_insights(team: str, competition: str, insights_data: list[dict]) -> dict | None:
    team_clean = normalizer.clean(team)
    for ins in insights_data or []:
        if competition and (ins.get("competition") or "") != competition:
            continue
        if normalizer.clean(ins.get("team") or "") == team_clean:
            return ins
    return None


def _extract_journalist_sources(competition: str, home: str, away: str, journalist_data: dict) -> dict[str, Any]:
    out = {"competition_videos": [], "matched_videos": [], "competition_errors": []}
    if not isinstance(journalist_data, dict):
        return out
    comps = journalist_data.get("competitions") or []
    home_slug = slugify(home)
    away_slug = slugify(away)
    for comp in comps:
        if competition and (comp.get("competition") or "") != competition:
            continue
        videos = comp.get("videos") or []
        out["competition_videos"] = videos
        out["competition_errors"] = comp.get("errors") or []
        matched = []
        for v in videos:
            haystack = " ".join([
                str(v.get("title") or ""),
                str(v.get("description") or ""),
                str(v.get("channel") or ""),
            ]).lower()
            if home_slug.replace("-", " ") in haystack or away_slug.replace("-", " ") in haystack:
                matched.append(v)
        out["matched_videos"] = matched
        break
    return out


def _prediction_competition(pred: dict) -> str:
    comp = str(pred.get("competition") or "").strip()
    if comp:
        return comp
    pid = str(pred.get("prediction_id") or "")
    return pid.split("_", 1)[0] if "_" in pid else ""


def _prediction_match_date(pred: dict) -> str:
    match_date = _safe_date(pred.get("match_date"))
    if match_date:
        return match_date
    pid = str(pred.get("prediction_id") or "")
    parts = pid.split("_")
    if len(parts) >= 2:
        return parts[1][:10]
    return ""


def build_trace_report(state: dict[str, Any]) -> dict[str, Any]:
    fixtures = state.get("fixtures") or []
    odds = state.get("odds_canonical") or []
    stats = state.get("stats_by_team") or []
    insights = state.get("insights") or []
    match_contexts = state.get("match_contexts") or []
    journalist = state.get("journalist_videos") or {}
    gate_summary = state.get("gate_summary") or {}
    predictions = state.get("predictions") or []
    betting_tips = state.get("betting_tips") or []
    analyst_web_checks = state.get("analyst_web_checks") or []
    analyst_trace = state.get("analyst_trace") or []
    bettor_trace = state.get("bettor_trace") or []
    meta = state.get("meta") or {}

    index: dict[str, dict] = {}

    # Base primaria: match_contexts
    for mc in match_contexts:
        comp = mc.get("competition") or ""
        match_date = _safe_date(mc.get("match_date"))
        home = ((mc.get("home") or {}).get("canonical_name")) or ""
        away = ((mc.get("away") or {}).get("canonical_name")) or ""
        rec = _ensure_record(index, comp, match_date, home, away, mc.get("match_id"))
        rec["trace"]["stats_agent"] = {
            "home_stats": (mc.get("home") or {}).get("stats"),
            "away_stats": (mc.get("away") or {}).get("stats"),
        }
        rec["trace"]["insights_agent"] = {
            "home_insights": (mc.get("home") or {}).get("insights"),
            "away_insights": (mc.get("away") or {}).get("insights"),
        }
        rec["trace"]["normalizer_agent"] = {
            "match_context": mc,
            "signals_clean": mc.get("signals_clean"),
            "signals_suspicious": mc.get("signals_suspicious"),
            "signals_summary": mc.get("signals_summary"),
            "data_quality": mc.get("data_quality"),
        }
        rec["trace"]["journalist_agent"] = _extract_journalist_sources(comp, home, away, journalist)

    for fx in fixtures:
        comp = fx.get("competition") or ""
        match_date = _safe_date(fx.get("utc_date"))
        home = fx.get("home_team") or ""
        away = fx.get("away_team") or ""
        rec = _find_record(index, comp, match_date, home, away) or _ensure_record(index, comp, match_date, home, away)
        rec["trace"]["fixtures_agent"] = {
            "output_fixture": fx,
            "source": fx.get("provider"),
        }

    for ev in odds:
        comp = ev.get("competition") or ""
        match_date = _safe_date(ev.get("commence_time"))
        home = ev.get("home_team") or ""
        away = ev.get("away_team") or ""
        rec = _find_record(index, comp, match_date, home, away) or _ensure_record(index, comp, match_date, home, away)
        rec["trace"]["odds_agent"] = {
            "output_odds": ev,
            "source": ev.get("provider"),
        }
        if not rec["trace"]["fixtures_agent"]:
            rec["trace"]["fixtures_agent"] = {
                "output_fixture": {
                    "competition": comp,
                    "home_team": home,
                    "away_team": away,
                    "utc_date": ev.get("commence_time"),
                    "match_key": ev.get("match_key"),
                },
                "source": "odds_fallback",
            }

    for evt in gate_summary.get("events") or []:
        match_id = evt.get("match_id") or ""
        home = evt.get("home") or ""
        away = evt.get("away") or ""
        rec = _find_record(index, match_id=match_id, home=home, away=away)
        if rec is None:
            rec = _ensure_record(index, evt.get("competition") or "", _safe_date(evt.get("match_date")), home, away, match_id)
        rec["trace"]["gate_agent"] = evt

    for awc in analyst_web_checks:
        rec = _find_record(index, match_id=awc.get("match_id") or "", home=awc.get("home_team") or "", away=awc.get("away_team") or "")
        if rec:
            rec["trace"]["analyst_agent"].setdefault("analyst_web_checks", []).append(awc)

    for atr in analyst_trace:
        rec = _find_record(
            index,
            match_id=atr.get("match_id") or "",
            competition=atr.get("competition") or "",
            match_date=_safe_date(atr.get("match_date")),
            home=atr.get("home_team") or "",
            away=atr.get("away_team") or "",
        )
        if rec is None:
            rec = _ensure_record(
                index,
                atr.get("competition") or "",
                _safe_date(atr.get("match_date")),
                atr.get("home_team") or "",
                atr.get("away_team") or "",
                atr.get("match_id"),
            )
        rec["trace"]["analyst_agent"].update(atr)

    for pred in predictions:
        rec = _find_record(
            index,
            competition=_prediction_competition(pred),
            match_date=_prediction_match_date(pred),
            home=pred.get("home_team") or "",
            away=pred.get("away_team") or "",
        )
        if rec is None:
            rec = _ensure_record(
                index,
                _prediction_competition(pred),
                _prediction_match_date(pred),
                pred.get("home_team") or "",
                pred.get("away_team") or "",
            )
        rec["trace"]["analyst_agent"].setdefault("final_predictions", []).append(pred)

    for btr in bettor_trace:
        rec = _find_record(
            index,
            competition=btr.get("competition") or "",
            match_date=_safe_date(btr.get("match_date")),
            home=btr.get("home_team") or "",
            away=btr.get("away_team") or "",
        )
        if rec is None:
            rec = _ensure_record(
                index,
                btr.get("competition") or "",
                _safe_date(btr.get("match_date")),
                btr.get("home_team") or "",
                btr.get("away_team") or "",
            )
        rec["trace"]["bettor_agent"] = btr

    for tip in betting_tips:
        match = str(tip.get("match") or "")
        if " vs " not in match:
            continue
        home, away = match.split(" vs ", 1)
        rec = _find_record(index, home=home, away=away)
        if rec:
            rec["trace"]["bettor_agent"].setdefault("tips", []).append(tip)

    for rec in index.values():
        comp = rec.get("competition") or ""
        home = rec.get("home_team") or ""
        away = rec.get("away_team") or ""

        if not rec["trace"]["stats_agent"]:
            rec["trace"]["stats_agent"] = {
                "home_stats": _find_team_stats(home, stats, comp),
                "away_stats": _find_team_stats(away, stats, comp),
            }

        if not rec["trace"]["insights_agent"] or (
            rec["trace"]["insights_agent"].get("home_insights") is None
            and rec["trace"]["insights_agent"].get("away_insights") is None
        ):
            rec["trace"]["insights_agent"] = {
                "home_insights": _find_team_insights(home, comp, insights),
                "away_insights": _find_team_insights(away, comp, insights),
            }

        if not rec["trace"]["journalist_agent"]:
            rec["trace"]["journalist_agent"] = _extract_journalist_sources(comp, home, away, journalist)

        home_ins = (rec["trace"]["insights_agent"] or {}).get("home_insights") or {}
        away_ins = (rec["trace"]["insights_agent"] or {}).get("away_insights") or {}
        rec["trace"]["web_agent"] = {
            "home_web_signals": home_ins.get("context_signals"),
            "away_web_signals": away_ins.get("context_signals"),
            "home_source": home_ins.get("source"),
            "away_source": away_ins.get("source"),
            "home_web_last_result": home_ins.get("web_last_result"),
            "away_web_last_result": away_ins.get("web_last_result"),
        }

        match_key = ((rec["trace"].get("normalizer_agent") or {}).get("match_context") or {}).get("match_key")
        if match_key:
            for audit in meta.get("web_odds_audit") or []:
                if audit.get("match_key") == match_key:
                    rec["trace"]["web_fixtures_agent"] = audit
                    break
        elif not rec["trace"]["web_fixtures_agent"]:
            for audit in meta.get("web_odds_audit") or []:
                if slugify(audit.get("home_team")) == slugify(home) and slugify(audit.get("away_team")) == slugify(away):
                    rec["trace"]["web_fixtures_agent"] = audit
                    break

        raw_home = (home_ins.get("context_signals") or [])
        raw_away = (away_ins.get("context_signals") or [])
        clean = rec["trace"]["normalizer_agent"].get("signals_clean") or []
        suspicious = rec["trace"]["normalizer_agent"].get("signals_suspicious") or []
        rec["trace"]["transitions"] = {
            "insights_to_normalizer": {
                "raw_signal_count": len(raw_home) + len(raw_away),
                "clean_count": len(clean),
                "suspicious_count": len(suspicious),
            }
        }

    matches = sorted(index.values(), key=lambda x: (x.get("competition") or "", x.get("match_date") or "", x.get("home_team") or ""))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_matches": len(matches),
            "with_analyst_trace": sum(1 for m in matches if m["trace"].get("analyst_agent")),
            "with_bettor_trace": sum(1 for m in matches if m["trace"].get("bettor_agent")),
        },
        "meta_snapshot": {
            "web_odds_audit": meta.get("web_odds_audit") or [],
            "manual_odds_audit": meta.get("manual_odds_audit") or [],
            "gate_summary": gate_summary,
        },
        "matches": matches,
    }
