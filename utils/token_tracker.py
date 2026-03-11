
import json
import os
import logging
from threading import Lock

logger = logging.getLogger(__name__)

TOKEN_USAGE_FILE = "token_usage.json"
_lock = Lock()

def load_token_usage():
    """Carga el uso de tokens desde el archivo JSON."""
    with _lock:
        if not os.path.exists(TOKEN_USAGE_FILE):
            return {}
        try:
            with open(TOKEN_USAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.error(f"Error cargando token_usage.json: {e}")
            return {}

def save_token_usage(usage):
    """Guarda el uso de tokens en el archivo JSON."""
    with _lock:
        try:
            with open(TOKEN_USAGE_FILE, "w", encoding="utf-8") as f:
                json.dump(usage, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error guardando token_usage.json: {e}")

def track_tokens(model, prompt_tokens, completion_tokens):
    """Actualiza de forma incremental el contador de tokens para un modelo."""
    if not model:
        model = "unknown"
    
    usage = load_token_usage()
    
    if model not in usage:
        usage[model] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "calls": 0
        }
    
    usage[model]["prompt_tokens"] += prompt_tokens
    usage[model]["completion_tokens"] += completion_tokens
    usage[model]["total_tokens"] += (prompt_tokens + completion_tokens)
    usage[model]["calls"] += 1
    
    save_token_usage(usage)
    logger.info(f"Tokens tracked for {model}: +{prompt_tokens + completion_tokens} (Total: {usage[model]['total_tokens']})")

def reset_tokens():
    """Reinicia el contador de tokens (elimina el archivo)."""
    with _lock:
        if os.path.exists(TOKEN_USAGE_FILE):
            try:
                os.remove(TOKEN_USAGE_FILE)
                logger.info("Contador de tokens reiniciado.")
            except Exception as e:
                logger.error(f"Error al reiniciar tokens: {e}")

# --- LangChain Callback Handler ---
try:
    from langchain_core.callbacks import BaseCallbackHandler
    
    class TokenTrackingCallbackHandler(BaseCallbackHandler):
        def on_llm_end(self, response, **kwargs):
            """Se ejecuta al finalizar una llamada de LLM en LangChain."""
            try:
                for generations in response.generations:
                    for generation in generations:
                        if hasattr(response, 'llm_output') and response.llm_output:
                            token_usage = response.llm_output.get("token_usage")
                            model_name = response.llm_output.get("model_name", "unknown")
                            if token_usage:
                                track_tokens(
                                    model=model_name,
                                    prompt_tokens=token_usage.get("prompt_tokens", 0),
                                    completion_tokens=token_usage.get("completion_tokens", 0)
                                )
                                return # Solo trackeamos una vez por respuesta
            except Exception as e:
                logger.error(f"Error en TokenTrackingCallbackHandler: {e}")

except ImportError:
    # Si no está instalado LangChain, el callback no se define
    pass
