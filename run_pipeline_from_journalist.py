import argparse
import io
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from graph_pipeline import create_initial_state
from agents.insights_agent import insights_agent_node
from agents.normalizer_agent import normalizer_agent_node
from agents.gate_agent import gate_agent_node
from agents.analyst_agent import analyst_agent_node
from agents.bettor_agent import bettor_agent_node
from run_pipeline import save_results

# Force UTF-8 on Windows consoles
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)-8s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def _load_json(path: str, default=None):
    p = Path(path)
    if not p.exists():
        if default is not None:
            logger.warning(f'Archivo no encontrado: {path} (usando default)')
            return default
        raise FileNotFoundError(f'No existe archivo requerido: {path}')
    with p.open('r', encoding='utf-8') as f:
        return json.load(f)


def _infer_competitions(odds_canonical, journalist_data):
    labels = []
    seen = set()

    for ev in odds_canonical or []:
        comp = (ev or {}).get('competition')
        if comp and comp not in seen:
            labels.append(comp)
            seen.add(comp)

    for comp_obj in (journalist_data or {}).get('competitions', []):
        comp = (comp_obj or {}).get('competition')
        if comp and comp not in seen:
            labels.append(comp)
            seen.add(comp)

    return [{'competition': c} for c in labels]


def _build_insights_sources_from_journalist(journalist_data):
    sources = {}
    for comp in (journalist_data or {}).get('competitions', []):
        label = comp.get('competition')
        if not label:
            continue
        urls = []
        for v in comp.get('videos', []) or []:
            url = (v or {}).get('url')
            if url:
                urls.append(url)
        sources[label] = urls
    return sources


def build_state_from_artifacts(journalist_path, odds_path, stats_path, fixtures_path=None):
    journalist = _load_json(journalist_path)
    odds = _load_json(odds_path)
    stats = _load_json(stats_path)
    fixtures = _load_json(fixtures_path, default=[]) if fixtures_path else []

    competitions = _infer_competitions(odds, journalist)
    if not competitions:
        raise ValueError('No se pudieron inferir competencias desde odds/journalist artifacts')

    state = create_initial_state(competitions, fixtures_days_ahead=30)
    state['fixtures'] = fixtures or []
    state['odds_canonical'] = odds or []
    state['stats_by_team'] = stats or []
    state['journalist_videos'] = journalist
    state['insights_sources'] = _build_insights_sources_from_journalist(journalist)

    meta = state.setdefault('meta', {})
    meta['resumed_from'] = 'journalist_artifact'
    meta['resumed_at'] = datetime.now().isoformat()
    meta['resume_inputs'] = {
        'journalist': str(journalist_path),
        'odds': str(odds_path),
        'stats': str(stats_path),
        'fixtures': str(fixtures_path) if fixtures_path else None,
    }
    meta.setdefault('errors', {}).setdefault('insights', {})

    return state


def run_partial_pipeline(state):
    logger.info('=' * 80)
    logger.info('PARTIAL PIPELINE: STARTING FROM INSIGHTS AGENT')
    logger.info('=' * 80)

    state = insights_agent_node(state)
    state = normalizer_agent_node(state)
    state = gate_agent_node(state)
    state = analyst_agent_node(state)
    state = bettor_agent_node(state)

    state.setdefault('meta', {})['completed_at'] = datetime.now().isoformat()

    logger.info('=' * 80)
    logger.info('PARTIAL PIPELINE COMPLETE')
    logger.info('=' * 80)
    return state


def parse_args():
    parser = argparse.ArgumentParser(
        description='Ejecuta pipeline parcial desde insights usando la salida persistida del periodista.'
    )
    parser.add_argument('--journalist', default='journalist_test_output.json', help='JSON de salida del periodista')
    parser.add_argument('--odds', default='pipeline_odds.json', help='JSON de odds canónicas')
    parser.add_argument('--stats', default='pipeline_stats.json', help='JSON de stats por equipo')
    parser.add_argument('--fixtures', default='pipeline_fixtures.json', help='JSON de fixtures (opcional, para contexto)')
    parser.add_argument('--no-fixtures', action='store_true', help='No cargar fixtures')
    parser.add_argument('--output-prefix', default='pipeline', help='Prefijo de archivos de salida')
    return parser.parse_args()


def main():
    load_dotenv()
    args = parse_args()

    fixtures_path = None if args.no_fixtures else args.fixtures

    state = build_state_from_artifacts(
        journalist_path=args.journalist,
        odds_path=args.odds,
        stats_path=args.stats,
        fixtures_path=fixtures_path,
    )

    logger.info(
        'Artefactos cargados | comps=%s | odds=%s | stats=%s | youtube_urls=%s',
        [c.get('competition') for c in state.get('competitions', [])],
        len(state.get('odds_canonical') or []),
        len(state.get('stats_by_team') or []),
        sum(len(v) for v in (state.get('insights_sources') or {}).values()),
    )

    result = run_partial_pipeline(state)
    save_results(result, output_prefix=args.output_prefix)

    print('\nResumen parcial:')
    print(f"- Insights: {len(result.get('insights', []) or [])}")
    print(f"- Match contexts: {len(result.get('match_contexts', []) or [])}")
    print(f"- Predictions: {len(result.get('predictions', []) or [])}")
    print(f"- Betting tips: {len(result.get('betting_tips', []) or [])}")


if __name__ == '__main__':
    main()
