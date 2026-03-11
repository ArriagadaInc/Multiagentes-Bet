
import streamlit as st
import pandas as pd
import json
import os
import re
import sys
import subprocess
import time
import streamlit.components.v1 as components
from datetime import datetime
from utils.normalizer import slugify, TeamNormalizer
from utils.token_tracker import load_token_usage, reset_tokens
from utils.wishlist import save_analyst_wishlist

# --- CONFIGURATION ---
st.set_page_config(
    page_title="Betting Agent AI",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- STYLES ---
st.markdown("""
    <style>
    /* Global settings */
    .main {
        background-color: #0e1117;
        color: #ffffff;
    }
    h1, h2, h3, p, li {
        color: #e6e6e6 !important;
    }
    
    /* Buttons */
    .stButton>button {
        width: 100%;
        border-radius: 5px;
        height: 3em;
        background-color: #ff4b4b;
        color: white;
        font-weight: bold;
        border: none;
    }
    .stButton>button:hover {
        background-color: #ff6b6b;
        color: white;
    }

    /* Metrics (KPIs) */
    [data-testid="stMetricValue"] {
        color: #ffffff !important;
        font-size: 1.8rem !important;
    }
    [data-testid="stMetricLabel"] {
        color: #b0b3b8 !important;
    }
    
    /* Expanders & Containers */
    .streamlit-expanderHeader {
        background-color: #262730;
        color: white !important;
        border-radius: 5px;
    }
    
    /* Custom Card Styling */
    .css-1r6slb0 {  /* Default card container adjustment if needed */
        background-color: #262730;
        border: 1px solid #41444b;
        padding: 15px;
        border-radius: 10px;
    }
    
    /* Make sure expander text is visible */
    .streamlit-expanderContent {
        background-color: #1a1c24;
        color: #e6e6e6 !important;
        border-bottom-left-radius: 5px;
        border-bottom-right-radius: 5px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- CONSTANTS ---
FILES = {
    "apuestas": "pipeline_bets.json",
    "predicciones": "pipeline_predictions.json",
    "fixtures": "pipeline_fixtures.json",
    "odds": "pipeline_odds.json",
    "stats": "pipeline_stats.json",
    "insights": "pipeline_insights.json",
    "analyst_web_checks": "pipeline_analyst_web_checks.json",
    "journalist": "journalist_test_output.json",
    "team_history": "data/knowledge/team_history.json",
    "analyst_wishlist": "predictions/analyst_wishlist.json"
}
MANUAL_NEWS_FILE = os.path.join("data", "inputs", "manual_news_input.json")

# --- FUNCTIONS ---
def load_data(file_key):
    path = FILES.get(file_key)
    if not path or not os.path.exists(path):
        return []
    
    # Intentar cargar con UTF-8 primero, luego UTF-16 (común en redirects de Powershell)
    encodings = ["utf-8", "utf-16"]
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc) as f:
                return json.load(f)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    
    # Último recurso: UTF-8 con reemplazo de errores
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except:
        return []

def load_team_history_data():
    """Carga el historial persistente de insights por equipo."""
    data = load_data("team_history")
    return data if isinstance(data, dict) else {}

def load_manual_news_text():
    """Carga el texto de noticias manuales ingresadas por usuario (si existe)."""
    if not os.path.exists(MANUAL_NEWS_FILE):
        return ""
    try:
        with open(MANUAL_NEWS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return str((data or {}).get("text") or "")
    except Exception:
        return ""

def save_manual_news_text(text: str):
    """Persiste noticias manuales para que las consuma el insights_agent."""
    os.makedirs(os.path.dirname(MANUAL_NEWS_FILE), exist_ok=True)
    payload = {
        "updated_at": datetime.now().isoformat(),
        "text": text.strip(),
    }
    with open(MANUAL_NEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

def _on_save_manual_news():
    """Callback Streamlit: guarda noticias manuales desde session_state."""
    save_manual_news_text(st.session_state.get("manual_news_text", ""))
    st.session_state["manual_news_status"] = ("success", "Noticias manuales guardadas.")

def _on_clear_manual_news():
    """Callback Streamlit: limpia widget + persistencia de noticias manuales."""
    st.session_state["manual_news_text"] = ""
    save_manual_news_text("")
    st.session_state["manual_news_status"] = ("info", "Noticias manuales limpiadas.")

def get_odds_info(match_name, all_odds):
    """Encuentra odds por nombre de partido (fuzzy match basic)."""
    # 1. Match Exacto de nombres normalizados
    if " vs " in match_name:
        t_home, t_away = match_name.split(" vs ", 1)
    else:
        t_home, t_away = match_name, ""
    target_slug = f"{slugify(t_home)} vs {slugify(t_away)}"
    
    for game in all_odds:
        # Check normal
        g_home = game.get('home_team', '')
        g_away = game.get('away_team', '')
        g_slug = f"{slugify(g_home)} vs {slugify(g_away)}"
        
        if g_slug == target_slug:
            return game
            
        # 2. Match Parcial (si ambos equipos del fixture están contenidos o viceversa)
        # Esto maneja "Atlético Madrid" vs "Club Atlético de Madrid"
        
        # Breakdown match_name (from fixture)
        # Assumes match_name is "Home vs Away"
        if " vs " in match_name:
            fix_home, fix_away = match_name.split(" vs ")
            
            # Cross check
            match_home = (g_home.lower() in fix_home.lower()) or (fix_home.lower() in g_home.lower())
            match_away = (g_away.lower() in fix_away.lower()) or (fix_away.lower() in g_away.lower())
            
            if match_home and match_away:
                return game

    return None

# --- MAIN PAGE DATA LOADING ---
stats_data = load_data("stats")
insights_data = load_data("insights")
odds_data = load_data("odds")

def run_pipeline_script(ligas: list = None):
    """Ejecuta el script del pipeline externo con streaming de logs y barra de progreso."""
    try:
        cmd = [sys.executable, "run_pipeline.py"]
        if ligas:
            cmd += ["--liga"] + [l.upper() for l in ligas]

        # UI Elements for Progress
        progress_bar = st.progress(0, text="Iniciando motores de IA...")
        status_box = st.empty()
        log_expander = st.expander("📜 Ver Logs en Tiempo Real", expanded=True)
        log_placeholder = log_expander.empty()
        full_logs = ""
        
        # Start Process (Merge stdout/stderr)
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8', 
            errors='replace',
            bufsize=1 # Line buffered
        )
        
        # Registrar PID para poder detenerlo
        st.session_state["pipeline_process"] = process
        st.session_state["pipeline_running"] = True
        
        try:
            # Keywords to mapping progress
            # (Log text fragment -> (Progress %, Display Message))
            progress_map = {
                "Fetching fixtures":  (10, "📅 Obteniendo partidos programados..."),
                "Fetching odds":      (20, "📊 Consultando cuotas de mercado (Odds API)..."),
                "STATS AGENT":        (30, "📈 Analizando estadísticas multifuente..."),
                "JOURNALIST AGENT":   (42, "🎙️ Agente Periodista descubriendo videos..."),
                "ANALYZING VIDEO":    (50, "🧠 Extrayendo insights de YouTube..."),
                "WEB AGENT":          (58, "🌐 Agente Web buscando contexto de jornada..."),
                "NORMALIZER AGENT":   (68, "🔗 Consolidando identidades de equipos..."),
                "GATE AGENT":         (73, "🛡️ Validando calidad y completitud de datos..."),
                "ANALYST AGENT":      (85, "🔮 Agente Analista pensando predicciones..."),
                "BETTOR AGENT":       (95, "💰 Agente Apostador buscando valor (Edge)..."),
                "SUCCESSFUL":         (100, "✅ ¡Análisis Completado!")
            }
            
            current_progress = 0
            
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                
                if line:
                    full_logs += line
                    log_placeholder.code(full_logs[-20000:], language='text') # Show last 20k char to avoid UI lag
                    
                    # Check for progress keywords
                    for key, (pct, msg) in progress_map.items():
                        if key in line:
                            current_progress = pct
                            progress_bar.progress(pct, text=msg)
                            break
        finally:
            st.session_state["pipeline_running"] = False
            if process.poll() is None:
                # Proceso aún vivo, matarlo con taskkill /F /T para que limpie hijos
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
            st.session_state.pop("pipeline_process", None)
        
        # Guardar log a disco para persistir entre sesiones
        try:
            with open("pipeline_last_run.log", "w", encoding="utf-8") as lf:
                lf.write(full_logs)
        except Exception:
            pass

        if process.returncode == 0:
            progress_bar.progress(100, text="✅ ¡Proceso Terminado!")
            time.sleep(1)
            progress_bar.empty()
            st.success("✅ ¡Pipeline ejecutado exitosamente!")
            return True, full_logs
        else:
            st.error("❌ Falló el Pipeline.")
            return False, full_logs
            
    except Exception as e:
        st.error(f"Error Crítico: {e}")
        return False, str(e)

def run_partial_pipeline_from_journalist_script():
    """Ejecuta el pipeline parcial desde insights usando la salida persistida del periodista."""
    try:
        script_name = "run_pipeline_from_journalist.py"
        if not os.path.exists(script_name):
            st.error("No existe `run_pipeline_from_journalist.py` en el proyecto.")
            return False, "runner parcial no encontrado"

        cmd = [sys.executable, script_name]

        progress_bar = st.progress(0, text="Preparando pipeline parcial (desde periodista)...")
        log_expander = st.expander("?? Ver Logs en Tiempo Real (Parcial)", expanded=True)
        log_placeholder = log_expander.empty()
        full_logs = ""

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1
        )

        # Registrar PID para poder detenerlo
        st.session_state["pipeline_process"] = process
        st.session_state["pipeline_running"] = True

        try:
            progress_map = {
                "PARTIAL PIPELINE: STARTING FROM INSIGHTS AGENT": (10, "??? Iniciando desde Insights..."),
                "INSIGHTS AGENT": (30, "?? Extrayendo insights de YouTube..."),
                "NORMALIZER AGENT": (55, "?? Consolidando identidades..."),
                "GATE AGENT": (70, "??? Validando calidad de datos..."),
                "ANALYST AGENT": (85, "?? Generando predicciones..."),
                "BETTOR AGENT": (95, "?? Generando apuestas..."),
                "PARTIAL PIPELINE COMPLETE": (100, "? Pipeline parcial completado"),
            }

            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break

                if line:
                    full_logs += line
                    log_placeholder.code(full_logs[-20000:], language='text')

                    for key, (pct, msg) in progress_map.items():
                        if key in line:
                            progress_bar.progress(pct, text=msg)
                            break
        finally:
            st.session_state["pipeline_running"] = False
            if process.poll() is None:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
            st.session_state.pop("pipeline_process", None)

        try:
            with open("pipeline_last_run.log", "w", encoding="utf-8") as lf:
                lf.write(full_logs)
            with open("pipeline_partial_last_run.log", "w", encoding="utf-8") as lf:
                lf.write(full_logs)
        except Exception:
            pass

        if process.returncode == 0:
            progress_bar.progress(100, text="? ?Proceso parcial terminado!")
            time.sleep(1)
            progress_bar.empty()
            st.success("? ?Pipeline parcial ejecutado exitosamente!")
            return True, full_logs
        else:
            st.error("? Fall? el Pipeline parcial.")
            return False, full_logs

    except Exception as e:
        st.error(f"Error Cr?tico (pipeline parcial): {e}")
        return False, str(e)

def run_web_agent_script(user_prompt: str):
    """Ejecuta el Agente Web standalone y devuelve (success, logs)."""
    try:
        script_name = "run_web_agent.py"
        if not os.path.exists(script_name):
            return False, "No existe run_web_agent.py"

        cmd = [sys.executable, script_name, "--prompt", user_prompt]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        logs = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        return result.returncode == 0, logs
    except Exception as e:
        return False, f"Error ejecutando Agente Web: {e}"

# --- SIDEBAR ---
with st.sidebar:
    st.title("⚽ Agente de Apuestas IA")
    st.markdown("---")
    
    st.subheader("⚙️ Panel de Control")
    
    liga_sidebar = st.selectbox(
        "⚽ Liga",
        options=["CHI1", "UCL", "Ambas"],
        index=0,
        key="sidebar_liga_sel",
        help="Elige la liga a analizar en este ciclo."
    )

    st.markdown("###")
    st.subheader("?? Noticias Manuales (Insights)")
    if "manual_news_text" not in st.session_state:
        st.session_state["manual_news_text"] = load_manual_news_text()
    st.text_area(
        "Agrega noticias/contexto (el agente de insights las ponderar? si aplican)",
        key="manual_news_text",
        height=140,
        placeholder="Ej: Real Madrid viene de pol?mica racial con alta presi?n medi?tica...\nHuachipato rota por Copa Libertadores..."
    )
    status_tuple = st.session_state.pop("manual_news_status", None)
    if status_tuple:
        level, msg = status_tuple
        if level == "success":
            st.success(msg)
        elif level == "info":
            st.info(msg)
        else:
            st.warning(msg)
    c_news1, c_news2 = st.columns(2)
    c_news1.button("Guardar Noticias", on_click=_on_save_manual_news)
    c_news2.button("Limpiar Noticias", on_click=_on_clear_manual_news)
    
    st.markdown("###")

    # ── Selector de liga ────────────────────────────────────────────────────
    liga_exec = st.selectbox(
        "⚽ Liga a ejecutar",
        options=["CHI1", "UCL", "Ambas"],
        index=0,
        key="pipeline_liga_exec",
        help="CHI1 = Solo Chile | UCL = Solo Champions | Ambas = las dos juntas"
    )
    _ligas_arg = None if liga_exec == "Ambas" else [liga_exec]
    btn_label = f"🚀 EJECUTAR ANÁLISIS ({liga_exec})"
    if st.button(btn_label):
        success, logs = run_pipeline_script(ligas=_ligas_arg)
        if success:
            st.session_state['last_run'] = datetime.now()
            st.session_state['logs'] = logs
            time.sleep(1)
            st.rerun()

    if st.button("? EJECUTAR PARCIAL (DESDE PERIODISTA)"):
        success, logs = run_partial_pipeline_from_journalist_script()
        if success:
            st.session_state['last_run'] = datetime.now()
            st.session_state['logs'] = logs
            time.sleep(1)
            st.rerun()

    if st.session_state.get("pipeline_running"):
        st.markdown("---")
        if st.button("🛑 DETENER EJECUCIÓN", type="secondary"):
            proc = st.session_state.get("pipeline_process")
            if proc:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            st.session_state["pipeline_running"] = False
            st.warning("⚠️ Ejecución detenida por el usuario.")
            time.sleep(1)
            st.rerun()

    st.markdown("---")
    if 'last_run' in st.session_state:
        st.caption(f"Última actualización: {st.session_state['last_run'].strftime('%H:%M:%S')}")

# --- MAIN PAGE ---
st.title("🧠 Dashboard de Análisis Deportivo IA")

# Load Data
bets_data = load_data("apuestas")
preds_data = load_data("predicciones")
fixtures_data = load_data("fixtures")
journalist_data = load_data("journalist")
analyst_web_checks_data = load_data("analyst_web_checks")
team_history_data = load_team_history_data()

# --- QUOTA ALERTS ---
if journalist_data:
    for comp in journalist_data.get("competitions", []):
        errors = comp.get("errors", [])
        for err in errors:
            if "cuota" in err.lower() or "403" in err or "quota" in err.lower():
                st.error(f"⚠️ **Cuota de YouTube Agotada:** No se pudieron descubrir nuevos videos para {comp.get('competition')}. Inicia sesión mañana para resetear la cuota.")
                break


# KPI ROW
col1, col2, col3, col4 = st.columns(4)

total_bets = len(bets_data)
value_bets = len([b for b in bets_data if b.get("type") == "value_bet"])
combos = len([b for b in bets_data if "combo" in b.get("type", "")])
avg_edge = 0
if value_bets > 0:
    edges = [b.get("edge_pct", 0) for b in bets_data if b.get("type") == "value_bet"]
    avg_edge = sum(edges) / len(edges) if edges else 0

col1.metric("Total Tips", total_bets, delta=f"{len(preds_data)} Analizados")
col2.metric("Value Bets", value_bets, delta="Alta Confianza")
col3.metric("Combinadas", combos, "Multiplicadores")
col4.metric("Edge Promedio", f"{avg_edge:.1f}%", help="Ventaja teórica sobre la casa")

# --- HELPER FUNCTIONS FOR TRACEABILITY ---
def get_fixture_info(match_name, fixtures):
    """Encuentra info del fixture por nombre de partido."""
    for f in fixtures:
        name = f"{f.get('home_team')} vs {f.get('away_team')}"
        if name == match_name:
            return f
    return None

def _local_slug(text):
    """Versión simplificada de slugify para la UI (elimina acentos y ruido básico)."""
    return slugify(text)

def _match_slug(home: str, away: str) -> str:
    return f"{slugify(home)} vs {slugify(away)}"

def _canon_team(name: str) -> str:
    raw = (name or "").strip()
    # Ignorar sufijos de desambiguación usados en algunas salidas, ej: "(CHI)"
    raw = re.sub(r"\s*\([A-Za-z]{2,5}\)\s*$", "", raw)
    return TeamNormalizer().clean(raw)

def _match_canonical(home: str, away: str) -> str:
    return f"{_canon_team(home)} vs {_canon_team(away)}"

def get_stats_info(team_name, all_stats):
    """Encuentra stats por nombre de equipo con tolerancia a acentos."""
    target = _local_slug(team_name)
    for s in all_stats:
        if _local_slug(s.get("team", "")) == target:
            return s
    return None

def get_insights_info(team_name, all_insights):
    """Encuentra insights por nombre de equipo con tolerancia a acentos."""
    target = _local_slug(team_name)
    for i in all_insights:
        if _local_slug(i.get("team", "")) == target:
            return i
    return None

def get_prediction_info(match_name, predictions):
    """Encuentra predicción por nombre de partido."""
    if " vs " in match_name:
        target_home, target_away = match_name.split(" vs ", 1)
    else:
        target_home, target_away = match_name, ""
    target_slug = _match_slug(target_home, target_away)
    target_canon = _match_canonical(target_home, target_away)
    for p in predictions:
        p_home = p.get("home_team", "")
        p_away = p.get("away_team", "")
        p_slug = _match_slug(p_home, p_away)
        p_canon = _match_canonical(p_home, p_away)
        if p_slug == target_slug or p_canon == target_canon:
            return p
    return None

def get_bet_info(match_name, bets):
    """Encuentra apuesta por nombre de partido."""
    if " vs " in match_name:
        target_home, target_away = match_name.split(" vs ", 1)
    else:
        target_home, target_away = match_name, ""
    target_slug = _match_slug(target_home, target_away)
    target_canon = _match_canonical(target_home, target_away)
    for b in bets:
        match = b.get("match", "")
        if " vs " in match:
            b_home, b_away = match.split(" vs ", 1)
        else:
            b_home, b_away = match, ""
        if _match_slug(b_home, b_away) == target_slug or _match_canonical(b_home, b_away) == target_canon:
            return b
    return None

def _match_id_slugs(match_id: str):
    """
    Extrae slugs home/away desde match_id:
    COMP_YYYY-MM-DD_home-slug_away-slug
    """
    if not match_id or not isinstance(match_id, str):
        return None, None
    parts = match_id.split("_")
    if len(parts) < 4:
        return None, None
    # tolera underscores extra en prefijo futuro: home/away son los dos últimos segmentos
    home_slug = parts[-2]
    away_slug = parts[-1]
    return home_slug, away_slug

def get_prediction_info_by_match_id(match_id, predictions):
    """Encuentra predicción usando slugs del match_id (fuente de verdad del normalizador)."""
    target_home_slug, target_away_slug = _match_id_slugs(match_id)
    if not target_home_slug or not target_away_slug:
        return None
    for p in predictions or []:
        p_home = slugify(p.get("home_team", ""))
        p_away = slugify(p.get("away_team", ""))
        if p_home == target_home_slug and p_away == target_away_slug:
            return p
    return None

def get_bet_info_by_match_id(match_id, bets):
    """Encuentra apuesta usando slugs del match_id."""
    target_home_slug, target_away_slug = _match_id_slugs(match_id)
    if not target_home_slug or not target_away_slug:
        return None
    for b in bets or []:
        match = b.get("match", "")
        if " vs " in match:
            b_home, b_away = match.split(" vs ", 1)
        else:
            b_home, b_away = match, ""
        if slugify(b_home) == target_home_slug and slugify(b_away) == target_away_slug:
            return b
    return None

def _render_insight_meta(meta):
    """Renderiza confianza y citas en la UI."""
    if not meta:
        return
    
    conf = meta.get("confidence", 0)
    conf_color = "🟢" if conf >= 0.7 else "🟡" if conf >= 0.4 else "🔴"
    st.markdown(f"**Confianza del Insight:** {conf_color} {conf*100:.0f}%")
    if meta.get("confidence_rationale"):
        st.caption(f"_{meta.get('confidence_rationale')}_")
    
    citations = meta.get("citations", [])
    if citations:
        with st.expander("📌 Ver Citas de YouTube"):
            for c in citations:
                if isinstance(c, dict):
                    ts = f"[{c.get('timestamp')}] " if c.get('timestamp') else ""
                    st.markdown(f"> \"{c.get('text')}\" {ts}")
                else:
                    # Caso: la cita es solo un string (URL o texto directo)
                    st.markdown(f"> {c}")


def _render_signal_provenance_badges(sig: dict):
    """Renderiza fuentes de una señal de contexto para auditoría visual rápida."""
    prov = sig.get("provenance") or []
    if isinstance(prov, str):
        prov = [prov]
    prov = [str(p).strip() for p in prov if str(p).strip()]
    if not prov:
        return
    badge_line = " ".join([f"`{p}`" for p in sorted(set(prov))])
    st.caption(f"Fuentes: {badge_line}")


def _render_trace_journalist_videos(team_name, journalist_data, videos_from_insights=None):
    """Renderiza el descubrimiento de videos para un equipo en el rastreo."""
    
    # Priorizar videos que ya vienen en el MatchContext (videos reales usados en el run)
    if videos_from_insights:
        st.write(f"🎥 **Videos procesados en este run ({len(videos_from_insights)}):**")
        for v in videos_from_insights[:5]: # Mostrar hasta 5
            st.markdown(f"- [{v.get('title')[:70]}...]({v.get('url')})")
            channel = v.get("channel")
            channel_name = channel if isinstance(channel, str) else channel.get("title") if isinstance(channel, dict) else "N/A"
            st.caption(f"   Canal: {channel_name}")
        return

    if not journalist_data:
        st.warning("Sin datos del Agente Periodista.")
        return

    # Buscar videos para este equipo en todas las competencias (Fallback a datos crudos del periodista)
    team_videos = []
    t_slug = slugify(team_name)
    
    for comp_group in journalist_data.get("competitions", []):
        for vid in comp_group.get("videos", []):
            rel = vid.get("relevance", {})
            matched = rel.get("matched_keywords", [])
            # Verificación simple: si el equipo está en los keywords match
            if any(t_slug in slugify(str(m)) for m in matched) or \
               t_slug in slugify(vid.get("title", "")) or \
               t_slug in slugify(vid.get("description_snippet", "")):
                team_videos.append(vid)

    if not team_videos:
        st.caption(f"No se encontraron videos específicos para {team_name} en este run.")
        return

    st.write(f"🎥 **Videos descubiertos ({len(team_videos)}):**")
    for v in team_videos[:3]: # Mostrar top 3
        st.markdown(f"- [{v.get('title')[:60]}...]({v.get('url')})")
        st.caption(f"   Canal: {v.get('channel', {}).get('title')} | Rel: {v.get('relevance', {}).get('score', 0):.2f}")


def _render_trace_gate_agent(mc):
    """Renderiza la validación del Gate Agent."""
    if not mc:
        return
    
    q_data = mc.get("data_quality", {})
    score = q_data.get("score", 1.0)
    notes = q_data.get("notes", [])
    
    q_color = "#2ecc71" if score >= 0.7 else "#f1c40f" if score >= 0.4 else "#e74c3c"
    
    st.markdown(f"""
    <div style="background-color: #1a1c24; padding: 15px; border-radius: 10px; border-left: 8px solid {q_color}; margin-top: 10px;">
        <h4 style="margin:0; color:{q_color};">🛡️ Gate Agent: Validation Score {score:.2f}</h4>
        <p style="font-size: 0.9em; color: #aaa; margin-top: 5px;">
            {" • ".join(notes) if notes else "Todos los controles de integridad pasaron correctamente."}
        </p>
    </div>
    """, unsafe_allow_html=True)


def _normalize_ui_text(text: str) -> str:
    """Normalización ligera para deduplicación visual en la UI."""
    from utils.normalizer import slugify
    t = (text or "").lower().strip()
    # Eliminar prefijos de contexto si existen
    t = re.sub(r"^contexto\s*\([^)]+\):", "", t)
    t = re.sub(r"^contexto:", "", t)
    # Slugify para comparar solo contenido alfanumérico
    return slugify(t).replace("-", "")

def _render_trace_team_insights(team_label, team_insights):
    """Renderiza en Rastreo de Agentes el payload de insights tal como lo recibe el analista."""
    if not team_insights:
        st.error("Sin Video Análisis")
        return

    if not isinstance(team_insights, dict):
        st.error(f"Error: Payload de insights para {team_label} no es un objeto válido.")
        st.code(str(team_insights))
        return

    insight_text = (team_insights.get("insight") or "").strip()
    as_of_date = (team_insights.get("as_of_date") or "").strip()
    if as_of_date:
        st.caption(f"Fecha del insight (payload): {as_of_date}")
    if insight_text:
        source_label = str(team_insights.get("source") or "insights")
        st.success(f"**Análisis Táctico ({source_label}):**")
        # Mostrar todas las líneas/bullets que recibe el analista (no solo bloque compacto)
        for ln in [x.strip() for x in insight_text.splitlines() if x.strip()]:
            if ln.startswith("- "):
                st.markdown(ln)
            else:
                st.markdown(f"- {ln}")
    else:
        st.warning("Hay payload de insights, pero el texto principal viene vac?o.")

    _render_insight_meta(team_insights.get("insight_meta"))

    context_signals = team_insights.get("context_signals") or []
    if context_signals:
        # Deduplicar contra el texto principal ya renderizado
        main_text_norms = { _normalize_ui_text(ln) for ln in insight_text.splitlines() if ln.strip() }
        
        visible_signals = []
        for sig in context_signals:
            if not isinstance(sig, dict): continue
            sig_text = sig.get("signal", "")
            if _normalize_ui_text(sig_text) in main_text_norms:
                continue
            visible_signals.append(sig)

        if visible_signals:
            st.markdown("**Contexto adicional detectado:**")
            for sig in visible_signals:
                sig_type = sig.get("type", "other")
                sig_text = sig.get("signal", "")
                sig_ev = sig.get("evidence", "")
                sig_conf = sig.get("confidence", None)
                sig_date = sig.get("date", None)
                sig_rumor = bool(sig.get("is_rumor", False))
                conf_txt = f" (conf. {sig_conf:.2f})" if isinstance(sig_conf, (int, float)) else ""
                date_txt = f" [{sig_date}]" if sig_date else ""
                rumor_txt = " `RUMOR`" if sig_rumor else ""
                st.markdown(f"- `{sig_type}`{date_txt}{rumor_txt}: {sig_text}{conf_txt}")
                _render_signal_provenance_badges(sig)
                if sig_ev:
                    st.caption(f"Evidencia: {sig_ev}")

    # --- NUEVA SECCIÓN: ENTIDADES (BAJAS/NOVEDADES) ---
    entities = team_insights.get("entities") or {}
    injuries = entities.get("injuries") or []
    suspensions = entities.get("suspensions") or []
    absences = entities.get("absences") or []
    
    if injuries or suspensions or absences:
        st.markdown("🚑 **Novedades de Plantilla:**")
        if injuries:
            for item in injuries: st.markdown(f" - ❗ *Lesión:* {item}")
        if suspensions:
            for item in suspensions: st.markdown(f" - 🟨 *Sanción:* {item}")
        if absences:
            for item in absences: st.markdown(f" - 👤 *Ausencia:* {item}")

    with st.expander(f"⚙️ Payload de Insights entregado al Analista ({team_label})", expanded=False):
        st.json(team_insights)

# --- MAIN PAGE DATA LOADING ---
# Data is already loaded at the top around line 100
# stats_data = ... (removed)
# insights_data = ... (removed)

# KPI ROW ... (mantener igual)

# TABS
tab_bets, tab_preds, tab_results, tab_wishlist, tab_trace, tab_data, tab_audit, tab_budget, tab_arch, tab_history, tab_web, tab_logs, tab_memory = st.tabs([
    "💰 Pronósticos", 
    "🧠 Predicciones", 
    "📈 Resultados",
    "📝 Bitácora (Wishlist)",
    "🕵️ Rastreo de Agentes", 
    "📊 Inspector",
    "🔍 Auditoría de APIs",
    "💸 Presupuesto",
    "🧩 Arquitectura",
    "📁 Insights Persistentes",
    "🌐 Agente Web",
    "📜 Logs",
    "🤖 Memoria del Analista"])



with tab_bets:
    st.header("🎯 Estrategias de Apuesta")
    
    # --- BOTÓN DE EJECUCIÓN ON-DEMAND ---
    col_t1, col_t2 = st.columns([3, 1])
    with col_t1:
        st.markdown("Selecciona el perfil que mejor se adapte a tu gestión de riesgo de hoy.")
    with col_t2:
        if st.button("🔄 Refrescar Consejos", help="Ejecuta el Agente Apostador usando las últimas predicciones y cuotas."):
            with st.spinner("Optimizando estrategias de apuesta..."):
                try:
                    result = subprocess.run([sys.executable, "run_bettor.py"], capture_output=True, text=True)
                    if result.returncode == 0:
                        st.success("¡Consejos actualizados!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"Error al ejecutar: {result.stderr}")
                except Exception as e:
                    st.error(f"Error: {e}")
    st.divider()

    if not bets_data:
        st.info("No hay tips de apuestas disponibles. ¡Ejecuta el pipeline!")
    else:
        tab_bank, tab_pasada = st.tabs(["📈 Construir Banca", "🔥 La Pasada"])
        
        with tab_bank:
            st.subheader("Estrategia: Construir Banca 🟢")
            st.markdown("Picks de **Alta Probabilidad (60%+ acierto)** y cuotas moderadas para crecimiento estable.")
            
            bank_singles = [b for b in bets_data if b.get("strategy") == "bank"]
            if bank_singles:
                df_bank = pd.DataFrame([{
                    "Partido": b.get("match"),
                    "Pick": b.get("pick"),
                    "Cuota": b.get("odds"),
                    "Edge": f"{b.get('edge_pct'):.1f}%",
                    "Confianza": f"{b.get('confidence')}%",
                    "Bookie": b.get("bookmaker"),
                    "Stake": f"{b.get('stake_units')}u"
                } for b in bank_singles])
                
                st.dataframe(df_bank, use_container_width=True, hide_index=True)
                
                # Racionales en expanders para no saturar
                with st.expander("📝 Ver por qué estos picks son para Banca"):
                    for b in bank_singles:
                        st.markdown(f"**{b['match']}**: {b['rationale']}")
            else:
                st.info("No se encontraron oportunidades seguras para banca en este run.")

        with tab_pasada:
            st.subheader("Estrategia: La Pasada 🔥")
            st.markdown("Picks de **Alto Riesgo/Retorno**. Incluye combinadas y singles de cuota alta.")
            
            # Singles agresivos
            pasada_singles = [b for b in bets_data if b.get("strategy") == "parlay" and b.get("type") == "value_bet"]
            # Combinadas
            combos_list = [b for b in bets_data if "combo" in b.get("type", "")]
            
            if not pasada_singles and not combos_list:
                st.info("No hay jugadas agresivas detectadas.")
            else:
                if pasada_singles:
                    st.markdown("#### 💎 Singles de Alto Valor")
                    df_pasada = pd.DataFrame([{
                        "Partido": b.get("match"),
                        "Pick": b.get("pick"),
                        "Cuota": b.get("odds"),
                        "Edge": f"{b.get('edge_pct'):.1f}%",
                        "Stake": f"{b.get('stake_units')}u",
                        "Racional": b.get("rationale")
                    } for b in pasada_singles])
                    st.dataframe(df_pasada, use_container_width=True, hide_index=True)

                if combos_list:
                    st.markdown("#### 🧩 Jugadas Combinadas")
                    for i, c in enumerate(combos_list):
                        with st.expander(f"Combo #{i+1} | Cuota Total: {c.get('total_odds')} | Retorno Potencial: {c.get('total_odds') * c.get('stake_units'):.2f}u"):
                            st.markdown(f"**Stake Sugerido:** {c.get('stake_units')}u")
                            st.markdown("**Selecciones:**")
                            for leg in c.get('legs', []):
                                st.markdown(f"- **{leg.get('match')}** 👉 `{leg.get('pick')}` (@{leg.get('odds')})")
                            st.caption(f"Racional: {c.get('rationale')}")

with tab_preds:
    st.header("Predicciones de Partido")
    
    if not preds_data:
        st.warning("No se encontraron predicciones.")
    else:
        search = st.text_input("🔍 Buscar partido...", "")
        
        for p in preds_data:
            match_name = f"{p.get('home_team')} vs {p.get('away_team')}"
            
            # Formatear fecha
            date_str = p.get("match_date", "")
            try:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                date_fmt = dt.strftime("%d/%m %H:%M")
            except:
                date_fmt = date_str

            # Check for missing data flags
            missing = p.get("missing_data", [])
            alert_emoji = ""
            alert_help = ""
            
            if missing:
                alert_emoji = "🔴"
                translations = {
                    "youtube_insights_home": "📹 Sin análisis video (local)",
                    "youtube_insights_away": "📹 Sin análisis video (visita)",
                    "odds_not_found": "📊 Sin cuotas de mercado",
                }
                missing_str = " | ".join(translations.get(m, m) for m in missing)
                alert_help = f"Datos faltantes: {missing_str}"
            
            if search.lower() in match_name.lower():
                score_pred = p.get('score_prediction') or "?"
                # Header con fecha
                header_text = f"🗓️ {date_fmt} | ⚽ {match_name} | Pick: {p.get('prediction')} ({p.get('confidence')}%) | Score: {score_pred} {alert_emoji}"
                
                with st.expander(header_text):
                    if alert_help:
                        st.error(alert_help)
                        
                    c1, c2 = st.columns([1, 2])
                    
                    with c1:
                        st.metric("Predicción Marcador", p.get("score_prediction"))
                        st.write(f"**Confianza:** {p.get('confidence')}/100")
                        st.caption(f"Fecha exacta: {date_str}")
                        
                    with c2:
                        st.write(f"**¿Por qué?** {p.get('rationale')}")
                        st.caption("Factores Clave:")
                        if p.get("key_factors"):
                            for kf in p.get("key_factors"):
                                st.markdown(f"- {kf}")

with tab_wishlist:
    st.header("📝 Intereses y Necesidades del Analista")
    st.markdown("""
    Esta sección define los **intereses persistentes** que el Agente Web busca en cada jornada. 
    Los requerimientos pueden ser **Globales** (para todos los partidos) o **Específicos** (por equipo).
    """)

    # --- Formulario para agregar nuevo item ---
    with st.expander("➕ Agregar Nuevo Interés / Necesidad"):
        with st.form("add_wishlist_item"):
            new_need = st.text_area("Necesidad / Pregunta específica", placeholder="Ej: Confirmar bajas de último minuto...")
            fcol1, fcol2 = st.columns(2)
            new_cat = fcol1.selectbox("Categoría", ["injuries", "tactical", "stats", "market", "context", "h2h"])
            new_prio = fcol2.selectbox("Prioridad", ["alta", "media", "baja"])
            new_teams = st.text_input("Equipos afectados (opcional, separados por coma)", help="Si se deja vacío, será un interés GLOBAL.")
            
            submit_wish = st.form_submit_button("Guardar en Wishlist")
            if submit_wish and new_need:
                current_wishlist = load_data("analyst_wishlist") or []
                teams_list = [t.strip() for t in new_teams.split(",") if t.strip()]
                new_item = {
                    "need": new_need,
                    "category": new_cat,
                    "priority": new_prio,
                    "teams_affected": teams_list,
                    "added_at": datetime.now().isoformat()
                }
                current_wishlist.insert(0, new_item) # Agregar al principio
                if save_analyst_wishlist(current_wishlist):
                    st.success("Interés guardado correctamente.")
                    st.rerun()
                else:
                    st.error("Error al guardar en el archivo.")

    st.divider()
    
    wishlist_data = load_data("analyst_wishlist")
    
    if not wishlist_data:
        st.info("No hay requerimientos registrados en la bitácora actualmente.")
    else:
        # Resumen de estadísticas
        all_items = wishlist_data
        
        if all_items:
            wcol1, wcol2, wcol3 = st.columns(3)
            wcol1.metric("Total Intereses", len(all_items))
            high_priority = len([i for i in all_items if i.get("priority", "").lower() == "alta"])
            wcol2.metric("Prioridad Alta", high_priority)
            
            categories = {}
            for i in all_items:
                cat = i.get("category", "other")
                categories[cat] = categories.get(cat, 0) + 1
            most_freq_cat = max(categories, key=categories.get) if categories else "N/A"
            wcol3.metric("Categoría predominante", most_freq_cat.upper())

            st.divider()

            # Selector de filtros
            f_cat_list = ["(Todas)"] + sorted(list(set(i.get("category", "other") for i in all_items)))
            f_type_list = ["(Todos)", "Globales", "Por Equipo"]
            
            fcol1, fcol2 = st.columns(2)
            f_cat = fcol1.selectbox("Filtrar por Categoría", f_cat_list, key="wishlist_cat_filter")
            f_type = fcol2.selectbox("Tipo de Interés", f_type_list, key="wishlist_type_filter")

            # Filtrar y mostrar
            filtered_wishlist = []
            for item in all_items:
                if f_cat != "(Todas)" and item.get("category") != f_cat:
                    continue
                
                is_global = len(item.get("teams_affected", [])) == 0
                if f_type == "Globales" and not is_global:
                    continue
                if f_type == "Por Equipo" and is_global:
                    continue
                    
                filtered_wishlist.append(item)

            if not filtered_wishlist:
                st.warning("No hay intereses que coincidan con los filtros seleccionados.")
            else:
                for item in filtered_wishlist:
                    prio = item.get("priority", "media").upper()
                    prio_color = "🔴" if prio == "ALTA" else "🟡" if prio == "MEDIA" else "🟢"
                    cat = item.get("category", "other").upper()
                    affected = item.get("teams_affected", [])
                    added = item.get("added_at", "")[:10]
                    
                    with st.container():
                        c1, c2 = st.columns([0.8, 0.2])
                        c1.markdown(f"**{prio_color} [{prio}] {cat}**")
                        c2.caption(f"🗓️ {added}")
                        st.write(f"👉 {item.get('need')}")
                        if affected:
                            st.caption(f"Equipos: {', '.join(affected)}")
                        else:
                            st.caption("🌎 Interés Global")
                        st.divider()

with tab_results:
    st.header("📈 Evaluación de Rendimiento")
    st.caption("El Agente Revisor/Evaluador corre como proceso separado (standalone), no forma parte del pipeline principal.")
    if st.button("🔎 Ejecutar Agente Revisor (Standalone)", key="run_evaluator_standalone_btn"):
        with st.spinner("Ejecutando Agente Revisor / Evaluador..."):
            try:
                result = subprocess.run([sys.executable, "run_evaluator.py"], capture_output=True, text=True)
                if result.returncode == 0:
                    st.success("Evaluación completada con éxito.")
                    st.rerun()
                else:
                    st.error(f"Error al ejecutar el evaluador: {result.stderr}")
            except Exception as e:
                st.error(f"Error: {e}")
    
    # Cargar archivos de evaluación
    evaluation_summary_file = os.path.join("predictions", "evaluation_summary.json")
    predictions_history_file = os.path.join("predictions", "predictions_history.json")
    
    if os.path.exists(evaluation_summary_file):
        with open(evaluation_summary_file, "r", encoding="utf-8") as f:
            summary_data = json.load(f)
        
        # Calcular Precisión de Marcador Promedio desde history data
        avg_score_acc = 0.0
        acc_by_model = {}
        acc_by_league = {}
        
        # --- NUEVA SECCIÓN: SIMULACIÓN DE BANCA (ROI) ---
        st.divider()
        st.subheader("💰 Simulación de Banca (ROI)")
        
        # Botón para recalcular ROI manualmente
        if st.button("🔄 Recalcular ROI (Simulación 1000 CLP)", key="btn_recalc_roi"):
            with st.spinner("Calculando ROI..."):
                subprocess.run([sys.executable, "utils/roi_calculator.py"])
                st.rerun()

        roi_file = os.path.join("predictions", "roi_simulation.json")
        if os.path.exists(roi_file):
            with open(roi_file, "r", encoding="utf-8") as f:
                roi_data = json.load(f)
            
            summ = roi_data.get("summary", {})
            
            # KPI ROW para ROI
            rk1, rk2, rk3, rk4 = st.columns(4)
            rk1.metric("Inversión Total", f"{summ.get('total_invested'):,} CLP")
            rk2.metric("Retorno Total", f"{summ.get('total_returned'):,} CLP")
            
            profit = summ.get('net_profit')
            profit_color = "normal" if profit >= 0 else "inverse"
            rk3.metric("Ganancia Neta", f"{profit:,.0f} CLP", delta=None, delta_color=profit_color)
            
            roi_pct = summ.get('roi_pct')
            rk4.metric("ROI %", f"{roi_pct}%", delta=None, delta_color="normal" if roi_pct >= 0 else "inverse")
            
            updated_at = summ.get('last_updated', '')[:19].replace('T', ' ')
            st.caption(f"Simulación basada en {summ.get('total_bets')} apuestas fijas de {summ.get('fixed_stake_per_bet'):,} CLP. Última actualización: {updated_at}")
            
            # --- NUEVA SUBSECCIÓN: EVOLUCIÓN TEMPORAL ---
            st.write("---")
            st.subheader("📈 Evolución Temporal")
            
            detailed = roi_data.get("detailed_results", [])
            if detailed:
                df_roi = pd.DataFrame(detailed)
                
                # Gráfico de Ganancia Acumulada
                st.write("**Evolución del Pozo (Ganancia Acumulada)**")
                st.line_chart(df_roi.set_index("date")["cumulative_profit"], use_container_width=True)
                
                # Tablas de Agregación
                tcol1, tcol2 = st.columns(2)
                
                with tcol1:
                    st.write("**Desempeño por Semana**")
                    weeks = roi_data.get("time_series", {}).get("by_week", {})
                    if weeks:
                        df_weeks = pd.DataFrame.from_dict(weeks, orient='index').reset_index()
                        df_weeks = df_weeks.rename(columns={"index": "Semana", "bets": "Apuestas", "profit": "G/P", "roi_pct": "ROI %"})
                        st.dataframe(df_weeks[["Semana", "Apuestas", "G/P", "ROI %"]], hide_index=True)
                
                with tcol2:
                    st.write("**Desempeño por Mes**")
                    months = roi_data.get("time_series", {}).get("by_month", {})
                    if months:
                        df_months = pd.DataFrame.from_dict(months, orient='index').reset_index()
                        df_months = df_months.rename(columns={"index": "Mes", "bets": "Apuestas", "profit": "G/P", "roi_pct": "ROI %"})
                        st.dataframe(df_months[["Mes", "Apuestas", "G/P", "ROI %"]], hide_index=True)

            with st.expander("📝 Ver detalle de apuestas simuladas"):
                if detailed:
                    # Traducir/Limpiar columnas para la UI
                    df_roi_ui = df_roi.rename(columns={
                        "date": "Fecha",
                        "match": "Partido",
                        "prediction": "Pick",
                        "correct": "Acertado",
                        "odds": "Cuota",
                        "odds_source": "Origen Cuota",
                        "profit": "G/P (CLP)"
                    })
                    st.dataframe(df_roi_ui[["Fecha", "Partido", "Pick", "Acertado", "Cuota", "Origen Cuota", "G/P (CLP)"]], use_container_width=True, hide_index=True)
        else:
            st.info("No hay datos de simulación de ROI. Haz clic en 'Recalcular ROI' para generarlos.")
        
        st.divider()
        st.subheader("📊 Métricas de Acierto")
        
        if os.path.exists(predictions_history_file):
            with open(predictions_history_file, "r", encoding="utf-8") as _hf:
                _hist = json.load(_hf)
            
            _evals = [p for p in _hist if p.get("evaluation_status") == "OK"]
            if _evals:
                total_acc = 0
                for item in _evals:
                    model = item.get("analyst_model_id", "gpt5")
                    comp = item.get("competition", "unknown")
                    
                    if model not in acc_by_model: acc_by_model[model] = {"total": 0, "count": 0}
                    if comp not in acc_by_league: acc_by_league[comp] = {"total": 0, "count": 0}
                    
                    item_acc = 0
                    ph = str(item.get("score_prediction", "")).strip()
                    ah = str(item.get("actual_score", "")).strip()
                    if "-" in ph and "-" in ah:
                        try:
                            p1, p2 = map(int, ph.split("-"))
                            a1, a2 = map(int, ah.split("-"))
                            pt = "1" if p1 > p2 else "2" if p2 > p1 else "X"
                            at = "1" if a1 > a2 else "2" if a2 > a1 else "X"
                            if pt == at: item_acc += 40
                            if p1 == a1: item_acc += 30
                            if p2 == a2: item_acc += 30
                        except ValueError:
                            pass
                    
                    total_acc += item_acc
                    acc_by_model[model]["total"] += item_acc
                    acc_by_model[model]["count"] += 1
                    acc_by_league[comp]["total"] += item_acc
                    acc_by_league[comp]["count"] += 1
                    
                avg_score_acc = total_acc / len(_evals)
        
        # Métricas Globales
        col_acc, col_score, col_tot, col_corr = st.columns(4)
        col_acc.metric("Accuracy 1X2", f"{summary_data.get('overall_accuracy_pct')}%")
        col_score.metric("Precisión Marcador", f"{avg_score_acc:.1f}%")
        col_tot.metric("Total Evaluados", summary_data.get("total_evaluated"))
        col_corr.metric("Total Aciertos", summary_data.get("total_correct"))
        
        st.write("---")
        
        # Métricas por Modelo y Liga
        col_mod, col_lea = st.columns(2)
        
        with col_mod:
            st.subheader("🤖 Accuracy por Modelo")
            by_model = summary_data.get("by_model", {})
            if by_model:
                model_df = pd.DataFrame([
                    {
                        "Modelo": k, 
                        "Accuracy 1X2": f"{v['accuracy']}%", 
                        "Prec. Marcador": f"{acc_by_model.get(k, {'total':0, 'count':1})['total'] / max(1, acc_by_model.get(k, {'count':1})['count']):.1f}%",
                        "Aciertos 1X2": f"{v['correct']}/{v['total']}"
                    }
                    for k, v in by_model.items()
                ])
                st.table(model_df)
            else:
                st.info("No hay datos por modelo.")
        
        with col_lea:
            st.subheader("🏆 Accuracy por Liga")
            by_league = summary_data.get("by_league", {})
            if by_league:
                league_df = pd.DataFrame([
                    {
                        "Liga": k, 
                        "Accuracy 1X2": f"{v['accuracy']}%", 
                        "Prec. Marcador": f"{acc_by_league.get(k, {'total':0, 'count':1})['total'] / max(1, acc_by_league.get(k, {'count':1})['count']):.1f}%",
                        "Aciertos 1X2": f"{v['correct']}/{v['total']}"
                    }
                    for k, v in by_league.items()
                ])
                st.table(league_df)
            else:
                st.info("No hay datos por liga.")
        
        st.write("---")
        st.subheader("📜 Historial de Evaluación")
        
        if os.path.exists(predictions_history_file):
            with open(predictions_history_file, "r", encoding="utf-8") as f:
                history_data = json.load(f)
            
            # Filtrar los que tienen evaluación
            evaluated_history = [p for p in history_data if p.get("evaluation_status") == "OK"]
            
            if evaluated_history:
                # Deduplicación robusa: Priorizar event_id, luego nombres normalizados
                unique_matches = {}
                for p in evaluated_history:
                    home = p.get("home_team", "").strip()
                    away = p.get("away_team", "").strip()
                    comp = p.get("competition", "").strip()
                    event_id = p.get("event_id")
                    
                    if event_id:
                        key = f"EVENT_{event_id}"
                    else:
                        # Si no hay event_id, usamos el matchup. 
                        # Ignoramos fecha si es sospechosa ("None", "", "?") para limpiar duplicados.
                        m_date = p.get("match_date", "")
                        if not m_date or m_date in ["None", "?", "null"]:
                            m_date = "unknown"
                        else:
                            m_date = m_date[:10]
                        key = f"{comp}_{home}_{away}_{m_date}".lower()
                    
                    unique_matches[key] = p
                
                dedup_history = list(unique_matches.values())

                # Botones de descarga
                col_d1, col_d2 = st.columns(2)
                
                # CSV Historial
                csv_hist_path = os.path.join("predictions", "predictions_history.csv")
                if os.path.exists(csv_hist_path):
                    with open(csv_hist_path, "rb") as f:
                        col_d1.download_button(
                            label="📥 Descargar Historial (CSV)",
                            data=f,
                            file_name="historial_predicciones.csv",
                            mime="text/csv"
                        )
                
                # CSV Resumen
                csv_sum_path = os.path.join("predictions", "evaluation_summary.csv")
                if os.path.exists(csv_sum_path):
                    with open(csv_sum_path, "rb") as f:
                        col_d2.download_button(
                            label="📥 Descargar Resumen (CSV)",
                            data=f,
                            file_name="resumen_evaluacion.csv",
                            )

                # Procesar fecha para hacerla legible
                for item in dedup_history:
                    raw_date = item.get("match_date")
                    if raw_date and "T" in str(raw_date) and str(raw_date) not in ("None", "?", "null"):
                        try:
                            # Parse "2026-02-19T20:14:04Z" to "19/02 20:14"
                            dt = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
                            item["match_date"] = dt.strftime("%d/%m %H:%M")
                            continue
                        except ValueError:
                            pass
                    
                    # Intentar extraer de prediction_id o match_id
                    match_id = item.get("prediction_id", "") or item.get("match_id", "")
                    m_date = re.search(r'202\d-\d{2}-\d{2}', str(match_id))
                    if m_date:
                        try:
                            dt = datetime.strptime(m_date.group(0), "%Y-%m-%d")
                            item["match_date"] = dt.strftime("%d/%m")
                            continue
                        except ValueError:
                            pass
                    
                    # Intentar extraer de generated_at
                    gen_date = item.get("generated_at")
                    if gen_date and "T" in str(gen_date):
                        try:
                            dt = datetime.fromisoformat(str(gen_date).replace("Z", "+00:00"))
                            item["match_date"] = dt.strftime("%d/%m (Gen)")
                            continue
                        except ValueError:
                            pass
                    
                    item["match_date"] = "Sin Fecha"
                    
                for item in dedup_history:
                    # Métrica: Precisión del Marcador
                    acc_pct = 0
                    pred_score = str(item.get("score_prediction", "")).strip()
                    actual_score = str(item.get("actual_score", "")).strip()
                    
                    if "-" in pred_score and "-" in actual_score:
                        try:
                            ph, pa = map(int, pred_score.split("-"))
                            ah, aa = map(int, actual_score.split("-"))
                            
                            pred_trend = "1" if ph > pa else "2" if pa > ph else "X"
                            actual_trend = "1" if ah > aa else "2" if aa > ah else "X"
                            
                            # 40% por atinarle al ganador o empate
                            if pred_trend == actual_trend:
                                acc_pct += 40
                            # 30% por atinar exacto a los goles del local
                            if ph == ah:
                                acc_pct += 30
                            # 30% por atinar exacto a los goles del visitante
                            if pa == aa:
                                acc_pct += 30
                        except ValueError:
                            pass
                    
                    item["score_acc"] = f"{acc_pct}%"

                # Tabla de historial
                h_df = pd.DataFrame(dedup_history)
                # Seleccionar y renombrar columnas
                disp_cols = {
                    "match_date": "Fecha",
                    "competition": "Liga",
                    "home_team": "Local",
                    "away_team": "Visita",
                    "prediction": "Tendencia",
                    "score_prediction": "Obj. Marc.",
                    "actual_score": "Marcador Real",
                    "score_acc": "Prec.",
                    "correct": "Acierto",
                    "analyst_model_id": "Modelo"
                }
                
                # Asegurar que las columnas existen
                valid_disp_cols = {k: v for k, v in disp_cols.items() if k in h_df.columns}
                table_df = h_df[list(valid_disp_cols.keys())].rename(columns=valid_disp_cols)
                
                # Formatear acierto con emoji
                if "Acierto" in table_df.columns:
                    table_df["Acierto"] = table_df["Acierto"].apply(lambda x: "✅" if x else "❌")
                
                st.dataframe(table_df, use_container_width=True, hide_index=True)
            else:
                st.info("No hay partidos evaluados en el historial todavía.")
        else:
            st.warning("No se encontró el archivo de historial.")
            
    else:
        st.info("Todavía no hay un resumen de evaluación. ¡Ejecuta el evaluador!")
        if st.button("🚀 Ejecutar Agente Evaluador Ahora", key="run_evaluator_empty_state_btn"):
            with st.spinner("Evaluando resultados contra ESPN API..."):
                try:
                    # Ejecutar el script
                    result = subprocess.run([sys.executable, "run_evaluator.py"], capture_output=True, text=True)
                    if result.returncode == 0:
                        st.success("Evaluación completada con éxito.")
                        st.rerun()
                    else:
                        st.error(f"Error al ejecutar el evaluador: {result.stderr}")
                except Exception as e:
                    st.error(f"Error: {e}")

with tab_trace:
    st.header("🕵️ Rastreo de Agentes: Flujo de Decisión")
    st.markdown("Visualiza qué datos recibió cada agente paso a paso para un partido específico.")

    # --- NUEVA SECCIÓN: CONTEXTO GLOBAL WEB (PANORÁMICA) ---
    st.subheader("🌐 Panorámica Global (Agente Web)")
    web_output_data = load_data("web") # Asumiendo que 'web' está en FILES, si no, usar WEB_AGENT_OUTPUT_FILE
    if not web_output_data:
        # Intentar cargar directamente si no está en FILES
        if os.path.exists("web_agent_output.json"):
            with open("web_agent_output.json", "r", encoding="utf-8") as f:
                web_output_data = json.load(f)
    
    if web_output_data:
        updated_at = web_output_data.get("generated_at", "N/A")
        st.caption(f"Última actualización global: {updated_at}")
        
        comps = web_output_data.get("data", {}).get("competitions") or []
        if comps:
            # Selector de liga para la panorámica
            pan_comp_list = [c.get("competition") for c in comps if c.get("competition")]
            selected_pan_comp = st.selectbox("Ver noticias globales de:", pan_comp_list, key="pan_comp_selector")
            
            target_comp = next((c for c in comps if c.get("competition") == selected_pan_comp), None)
            if target_comp:
                with st.expander(f"Ver todos los hallazgos recientes para {selected_pan_comp}", expanded=True):
                    teams_web = target_comp.get("teams") or []
                    if not teams_web:
                        st.info("No hay detalles por equipo en este run.")
                    else:
                        for tw in teams_web:
                            t_name = tw.get("team", "Equipo Desconocido")
                            t_res = tw.get("last_result") or ""
                            t_ctx = tw.get("raw_context") or ""
                            
                            # Resaltar si hay hitos importantes (evitar error de NoneType)
                            text_to_search = (str(t_res) + str(t_ctx)).lower()
                            is_key_context = any(k in text_to_search for k in ["elimino", "clasifico", "campeon", "descendio", "crisis", "quiebra"])
                            
                            st.markdown(f"**{t_name}** {'⭐' if is_key_context else ''}")
                            if t_res: st.markdown(f"> `{t_res}`")
                            if t_ctx: st.write(t_ctx)
                            
                            # Mostrar señales si existen
                            sigs = tw.get("context_signals") or []
                            if sigs:
                                cols = st.columns(len(sigs) if len(sigs) < 4 else 4)
                                for idx, s in enumerate(sigs[:4]):
                                    with cols[idx]:
                                        st.caption(f"🎯 {s.get('signal')[:40]}...")
                            st.divider()
    else:
        st.info("No hay datos de contexto global disponibles todavía.")

    st.divider()
    st.subheader("🎯 Rastreo de Partido Específico")

    # Cargar match_contexts del normalizador (fuente de verdad)
    MC_FILE = "pipeline_match_contexts.json"
    match_contexts_data = []
    if os.path.exists(MC_FILE):
        with open(MC_FILE, "r", encoding="utf-8") as f:
            match_contexts_data = json.load(f)
    
    # 1. Selector de Partido — usa match_contexts si existen, sino fixtures
    if match_contexts_data:
        def _trace_label(mc_item):
            home_label = mc_item.get("home", {}).get("canonical_name") or "home"
            away_label = mc_item.get("away", {}).get("canonical_name") or "away"
            # Si existen nombres originales desde stats, agregarlos para evitar confusiones
            home_stats_team = ((mc_item.get("home", {}) or {}).get("stats") or {}).get("team")
            away_stats_team = ((mc_item.get("away", {}) or {}).get("stats") or {}).get("team")
            if home_stats_team and away_stats_team:
                return f"{home_label} vs {away_label}  [{home_stats_team} vs {away_stats_team}]"
            return f"{home_label} vs {away_label}"

        match_options = [mc.get("match_id") for mc in match_contexts_data if mc.get("match_id")]
        match_contexts_by_id = {mc.get("match_id"): mc for mc in match_contexts_data if mc.get("match_id")}
        match_labels_by_id = {mc.get("match_id"): _trace_label(mc) for mc in match_contexts_data if mc.get("match_id")}
    elif fixtures_data:
        match_options = [f"{f.get('home_team')} vs {f.get('away_team')}" for f in fixtures_data]
    else:
        match_options = []

    # Asegurar que no hay duplicados en los labels visibles del selector
    # Si hay labels idénticos para distintos IDs, format_func debe diferenciarlos.
    if match_contexts_data:
        seen_labels = {}
        for mid in match_options:
            label = match_labels_by_id.get(mid, mid)
            if label in seen_labels:
                # Si el label está duplicado, le añadimos un sufijo con el ID del partido para diferenciar
                # Esto es un fallback de emergencia si la normalización falla.
                match_labels_by_id[mid] = f"{label} ({mid})"
            seen_labels[label] = mid

    if not match_options:
        st.info("No hay partidos para rastrear. Ejecuta el pipeline primero.")
    else:
        if match_contexts_data:
            selected_match_id = st.selectbox(
                "Selecciona un Partido",
                match_options,
                format_func=lambda mid: match_labels_by_id.get(mid, mid)
            )
            selected_match = match_labels_by_id.get(selected_match_id, selected_match_id)
        else:
            selected_match = st.selectbox("Selecciona un Partido", match_options)
            selected_match_id = None
        
        if selected_match:
            if match_contexts_data and selected_match_id:
                mc = match_contexts_by_id.get(selected_match_id)
                home_team = (mc.get("home", {}) or {}).get("canonical_name", "") if mc else ""
                away_team = (mc.get("away", {}) or {}).get("canonical_name", "") if mc else ""
            else:
                home_team, away_team = selected_match.split(" vs ", 1) if " vs " in selected_match else (selected_match, "")
            
            # Buscar MatchContext del normalizador
            if not (match_contexts_data and selected_match_id):
                mc = next((m for m in match_contexts_data
                           if m["home"]["canonical_name"] == home_team and m["away"]["canonical_name"] == away_team), None)
            
            pred_match_name = f"{home_team} vs {away_team}"
            prediction = None
            bet = None
            if selected_match_id:
                prediction = get_prediction_info_by_match_id(selected_match_id, preds_data)
                bet = get_bet_info_by_match_id(selected_match_id, bets_data)
            if prediction is None:
                prediction = get_prediction_info(pred_match_name, preds_data)
            if bet is None:
                bet = get_bet_info(pred_match_name, bets_data)
            
            # --- Alertas de datos faltantes ---
            missing = mc.get("missing_data", []) if mc else []
            if missing:
                translations = {
                    "odds_not_found": "📊 Sin cuotas de mercado",
                    "youtube_insights_home": "📹 Sin análisis video (local)",
                    "youtube_insights_away": "📹 Sin análisis video (visita)",
                    "stats_home_not_found": "📈 Sin stats (local)",
                    "stats_away_not_found": "📈 Sin stats (visita)",
                }
                missing_str = " | ".join(translations.get(m, m) for m in missing)
                st.error(f"🔴 **Datos que le faltaron al Analista:** {missing_str}")

            if mc:
                st.caption(f"🔑 Match ID: `{mc.get('match_id')}`")
            
            # --- FLUJO SECUENCIAL DEL PIPELINE ---
            
            # PASO 1: INSUMOS (Stats & Odds)
            st.subheader("1. Insumos Base (Stats & Odds)")
            
            # Odds compactas
            odds_info = mc.get("odds") if mc else None
            if odds_info:
                st.markdown(f"""
                <div style="background-color: #1a1c24; padding: 10px; border-radius: 5px; margin-bottom: 10px; border-left: 5px solid #ff4b4b;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span><strong>📊 Cuotas: {home_team} vs {away_team}</strong> ({odds_info.get('bookmaker', '?')})</span>
                    </div>
                    <div style="display: flex; justify-content: space-around; margin-top: 5px; font-size: 0.9em;">
                        <div>🏠 1: <strong>{odds_info.get('home_odds')}</strong></div>
                        <div>🤝 X: <strong>{odds_info.get('draw_odds')}</strong></div>
                        <div>✈️ 2: <strong>{odds_info.get('away_odds')}</strong></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.warning("⚠️ Sin cuotas de mercado.")

            # Stats compactas
            home_stats = mc.get("home", {}).get("stats") if mc else get_stats_info(home_team, stats_data)
            away_stats = mc.get("away", {}).get("stats") if mc else get_stats_info(away_team, stats_data)
            
            cs1, cs2 = st.columns(2)
            with cs1:
                if home_stats:
                    s = home_stats.get("stats", {})
                    st.caption(f"🏠 {home_team}: Pos {s.get('position')} | {s.get('won')}G-{s.get('draw')}E-{s.get('lost')}P | Forma: {s.get('form') or '?'}")
                else: st.caption(f"🏠 {home_team}: Sin estadísticas")
            with cs2:
                if away_stats:
                    s = away_stats.get("stats", {})
                    st.caption(f"✈️ {away_team}: Pos {s.get('position')} | {s.get('won')}G-{s.get('draw')}E-{s.get('lost')}P | Forma: {s.get('form') or '?'}")
                else: st.caption(f"✈️ {away_team}: Sin estadísticas")

            # PASO 2: DESCUBRIMIENTO (Agente Periodista)
            st.markdown("⬇️")
            st.subheader("2. Descubrimiento (Agente Periodista)")
            
            home_insights = mc.get("home", {}).get("insights") if mc else get_insights_info(home_team, insights_data)
            away_insights = mc.get("away", {}).get("insights") if mc else get_insights_info(away_team, insights_data)
            
            cp1, cp2 = st.columns(2)
            with cp1: 
                v_home = (home_insights.get("video") or {}).get("videos") if home_insights else None
                _render_trace_journalist_videos(home_team, journalist_data, videos_from_insights=v_home)
            with cp2: 
                v_away = (away_insights.get("video") or {}).get("videos") if away_insights else None
                _render_trace_journalist_videos(away_team, journalist_data, videos_from_insights=v_away)

            # PASO 3: INTELIGENCIA (Insights & Web)
            st.markdown("⬇️")
            st.subheader("3. Inteligencia (Insights & Web)")
            
            ci1, ci2 = st.columns(2)
            with ci1: _render_trace_team_insights(home_team, home_insights)
            with ci2: _render_trace_team_insights(away_team, away_insights)
            
            # Verificación Web On-demand (si existe)
            match_web_checks = []
            if selected_match_id and isinstance(analyst_web_checks_data, list):
                match_web_checks = [x for x in analyst_web_checks_data if isinstance(x, dict) and x.get("match_id") == selected_match_id]
            
            if match_web_checks:
                with st.expander(f"🌐 Verificaciones Web On-demand ({len(match_web_checks)})", expanded=False):
                    for idx, item in enumerate(match_web_checks, start=1):
                        req = item.get("request") or {}
                        res = item.get("result") or {}
                        ok_check = bool(res.get("ok"))
                        
                        st.markdown(f"**Check {idx}: {item.get('target_team', '?')}**")
                        st.caption(f"Motivo: {req.get('trigger_reason', 'N/A')}")
                        
                        if ok_check:
                            data_chk = res.get("data") or {}
                            checks = data_chk.get("checks") or []
                            for chk in checks:
                                if not isinstance(chk, dict): continue
                                st.success(chk.get("answer_summary", "Sin resumen"))
                                # Mostrar señales si las hay
                                for s in (chk.get("context_signals") or []):
                                    st.markdown(f"- `{s.get('type')}`: {s.get('signal')} (conf {s.get('confidence', 0)})")
                        else:
                            st.error(f"Error: {res.get('error', 'Fallo desconocido')}")
                        st.divider()

            # PASO 4: VALIDACIÓN (Gate Agent)
            st.markdown("⬇️")
            st.subheader("4. Auditoría de Calidad (Gate Agent)")
            _render_trace_gate_agent(mc)

            # PASO 5: PREDICCIÓN (Agente Analista)
            st.markdown("⬇️")
            st.subheader("5. Predicción (Agente Analista)")
            if prediction:
                st.markdown(f"""
                <div style="padding:15px; border:1px solid #444; border-radius:10px; background-color:#1e212b;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <h4 style="margin:0;">🧠 {prediction.get('prediction')}</h4>
                        <span style="background-color: #ff4b4b; padding: 2px 8px; border-radius: 12px; font-size: 0.8em;">Conf: {prediction.get('confidence')}%</span>
                    </div>
                    <p style="margin-top:10px;"><strong>Rationale:</strong> {prediction.get('rationale')}</p>
                    <p style="font-style: italic; color: #aaa;">Score estimado: {prediction.get('score_prediction')}</p>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.warning("El Analista no generó predicción para este partido.")
                
            # PASO 6: GESTIÓN (Agente Apostador)
            st.markdown("⬇️")
            st.subheader("6. Decisión (Agente Apostador)")
            if bet:
                st.markdown(f"""
                <div style="padding:15px; border:1px solid #2ecc71; border-radius:10px; background-color:#145a32;">
                    <h3 style="margin:0; color: #2ecc71;">💰 APUESTA SUGERIDA</h3>
                    <p style="font-size: 1.2em; margin: 10px 0;"><strong>{bet.get('pick')}</strong> @ {bet.get('odds')}</p>
                    <div style="display: flex; gap: 20px; font-size: 0.9em; opacity: 0.9;">
                        <span>Stake: <strong>{bet.get('stake_units')}u</strong></span>
                        <span>Edge: <strong>{bet.get('edge_pct')}%</strong></span>
                    </div>
                    <hr style="opacity: 0.3; margin: 10px 0;">
                    <p style="font-size: 0.9em; font-style: italic;">{bet.get('rationale')}</p>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.info("ℹ️ No se encontró valor suficiente para apostar.")


with tab_budget:
    st.header("💸 Presupuesto y Uso de Tokens")
    st.info("Seguimiento incremental del uso de LLM por modelo.")
    
    col_reset, _ = st.columns([1, 4])
    if col_reset.button("Reiniciar Tokens"):
        reset_tokens()
        st.success("Contador de tokens reiniciado.")
        st.rerun()
        
    usage = load_token_usage()
    if not usage:
        st.warning("No hay datos de uso de tokens registrados.")
    else:
        # Convertir a DataFrame para visualización
        data_rows = []
        total_prompt = 0
        total_completion = 0
        total_overall = 0
        
        for model, stats in usage.items():
            data_rows.append({
                "Modelo": model,
                "Llamadas": stats.get("calls", 0),
                "Prompt Tokens": stats.get("prompt_tokens", 0),
                "Completion Tokens": stats.get("completion_tokens", 0),
                "Total Tokens": stats.get("total_tokens", 0)
            })
            total_prompt += stats.get("prompt_tokens", 0)
            total_completion += stats.get("completion_tokens", 0)
            total_overall += stats.get("total_tokens", 0)
            
        df_usage = pd.DataFrame(data_rows)
        st.table(df_usage)
        
        # Totales Globales
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Prompt", f"{total_prompt:,}")
        c2.metric("Total Completion", f"{total_completion:,}")
        c3.metric("Total General", f"{total_overall:,}")


with tab_audit:
    st.header("🔍 Auditoría de APIs y Agentes")
    st.markdown("Vista estructurada de los datos crudos de cada agente del pipeline. Útil para detectar datos faltantes, inconsistencias y cobertura.")

    # ─── Cargar todos los datos ──────────────────────────────────────────────
    audit_odds       = load_data("odds")               or []
    audit_stats      = load_data("stats")              or []
    audit_insights   = load_data("insights")           or []
    audit_journalist = load_data("journalist")         or {}
    audit_awc        = load_data("analyst_web_checks") or []
    audit_preds      = load_data("predicciones")       or []
    audit_bets       = load_data("apuestas")           or []
    MC_FILE_AUDIT    = "pipeline_match_contexts.json"
    audit_mc         = json.load(open(MC_FILE_AUDIT, encoding="utf-8")) if os.path.exists(MC_FILE_AUDIT) else []
    WEB_AGENT_FILE   = "web_agent_output.json"
    audit_web        = json.load(open(WEB_AGENT_FILE, encoding="utf-8")) if os.path.exists(WEB_AGENT_FILE) else {}

    # ─── Métricas globales ───────────────────────────────────────────────────
    st.subheader("📊 Cobertura global del Pipeline")
    jcomp = audit_journalist.get("competitions", []) if isinstance(audit_journalist, dict) else []
    total_yt_videos = sum(len(c.get("videos", [])) for c in jcomp)
    mc_ok   = len([m for m in audit_mc if not m.get("missing_data")])
    mc_warn = len([m for m in audit_mc if m.get("missing_data")])
    awc_count = len(audit_awc) if isinstance(audit_awc, list) else 0

    ka1, ka2, ka3, ka4, ka5, ka6, ka7, ka8 = st.columns(8)
    ka1.metric("🏟️ Partidos",     len(audit_odds))
    ka2.metric("📈 Stats",        len(audit_stats))
    ka3.metric("📹 Videos YT",    total_yt_videos)
    ka4.metric("🧠 Insights",     len(audit_insights))
    ka5.metric("🔎 Web Checks",   awc_count)
    ka6.metric("🏁 Predicciones", len(audit_preds))
    ka7.metric("✅ Completos",    mc_ok)
    ka8.metric("⚠️ Con gaps",     mc_warn, delta_color="inverse")

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════════════════
    # AGENTE 1: ODDS API
    # ═══════════════════════════════════════════════════════════════════════
    with st.expander("🎯  Agente #1 — The Odds API  (Partidos + Cuotas)", expanded=True):
        st.caption("Fuente principal de partidos y cuotas 1X2.")
        if not audit_odds:
            st.warning("Sin datos. Ejecuta el pipeline.")
        else:
            rows = []
            for f in audit_odds:
                bms = f.get("bookmakers", [])
                bm0 = bms[0] if bms else {}
                rows.append({
                    "Competencia": f.get("competition", "—"),
                    "Fecha":       str(f.get("commence_time") or "—")[:16],
                    "Local":       f.get("home_team") or "❌ None",
                    "Visitante":   f.get("away_team") or "❌ None",
                    "Casa":        str(bm0.get("home_odds") or "—"),
                    "Empate":      str(bm0.get("draw_odds") or "—"),
                    "Visita":      str(bm0.get("away_odds") or "—"),
                    "# Casas":     str(f.get("bookmakers_count") or len(bms)),
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            none_rows = [r for r in rows if "❌" in r.get("Local","") or "❌" in r.get("Visitante","")]
            if none_rows:
                st.error(f"⚠️ {len(none_rows)} evento(s) con home_team o away_team = None.")
            else:
                st.success("✅ Todos los partidos tienen equipos válidos.")
            UNMATCHED_FILE = "pipeline_odds_unmatched.json"
            if os.path.exists(UNMATCHED_FILE):
                with open(UNMATCHED_FILE, encoding="utf-8") as _f:
                    unmatched_data = json.load(_f)
                if unmatched_data:
                    st.warning(f"⚠️ {len(unmatched_data)} evento(s) sin fixture matching:")
                    for u in unmatched_data:
                        st.code(f"{u['home_team']}  vs  {u['away_team']}  [{u.get('competition','')}]")
                else:
                    st.success("✅ Todos los eventos matchearon un partido.")

    # ═══════════════════════════════════════════════════════════════════════
    # AGENTE 2: ESPN STATS
    # ═══════════════════════════════════════════════════════════════════════
    with st.expander("📊  Agente #2 — ESPN  (Estadísticas de Temporada)"):
        st.caption("Estadísticas de tabla: posición, puntos, forma, goles.")
        if not audit_stats:
            st.warning("Sin datos.")
        else:
            rows = []
            for s in audit_stats:
                st_data = s.get("stats", {})
                rows.append({
                    "Equipo":      s.get("team", "—"),
                    "Competencia": s.get("competition", "—"),
                    "Pos":         st_data.get("position", "—"),
                    "Pts":         st_data.get("points", "—"),
                    "J":           st_data.get("played", "—"),
                    "G-E-P":       f"{st_data.get('won','?')}-{st_data.get('draw','?')}-{st_data.get('lost','?')}",
                    "GF":          st_data.get("goals_for", "—"),
                    "GC":          st_data.get("goals_against", "—"),
                    "Forma":       st_data.get("form", "—"),
                })
            st.dataframe(pd.DataFrame(rows).astype(str), use_container_width=True, hide_index=True)
            ucl_stats = [s for s in audit_stats if s.get("competition") == "UCL"]
            if ucl_stats:
                st.markdown("---")
                st.subheader("🇪🇺 Detalle Avanzado UCL (xG)")
                processed_teams = set()
                teams_no_adv = []
                for s in ucl_stats:
                    cn = s.get("canonical_name") or _local_slug(s.get("team", ""))
                    if cn in processed_teams: continue
                    processed_teams.add(cn)
                    adv = s.get("advanced_stats") or {}
                    lineup = s.get("lineup") or {}
                    if adv or lineup:
                        with st.expander(f"⚙️ {s.get('team')} — xG / Alineación"):
                            c1, c2 = st.columns(2)
                            c1.write(f"xG: `{adv.get('xg','N/D')}` | xAG: `{adv.get('xag','N/D')}`")
                            c2.write(f"Formación: `{lineup.get('formation','N/D')}`")
                    else:
                        teams_no_adv.append(s.get("team",""))
                if teams_no_adv:
                    st.info(f"ℹ️ Sin datos avanzados para: {', '.join(set(teams_no_adv))}")
            if audit_odds:
                try:
                    from agents.normalizer_agent import _fuzzy_match as _fm
                except ImportError:
                    _fm = lambda a, b: a.lower() == b.lower()
                stat_teams = [s.get("team","") for s in audit_stats if s.get("team")]
                missing_teams = sorted(set(
                    t for ev in audit_odds
                    for t in [ev.get("home_team"), ev.get("away_team")]
                    if t and not any(_fm(t, st) for st in stat_teams)
                ))
                if missing_teams:
                    st.warning(f"⚠️ {len(missing_teams)} equipo(s) sin stats: {' | '.join(missing_teams)}")
                else:
                    st.success("✅ Todos los equipos tienen stats de ESPN.")

    # ═══════════════════════════════════════════════════════════════════════
    # AGENTE 3: PERIODISTA
    # ═══════════════════════════════════════════════════════════════════════
    with st.expander("🎙️  Agente #3 — Periodista  (Descubrimiento YouTube)"):
        st.caption("Videos de YouTube descubiertos y seleccionados para cada competencia.")
        if not audit_journalist or not isinstance(audit_journalist, dict):
            st.warning("Sin datos del Agente Periodista.")
        else:
            meta_j = audit_journalist.get("meta", {})
            col_j1, col_j2, col_j3 = st.columns(3)
            col_j1.metric("Videos Totales", total_yt_videos)
            col_j2.metric("Candidatos Escaneados", meta_j.get("total_candidates_scanned", "—"))
            col_j3.metric("Ventana (días)", audit_journalist.get("lookback_days", "—"))
            st.markdown("")
            for c_group in audit_journalist.get("competitions", []):
                comp_name = c_group.get("competition", "—")
                vids = c_group.get("videos", [])
                errors = c_group.get("errors", [])
                st.markdown(f"**🏆 {comp_name}** — {len(vids)} videos seleccionados")
                if errors:
                    for err in errors: st.error(f"❌ {err}")
                if vids:
                    rows = [{
                        "Video":      f"[{v.get('title','—')}]({v.get('url','')})",
                        "Canal":      v.get("channel", {}).get("title", "—"),
                        "Publicado":  v.get("published_at", "")[:10],
                        "Vistas":     f"{v.get('metrics', {}).get('views', 0):,}",
                        "Rep.":       f"{v.get('reputation', {}).get('score', 0):.2f}",
                        "Rel.":       f"{v.get('relevance', {}).get('score', 0):.2f}",
                    } for v in vids]
                    st.write(pd.DataFrame(rows).to_html(escape=False, index=False), unsafe_allow_html=True)
                else:
                    st.info("Sin videos seleccionados para esta competencia.")
                st.markdown("---")

    # ═══════════════════════════════════════════════════════════════════════
    # AGENTE 4: INSIGHTS (YouTube + LLM)
    # ═══════════════════════════════════════════════════════════════════════
    with st.expander("📹  Agente #4 — Insights  (YouTube + LLM)"):
        st.caption("Análisis basado en transcripciones de videos de YouTube por equipo.")
        if not audit_insights:
            st.warning("Sin datos. El insights_agent requiere que el journalist_agent descubra videos primero.")
        else:
            rows = []
            for ins in audit_insights:
                forecast = ins.get("forecast") or {}
                entities = ins.get("entities") or {}
                bullets_raw = ins.get("insight") or ins.get("insights") or []
                bullets = bullets_raw if isinstance(bullets_raw, list) else [bullets_raw]
                rows.append({
                    "Equipo":      str(ins.get("team") or "—"),
                    "Competencia": str(ins.get("competition") or "—"),
                    "Pronostico":  str(forecast.get("outcome") or "—"),
                    "Confianza":   str(forecast.get("confidence") or "—"),
                    "Insights":    str(len(bullets)),
                    "Lesionados":  str(", ".join(entities.get("injuries", [])) or "—"),
                    "Suspendidos": str(", ".join(entities.get("suspensions", [])) or "—"),
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            teams_no = [r["Equipo"] for r in rows if r["Insights"] in ("0","1")]
            if teams_no:
                st.warning(f"⚠️ Equipos con pocos insights: {' | '.join(teams_no)}")
            else:
                st.success(f"✅ {len(rows)} equipos con insights generados.")

    # ═══════════════════════════════════════════════════════════════════════
    # AGENTE WEB
    # ═══════════════════════════════════════════════════════════════════════
    with st.expander("🌐  Agente Web  (Contexto Web Panorámico)"):
        st.caption("Búsqueda web panorámica de noticias, lesiones y contexto por equipo.")
        if not audit_web or not isinstance(audit_web, dict):
            st.warning("Sin datos del Agente Web (web_agent_output.json no encontrado).")
        else:
            web_ok    = audit_web.get("ok", False)
            web_model = audit_web.get("model", "—")
            web_date  = str(audit_web.get("completed_at", "—"))[:19]
            wc1, wc2, wc3 = st.columns(3)
            wc1.metric("Estado", "✅ OK" if web_ok else "❌ Error")
            wc2.metric("Modelo", web_model)
            wc3.metric("Generado", web_date)
            if not web_ok:
                st.error(f"Error: {audit_web.get('error', 'Desconocido')}")
            web_data = audit_web.get("data", {})
            for comp_block in (web_data.get("competitions") or []):
                comp_id = comp_block.get("competition", "—")
                teams   = comp_block.get("teams", [])
                with st.expander(f"**{comp_id}** — {len(teams)} equipos cubiertos"):
                    st.caption(comp_block.get("summary", ""))
                    for td in teams:
                        conf = td.get("confidence", 0)
                        icon = "🟢" if conf >= 0.7 else ("🟡" if conf >= 0.4 else "🔴")
                        st.markdown(f"**{icon} {td.get('team','—')}** (conf. {conf:.2f})")
                        for b in (td.get("web_insights") or [])[:3]:
                            st.markdown(f"  - {b}")

    # ═══════════════════════════════════════════════════════════════════════
    # ANALYST WEB CHECK
    # ═══════════════════════════════════════════════════════════════════════
    with st.expander("🔎  Analyst Web Check  (Verificaciones On-Demand del Analista)"):
        st.caption("Verificaciones web puntuales solicitadas por el Agente Analista.")
        awc_list = audit_awc if isinstance(audit_awc, list) else (
            [audit_awc] if isinstance(audit_awc, dict) and audit_awc else []
        )
        if not awc_list:
            st.warning("Sin datos de verificaciones web del analista.")
        else:
            awc_summary = []
            for awc_item in awc_list:
                awc_data = awc_item.get("data", awc_item)
                match_id  = awc_data.get("match_id") or awc_item.get("match_id", "—")
                trigger   = awc_data.get("trigger_reason", "—")
                checks_out= awc_data.get("checks", [])
                awc_summary.append({
                    "Partido (match_id)": str(match_id),
                    "Trigger": str(trigger)[:80],
                    "Checks":  len(checks_out),
                    "Estado":  "✅" if awc_item.get("ok", True) else "❌"
                })
            st.dataframe(pd.DataFrame(awc_summary), use_container_width=True, hide_index=True)
            for awc_item in awc_list[:10]:
                awc_data   = awc_item.get("data", awc_item)
                match_id   = awc_data.get("match_id") or "—"
                checks_out = awc_data.get("checks", [])
                if checks_out:
                    with st.expander(f"🔍 Detalle: {match_id}"):
                        for chk in checks_out:
                            icon = {"confirmed":"✅","unconfirmed":"❓","not_found":"❌","partially_confirmed":"🟡"}.get(chk.get("status",""),"❓")
                            st.markdown(f"**{icon} {chk.get('question','—')}**")
                            st.caption(chk.get("answer_summary","—"))
                            for sig in (chk.get("context_signals") or []):
                                st.markdown(f"  - `{sig.get('type','?')}` {sig.get('signal','')} _(conf. {sig.get('confidence',0):.2f})_")

    # ═══════════════════════════════════════════════════════════════════════
    # GATE AGENT
    # ═══════════════════════════════════════════════════════════════════════
    with st.expander("🚦  Gate Agent  (Auditoría de Calidad de Datos)"):
        st.caption("El Gate Agent evalúa la completitud de datos antes de pasar al analista.")
        if not audit_mc:
            st.warning("Sin datos del Gate Agent.")
        else:
            gate_rows = []
            for mc in audit_mc:
                score  = mc.get("quality_score") or mc.get("gate_score")
                passed = mc.get("gate_passed")
                missing= mc.get("missing_data", [])
                gate_rows.append({
                    "Partido":      f"{mc.get('home_team','?')} vs {mc.get('away_team','?')}",
                    "Comp.":        mc.get("competition","—"),
                    "Score Calidad":f"{score:.2f}" if isinstance(score, float) else ("—" if score is None else score),
                    "Gate":         "✅ PASS" if passed else ("❌ FAIL" if passed is False else "—"),
                    "Gaps":         " | ".join(missing) if missing else "✅ Completo",
                })
            df_gate = pd.DataFrame(gate_rows)

            def _cg(val):
                if "PASS" in str(val) or "Completo" in str(val): return "background-color:#145a32;color:white;"
                elif "FAIL" in str(val) or (str(val) not in ("—","") and "|" in str(val)): return "background-color:#6e2d12;color:white;"
                return ""

            st.dataframe(df_gate.style.map(_cg, subset=["Gate","Gaps"]), use_container_width=True, hide_index=True)
            n_pass = len([r for r in gate_rows if "PASS" in r["Gate"]])
            n_fail = len([r for r in gate_rows if "FAIL" in r["Gate"]])
            if n_pass or n_fail: st.caption(f"✅ PASS: {n_pass} | ❌ FAIL: {n_fail}")

    # ═══════════════════════════════════════════════════════════════════════
    # NORMALIZADOR
    # ═══════════════════════════════════════════════════════════════════════
    with st.expander("🔗  Agente Normalizador  (MatchContext — Cruce Consolidado)"):
        st.caption("Tabla de cruce final del Normalizador para cada partido.")
        if not audit_mc:
            st.info("Sin datos. Ejecuta el pipeline para generar pipeline_match_contexts.json.")
        else:
            rows = []
            for mc in audit_mc:
                miss = mc.get("missing_data", [])
                odds = mc.get("odds") or {}
                rows.append({
                    "match_id":  str(mc.get("match_id") or "—"),
                    "Local":     str(mc.get("home_team") or "—"),
                    "Visitante": str(mc.get("away_team") or "—"),
                    "Fecha":     str(mc.get("match_date") or "—")[:10],
                    "Comp.":     str(mc.get("competition") or "—"),
                    "Casa":      str(odds.get("home_odds") or "❌"),
                    "Emp.":      str(odds.get("draw_odds") or "❌"),
                    "Vis.":      str(odds.get("away_odds") or "❌"),
                    "Gaps":      " | ".join(miss) if miss else "✅ Completo",
                })
            def color_gaps(val):
                if "✅" in str(val): return "background-color:#145a32;color:white;"
                elif val and val != "—": return "background-color:#6e2d12;color:white;"
                return ""
            st.dataframe(pd.DataFrame(rows).style.map(color_gaps, subset=["Gaps"]), use_container_width=True, hide_index=True)

    # ═══════════════════════════════════════════════════════════════════════
    # ANALYST AGENT
    # ═══════════════════════════════════════════════════════════════════════
    with st.expander("🧠  Agente Analista  (Predicciones generadas)"):
        st.caption("Predicciones generadas por el Agente Analista para cada partido.")
        if not audit_preds:
            st.warning("Sin predicciones disponibles.")
        else:
            rows_pred = [{
                "Partido":       f"{p.get('home_team','?')} vs {p.get('away_team','?')}",
                "Competencia":   p.get("competition","—"),
                "Prediccion":    p.get("prediction","—"),
                "Score Pred.":   p.get("score_prediction","—"),
                "Confianza":     f"{p.get('confidence',0)}%",
                "Modelo":        p.get("analyst_model_id","—"),
                "Gaps":          " | ".join(p.get("missing_data",[])) or "✅ OK",
            } for p in audit_preds]

            def _cp(val):
                if "✅" in str(val): return "background-color:#145a32;color:white;"
                elif "|" in str(val) and val not in ("—",""): return "background-color:#5a4a12;color:white;"
                return ""

            st.dataframe(pd.DataFrame(rows_pred).style.map(_cp, subset=["Gaps"]), use_container_width=True, hide_index=True)

    # ═══════════════════════════════════════════════════════════════════════
    # BETTOR AGENT
    # ═══════════════════════════════════════════════════════════════════════
    with st.expander("💰  Agente Apostador  (Tips de Apuesta generados)"):
        st.caption("Tips de apuesta y su razonamiento generados por el Bettor Agent.")
        if not audit_bets:
            st.warning("Sin tips de apuesta disponibles.")
        else:
            value_bets = [b for b in audit_bets if b.get("type") == "value_bet"]
            combos     = [b for b in audit_bets if "combo" in b.get("type","")]
            bc1, bc2 = st.columns(2)
            bc1.metric("💎 Value Bets", len(value_bets))
            bc2.metric("🔗 Combinadas", len(combos))
            if value_bets:
                rows_bets = [{
                    "Partido":    b.get("match","—"),
                    "Pick":       b.get("pick","—"),
                    "Cuota":      b.get("odds","—"),
                    "Edge (%)":   f"{b.get('edge_pct',0):.1f}%",
                    "Stake":      f"{b.get('stake_units',0)}u",
                    "Confianza":  b.get("confidence","—"),
                    "Razon":      (b.get("rationale","") or "")[:100],
                } for b in value_bets]
                st.dataframe(pd.DataFrame(rows_bets), use_container_width=True, hide_index=True)


with tab_data:
    st.subheader("Inspector de JSON Crudo")
    file_option = st.selectbox("Seleccionar Archivo", list(FILES.keys()))
    data = load_data(file_option)
    st.json(data, expanded=False)


with tab_arch:
    st.header("🧩 Arquitectura del Sistema")
    st.caption("Arquitectura completa del pipeline principal + ciclo de retroalimentación y mejora continua.")

    # Diagrama embebido directamente para garantizar compatibilidad con Mermaid v10
    ARCH_DIAGRAM = """
graph TD
    START([INICIO]) --> AG1

    subgraph PIPELINE ["Pipeline Principal"]
        AG1["1. Odds Fetcher"]
        AG2["2. Stats Agent"]
        AG3["3. Journalist Agent"]
        AG35["3.5 Web Agent"]
        AG4["4. Insights Agent"]
        AG5["5. Normalizer Agent"]
        AG55["5.5 Gate Agent"]
        AG6["6. Analyst Agent"]
        AG7["7. Bettor Agent"]
        AWC["Analyst Web Check"]
    end

    subgraph HISTPERSIST ["Persistencia"]
        THIST[("team_history.json")]
        WAOUT[("web_agent_output.json")]
    end

    subgraph MEMORIA ["Memoria"]
        MEM[("analyst_memory.json")]
    end

    subgraph RETROALIMENTACION ["Feedback Loop"]
        BTN["Boton Revisor UI"]
        PMA["Post-Match Agent"]
        FBA["Feedback Agent"]
    end

    HIST[("predictions_history.json")]

    AG1 --> AG2
    AG2 --> AG3
    AG3 --> AG35
    AG35 -->|"guarda"| WAOUT
    WAOUT -->|"lee"| AG4
    AG35 --> AG4
    AG4 --> AG5
    AG5 --> AG55
    AG55 --> AG6
    AG6 --> AG7
    AG7 --> END2([FIN])

    THIST -->|"history"| AG4
    AG4 -->|"guarda"| THIST

    AG6 --> AWC
    AWC --> AG6

    AG6 --> HIST
    MEM -->|"feedback"| AG6

    BTN --> PMA
    PMA -->|"results"| HIST
    HIST --> FBA
    FBA --> MEM

    style PIPELINE fill:#0d2137,stroke:#1a6fa8,color:#c9d1d9
    style RETROALIMENTACION fill:#1a1a2e,stroke:#6b46c1,color:#c9d1d9
    style MEMORIA fill:#0d3b2c,stroke:#238636,color:#c9d1d9
    style HISTPERSIST fill:#1a1200,stroke:#d29922,color:#c9d1d9
    style THIST fill:#2d2505,stroke:#d29922,color:#f0c040
    style WAOUT fill:#2d2505,stroke:#d29922,color:#f0c040
    style MEM fill:#1a4731,stroke:#238636,color:#7ee787
    style HIST fill:#161b22,stroke:#30363d,color:#8b949e
    style AG35 fill:#1a2040,stroke:#1a6fa8,color:#9ecbff
    style AG4 fill:#1a2d1a,stroke:#3fb950,color:#c9d1d9
    style AG6 fill:#1f3d1f,stroke:#238636,color:#7ee787
    style AWC fill:#2d2505,stroke:#d29922,color:#f0c040
    style FBA fill:#2d1f5e,stroke:#6b46c1,color:#e2d9f3
"""

    import re as _re

    components.html(
        f"""
        <div id="mermaid-container" style="
            background-color: #0d1117;
            padding: 40px;
            border-radius: 16px;
            border: 1px solid #30363d;
            box-shadow: 0 4px 20px rgba(0,0,0,0.4);
            overflow: auto;
        ">
            <div class="mermaid" style="width: 100%; text-align: center;">
                {ARCH_DIAGRAM}
            </div>
        </div>
        <script type="module">
            import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
            mermaid.initialize({{
                startOnLoad: true,
                theme: 'dark',
                themeVariables: {{
                    primaryColor: '#1a6fa8',
                    primaryTextColor: '#c9d1d9',
                    primaryBorderColor: '#30363d',
                    lineColor: '#8b949e',
                    secondaryColor: '#161b22',
                    tertiaryColor: '#0d1117',
                    mainBkg: '#161b22',
                    nodeBkg: '#161b22',
                    clusterBkg: '#0d2137',
                    clusterBorder: '#1a6fa8',
                    edgeLabelBackground: '#161b22',
                    fontFamily: 'Segoe UI, sans-serif',
                    fontSize: '14px'
                }},
                securityLevel: 'loose',
                flowchart: {{
                    useMaxWidth: false,
                    htmlLabels: true,
                    curve: 'basis',
                    padding: 20
                }}
            }});
        </script>
        """,
        height=1800,
    )

    st.divider()

    # Leyenda
    col_l1, col_l2, col_l3 = st.columns(3)
    with col_l1:
        st.markdown("#### 📡 Pipeline Principal")
        st.markdown("""
- **Odds Fetcher**: The Odds API — fuente única de partidos y cuotas
- **Stats Agent**: ESPN — posición, forma, goleadores
- **Journalist Agent**: YouTube — descubrimiento de videos relevantes
- **Insights Agent**: YouTube + Web + Manual + **historial persistente** → genera contexto por equipo y actualiza `team_history.json`
- **🗃️ team_history.json**: insights que trascienden entre jornadas. Input del Insights Agent en cada ejecución
- **Normalizer Agent**: cruce y consolidación de fuentes
- **Gate Agent**: filtro de calidad de datos
- **Analyst Agent**: **GPT-5** — predicciones con ancla bayesiana en cuotas
- **🔎 Analyst Web Check**: búsqueda puntual on-demand (bajas/sanciones confirmadas)
- **Bettor Agent**: detección de value bets
        """)
    with col_l2:
        st.markdown("#### 🔄 Ciclo de Retroalimentación")
        st.markdown("""
- **Post-Match Agent**: compara predicciones vs. resultados reales ESPN
- **Feedback Agent**: GPT-5 — genera lecciones por liga (CHI1 / UCL)
- **Analyst Memory**: `analyst_memory.json` — lecciones persistidas
- **Trigger**: botón "Ejecutar Agente Revisor" en esta UI
        """)
    with col_l3:
        st.markdown("#### ⚙️ Configuración")
        st.markdown("""
- Liga seleccionable en sidebar: `CHI1`, `UCL` o `Ambas`
- CLI: `python run_pipeline.py --liga CHI1`
- Env var: `PIPELINE_LIGA=CHI1`
- Memoria del Analista: pestaña 🤖 en esta UI
- Logs del Agente Revisor: `predictions/reviewer_last_run.log`
        """)


with tab_history:
    st.header("??? Insights Persistentes por Equipo")
    st.caption("Fuente: `data/knowledge/team_history.json` (historial acumulado de insights y se?ales de contexto).")

    if not team_history_data:
        st.info("No hay historial persistente todav?a. Ejecuta el pipeline (o el parcial desde periodista) para generarlo.")
    else:
        rows = []
        for team, entries in team_history_data.items():
            if not isinstance(entries, list):
                continue
            for item in entries:
                if not isinstance(item, dict):
                    continue
                rows.append({
                    "Equipo": team,
                    "Fecha": item.get("date", ""),
                    "Competencia": item.get("competition", ""),
                    "Tipo": item.get("kind", "insight"),
                    "Insight": item.get("insight", ""),
                    "SignalType": item.get("signal_type", ""),
                    "Confianza": item.get("confidence", None),
                })

        if not rows:
            st.info("El archivo existe pero no contiene entradas legibles.")
        else:
            hist_df = pd.DataFrame(rows)
            hist_df["Fecha"] = hist_df["Fecha"].fillna("")
            hist_df["Competencia"] = hist_df["Competencia"].fillna("")
            hist_df["Tipo"] = hist_df["Tipo"].fillna("insight")
            hist_df["Insight"] = hist_df["Insight"].fillna("")

            c1, c2, c3 = st.columns([2, 1, 1])
            team_options = ["(Todos)"] + sorted(hist_df["Equipo"].dropna().unique().tolist())
            comp_options = ["(Todas)"] + sorted([c for c in hist_df["Competencia"].dropna().unique().tolist() if c])
            type_options = ["(Todos)"] + sorted(hist_df["Tipo"].dropna().unique().tolist())

            selected_team = c1.selectbox("Equipo", team_options, key="hist_team_filter")
            selected_comp = c2.selectbox("Competencia", comp_options, key="hist_comp_filter")
            selected_type = c3.selectbox("Tipo", type_options, key="hist_type_filter")

            search_hist = st.text_input("?? Buscar en insights persistentes", "", key="hist_search_filter")

            filtered = hist_df.copy()
            if selected_team != "(Todos)":
                filtered = filtered[filtered["Equipo"] == selected_team]
            if selected_comp != "(Todas)":
                filtered = filtered[filtered["Competencia"] == selected_comp]
            if selected_type != "(Todos)":
                filtered = filtered[filtered["Tipo"] == selected_type]
            if search_hist.strip():
                q = search_hist.strip().lower()
                filtered = filtered[
                    filtered["Insight"].astype(str).str.lower().str.contains(q, na=False)
                    | filtered["Equipo"].astype(str).str.lower().str.contains(q, na=False)
                    | filtered["SignalType"].astype(str).str.lower().str.contains(q, na=False)
                ]

            filtered = filtered.sort_values(by=["Fecha", "Equipo"], ascending=[False, True])
            st.caption(f"Registros: {len(filtered)} / {len(hist_df)}")
            st.dataframe(filtered, use_container_width=True, hide_index=True)

with tab_web:
    st.header("🌐 Agente Web (Standalone)")
    st.caption("Búsqueda web con OpenAI Responses + web_search. No está integrado aún al pipeline principal.")

    default_web_prompt = (
        "Busca en internet un panorama ACTUAL (prioriza últimos 7 días y, si falta cobertura, amplía hasta 14 días) "
        "de los equipos de la Primera División de Chile (CHI1) y de los equipos que participan en la UEFA Champions League (UCL) en mi corrida actual.\n\n"
        "Objetivo: extraer información útil para pronóstico deportivo por equipo (no solo noticias generales).\n\n"
        "Para cada equipo, prioriza y resume con fecha:\n"
        "1. Resultados recientes (últimos partidos) y tendencia (racha, rendimiento local/visita).\n"
        "2. Goleadores actuales y jugadores más determinantes (figuras, asistidores, portero clave, etc.).\n"
        "3. Lesionados, suspendidos, dudas físicas y posibles retornos, acá es crucial que entregues contexto de quien es el jugador o la persona aludida, ejemplo Zampedri, el goleador del equipo, lesionado; Assadi - la Figura del equipo; De Paul - arquero titular, etc.\n"
        "4. Cambios de técnico / cuerpo técnico / esquema reciente.\n"
        "5. Contexto institucional relevante (crisis, sanciones, problemas económicos, conflictos internos, presión mediática, polémicas disciplinarias, racismo, etc.).\n"
        "6. Carga de calendario / doble competencia / rotaciones / desgaste.\n"
        "7. Contexto del partido anterior que pueda impactar el siguiente (derrota dura, polémica arbitral, expulsiones, desgaste emocional, etc.).\n\n"
        "Instrucciones de calidad:\n"
        "- Usa fuentes verificables y cita URLs.\n"
        "- Incluye fecha de cada señal cuando exista.\n"
        "- Distingue hechos confirmados de versiones no confirmadas (evita rumores si no hay respaldo).\n"
        "- Si no encuentras información reciente de un equipo, indícalo explícitamente en vez de inventar.\n"
        "- Prioriza señales con impacto potencial en rendimiento para apuestas/pronóstico.\n\n"
        "Intenta cubrir al menos 8-10 equipos por competencia si hay información disponible; prioriza los equipos presentes en la corrida actual."
    )
    if "web_agent_prompt_ui" not in st.session_state:
        st.session_state["web_agent_prompt_ui"] = default_web_prompt

    st.text_area(
        "Prompt del Agente Web",
        key="web_agent_prompt_ui",
        height=120,
    )

    cwa1, cwa2 = st.columns([1, 1])
    if cwa1.button("Ejecutar Agente Web"):
        with st.spinner("Ejecutando Agente Web..."):
            ok, logs = run_web_agent_script(st.session_state.get("web_agent_prompt_ui", default_web_prompt))
        st.session_state["web_agent_last_logs"] = logs
        st.session_state["web_agent_last_run"] = datetime.now().isoformat()
        if ok:
            st.success("Agente Web ejecutado correctamente.")
        else:
            st.error("Falló la ejecución del Agente Web.")

    if cwa2.button("Recargar Resultado Web"):
        st.session_state["web_agent_last_run"] = datetime.now().isoformat()

    if st.session_state.get("web_agent_last_run"):
        st.caption(f"Última acción Agente Web: {st.session_state['web_agent_last_run']}")

    web_output_path = "web_agent_output.json"
    web_output = None
    if os.path.exists(web_output_path):
        try:
            with open(web_output_path, "r", encoding="utf-8") as f:
                web_output = json.load(f)
        except Exception as e:
            st.warning(f"No se pudo leer {web_output_path}: {e}")

    if st.session_state.get("web_agent_last_logs"):
        with st.expander("Logs Agente Web", expanded=False):
            st.code(st.session_state["web_agent_last_logs"], language="text")

    if not web_output:
        st.info("No hay salida todavía. Ejecuta `run_web_agent.py` desde esta pestaña o por terminal.")
    else:
        ok_flag = web_output.get("ok")
        st.metric("Salida válida", "Sí" if ok_flag else "No")
        if web_output.get("validation_errors"):
            st.warning("La salida tiene errores de validación.")
            st.code("\n".join(web_output.get("validation_errors", [])), language="text")

        data = web_output.get("data") or {}
        coverage_meta = data.get("coverage_meta") or {}
        subcall_errors = data.get("subcall_errors") or {}
        comps = data.get("competitions") or []
        if coverage_meta:
            st.subheader("Cobertura / Lookback por Competencia")
            cov_rows = []
            for comp_name, meta_cov in coverage_meta.items():
                if not isinstance(meta_cov, dict):
                    continue
                cov_rows.append({
                    "Competencia": comp_name,
                    "Lookback usado": meta_cov.get("lookback_used"),
                    "Fallback 14d": "Sí" if meta_cov.get("fallback_applied") else "No",
                    "Equipos objetivo": len(meta_cov.get("target_teams") or []),
                    "Equipos cubiertos": len(meta_cov.get("covered_teams") or []),
                    "Equipos faltantes": len(meta_cov.get("missing_teams") or []),
                })
            if cov_rows:
                st.dataframe(pd.DataFrame(cov_rows), use_container_width=True, hide_index=True)
        if subcall_errors:
            err_lines = []
            for comp_name, err in subcall_errors.items():
                err_lines.append(f"{comp_name}: {err}")
            if err_lines:
                with st.expander("Errores de sub-búsquedas por competencia", expanded=False):
                    st.code("\n".join(err_lines), language="text")

        if comps:
            rows = []
            for comp in comps:
                teams = comp.get("teams") or []
                rows.append({
                    "Competencia": comp.get("competition"),
                    "Resumen": comp.get("summary", "")[:180],
                    "Equipos": len(teams),
                })
            st.subheader("Resumen por Competencia")
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            st.subheader("Detalle por Equipo")
            comp_opts = ["(Todas)"] + [c.get("competition") for c in comps if c.get("competition")]
            selected_comp = st.selectbox("Filtrar competencia", comp_opts, key="web_agent_comp_filter")
            team_rows = []
            for comp in comps:
                if selected_comp != "(Todas)" and comp.get("competition") != selected_comp:
                    continue
                for t in comp.get("teams") or []:
                    team_rows.append({
                        "Competencia": comp.get("competition"),
                        "Equipo": t.get("team"),
                        "Confianza": t.get("confidence"),
                        "Resumen": t.get("summary", ""),
                        "#Insights": len(t.get("web_insights") or []),
                        "#Fuentes": len(t.get("sources") or []),
                    })
            if team_rows:
                st.dataframe(pd.DataFrame(team_rows), use_container_width=True, hide_index=True)

            with st.expander("Ver JSON estructurado del Agente Web", expanded=False):
                st.json(data, expanded=False)
        else:
            st.info("El archivo existe, pero no contiene `competitions` parseadas.")

with tab_logs:
    st.subheader("Log de Ejecución del Pipeline")
    LOG_FILE = "pipeline_last_run.log"
    
    # Siempre leer el log de disco (fuente de verdad)
    logs_content = None
    
    # Si no hay en sesión, leer desde disco (ejecución anterior)
    if os.path.exists(LOG_FILE):
        encodings = ["utf-8", "utf-16"]
        for enc in encodings:
            try:
                with open(LOG_FILE, "r", encoding=enc) as lf:
                    logs_content = lf.read()
                break
            except UnicodeDecodeError:
                continue
        
        # Fallback si nada funcionó
        if not logs_content:
            with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as lf:
                logs_content = lf.read()
        
        st.caption("📂 Mostrando logs de la última ejecución guardada.")
    
    if logs_content:
        st.text_input(
            "🔎 Buscar en logs",
            value="Reintentando con YOUTUBE_API_KEY_ALTERNATIVA",
            key="logs_filter"
        )
        filter_value = st.session_state.get("logs_filter", "").strip()
        if filter_value:
            hits = [line for line in logs_content.splitlines() if filter_value in line]
            st.caption(f"Coincidencias: {len(hits)}")
            if hits:
                st.code("\n".join(hits), language='text')
        st.code(logs_content, language='text')
        st.info("Aún no hay logs. Ejecuta el pipeline para ver la salida.")

# ─────────────────────────────────────────────────────────────────────────────
# TAB: MEMORIA DEL ANALISTA 🤖
# ─────────────────────────────────────────────────────────────────────────────
with tab_memory:
    import os as _os

    st.header("🤖 Memoria del Analista")
    st.markdown("""
    Sistema de **retroalimentación y mejora continua** de ciclo cerrado:

    | Paso | Agente | Qué hace |
    |---|---|---|
    | 1 | **Post-Match Agent** | Busca resultados reales en ESPN para predicciones pasadas y calcula si acertamos |
    | 2 | **Feedback Agent (GPT-5)** | Analiza patrones de error por liga (CHI1 / UCL) y genera lecciones accionables |
    | 3 | **Analista** | En la próxima jornada, lee `analyst_memory.json` e incorpora las lecciones al prompt |
    """)

    st.divider()

    # ── Botón Ejecutar Agente Revisor (subprocess con logs en tiempo real) ────
    st.subheader("▶️ Ejecutar Agente Revisor")
    st.caption("Ejecuta Post-Match Agent → Feedback Agent (GPT-5) en secuencia. Los logs aparecen en tiempo real.")

    col_btn1, col_btn2 = st.columns([2, 3])
    with col_btn1:
        run_reviewer = st.button(
            "🔍 Ejecutar Agente Revisor",
            type="primary",
            key="btn_run_reviewer",
            help="Evalúa predicciones pasadas + genera lecciones aprendidas por liga"
        )

    REVIEWER_LOG_FILE = _os.path.join("predictions", "reviewer_last_run.log")

    if run_reviewer:
        st.info("⏳ Ejecutando Post-Match Agent y Feedback Agent... Los logs aparecen abajo.")
        log_expander = st.expander("📋 Logs en tiempo real", expanded=True)
        log_placeholder = log_expander.empty()
        full_logs = ""

        try:
            proc = subprocess.Popen(
                [sys.executable, "run_reviewer.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )

            with st.status("🛠️ Ejecutando Agente Revisor...", expanded=True) as status:
                st.write("Iniciando procesos de Post-Match y Feedback...")
                log_placeholder = st.empty()
                full_logs = ""
                
                while True:
                    line = proc.stdout.readline()
                    if not line and proc.poll() is not None:
                        break
                    if line:
                        full_logs += line
                        log_placeholder.code(full_logs[-10000:], language="text")

                # Guardar log a disco
                try:
                    _os.makedirs("predictions", exist_ok=True)
                    with open(REVIEWER_LOG_FILE, "w", encoding="utf-8") as _lf:
                        _lf.write(full_logs)
                except Exception:
                    pass

                if proc.returncode == 0:
                    status.update(label="✅ Agente Revisor completado!", state="complete", expanded=False)
                    st.success("La Memoria del Analista fue actualizada exitosamente.")
                else:
                    status.update(label="❌ Error en el Agente Revisor", state="error", expanded=True)
                st.session_state["reviewer_done"] = True
                time.sleep(0.5)
                st.rerun()

        except Exception as _e:
            st.error(f"❌ Error lanzando el Agente Revisor: {_e}")

    else:
        # Mostrar log de la última ejecución si existe
        if _os.path.exists(REVIEWER_LOG_FILE):
            with st.expander("📋 Log de la última ejecución", expanded=False):
                try:
                    with open(REVIEWER_LOG_FILE, "r", encoding="utf-8") as _lf:
                        _prev_log = _lf.read()
                    st.code(_prev_log, language="text")
                except Exception:
                    st.warning("No se pudo leer el log anterior.")

    st.divider()

    # ── Visualización de la Memoria ────────────────────────────────────────────
    memory_file = _os.path.join("predictions", "analyst_memory.json")

    if not _os.path.exists(memory_file):
        st.info("🔸 La Memoria del Analista aún no fue generada. Ejecuta el Agente Revisor para crearla.")
    else:
        import json as _json
        with open(memory_file, "r", encoding="utf-8") as _f:
            memory = _json.load(_f)

        gen_at = memory.get("generated_at", "?")[:19].replace("T", " ")
        total_ev = memory.get("total_evaluated", 0)
        acc_overall = memory.get("accuracy_overall", 0)

        # Métricas globales
        st.subheader("📊 Resumen Global")
        mc1, mc2, mc3 = st.columns(3)
        mc1.metric("Partidos Evaluados", total_ev)
        mc2.metric("Precisión Global", f"{acc_overall}%")
        mc3.metric("Actualizado", gen_at)

        st.divider()

        # Sección por liga
        by_league = memory.get("by_league", {})
        league_tabs_labels = list(by_league.keys())

        if not league_tabs_labels:
            st.warning("No hay datos por liga en la memoria.")
        else:
            league_tab_objects = st.tabs([f"⚽ {lg}" for lg in league_tabs_labels])
            for lt, comp in zip(league_tab_objects, league_tabs_labels):
                with lt:
                    data = by_league[comp]
                    stats = data.get("stats", {})
                    lessons = data.get("lessons", [])
                    top = data.get("top_lesson", "")
                    cal = data.get("calibration_note", "")

                    # Métricas de liga
                    l1, l2, l3, l4 = st.columns(4)
                    l1.metric("Partidos", stats.get("total", 0))
                    l2.metric("Precisión", f"{stats.get('accuracy', 0)}%")
                    acc_by_sign = stats.get("accuracy_by_sign", {})
                    l3.metric("Sign-1 acc", f"{acc_by_sign.get('1', {}).get('accuracy', 0)}%")
                    l4.metric("Sign-X acc", f"{acc_by_sign.get('X', {}).get('accuracy', 0)}%")

                    # Distribuciones
                    col_dist1, col_dist2 = st.columns(2)
                    with col_dist1:
                        pred_dist = stats.get("pred_distribution", {})
                        if pred_dist:
                            st.markdown("**Distribución de predicciones**")
                            for sign in ["1", "X", "2"]:
                                n = pred_dist.get(sign, 0)
                                total = stats.get("total", 1)
                                pct = round(n / total * 100) if total else 0
                                st.write(f"  `{sign}`: {n} ({pct}%)")
                    with col_dist2:
                        real_dist = stats.get("real_distribution", {})
                        if real_dist:
                            st.markdown("**Distribución de resultados reales**")
                            for sign in ["1", "X", "2"]:
                                n = real_dist.get(sign, 0)
                                total = stats.get("total", 1)
                                pct = round(n / total * 100) if total else 0
                                st.write(f"  `{sign}`: {n} ({pct}%)")

                    # Errores
                    error_counts = stats.get("error_counts", {})
                    if error_counts:
                        st.markdown("**Tipos de error detectados**")
                        sorted_errors = sorted(error_counts.items(), key=lambda x: -x[1])
                        for etype, cnt in sorted_errors:
                            total = stats.get("total", 1)
                            pct = round(cnt / total * 100, 1)
                            icon = "✅" if etype == "correct" else "❌"
                            st.write(f"  {icon} `{etype}`: {cnt} ({pct}%)")

                    st.divider()

                    # Lección maestra
                    if top:
                        st.info(f"⭐ **Lección Maestra {comp}**: {top}")

                    # Calibración
                    if cal:
                        st.warning(f"📏 **Calibración**: {cal}")

                    # Lecciones detalladas
                    if lessons:
                        st.markdown(f"**📚 Lecciones aprendidas para {comp}**")
                        for les in sorted(lessons, key=lambda x: {"alta": 0, "media": 1, "baja": 2}.get(x.get("severity", "baja"), 2)):
                            sev = les.get("severity", "?")
                            color_map = {"alta": "🔴", "media": "🟡", "baja": "🟢"}
                            icon = color_map.get(sev, "⚪")
                            with st.expander(f"{icon} [{sev.upper()}] {les.get('pattern','')} — {les.get('description','')}"):
                                st.markdown(f"**Regla para el Analista:**")
                                st.markdown(f"> {les.get('lesson','')}")
                    else:
                        st.info("No hay lecciones generadas aún. Ejecuta el Agente Revisor.")
