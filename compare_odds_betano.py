
import json
import logging

def main():
    try:
        with open("pipeline_odds.json", "r", encoding="utf-8") as f:
            odds_data = json.load(f)
    except Exception as e:
        print(f"Error: {e}")
        return

    # Partidos de interés (según imagen Betano)
    targets = [
        ("Atlético Madrid", "Club Brugge"),
        ("Bayer Leverkusen", "Olympiacos"), # API puede tener nombres distintos, usaremos contains
        ("Inter", "Bodø"),
        ("Newcastle", "Qarabağ"),
        ("Atalanta", "Dortmund"),
        ("Juventus", "Galatasaray"),
        ("Real Madrid", "Benfica"),
        ("Paris", "Monaco")
    ]

    print(f"{'PARTIDO':<40} | {'API (Promedio)':<20} | {'BETANO (Ref)':<15}")
    print("-" * 85)

    for t_home, t_away in targets:
        # Buscar evento
        found = None
        for ev in odds_data:
            h = ev.get("home_team", "")
            a = ev.get("away_team", "")
            if (t_home.lower() in h.lower() or h.lower() in t_home.lower()) and \
               (t_away.lower() in a.lower() or a.lower() in t_away.lower()):
                found = ev
                break
        
        if found:
            # Calcular promedio de odds
            home_odds = []
            draw_odds = []
            away_odds = []
            for bk in found.get("bookmakers", []):
                if bk.get("home_odds"): home_odds.append(bk["home_odds"])
                if bk.get("draw_odds"): draw_odds.append(bk["draw_odds"])
                if bk.get("away_odds"): away_odds.append(bk["away_odds"])
            
            avg_1 = sum(home_odds)/len(home_odds) if home_odds else 0
            avg_X = sum(draw_odds)/len(draw_odds) if draw_odds else 0
            avg_2 = sum(away_odds)/len(away_odds) if away_odds else 0
            
            match_str = f"{found['home_team']} vs {found['away_team']}"
            api_str = f"1:{avg_1:.2f} X:{avg_X:.2f} 2:{avg_2:.2f}"
            print(f"{match_str:<40} | {api_str:<20} | {'(Ver imagen)'}")
            
            # Alerta de inversión
            if "Inter" in t_home:
                print(f"   >>> DETALLE INTER: Min Home: {min(home_odds) if home_odds else 0}, Max Home: {max(home_odds) if home_odds else 0}")
        else:
            print(f"❌ No encontrado en API: {t_home} vs {t_away}")

if __name__ == "__main__":
    main()
