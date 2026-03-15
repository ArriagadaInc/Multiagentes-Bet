import re
import unicodedata
from datetime import datetime
from typing import Dict, List, Any, Set, Tuple

# Reusamos la lógica simple de matcheo existente en el pipeline para nombres
def _signal_team_match_scores(team_name: str, text: str) -> Tuple[int, int]:
    """Copia simplificada del matcheador de nombres del Analyst."""
    if not team_name or not text: return 0, 0
    t_clean = slugify(team_name).replace("-", " ")
    words = t_clean.split()
    score = 0
    if len(words) >= 2:
        exact = f" {t_clean} " in f" {text} "
        if exact: return 100, 100
        matches = sum(1 for w in words if len(w)>3 and w in text)
        if matches > 0: score = int((matches/len(words))*100)
    else:
        if t_clean in text: score = 100
    return score, score

def slugify(text: str) -> str:
    if not text: return ""
    text = str(text).lower()
    text = ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')
    text = re.sub(r'[^\w\s-]', '', text).strip()
    return re.sub(r'[-\s]+', '-', text)

def _normalize_for_dedup(s: str) -> str:
    s = str(s).lower()
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    s = re.sub(r'[^\w\s]', '', s).strip()
    s = re.sub(r'\s+', ' ', s)
    return s.replace("la champions", "champions")

def _determine_subject_type(t_text_lower: str, player_clean: str) -> str:
    if player_clean:
        coach_keywords = ["tecnico", "técnico", "dt", "entrenador", "mister", "manager", "dirige"]
        if any(k in t_text_lower for k in coach_keywords):
            return "coach"
        return "player"
    
    team_keywords = ["equipo", "plantilla", "club", "dirigencia", "local", "visitante", "plantel"]
    comp_keywords = ["liga", "champions", "copa", "torneo", "jornada", "fecha", "calendario"]
    case_keywords = ["caso", "juicio", "demanda", "investigacion", "sancion original", "fifa", "tas", "tribunal", "directiva", "financier", "quiebra"]
    
    if any(k in t_text_lower for k in case_keywords): return "case"
    if any(k in t_text_lower for k in comp_keywords): return "competition"
    if any(k in t_text_lower for k in team_keywords): return "team"
    return "unknown"

