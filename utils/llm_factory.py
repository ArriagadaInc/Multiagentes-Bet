import os
import logging

logger = logging.getLogger(__name__)

def get_llm(temperature=0, max_tokens=None, model_name=None, **kwargs):
    """
    Factory para instanciar el LLM según la configuración 'Modo Caro'.
    Respeta la variable EXPENSIVE_MODE.
    """
    expensive_mode = os.getenv("EXPENSIVE_MODE", "true").lower() in ("true", "1", "yes")

    if expensive_mode:
        model = model_name or os.getenv("OPENAI_MODEL", "gpt-5")
        provider = "openai"
        try:
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                temperature=temperature,
                model=model,
                max_tokens=max_tokens,
                **kwargs
            )
            logger.info(f"LLM selected: {model} | provider={provider} | expensive_mode=true")
            return llm
        except Exception as e:
            logger.error(f"Fallo al inicializar ChatOpenAI en modo caro: {e}")
            raise

    else:
        # Modo Económico: Gemini
        model = model_name or os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
        provider = "google"
        
        # Resolución de API KEY
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            error_msg = "Error: Modo económico activado pero no se encontró GEMINI_API_KEY ni GOOGLE_API_KEY."
            logger.error(error_msg)
            raise ValueError(error_msg)
            
        gemini_kwargs = kwargs.copy()
        # Leer budget si existe para configurar thinking
        thinking_budget = os.getenv("GEMINI_THINKING_BUDGET")
        if thinking_budget:
            try:
                gemini_kwargs["thinking"] = True
                logger.info(f"Gemini configurado con thinking budget: {thinking_budget}")
            except Exception as e:
                logger.warning(f"No se pudo parsear GEMINI_THINKING_BUDGET: {e}")

        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            llm = ChatGoogleGenerativeAI(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                google_api_key=api_key,
                **gemini_kwargs
            )
            logger.info(f"LLM selected: {model} | provider={provider} | expensive_mode=false")
            return llm
        except Exception as e:
            logger.error(f"Fallo al inicializar ChatGoogleGenerativeAI en modo económico: {e}")
            raise
