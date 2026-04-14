import requests
import json

def debug_espn():
    leagues = ["chi.1", "chi.2", "chi.copa_chi"]
    dates = ["20260320", "20260321", "20260322", "20260323"]
    
    for league in leagues:
        for date in dates:
            url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"
            params = {"dates": date}
            print(f"\nChecking League: {league}, Date: {date}")
            try:
                r = requests.get(url, params=params, timeout=10)
                data = r.json()
                events = data.get("events", [])
                if not events:
                    print("  No events found.")
                for ev in events:
                    name = ev.get("name")
                    print(f"  Match: {name} (ID: {ev['id']})")
                    comp = ev.get("competitions", [{}])[0]
                    competitors = comp.get("competitors", [])
                    for c in competitors:
                        team_name = c.get("team", {}).get("name")
                        print(f"    - Team: {team_name} (Home/Away: {c.get('homeAway')})")
            except Exception as e:
                print(f"  Error: {e}")

if __name__ == "__main__":
    debug_espn()
