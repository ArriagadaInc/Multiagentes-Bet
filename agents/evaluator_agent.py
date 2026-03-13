import os
import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Dict

from dotenv import load_dotenv
load_dotenv()

from utils.normalizer import TeamNormalizer
from utils.token_tracker import TokenTrackingCallbackHandler

from utils.espn_api import ESPNAPI

logger = logging.getLogger(__name__)

# Mapeo de ligas solicitado
COMPETITION_MAP = {
    "CHI1": "chi.1",
    "UCL": "uefa.champions"
}

PREDICTIONS_FILE = os.path.join("predictions", "predictions_history.json")
EVALUATION_REPORT_FILE = os.path.join("predictions", "evaluation_summary.json")

class ResultEvaluator:
    def __init__(self):
        self.espn = ESPNAPI()
        self.cache_scoreboards = {} # (league, date) -> data

    def load_predictions(self) -> List[Dict]:
        if not os.path.exists(PREDICTIONS_FILE):
            return []
        try:
            with open(PREDICTIONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading predictions: {e}")
            return []

    def save_predictions(self, predictions: List[Dict]):
        try:
            with open(PREDICTIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(predictions, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving predictions: {e}")

    def normalize_name(self, name: str) -> str:
        """Normalización robusta de nombres de equipos."""
        if not name: return ""
        n = name.lower()
        
        # Mapeos manuales prioritarios antes de limpiar tokens
        manual = {
            "internazionale": "inter milan",
            "inter milano": "inter milan",
            "fc internazionale milano": "inter milan",
            "bayer 04 leverkusen": "bayer leverkusen",
            "olympiakos piraeus": "olympiakos",
            "pae olympiakos sfp": "olympiakos",
            "sport lisboa e benfica": "benfica",
            "sl benfica": "benfica",
            "club brugge kv": "club brugge",
            "atletico de madrid": "atletico madrid",
            "club atletico de madrid": "atletico madrid",
            "paris saint germain fc": "psg",
            "paris saint germain": "psg",
            "as monaco fc": "monaco",
            "sporting cp": "sporting lisbon",
            "fk qarabag": "qarabag",
            "fk bodo glimt": "bodo glimt",
            "bodo/glimt": "bodo glimt"
        }
        
        for k, v in manual.items():
            if k in n:
                n = n.replace(k, v)
                break

        n = re.sub(r'[áàäâă]', 'a', n)
        n = re.sub(r'[éèëê]', 'e', n)
        n = re.sub(r'[íìïîı]', 'i', n)
        n = re.sub(r'[óòöôø]', 'o', n)
        n = re.sub(r'[úùüû]', 'u', n)
        n = n.replace('ñ', 'n')
        n = re.sub(r'[çç]', 'c', n)
        n = re.sub(r'[şş]', 's', n)
        n = re.sub(r'[ğğ]', 'g', n)
        n = re.sub(r'\b(fc|cf|cd|club|sd|ks|sk|pae|fk|kv|caf|gk|bk|sv|fk|bv|tsv|afc|cfc|ufc|utd|united|city|town|real|clube|deportivo|deportes|universidad|atletico|as|ss|us)\b', '', n)
        n = re.sub(r'\(.*?\)', '', n) # Quitar paréntesis
        n = re.sub(r'[^a-z0-9\s]+', ' ', n) # Quitar caracteres no alfanuméricos restantes
        n = re.sub(r'\s+', ' ', n).strip()
        return n

    def is_match(self, name1: str, name2: str) -> bool:
        """Verifica si dos nombres de equipos coinciden de forma flexible."""
        if not name1 or not name2: return False
        n1 = self.normalize_name(name1)
        n2 = self.normalize_name(name2)
        
        # 1. Match exacto o substring
        if n1 == n2 or n1 in n2 or n2 in n1:
            return True
            
        # 2. Match por tokens
        t1 = set(n1.split())
        t2 = set(n2.split())
        if not t1 or not t2: return False
        
        intersection = t1.intersection(t2)
        if len(intersection) >= min(len(t1), len(t2)):
            return True
            
        # 3. Fuzzy ratio
        import difflib
        ratio = difflib.SequenceMatcher(None, n1, n2).ratio()
        if ratio > 0.75:
            return True
        
        # logger.debug(f"No match: '{n1}' vs '{n2}' (ratio: {ratio:.2f})")
        return False

    def _get_llm_matching(self, pred_home: str, pred_away: str, candidates: List[Dict]) -> Optional[str]:
        """Usa el LLM para identificar un partido entre candidatos de ESPN."""
        try:
            from utils.llm_factory import get_llm
            
            llm = get_llm(
                temperature=0,
                callbacks=[TokenTrackingCallbackHandler()]
            )
            
            prompt = f"""Empareja el siguiente partido de nuestra base de datos con un evento de ESPN.
            
PARTIDO BUSCADO: {pred_home} vs {pred_away}

CANDIDATOS ESPN:
{json.dumps([{'id': c['id'], 'name': c['name']} for c in candidates], indent=2)}

REGLAS:
1. Responde ÚNICAMENTE con el ID del evento que coincida mejor.
2. Si ninguno coincide remotamente, responde "NONE".
3. Considera que los nombres pueden variar (ej: "Real Madrid CF" vs "Real Madrid").
"""
            response = llm.invoke(prompt)
            content = response.content.strip()
            if "NONE" in content: return None
            # Extraer solo el ID numérico si viene con texto
            match = re.search(r'(\d+)', content)
            return match.group(1) if match else None
        except Exception as e:
            logger.warning(f"Error in LLM matching: {e}")
            return None

    def find_event_id(self, pred: Dict, scoreboard: Dict) -> Optional[Dict]:
        """Busca el evento coincidente en el scoreboard."""
        events = scoreboard.get("events", [])
        if not events: return None
        
        home_target = self.normalize_name(pred.get("home_team"))
        away_target = self.normalize_name(pred.get("away_team"))
        
        candidates = []
        for ev in events:
            comp = ev.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])
            if len(competitors) < 2: continue
            
            e_home = ""
            e_away = ""
            for c in competitors:
                if c.get("homeAway") == "home": e_home = self.normalize_name(c.get("team", {}).get("name", ""))
                if c.get("homeAway") == "away": e_away = self.normalize_name(c.get("team", {}).get("name", ""))
            
            # Match robusto
            is_home_match = self.is_match(home_target, e_home)
            is_away_match = self.is_match(away_target, e_away)
            
            # También probar match invertido
            is_home_inv_match = self.is_match(home_target, e_away)
            is_away_inv_match = self.is_match(away_target, e_home)

            if (is_home_match and is_away_match) or (is_home_inv_match and is_away_inv_match):
                return ev
            
            candidates.append({"id": ev["id"], "name": ev.get("name")})

        # Matching por LLM si falló el simple
        if candidates:
            event_id = self._get_llm_matching(pred.get("home_team"), pred.get("away_team"), candidates)
            if event_id:
                for ev in events:
                    if str(ev["id"]) == str(event_id): return ev
                    
        return None

    def evaluate_all(self):
        predictions = self.load_predictions()
        if not predictions:
            logger.info("No predictions found to evaluate.")
            return

        evaluated_count = 0
        now_iso = datetime.now(timezone.utc).isoformat()

        for pred in predictions:
            if pred.get("correct") is not None and pred.get("evaluation_status") == "OK":
                continue
            
            comp_id = pred.get("competition")
            league = COMPETITION_MAP.get(comp_id)
            if not league:
                pred["evaluation_status"] = "SKIPPED_UNSUPPORTED_LEAGUE"
                continue

            is_legacy = False
            match_date_str = pred.get("match_date")
            if not match_date_str:
                pred_id = pred.get("prediction_id", "")
                m_date = re.search(r'202\d-\d{2}-\d{2}', pred_id)
                if m_date:
                    match_date_str = m_date.group(0) + "T00:00:00Z"
                else:
                    match_date_str = pred.get("generated_at")
                    is_legacy = True
            
            if not match_date_str:
                pred["evaluation_status"] = "NO_DATE"
                continue
            
            try:
                dt = datetime.fromisoformat(match_date_str.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                
                # Omitir solo si el partido es realmente en el futuro (después de hoy)
                if dt.date() > now.date():
                    pred["evaluation_status"] = "FUTURE_MATCH"
                    continue
                
                # Si es hoy, permitir seguir adelante si ya pasaron al menos 4 horas 
                # (aunque luego validaremos el estado 'completed' de ESPN)
                if dt.date() == now.date() and dt + timedelta(hours=4) > now:
                    # Dejamos que intente buscarlo, si ESPN dice 'post' lo tomamos
                    pass
                    
                date_yyyymmdd = dt.strftime("%Y%m%d")
            except Exception as e:
                pred["evaluation_status"] = "INVALID_DATE"
                continue

            if is_legacy:
                dates_to_try = [
                    date_yyyymmdd,
                    (dt - timedelta(days=1)).strftime("%Y%m%d"),
                    (dt - timedelta(days=2)).strftime("%Y%m%d"),
                    (dt + timedelta(days=1)).strftime("%Y%m%d")
                ]
                for ad_days in range(2, 6):
                    dates_to_try.append((dt + timedelta(days=ad_days)).strftime("%Y%m%d"))
            else:
                dates_to_try = [
                    date_yyyymmdd,
                    (dt - timedelta(days=1)).strftime("%Y%m%d"),
                    (dt + timedelta(days=1)).strftime("%Y%m%d")
                ]
            
            event_found = None
            for d in dates_to_try:
                cache_key = (league, d)
                if cache_key not in self.cache_scoreboards:
                    self.cache_scoreboards[cache_key] = self.espn.get_scoreboard(league, d)
                
                sb = self.cache_scoreboards[cache_key]
                if sb:
                    event_found = self.find_event_id(pred, sb)
                    if event_found: break
            
            if not event_found:
                logger.debug(f"Event not found for {pred.get('home_team')} vs {pred.get('away_team')} around {date_yyyymmdd}. Try list: {dates_to_try}")
                pred["evaluation_status"] = "NOT_FOUND"
                continue

            comp_data = event_found.get("competitions", [{}])[0]
            status = comp_data.get("status", {}).get("type", {}).get("completed", False)
            
            if not status:
                pred["evaluation_status"] = "PENDING"
                continue
            
            competitors = comp_data.get("competitors", [])
            h_score = 0
            a_score = 0
            
            home_target = self.normalize_name(pred.get("home_team", ""))
            away_target = self.normalize_name(pred.get("away_team", ""))
            
            espn_home_score = 0
            espn_away_score = 0
            espn_home_name = ""
            espn_away_name = ""
            
            for c in competitors:
                score = int(c.get("score", 0))
                team_name = self.normalize_name(c.get("team", {}).get("name", ""))
                if c.get("homeAway") == "home": 
                    espn_home_score = score
                    espn_home_name = team_name
                else: 
                    espn_away_score = score
                    espn_away_name = team_name
            
            # Lógica robusta para detectar local/visitante y evitar inversiones
            # 1. ¿Match Directo? (Home=Home, Away=Away)
            direct_match = self.is_match(home_target, espn_home_name) and self.is_match(away_target, espn_away_name)
            
            # 2. ¿Match Invertido? (Home=Away, Away=Home)
            inverted_match = self.is_match(home_target, espn_away_name) and self.is_match(away_target, espn_home_name)
            
            if direct_match and not inverted_match:
                h_score = espn_home_score
                a_score = espn_away_score
            elif inverted_match and not direct_match:
                h_score = espn_away_score
                a_score = espn_home_score
            elif direct_match and inverted_match:
                h_score = espn_home_score
                a_score = espn_away_score
            else:
                pred["evaluation_status"] = "MATCHING_AMBIGUITY"
                logger.warning(f"Ambiguity for {pred.get('home_team')} vs {pred.get('away_team')}")
                logger.warning(f"Targets: '{home_target}' | '{away_target}'")
                logger.warning(f"ESPN: '{espn_home_name}' | '{espn_away_name}'")
                continue
                
            actual_res = "DRAW"
            if h_score > a_score: actual_res = "1"
            elif a_score > h_score: actual_res = "2"
            else: actual_res = "X"
            
            pred_val = str(pred.get("prediction"))
            is_correct = (pred_val == actual_res)
            
            pred["actual_score"] = f"{h_score}-{a_score}"
            pred["result"] = actual_res
            pred["correct"] = is_correct
            pred["evaluation_status"] = "OK"
            pred["evaluated_at"] = now_iso
            pred["event_id"] = event_found["id"]
            
            evaluated_count += 1
            status_mark = "OK" if is_correct else "FAIL"
            logger.info(f"Evaluated: {pred.get('home_team')} vs {pred.get('away_team')} -> {status_mark} ({pred['actual_score']})")

        self.save_predictions(predictions)
        
        # Deduplicar antes de exportar CSV y generar reporte
        unique_history = self._deduplicate_history(predictions)
        
        self.save_predictions_csv(unique_history)
        self.generate_report(unique_history)
        logger.info(f"Evaluation complete. {evaluated_count} new records evaluated.")

    def _deduplicate_history(self, predictions: List[Dict]) -> List[Dict]:
        """Keep only the latest prediction for each match using a robust key."""
        unique_matches = {}
        for p in predictions:
            home = p.get("home_team", "").strip()
            away = p.get("away_team", "").strip()
            comp = p.get("competition", "").strip()
            event_id = p.get("event_id")
            
            if event_id:
                key = f"EVENT_{event_id}"
            else:
                m_date = p.get("match_date") or p.get("generated_at") or "unknown"
                m_date = m_date[:10] if len(m_date) >= 10 else "unknown"
                key = f"{comp}_{home}_{away}_{m_date}".lower()
                
            unique_matches[key] = p
        return list(unique_matches.values())

    def save_predictions_csv(self, predictions: List[Dict]):
        """Guarda el historial completo de predicciones evaluadas en CSV."""
        try:
            import pandas as pd
            history_file_csv = os.path.join("predictions", "predictions_history.csv")
            df = pd.DataFrame(predictions)
            
            # Columnas deseadas y ordenadas
            cols = [
                "match_date", "competition", "home_team", "away_team", 
                "prediction", "confidence", "score_prediction", 
                "actual_score", "result", "correct", "analyst_model_id",
                "generated_at", "evaluated_at", "prediction_id", "evaluation_status"
            ]
            
            # Filtrar solo las que existen en el DF
            final_cols = [c for c in cols if c in df.columns]
            
            # Guardar con UTF-8 con BOM para Excel
            df[final_cols].to_csv(history_file_csv, index=False, encoding="utf-8-sig")
            logger.info(f"✓ Historial evaluado guardado en CSV: {history_file_csv}")
        except Exception as e:
            logger.warning(f"No se pudo guardar el CSV de historial: {e}")

    def generate_report(self, predictions: List[Dict]):
        ok_preds = [p for p in predictions if p.get("evaluation_status") == "OK"]
        if not ok_preds: return

        total = len(ok_preds)
        correct = sum(1 for p in ok_preds if p.get("correct") is True)
        
        by_league = {}
        for p in ok_preds:
            l = p["competition"]
            if l not in by_league: by_league[l] = {"total": 0, "correct": 0}
            by_league[l]["total"] += 1
            if p.get("correct") is True: by_league[l]["correct"] += 1
            
        for l in by_league:
            by_league[l]["accuracy"] = round((by_league[l]["correct"] / by_league[l]["total"]) * 100, 2)
            
        by_model = {}
        for p in ok_preds:
            m = p.get("analyst_model_id", "gpt5")
            if m not in by_model: by_model[m] = {"total": 0, "correct": 0}
            by_model[m]["total"] += 1
            if p.get("correct") is True: by_model[m]["correct"] += 1
            
        for m in by_model:
            by_model[m]["accuracy"] = round((by_model[m]["correct"] / by_model[m]["total"]) * 100, 2)

        summary = {
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "total_evaluated": total,
            "total_correct": correct,
            "overall_accuracy_pct": round((correct / total) * 100, 2) if total > 0 else 0,
            "by_league": by_league,
            "by_model": by_model,
            "status_counts": {
                "OK": total,
                "PENDING": sum(1 for p in predictions if p.get("evaluation_status") == "PENDING"),
                "NOT_FOUND": sum(1 for p in predictions if p.get("evaluation_status") == "NOT_FOUND"),
                "NO_DATE": sum(1 for p in predictions if p.get("evaluation_status") == "NO_DATE")
            }
        }
        
        with open(EVALUATION_REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        # Generar versión CSV del resumen (Métricas por liga y modelo)
        self.save_summary_csv(summary)
        
        print("\n" + "="*40)
        print(" RESUMEN DE EVALUACIÓN")
        print("="*40)
        print(f"Precisión Global: {summary['overall_accuracy_pct']}% ({correct}/{total})")
        print("\nPor Modelo:")
        for m, s in by_model.items():
            print(f"  - {m}: {s['accuracy']}% ({s['correct']}/{s['total']})")
        print("="*40 + "\n")

    def save_summary_csv(self, summary: Dict):
        """Genera un archivo CSV con las métricas del resumen."""
        try:
            import pandas as pd
            rows = []
            
            # 1. Métricas por Modelo
            for model, stats in summary.get("by_model", {}).items():
                rows.append({
                    "Category": "Model",
                    "Target": model,
                    "Accuracy %": stats.get("accuracy"),
                    "Total": stats.get("total"),
                    "Correct": stats.get("correct")
                })
            
            # 2. Métricas por Liga
            for league, stats in summary.get("by_league", {}).items():
                rows.append({
                    "Category": "League",
                    "Target": league,
                    "Accuracy %": stats.get("accuracy"),
                    "Total": stats.get("total"),
                    "Correct": stats.get("correct")
                })
            
            # 3. Global
            rows.append({
                "Category": "Overall",
                "Target": "Global",
                "Accuracy %": summary.get("overall_accuracy_pct"),
                "Total": summary.get("total_evaluated"),
                "Correct": summary.get("total_correct")
            })
            
            summary_csv_file = os.path.join("predictions", "evaluation_summary.csv")
            pd.DataFrame(rows).to_csv(summary_csv_file, index=False, encoding="utf-8-sig")
            logger.info(f"✓ Resumen de métricas guardado en CSV: {summary_csv_file}")
            
        except Exception as e:
            logger.warning(f"No se pudo guardar el CSV de resumen: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    evaluator = ResultEvaluator()
    evaluator.evaluate_all()
