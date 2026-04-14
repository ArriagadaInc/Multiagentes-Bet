import os
import logging

logger = logging.getLogger(__name__)

def get_llm(temperature=0, max_tokens=None, model_name=None, profile: str | None = None, **kwargs):
    """
    Factory para instanciar el LLM según la configuración.

    Perfiles dedicados (ignoran EXPENSIVE_MODE):
      - tournament_research_gpt51: SIEMPRE gpt-5.1
      - web_research_forced:       SIEMPRE OpenAI (modelo configurable por WEB_RESEARCH_MODEL)
      - journalist_fast:           SIEMPRE gpt-4o-mini (rápido, sin rate-limit agresivo)

    Modos generales:
      - EXPENSIVE_MODE=false (default): Gemini principal → fallback gpt-4o-mini de OpenAI
      - EXPENSIVE_MODE=true:            Claude claude-sonnet-4-6 (Anthropic)
    """

    # =========================================================================
    # PERFILES DEDICADOS
    # =========================================================================

    if profile == "tournament_research_gpt51":
        model = "gpt-5.1"
        try:
            from utils.token_tracker import TokenTrackingCallbackHandler
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                temperature=0.2,
                model=model,
                max_tokens=max_tokens,
                callbacks=[TokenTrackingCallbackHandler()],
                **kwargs
            )
            logger.info(f"🏆 LLM Resolution (Tournament Research): profile=tournament_research_gpt51 | model={model} | forced=true | temp=0.2")
            return llm
        except Exception as e:
            logger.error(f"Fallo al inicializar ChatOpenAI (tournament_research_gpt51): {e}. Verifica OPENAI_API_KEY en .env")
            raise

    if profile == "web_research_forced":
        model = os.getenv("WEB_RESEARCH_MODEL", "gpt-4.1")
        if max_tokens is None:
            try:
                max_tokens = int(os.getenv("WEB_RESEARCH_MAX_TOKENS", "3500"))
            except Exception:
                max_tokens = None
        try:
            from utils.token_tracker import TokenTrackingCallbackHandler
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                temperature=temperature,
                model=model,
                max_tokens=max_tokens,
                callbacks=[TokenTrackingCallbackHandler()],
                **kwargs
            )
            logger.info(f"LLM Resolution (profile): profile=web_research_forced | resolved={model} | provider=openai | forced=true | max_tokens={max_tokens}")
            return llm
        except Exception as e:
            logger.error(f"Fallo al inicializar ChatOpenAI (profile=web_research_forced): {e}. Verifica OPENAI_API_KEY en .env")
            raise

    if profile == "journalist_fast":
        model = os.getenv("JOURNALIST_MODEL", "gpt-4o-mini")
        if max_tokens is None:
            max_tokens = 1500
        try:
            from utils.token_tracker import TokenTrackingCallbackHandler
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                temperature=temperature,
                model=model,
                max_tokens=max_tokens,
                callbacks=[TokenTrackingCallbackHandler()],
                **kwargs
            )
            logger.info(f"LLM Resolution (profile): profile=journalist_fast | resolved={model} | provider=openai | forced=true")
            return llm
        except Exception as e:
            logger.error(f"Fallo al inicializar ChatOpenAI (profile=journalist_fast): {e}")
            # Si falla (ej. sin OPENAI_API_KEY), caer al flujo normal silenciosamente
            pass

    # =========================================================================
    # MODO GENERAL: EXPENSIVE_MODE controla el proveedor principal
    # =========================================================================

    if profile in ("insights_core", "analyst_core"):
        # Estos dos perfiles SÍ respetan EXPENSIVE_MODE:
        # - EXPENSIVE_MODE=true  → Claude claude-sonnet-4-6 (razonamiento profundo)
        # - EXPENSIVE_MODE=false → Gemini + fallback gpt-4o-mini (económico)
        # El RESTO de agentes siempre usan el flujo económico, independientemente de EXPENSIVE_MODE.
        expensive_mode_profile = os.getenv("EXPENSIVE_MODE", "false").lower() in ("true", "1", "yes")
        if expensive_mode_profile:
            model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                logger.error(f"EXPENSIVE_MODE=true para {profile} pero no se encontró ANTHROPIC_API_KEY")
                raise ValueError("ANTHROPIC_API_KEY no configurada")
            try:
                from utils.token_tracker import TokenTrackingCallbackHandler
                from langchain_anthropic import ChatAnthropic
                llm = ChatAnthropic(
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens or 4096,
                    anthropic_api_key=api_key,
                    callbacks=[TokenTrackingCallbackHandler()],
                    **kwargs
                )
                logger.info(f"🧠 LLM Resolution: profile={profile} | resolved={model} | provider=anthropic | expensive_mode=true")
                return llm
            except Exception as e:
                logger.error(f"Fallo al inicializar Claude para {profile}: {e}")
                raise
        # Si no es modo caro, cae al flujo económico genérico (Gemini + fallback)
        # Se sigue con la lógica de abajo (expensive_mode=False)

    expensive_mode = os.getenv("EXPENSIVE_MODE", "false").lower() in ("true", "1", "yes")

    if expensive_mode and profile not in ("insights_core", "analyst_core"):
        # Para agentes sin perfil dedicado, ignorar EXPENSIVE_MODE y usar el flujo económico.
        # Claude está reservado exclusivamente para insights_core y analyst_core.
        logger.debug(f"EXPENSIVE_MODE=true ignorado para perfil '{profile}' (solo se aplica a insights_core / analyst_core)")
        expensive_mode = False

    if expensive_mode:
        # ► Claude claude-sonnet-4-6 (solo alcanzable desde insights_core/analyst_core con EXPENSIVE_MODE=true)
        model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            logger.error("Modo caro activado pero no se encontró ANTHROPIC_API_KEY en .env")
            raise ValueError("ANTHROPIC_API_KEY no configurada")
        try:
            from utils.token_tracker import TokenTrackingCallbackHandler
            from langchain_anthropic import ChatAnthropic
            
            # Gestionar callbacks para evitar duplicados en kwargs
            passed_callbacks = kwargs.pop("callbacks", [])
            all_callbacks = [TokenTrackingCallbackHandler()] + (passed_callbacks if isinstance(passed_callbacks, list) else [passed_callbacks])
            
            llm = ChatAnthropic(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens or 4096,
                anthropic_api_key=api_key,
                callbacks=all_callbacks,
                **kwargs
            )
            logger.info(f"LLM Resolution: resolved={model} | provider=anthropic | expensive_mode=true")
            return llm
        except Exception as e:
            logger.error(f"Fallo al inicializar ChatAnthropic en modo caro: {e}")
            raise

    else:
        # ── MODO BARATO: Gemini principal → fallback gpt-4o-mini ─────────────────────
        if model_name:
            if "gpt-4" in model_name.lower() or "gpt-3.5" in model_name.lower():
                model = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
                logger.info(f"Economic Mode: Mapping {model_name} -> {model}")
            elif "gpt-5" in model_name.lower() or "o1" in model_name.lower():
                model = "gemini-1.5-pro"
                logger.info(f"Economic Mode: Mapping {model_name} -> {model}")
            else:
                model = model_name
        else:
            model = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if api_key:
            gemini_kwargs = kwargs.copy()
            thinking_budget = os.getenv("GEMINI_THINKING_BUDGET")
            if thinking_budget:
                try:
                    gemini_kwargs["thinking"] = True
                    logger.info(f"Gemini configurado con thinking budget: {thinking_budget}")
                except Exception as e:
                    logger.warning(f"No se pudo parsear GEMINI_THINKING_BUDGET: {e}")
            try:
                from utils.token_tracker import TokenTrackingCallbackHandler
                from langchain_google_genai import ChatGoogleGenerativeAI
                llm = ChatGoogleGenerativeAI(
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    google_api_key=api_key,
                    callbacks=[TokenTrackingCallbackHandler()],
                    **gemini_kwargs
                )
                logger.info(f"LLM Resolution: requested={model_name or 'default'} | resolved={model} | provider=google | expensive_mode=false")
                return llm
            except Exception as gemini_error:
                logger.warning(f"Gemini falló ({gemini_error}). Intentando fallback con gpt-4o-mini...")
        else:
            logger.warning("Sin GEMINI_API_KEY/GOOGLE_API_KEY. Intentando fallback con gpt-4o-mini...")

        # Fallback: gpt-4o-mini
        fallback_model = os.getenv("FALLBACK_MODEL", "gpt-4o-mini")
        fallback_key = os.getenv("OPENAI_API_KEY")
        if not fallback_key:
            raise ValueError("Sin Gemini ni OpenAI API Key configurada. Imposible inicializar LLM.")
        try:
            from utils.token_tracker import TokenTrackingCallbackHandler
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                temperature=temperature,
                model=fallback_model,
                max_tokens=max_tokens,
                callbacks=[TokenTrackingCallbackHandler()],
            )
            logger.info(f"LLM Resolution: resolved={fallback_model} | provider=openai | mode=fallback_cheap")
            return llm
        except Exception as e:
            logger.error(f"Fallback gpt-4o-mini también falló: {e}")
            raise
