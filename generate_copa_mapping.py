#!/usr/bin/env python3
"""
Fetch Copa Libertadores teams from Football-Data.org and generate golden mapping
"""

import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")
BASE_URL = "https://api.football-data.org/v4"

if not API_KEY:
    print("❌ FOOTBALL_DATA_API_KEY not set")
    exit(1)

print("\n📡 Fetching Copa Libertadores teams from Football-Data.org...")
print("="*80)

headers = {"X-Auth-Token": API_KEY}
response = requests.get(f"{BASE_URL}/competitions/CLI/teams", headers=headers, timeout=10)

if response.status_code != 200:
    print(f"❌ Failed: HTTP {response.status_code}")
    exit(1)

teams_data = response.json()
teams = teams_data.get("teams", [])

print(f"✅ Found {len(teams)} teams\n")

# Manual alias mapping for Copa teams (extensive one-time build)
aliases_map = {
    # Brasil (12 teams)
    "fluminense": {
        "official_name": "Fluminense Football Club",
        "aliases": ["flu", "fluminense fc", "fluminense rio", "tricolor carioca", "torres", "as torres"]
    },
    "palmeiras": {
        "official_name": "SE Palmeiras",
        "aliases": ["palmeiras sp", "verdão", "palestra", "palestra italia", "manchester paulista"]
    },
    "botafogo": {
        "official_name": "Botafogo FR",
        "aliases": ["botafogo rio", "botafogo de futebol", "estrela solitária", "general severiano"]
    },
    "cruzeiro": {
        "official_name": "Cruzeiro Esporte Clube",
        "aliases": ["cruzeiro mg", "raposa", "celeste", "minas gerais"]
    },
    "bahia": {
        "official_name": "EC Bahia",
        "aliases": ["bahia fc", "bahia ba", "tricolor baiano", "bahiano"]
    },
    "internacional": {
        "official_name": "Sport Club Internacional",
        "aliases": ["inter", "internacional rs", "colorado", "rubro-negro"]
    },
    "grêmio": {
        "official_name": "Grêmio Football Club",
        "aliases": ["gremio", "gremio rs", "tricolor", "tricolor gaúcho"]
    },
    "atlético-mg": {
        "official_name": "Clube Atlético Mineiro",
        "aliases": ["atletico mineiro", "atletico mg", "atletico minas", "galo", "campão de campões"]
    },
    "fortaleza": {
        "official_name": "Fortaleza Esporte Clube",
        "aliases": ["fortaleza ce", "leão do pici", "leão"]
    },
    "santos": {
        "official_name": "Santos Futebol Clube",
        "aliases": ["santos sp", "peixe", "santista", "meninos da vila"]
    },
    "corinthians": {
        "official_name": "Sport Club Corinthians Paulista",
        "aliases": ["corinthians sp", "timão", "coringão"]
    },
    "são paulo": {
        "official_name": "São Paulo Football Club",
        "aliases": ["sao paulo", "spfc", "tricolor paulista", "peixada"]
    },
    # Argentina (8 teams)
    "river plate": {
        "official_name": "Club Atlético River Plate",
        "aliases": ["river", "millonarios", "river Buenos Aires", "superclásico"]
    },
    "boca juniors": {
        "official_name": "Club Atlético Boca Juniors",
        "aliases": ["boca", "xeneize", "bombonera", "boca buenos aires"]
    },
    "independiente": {
        "official_name": "Club Atlético Independiente",
        "aliases": ["independiente", "rojo", "independiente ba", "roji-negro"]
    },
    "racing": {
        "official_name": "Racing Club",
        "aliases": ["racing club", "racing argentina", "ajedrez", "celeste y blanco"]
    },
    "san lorenzo": {
        "official_name": "Club Atlético San Lorenzo de Almagro",
        "aliases": ["san lorenzo", "ciclón", "matador", "santo lorenzo"]
    },
    "vélez sarsfield": {
        "official_name": "Club Atlético Vélez Sarsfield",
        "aliases": ["velez", "veles sarsfield", "veles", "fortín", "linojero"]
    },
    "argentinos juniors": {
        "official_name": "Asociación Atlética Argentinos Juniors",
        "aliases": ["argentinos", "argentinos juniors", "bicampeón", "la paternal"]
    },
    "newell's old boys": {
        "official_name": "Club Atlético Newell's Old Boys",
        "aliases": ["newell's", "newells", "newell", "lepra", "rosarino"]
    },
    # Paraguay (2 teams)
    "olimpia": {
        "official_name": "Club Olimpia",
        "aliases": ["olimpia paraguay", "olimpia pa", "décima"]
    },
    "cerro porteño": {
        "official_name": "Cerro Porteño",
        "aliases": ["cerro porteno", "rojo habanero", "azulgrana"]
    },
    # Uruguay (2 teams)
    "nacional": {
        "official_name": "Club Nacional de Football",
        "aliases": ["nacional uruguay", "tricolor", "bolso"]
    },
    "peñarol": {
        "official_name": "Peñarol",
        "aliases": ["penarol", "peñarol uruguay", "carbonero", "manya"]
    },
    # Colombia (2 teams)
    "millonarios": {
        "official_name": "Millonarios Fútbol Club",
        "aliases": ["millonarios colombia", "embajador", "azul cielo"]
    },
    "nacional": {
        "official_name": "Atlético Nacional",
        "aliases": ["atletico nacional", "nacional colombia", "verde", "verdolaga", "millo 1946"]
    },
    # Chile (2 teams)
    "colo-colo": {
        "official_name": "Club Social y Deportivo Colo-Colo",
        "aliases": ["colo colo", "colocolo", "cacique", "alba blanca"]
    },
    "universidad de chile": {
        "official_name": "Club Universidad de Chile",
        "aliases": ["u de chile", "la u", "azules", "chuncho"]
    },
    # Perú (2 teams)
    "alianza lima": {
        "official_name": "Alianza Lima",
        "aliases": ["alianza", "alianza lima pe", "íntimos", "blanquiazul"]
    },
    "sporting cristal": {
        "official_name": "Sporting Cristal",
        "aliases": ["sporting", "sporting cristal pe", "rimense", "celeste"]
    },
    # Bolivia (1 team)
    "the strongest": {
        "official_name": "The Strongest",
        "aliases": ["strongest", "the strongest bolivia", "millonarios altiplano", "pumas"]
    },
    # Ecuador (1 team)
    "barcelona": {
        "official_name": "Barcelona Sporting Club",
        "aliases": ["barcelona ecuador", "barcelona sc", "toreros", "canario"]
    },
    # Venezuela (1 team)
    "estudiantes": {
        "official_name": "Estudiantes de Mérida",
        "aliases": ["estudiantes venezuela", "estudiantes merida", "blanco-azules"]
    },
}

