"""
Visualizador de Odds - Muestra los JSONs de salida de forma legible y formatada.

Este script permite visualizar los datos de odds normalizados con:
- Pretty-print JSON
- Filtrado por competencia
- Formateo con colores
- Estadísticas detalladas
- Búsqueda de eventos específicos

Uso:
    python view_odds.py                    # Muestra resumen
    python view_odds.py --full             # Todos los eventos (puede ser largo)
    python view_odds.py --ucl              # Solo Champions League
    python view_odds.py --chi1             # Solo Primera División Chile
    python view_odds.py --teams "Real Madrid" # Buscar equipo específico
    python view_odds.py --event 0          # Ver evento específico (número)
"""

import json
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any

# Colores ANSI para terminal
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

def load_odds_data() -> Optional[Dict[str, Any]]:
    """Carga datos desde odds_result.json"""
    odds_file = Path("odds_result.json")
    
    if not odds_file.exists():
        print(f"{Colors.RED}✗ Archivo no encontrado: {odds_file}{Colors.END}")
        return None
    
    try:
        with open(odds_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"{Colors.RED}✗ Error al parsear JSON: {e}{Colors.END}")
        return None


def print_header(text: str, char: str = "="):
    """Imprime un encabezado formateado"""
    width = 80
    print(f"\n{Colors.BOLD}{Colors.CYAN}{char * width}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{text.center(width)}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{char * width}{Colors.END}\n")


def print_subheader(text: str):
    """Imprime un sub-encabezado"""
    print(f"{Colors.BOLD}{Colors.BLUE}► {text}{Colors.END}")


def print_metadata_summary(meta: Dict[str, Any]):
    """Imprime resumen de metadatos"""
    print_header("METADATOS DEL PIPELINE", "=")
    
    print(f"{Colors.GREEN}Generado:{Colors.END} {meta.get('generated_at', 'N/A')}")
    print(f"{Colors.GREEN}Tiempo de procesamiento:{Colors.END} {meta.get('processing_time_seconds', 0):.2f}s")
    
    print(f"\n{Colors.BOLD}{Colors.YELLOW}Estadísticas Generales:{Colors.END}")
    print(f"  • Total eventos: {Colors.CYAN}{meta.get('total_events', 0)}{Colors.END}")
    print(f"  • Llamadas API: {Colors.CYAN}{meta.get('api_calls', 0)}{Colors.END}")
    print(f"  • Cache hits: {Colors.GREEN}{meta.get('cache_hits', 0)}{Colors.END}")
    
    print(f"\n{Colors.BOLD}{Colors.YELLOW}Por Competencia:{Colors.END}")
    for comp_code, comp_data in meta.get("competitions", {}).items():
        status_icon = "✓" if not comp_data.get("error") else "✗"
        status_color = Colors.GREEN if not comp_data.get("error") else Colors.RED
        cached_label = " (CACHED)" if comp_data.get("cache_hit") else ""
        
        print(f"  {status_color}{status_icon} {comp_code}{Colors.END}: "
              f"{comp_data.get('events', 0)} eventos{cached_label}")
        
        if comp_data.get("error"):
            print(f"    {Colors.RED}Error: {comp_data.get('error')}{Colors.END}")
    
    if meta.get("errors"):
        print(f"\n{Colors.RED}{Colors.BOLD}Errores:{Colors.END}")
        for err in meta.get("errors", [])[:5]:
            print(f"  • {err.get('error', 'Unknown')}")