def evaluate_signal_suspicion(
    sig: Dict[str, Any], 
    target_team: str, 
    home_team: str, 
    away_team: str,
    home_observed_players: Set[str],
    away_observed_players: Set[str],
    seen_texts: Dict[str, List[str]],
    match_id: str
) -> Tuple[bool, List[str]]:
    
    raw_reasons = []
    
    sig_type = sig.get("type", "unknown")
    scope = sig.get("signal_scope", "unknown")
    source_type = sig.get("source_type", "unknown")
    subject_type = sig.get("subject_type", "unknown")
    player_clean = sig.get("player", "")
    date_clean = sig.get("date", "")
    t_text = str(sig.get("signal", ""))
    t_text_lower = t_text.lower()
    
    other_team = away_team if target_team == home_team else home_team
    is_opponent_type = sig_type.startswith("opponent_")

    # 1. team_not_in_match
    if target_team not in (home_team, away_team):
        raw_reasons.append("team_not_in_match")
        
    # 2. subject_type_type_mismatch
    mismatch_triggered = False
    if subject_type == "player" and sig_type in {"case", "competition_context", "legal_context", "managerial_context"}:
        mismatch_triggered = True
    elif subject_type == "player":
        mismatch_coach = ["dt", "técnico", "tecnico", "mister", "entrenador", "evalúa rotaciones", "evalua rotaciones", "política de no arriesgar"]
        mismatch_case = ["caso", "procesamiento", "justicia", "demanda", "sanción", "sancion", "fifa"]
        if any(w in t_text_lower for w in mismatch_coach + mismatch_case):
            mismatch_triggered = True
    elif subject_type == "competition" and sig_type in {"injury_news", "disciplinary_issue", "availability", "rotation"}:
        mismatch_triggered = True
    elif subject_type in {"coach", "case"} and sig_type in {"form", "recent_form"}:
        mismatch_triggered = True
    elif subject_type == "unknown":
        if re.search(r'\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\b', str(sig.get("signal", ""))):
            mismatch_triggered = True
            
    if mismatch_triggered:
        opponent_types = {"opponent_form", "opponent_crisis", "opponent_strength", "opponent_availability", "opponent_schedule"}
        if scope == "opponent" and sig_type in opponent_types and subject_type in {"unknown", "team"}:
            pass
        else:
            raw_reasons.append("subject_type_type_mismatch")
        
    # 3. foreign_entity_in_team_signal
    if player_clean and subject_type == "player" and scope != "opponent":
        p_lower = player_clean.lower()
        opponent_observed = away_observed_players if target_team == home_team else home_observed_players
        self_observed = home_observed_players if target_team == home_team else away_observed_players
        
        if _signal_team_match_scores(other_team, player_clean)[0] > 0:
            raw_reasons.append("foreign_entity_in_team_signal")
        elif p_lower in opponent_observed and p_lower not in self_observed:
            raw_reasons.append("foreign_entity_in_team_signal")
        elif _signal_team_match_scores(other_team, t_text_lower)[0] > 0 and p_lower not in self_observed:
            raw_reasons.append("foreign_entity_in_team_signal")
    
    # 4. stale_or_implausible_history_signal
    if source_type == "history":
        stale_words = ["cambio de dt", "histórico", "historico", "pasó de", "paso de", "era de", "mitad de temporada", "asume capitanía"]
        if any(w in t_text_lower for w in stale_words):
            raw_reasons.append("stale_or_implausible_history_signal")
            
    # 5. missing_date_for_time_sensitive_signal
    time_sensitive_types = {"injury_news", "availability", "fatigue", "disciplinary_issue", "rotation", "medical_doubt"}
    if not date_clean and sig_type in time_sensitive_types:
        raw_reasons.append("missing_date_for_time_sensitive_signal")
        
    # 6. possible_duplicate_signal
    norm_text = _normalize_for_dedup(t_text)
    group_key = f"{match_id}_{target_team}_{sig_type}"
    
    is_dup = False
    if group_key not in seen_texts:
        seen_texts[group_key] = []
    else:
        for past_text in seen_texts[group_key]:
            if norm_text == past_text or norm_text in past_text or past_text in norm_text:
                is_dup = True
                break
    if is_dup:
        raw_reasons.append("possible_duplicate_signal")
    else:
        seen_texts[group_key].append(norm_text)
    
    # 7. scope_unknown_for_actionable_signal
    actionable_types = {"injury_news", "disciplinary_issue", "squad_availability", "heavy_rotation", "medical_doubt", "fatigue", "form", "coach_change"}
    if scope == "unknown" and sig_type in actionable_types:
        if sig_type in {"form", "schedule_load"}:
            if not date_clean or subject_type == "unknown":
                raw_reasons.append("scope_unknown_for_actionable_signal")
        else:
            raw_reasons.append("scope_unknown_for_actionable_signal")
        
    # 8. manual_signal_low_clarity
    if source_type == "manual" and (scope == "unknown" or subject_type == "unknown" or not date_clean):
        raw_reasons.append("manual_signal_low_clarity")
        
    # 9. opponent_scope_attached_to_team
    if scope == "opponent" and not is_opponent_type:
        raw_reasons.append("opponent_scope_attached_to_team")
        
    # 10. low_information_signal
    if not t_text or len(t_text.strip()) < 12:
        raw_reasons.append("low_information_signal")
    else:
        generic_phrases = ["mal momento", "complicado", "buen momento", "en duda", "lesionado", "partido dificil", "sin informacion"]
        if t_text.strip().lower() in generic_phrases:
            raw_reasons.append("low_information_signal")

    priority_order = [
         "foreign_entity_in_team_signal", "subject_type_type_mismatch",
         "stale_or_implausible_history_signal", "possible_duplicate_signal",
         "missing_date_for_time_sensitive_signal", "scope_unknown_for_actionable_signal",
         "team_not_in_match", "manual_signal_low_clarity", "opponent_scope_attached_to_team",
         "low_information_signal"
    ]
    reasons = sorted(raw_reasons, key=lambda x: priority_order.index(x) if x in priority_order else 99)
    return bool(reasons), reasons

