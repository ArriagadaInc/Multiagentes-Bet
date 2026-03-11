"""Script para mostrar stats con rachas, goleadores, match stats y recent match."""
import json

data = json.load(open("pipeline_stats.json", "r", encoding="utf-8"))
print(f"Total: {len(data)} equipos\n")

for i, d in enumerate(data, 1):
    s = d.get("stats", {})
    scorers = d.get("top_scorers", [])
    form = s.get("form", "")
    prov = d.get("provider", "?")
    ms = s.get("match_stats", {})
    rm = d.get("recent_match", {})
    
    pos = s.get("position", "?")
    pts = s.get("points", 0)
    pj = s.get("played", 0)
    w = s.get("won", 0)
    dr = s.get("draw", 0)
    l = s.get("lost", 0)
    gf = s.get("goals_for", 0)
    ga = s.get("goals_against", 0)
    gd = s.get("goal_difference", 0)
    
    form_str = f" racha={form}" if form else ""
    print(f"[{i:>2}] {d.get('competition','?'):4} | {d.get('team','?'):28} | pos={pos:>3} pts={pts:>2} PJ={pj:>2} G={w} E={dr} P={l} GF={gf:>2} GC={ga:>2} DG={gd:>3}{form_str} [{prov}]")
    
    if ms:
        poss = ms.get("possession_pct", 0)
        sh = ms.get("shots", 0)
        sot = ms.get("shots_on_target", 0)
        cor = ms.get("corners", 0)
        fl = ms.get("fouls", 0)
        print(f"     Match: pos={poss}% tiros={sh}({sot}ot) corners={cor} faltas={fl}")
    
    if rm and rm.get("opponent"):
        opp = rm.get("opponent", "?")
        sc = rm.get("score", "?")
        ha = rm.get("home_away", "?")
        venue = rm.get("venue", "")
        att = rm.get("attendance", "")
        hl = rm.get("headline", "")
        
        att_str = f" att={att}" if att else ""
        print(f"     Último: vs {opp} {sc} ({ha}) en {venue}{att_str}")
        
        for g in rm.get("goals", []):
            print(f"       ⚽ {g['minute']:>6} {g['player']} ({g['type']})")
        for g in rm.get("goals_against", []):
            print(f"       ❌ {g['minute']:>6} {g['player']} ({g['type']})")
        for c in rm.get("cards", []):
            emoji = "🔴" if c.get("card") == "red" else "🟡"
            print(f"       {emoji} {c['minute']:>6} {c['player']}")
        
        if hl:
            print(f"     📰 {hl[:100]}")
    
    if scorers:
        scorer_strs = [f"{sc['player']}({sc['goals']}g)" for sc in scorers]
        print(f"     Goleadores: {', '.join(scorer_strs)}")