def print_event_details(event: Dict[str, Any], event_num: int, total: int):
    """Imprime detalles de un evento individual"""
    print(f"\n{Colors.BOLD}[Evento {event_num}/{total}]{Colors.END}")
    print(f"━" * 80)
    
    # Información básica
    competition = event.get("competition", "N/A")
    home_team = event.get("home_team", "N/A")
    away_team = event.get("away_team", "N/A")
    commence_time = event.get("commence_time", "N/A")
    
    print(f"{Colors.BOLD}{Colors.YELLOW}Competencia:{Colors.END} {Colors.CYAN}{competition}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.YELLOW}Partidos:{Colors.END} {Colors.CYAN}{home_team}{Colors.END} vs {Colors.CYAN}{away_team}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.YELLOW}Hora del partido:{Colors.END} {Colors.CYAN}{commence_time}{Colors.END}")
    
    # Fixture match
    if event.get("fixture_match"):
        match_info = event.get("fixture_match")
        if match_info and match_info.get("matched"):
            print(f"{Colors.GREEN}✓ Matcheado con fixture (score: {match_info.get('match_score', 0):.3f}){Colors.END}")
    
    # Bookmakers
    bookmakers = event.get("bookmakers", [])
    print(f"\n{Colors.BOLD}{Colors.YELLOW}Bookmakers ({len(bookmakers)}):{Colors.END}")
    
    for i, bm in enumerate(bookmakers[:5], 1):  # Mostrar solo primeros 5
        print(f"\n  {i}. {Colors.CYAN}{bm.get('title', 'Unknown')}{Colors.END} ({bm.get('key', 'N/A')})")
        print(f"     Actualizado: {bm.get('last_update', 'N/A')}")
        
        outcomes = bm.get("outcomes", [])
        for outcome in outcomes:
            print(f"       • {outcome.get('name', 'N/A')}: {Colors.GREEN}{outcome.get('price', 'N/A')}{Colors.END}")
    
    if len(bookmakers) > 5:
        print(f"\n  ... y {len(bookmakers) - 5} bookmakers más")


def filter_events(events: List[Dict], competition: Optional[str] = None, 
                  teams_search: Optional[str] = None) -> List[Dict]:
    """Filtra eventos según criterios"""
    filtered = events
    
    if competition:
        filtered = [e for e in filtered if e.get("competition") == competition.upper()]
    
    if teams_search:
        search_lower = teams_search.lower()
        filtered = [e for e in filtered 
                   if search_lower in e.get("home_team", "").lower() 
                   or search_lower in e.get("away_team", "").lower()]
    
    return filtered


def show_full_view(data: Dict[str, Any], competition: Optional[str] = None, 
                   teams_search: Optional[str] = None, limit: int = 10):
    """Muestra vista completa con eventos"""
    events = data.get("odds_canonical", [])
    
    # Filtrar
    events = filter_events(events, competition, teams_search)
    
    if not events:
        print(f"{Colors.RED}✗ No se encontraron eventos con los criterios especificados{Colors.END}")
        return
    
    print_header(f"ODDS CANÓNICOS - Total: {len(events)} evento(s)", "=")
    
    # Mostrar solo primeros N
    display_count = min(limit, len(events))
    
    for i, event in enumerate(events[:display_count], 1):
        print_event_details(event, i, display_count)
    
    if len(events) > display_count:
        remaining = len(events) - display_count
        print(f"\n{Colors.YELLOW}... y {remaining} evento(s) más no mostrado(s){Colors.END}")
        print(f"{Colors.YELLOW}Usa --full para ver todos o --event N para ver un evento específico{Colors.END}\n")


def show_compact_view(data: Dict[str, Any], competition: Optional[str] = None):
    """Muestra vista compacta de eventos"""
    events = data.get("odds_canonical", [])
    events = filter_events(events, competition)
    
    print_header("VISTA COMPACTA - TODOS LOS EVENTOS", "=")
    
    print(f"{Colors.BOLD}{'Comp':<6} {'Home Team':<20} {'Away Team':<20} {'Bookmakers':<12} {'Match':<8}{Colors.END}")
    print(f"{'-' * 80}")
    
    for event in events:
        comp = event.get("competition", "N/A")[:4]
        home = event.get("home_team", "N/A")[:18]
        away = event.get("away_team", "N/A")[:18]
        bms = len(event.get("bookmakers", []))
        fixture_match = event.get("fixture_match")
        matched = "✓" if (fixture_match and fixture_match.get("matched")) else "✗"
        
        print(f"{comp:<6} {home:<20} {away:<20} {bms:<12} {matched:<8}")