def _build_signals_summary(signals_clean: List[Dict], signals_suspicious: List[Dict]) -> Dict[str, Any]:
    reasons_counter = {}
    for sig in signals_suspicious:
        for r in sig.get("suspicion_reasons", []):
            reasons_counter[r] = reasons_counter.get(r, 0) + 1
            
    sorted_reasons = sorted(reasons_counter.items(), key=lambda x: x[1], reverse=True)
    top_reasons = [k for k, v in sorted_reasons[:5]]
    
    total_sigs = len(signals_clean) + len(signals_suspicious)
    ratio = round(len(signals_suspicious) / total_sigs, 2) if total_sigs > 0 else 0.0
    
    return {
        "total": total_sigs,
        "clean_count": len(signals_clean),
        "suspicious_count": len(signals_suspicious),
        "suspicious_ratio": ratio,
        "top_suspicion_reasons": top_reasons
    }

def normalize_signal_fields(sig: Dict[str, Any], target_team: str, is_home: bool) -> None:
    """Enriquece los campos base de una señal antes de auditarla. Muta el dict."""
    sig["team"] = target_team
    sig["source_type"] = sig.get("source_type", "unknown")
    sig["signal_scope"] = sig.get("signal_scope", "unknown")
    
    player = sig.get("player")
    sig["player"] = player.strip() if player and str(player).strip().lower() not in ["none", "null", ""] else ""
    
    date_val = sig.get("date")
    sig["date"] = str(date_val).strip() if date_val and str(date_val).strip().lower() not in ["none", "null", ""] else ""
    
    if "subject_type" not in sig or sig["subject_type"] == "unknown":
        sig["subject_type"] = _determine_subject_type(str(sig.get("signal", "")).lower(), sig["player"])

def extract_observed_players(team_dict: Dict) -> Set[str]:
    players = set()
    if not team_dict or "insights" not in team_dict: return players
    for sig in team_dict["insights"].get("context_signals", []):
        pl = sig.get("player")
        if pl and str(pl).strip().lower() not in ["none", "null", ""]:
            players.add(str(pl).strip().lower())
    return players

def partition_match_signals(match_context: Dict[str, Any], force_recompute: bool = False) -> Dict[str, Any]:
    """
    Toma un match_context, consolida sus context_signals de home y away, 
    calcula la sospecha epistemológica y agrupa en signals_clean / signals_suspicious.
    Muta y devuelve el dict.
    """
    # Si ya tiene la partición y no se fuerza recómputo, passthrough
    if not force_recompute and "signals_clean" in match_context and "signals_summary" in match_context:
        return match_context
        
    home_team = match_context.get("home", {}).get("canonical_name", "home")
    away_team = match_context.get("away", {}).get("canonical_name", "away")
    match_id = match_context.get("match_id", "unknown_match")
    
    home_players = extract_observed_players(match_context.get("home", {}))
    away_players = extract_observed_players(match_context.get("away", {}))
    seen_texts = {}
    
    all_signals = []
    
    # Recolectar señales
    for side, team_name in [("home", home_team), ("away", away_team)]:
        side_dict = match_context.get(side, {})
        signals = side_dict.get("insights", {}).get("context_signals", [])
        
        for sig in signals:
            if not isinstance(sig, dict): continue
            
            normalize_signal_fields(sig, team_name, side=="home")
            
            # Solo recalcular si no tienen ya o se fuerza recómputo
            if force_recompute or "is_suspicious" not in sig:
                is_susp, reasons = evaluate_signal_suspicion(
                    sig, team_name, home_team, away_team, 
                    home_players, away_players, seen_texts, match_id
                )
                sig["is_suspicious"] = is_susp
                sig["suspicion_reasons"] = reasons
                
            all_signals.append(sig)

    signals_clean = [s for s in all_signals if not s.get("is_suspicious")]
    signals_suspicious = [s for s in all_signals if s.get("is_suspicious")]
    
    summary = _build_signals_summary(signals_clean, signals_suspicious)
    
    # Montar in match_context
    match_context["signals_clean"] = signals_clean
    match_context["signals_suspicious"] = signals_suspicious
    match_context["signals_summary"] = summary
    match_context["signal_partition_meta"] = {
        "version": "v1.1",
        "fallback_used": False,
        "generated_at": datetime.now().isoformat(),
        "total_signals_seen": len(all_signals)
    }
    
    # También proveer una vista unificada plana si la UI actual u otro nodo la precisa:
    match_context["all_signals"] = all_signals
    
    return match_context
