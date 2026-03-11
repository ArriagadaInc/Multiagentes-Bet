"""Script temporal para mostrar insights de forma legible."""
import json

data = json.load(open("pipeline_insights.json", "r", encoding="utf-8"))
print(f"Total insights: {len(data)}\n")

for i, ins in enumerate(data, 1):
    comp = ins.get("competition", "?")
    team = ins.get("team", "?")
    nm = ins.get("next_match")
    fc = ins.get("forecast")
    ent = ins.get("entities") or {}
    inj = ent.get("injuries", [])
    sus = ent.get("suspensions", [])
    abs_ = ent.get("absences", [])

    print(f"=== [{i}] {comp} | {team} ===")
    if nm:
        opp = nm.get("opponent", "?")
        dt = nm.get("date", "?")[:10]
        print(f"  Proximo partido: {team} vs {opp} ({dt})")
    
    insight = ins.get("insight", "")
    if insight:
        for line in insight.split("\n"):
            if line.strip():
                print(f"  {line.strip()}")
    
    if fc:
        outcome = fc.get("outcome", "?")
        conf = fc.get("confidence", "?")
        rat = fc.get("rationale", "")
        print(f"  PRONOSTICO: {outcome} (confianza={conf})")
        print(f"  Razon: {rat}")
    
    if inj:
        print(f"  Lesiones: {', '.join(inj)}")
    if sus:
        print(f"  Sanciones: {', '.join(sus)}")
    if abs_:
        print(f"  Ausencias: {', '.join(abs_)}")
    
    print()