def show_json_raw(data: Dict[str, Any], section: str = "meta"):
    """Muestra JSON raw formateado"""
    if section == "meta":
        obj = data.get("meta", {})
        title = "METADATOS (JSON Raw)"
    elif section == "events":
        obj = data.get("odds_canonical", [])[:3]  # Primeros 3 eventos
        title = "PRIMEROS 3 EVENTOS (JSON Raw)"
    else:
        print(f"{Colors.RED}Sección desconocida: {section}{Colors.END}")
        return
    
    print_header(title, "=")
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def show_team_search(data: Dict[str, Any], team_name: str):
    """Busca eventos por nombre de equipo"""
    events = filter_events(data.get("odds_canonical", []), teams_search=team_name)
    
    if not events:
        print(f"{Colors.RED}✗ No se encontraron eventos con: {team_name}{Colors.END}")
        return
    
    print_header(f"BÚSQUEDA: {team_name} - {len(events)} evento(s) encontrado(s)", "=")
    
    for i, event in enumerate(events[:10], 1):
        print_event_details(event, i, len(events))
    
    if len(events) > 10:
        print(f"\n{Colors.YELLOW}... y {len(events) - 10} evento(s) más{Colors.END}")


def main():
    """Función principal"""
    # Cargar datos
    data = load_odds_data()
    if not data:
        sys.exit(1)
    
    # Parsear argumentos
    args = sys.argv[1:]
    
    if not args or "--help" in args:
        print(__doc__)
        print_header("RESUMEN DISPONIBLE", "=")
        print_metadata_summary(data.get("meta", {}))
        return
    
    # Procesar argumentos
    if "--full" in args:
        # Mostrar todos los eventos
        competition = "--ucl" in args and "UCL" or ("--chi1" in args and "CHI1" or None)
        teams_search = None
        
        for i, arg in enumerate(args):
            if arg == "--teams" and i + 1 < len(args):
                teams_search = args[i + 1]
        
        show_full_view(data, competition, teams_search, limit=len(data.get("odds_canonical", [])))
    
    elif "--json-meta" in args:
        show_json_raw(data, "meta")
    
    elif "--json-events" in args:
        show_json_raw(data, "events")
    
    elif "--ucl" in args or "--chi1" in args:
        competition = "UCL" if "--ucl" in args else "CHI1"
        show_full_view(data, competition, limit=5)
    
    elif "--compact" in args:
        competition = "--ucl" in args and "UCL" or ("--chi1" in args and "CHI1" or None)
        show_compact_view(data, competition)
    
    elif "--teams" in args:
        idx = args.index("--teams")
        if idx + 1 < len(args):
            team_name = args[idx + 1]
            show_team_search(data, team_name)
        else:
            print(f"{Colors.RED}✗ Debes especificar un nombre de equipo después de --teams{Colors.END}")
    
    elif "--event" in args:
        idx = args.index("--event")
        if idx + 1 < len(args):
            try:
                event_num = int(args[idx + 1])
                events = data.get("odds_canonical", [])
                
                if 0 <= event_num < len(events):
                    print_header(f"EVENTO #{event_num}", "=")
                    print(json.dumps(events[event_num], indent=2, ensure_ascii=False))
                else:
                    print(f"{Colors.RED}✗ Evento #{event_num} fuera de rango (0-{len(events)-1}){Colors.END}")
            except ValueError:
                print(f"{Colors.RED}✗ Número de evento inválido{Colors.END}")
        else:
            print(f"{Colors.RED}✗ Debes especificar un número de evento después de --event{Colors.END}")
    
    else:
        # Mostrar resumen por defecto
        print_metadata_summary(data.get("meta", {}))
        print("\n")
        show_compact_view(data)
        print(f"\n{Colors.YELLOW}Tip: Usa --full para ver detalles completos, o --help para más opciones{Colors.END}\n")


if __name__ == "__main__":
    main()