# Build golden mapping from actual API teams
golden_mapping = []

for team in teams:
    team_name = team.get("name", "").lower().strip()
    team_id = team.get("id")
    
    print(f"  Processing: {team_name} (ID: {team_id})")
    
    # Find best match in aliases_map
    canonical = None
    aliases = []
    official_name = team.get("name", team_name)
    
    # Try exact match first
    if team_name in aliases_map:
        canonical = team_name
        aliases = aliases_map[team_name]["aliases"]
        official_name = aliases_map[team_name]["official_name"]
    else:
        # Try substring match
        for key, data in aliases_map.items():
            if key in team_name or team_name in key:
                canonical = key
                aliases = data["aliases"]
                official_name = data["official_name"]
                break
    
    if not canonical:
        # Fallback: use team name as canonical
        canonical = team_name
        print(f"    ⚠️  No aliases found, using team name as canonical")
    
    # Add base name and variations
    base_aliases = [team_name]
    # Add lowercase and variations
    if "-" in team_name:
        base_aliases.append(team_name.replace("-", " "))
        base_aliases.append(team_name.replace("-", ""))
    
    # Combine all aliases
    all_aliases = list(set(base_aliases + aliases))
    
    mapping_entry = {
        "canonical_name": canonical,
        "official_name": official_name,
        "aliases": sorted(list(set(all_aliases)))
    }
    
    golden_mapping.append(mapping_entry)

print(f"\n✅ Built golden mapping for {len(golden_mapping)} teams")
print(f"   Sample: {golden_mapping[0]}")

# Write to file
output_file = "utils/copa_golden_mapping.json"
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(golden_mapping, f, ensure_ascii=False, indent=4)

print(f"\n✅ Saved to {output_file}")
print("="*80)
