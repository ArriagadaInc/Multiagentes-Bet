"""
Script ejecutable por subprocess para correr el ciclo Post-Match + Feedback Agent.
Escribe logs al archivo predictions/reviewer_last_run.log y a stdout.
"""
import sys
import os
import io
import logging
from datetime import datetime

# Asegurarse de correr desde el root del proyecto
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from dotenv import load_dotenv
load_dotenv()

LOG_FILE = os.path.join("predictions", "reviewer_last_run.log")
os.makedirs("predictions", exist_ok=True)

# Forzar stdout en UTF-8 (evita UnicodeEncodeError con emojis en Windows/cp1252)
if hasattr(sys.stdout, "buffer"):
    _utf8_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
else:
    _utf8_stdout = sys.stdout

# Logger dual: archivo + stdout (ambos en utf-8)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(_utf8_stdout),
        logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8"),
    ]
)
log = logging.getLogger("reviewer")


def main():
    log.info("=" * 60)
    log.info("AGENTE REVISOR — INICIO")
    log.info(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    # ── PASO 1: Post-Match Agent ──────────────────────────────────────
    log.info("")
    log.info("PASO 1/2 — POST-MATCH AGENT")
    log.info("  🔍 Objetivo: comparar predicciones pasadas con resultados reales de ESPN")
    log.info("  📂 Leyendo predictions/predictions_history.json ...")

    try:
        from agents.post_match_agent import PostMatchAgent

        def pm_progress(msg):
            log.info(f"  {msg}")

        agent = PostMatchAgent()
        pm_result = agent.run(progress_callback=pm_progress)

        evaluated  = pm_result.get("evaluated", 0)
        not_found  = pm_result.get("not_found", 0)
        skipped    = pm_result.get("skipped", 0)
        total_pend = pm_result.get("total_pending", 0)

        log.info(f"  ✅ Post-Match completado:")
        log.info(f"     Pendientes revisadas : {total_pend}")
        log.info(f"     Evaluadas con ESPN   : {evaluated}")
        log.info(f"     No encontradas       : {not_found}")
        log.info(f"     Omitidas (ya tenían) : {skipped}")

    except Exception as e:
        log.error(f"  ❌ Post-Match Agent falló: {e}")
        import traceback
        log.error(traceback.format_exc())
        sys.exit(1)

    # ── PASO 2: Feedback Agent ────────────────────────────────────────
    log.info("")
    log.info("PASO 2/2 — FEEDBACK AGENT (GPT-5)")
    log.info("  🧠 Objetivo: analizar patrones de error por liga y generar lecciones")
    log.info("  📊 Calculando estadísticas por liga (CHI1 / UCL)...")

    try:
        from agents.feedback_agent import run_feedback_agent

        def fb_progress(msg):
            log.info(f"  {msg}")

        fb_result = run_feedback_agent(progress_callback=fb_progress)

        if "error" in fb_result:
            log.warning(f"  ⚠️  {fb_result['error']}")
        else:
            log.info(f"  ✅ Feedback completado:")
            log.info(f"     Partidos analizados : {fb_result.get('total_evaluated', 0)}")
            log.info(f"     Precisión global    : {fb_result.get('accuracy_overall', '?')}%")
            log.info(f"     Ligas con lecciones : {', '.join(fb_result.get('leagues', []))}")
            log.info(f"     Memoria guardada en : {fb_result.get('memory_file', '?')}")

    except Exception as e:
        log.error(f"  ❌ Feedback Agent falló: {e}")
        import traceback
        log.error(traceback.format_exc())
        sys.exit(1)

    log.info("")
    log.info("=" * 60)
    log.info("AGENTE REVISOR — COMPLETADO OK")
    log.info("  Las lecciones ya están disponibles en predictions/analyst_memory.json")
    log.info("  El Analista las incorporará en la próxima jornada automáticamente.")
    log.info("=" * 60)
    sys.exit(0)


if __name__ == "__main__":
    main()
