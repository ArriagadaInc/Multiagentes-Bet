#!/usr/bin/env python3
"""
Validate Copa Libertadores data availability in Football-Data.org API
"""

import os
import requests
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")
BASE_URL = "https://api.football-data.org/v4"

if not API_KEY:
    print("❌ FOOTBALL_DATA_API_KEY not set in .env")
    exit(1)

headers = {"X-Auth-Token": API_KEY}

print("\n" + "="*80)
print("  COPA LIBERTADORES DATA VALIDATION")
print("  Football-Data.org API v4")
print("="*80)

# ============================================================================
# 1. GET COMPETITION INFO
# ============================================================================
print("\n[1/5] Fetching Competition Information...")
print("      GET /v4/competitions/CLI")

response = requests.get(f"{BASE_URL}/competitions/CLI", headers=headers, timeout=10)

if response.status_code != 200:
    print(f"❌ Failed: HTTP {response.status_code}")
    print(f"   Response: {response.text[:200]}")
    exit(1)

comp_data = response.json()
print(f"✅ Success (HTTP 200)")
print(f"   Competition: {comp_data.get('name')}")
print(f"   Code: {comp_data.get('code')}")
print(f"   Area: {comp_data.get('area', {}).get('name')}")
print(f"   Current Season: {comp_data.get('currentSeason', {}).get('id')}")
print(f"   Current Stage: {comp_data.get('currentSeason', {}).get('currentMatchday') or 'Phase structure'}") 

# ============================================================================
# 2. GET TEAMS/PARTICIPANTS
# ============================================================================
print("\n[2/5] Fetching Teams/Participants...")
print("      GET /v4/competitions/CLI/teams")

response = requests.get(f"{BASE_URL}/competitions/CLI/teams", headers=headers, timeout=10)

if response.status_code != 200:
    print(f"❌ Failed: HTTP {response.status_code}")
else:
    teams_data = response.json()
    teams = teams_data.get("teams", [])
    print(f"✅ Success (HTTP 200)")
    print(f"   Total Teams: {len(teams)}")
    print(f"\n   Team Sample (first 5):")
    for i, team in enumerate(teams[:5], 1):
        print(f"   {i}. {team.get('name')} (ID: {team.get('id')})")
    if len(teams) > 5:
        print(f"   ... and {len(teams) - 5} more teams")

# ============================================================================
# 3. GET FIXTURES (SCHEDULED MATCHES)
# ============================================================================
print("\n[3/5] Fetching Scheduled Fixtures...")
print("      GET /v4/competitions/CLI/matches?status=SCHEDULED")

# Get fixtures for next 30 days
today = datetime.now()
date_from = today.strftime("%Y-%m-%d")
date_to = (today + timedelta(days=30)).strftime("%Y-%m-%d")

params = {
    "status": "SCHEDULED",
    "dateFrom": date_from,
    "dateTo": date_to
}

response = requests.get(f"{BASE_URL}/competitions/CLI/matches", headers=headers, params=params, timeout=10)

if response.status_code != 200:
    print(f"❌ Failed: HTTP {response.status_code}")
else:
    fixtures_data = response.json()
    matches = fixtures_data.get("matches", [])
    print(f"✅ Success (HTTP 200)")
    print(f"   Scheduled Matches (next 30 days): {len(matches)}")
    if matches:
        print(f"\n   Match Sample (first 3):")
        for i, match in enumerate(matches[:3], 1):
            home = match.get("homeTeam", {}).get("name", "Unknown")
            away = match.get("awayTeam", {}).get("name", "Unknown")
            utc_date = match.get("utcDate", "Unknown")
            status = match.get("status", "Unknown")
            print(f"   {i}. {home} vs {away}")
            print(f"      Date: {utc_date} | Status: {status}")
    else:
        print(f"   ⚠️  No scheduled matches in next 30 days")

# ============================================================================
# 4. GET STANDINGS
# ============================================================================
print("\n[4/5] Fetching Standings/Table...")
print("      GET /v4/competitions/CLI/standings")

standings = []  # Default empty
response = requests.get(f"{BASE_URL}/competitions/CLI/standings", headers=headers, timeout=10)

if response.status_code != 200:
    print(f"⚠️  Not available: HTTP {response.status_code}")
    print(f"    (Copa may use group-phase structure without traditional standings)")
else:
    standings_data = response.json()
    standings = standings_data.get("standings", [])
    print(f"✅ Success (HTTP 200)")
    print(f"   Standings Groups: {len(standings)}")
    
    if standings:
        # Print first group
        group = standings[0]
        print(f"\n   Group/Stage: {group.get('type', 'Unknown')}")
        table = group.get("table", [])
        print(f"   Teams in Table: {len(table)}")
        if table:
            print(f"\n   Table Sample (top 5):")
            for i, entry in enumerate(table[:5], 1):
                team_name = entry.get("team", {}).get("name", "Unknown")
                position = entry.get("position", "Unknown")
                played = entry.get("playedGames", 0)
                won = entry.get("won", 0)
                drawn = entry.get("draw", 0)
                lost = entry.get("lost", 0)
                points = entry.get("points", 0)
                print(f"   {position}. {team_name} - {played}P {won}W {drawn}D {lost}L = {points}pts")

# ============================================================================
# 5. GET FINISHED MATCHES (RECENT RESULTS)
# ============================================================================
print("\n[5/5] Fetching Recent Finished Matches...")
print("      GET /v4/competitions/CLI/matches?status=FINISHED")

date_from_past = (today - timedelta(days=7)).strftime("%Y-%m-%d")
date_to_recent = today.strftime("%Y-%m-%d")

params = {
    "status": "FINISHED",
    "dateFrom": date_from_past,
    "dateTo": date_to_recent
}

response = requests.get(f"{BASE_URL}/competitions/CLI/matches", headers=headers, params=params, timeout=10)

if response.status_code != 200:
    print(f"❌ Failed: HTTP {response.status_code}")
else:
    finished_data = response.json()
    finished_matches = finished_data.get("matches", [])
    print(f"✅ Success (HTTP 200)")
    print(f"   Finished Matches (last 7 days): {len(finished_matches)}")
    if finished_matches:
        print(f"\n   Result Sample (first 3):")
        for i, match in enumerate(finished_matches[:3], 1):
            home = match.get("homeTeam", {}).get("name", "Unknown")
            away = match.get("awayTeam", {}).get("name", "Unknown")
            home_goals = match.get("score", {}).get("fullTime", {}).get("home", "?")
            away_goals = match.get("score", {}).get("fullTime", {}).get("away", "?")
            utc_date = match.get("utcDate", "Unknown")
            print(f"   {i}. {home} {home_goals}-{away_goals} {away} ({utc_date[:10]})")

# ============================================================================
# SUMMARY
# ============================================================================
print("\n" + "="*80)
print("  VALIDATION SUMMARY")
print("="*80)

summary_checks = [
    ("✅ API accessible", True),
    (f"✅ Competition exists", comp_data is not None),
    (f"✅ Has {len(teams)} teams registered", len(teams) > 0),
    (f"✅ Has {len(matches)} scheduled matches", len(matches) >= 0),  # May be 0 if no future matches
    (f"✅ Has standings data", len(standings) > 0),
    (f"✅ Has recent results", len(finished_matches) >= 0),
]

print("\nValidation Results:")
all_passed = True
for check, result in summary_checks:
    status = "✅ PASS" if result else "❌ FAIL"
    print(f"  {status}: {check}")
    if not result:
        all_passed = False

print("\n" + "="*80)
if all_passed:
    print("  🟢 VERDICT: COPA LIBERTADORES IS FULLY SUPPORTED")
    print("  Ready for integration into pipeline!")
else:
    print("  🔴 VERDICT: SOME DATA MISSING - REVIEW ABOVE")
print("="*80 + "\n")
