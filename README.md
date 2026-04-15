# Multiagentes-Bet

Sistema multiagente para análisis pre-partido de fútbol, generación de predicciones 1X2 y apoyo a decisiones de apuesta con guardrails de calidad.

Repositorio oficial:
- `https://github.com/ArriagadaInc/Multiagentes-Bet`

## Qué hace
El sistema toma fixtures, cuotas, estadísticas y contexto cualitativo, construye un `match_context` canónico por partido, controla la calidad de la información antes del análisis y luego genera:
- predicciones 1X2
- score estimado
- trazabilidad completa del pipeline
- sugerencias de apuesta
- herramientas UI para carga manual de noticias y cuotas
- un optimizador Betano basado en OCR + bankroll

No está diseñado como un scraper aislado ni como un predictor “caja negra”. La arquitectura separa ingestión, contexto, control de calidad, predicción y decisión de apuesta.

## Esquema general
```text
Fixtures -> Odds -> Stats -> Journalist -> Web -> Insights -> Normalizer -> Gate -> Analyst -> Bettor
                              |            |         |            |         |
                              |            |         |            |         +-> recomendaciones / value / portafolio
                              |            |         |            +-> match_context canónico
                              |            |         +-> señales YouTube / web / manuales / history
                              |            +-> investigación web complementaria
                              +-> descubrimiento de fuentes y videos
```

## Agentes
### 1. Fixtures Agent
- obtiene partidos por competencia
- normaliza fixtures
- respeta ventanas de tiempo por torneo

### 2. Web Fixtures / Web Odds Fallback
- contingencia si faltan fixtures u odds
- especialmente relevante en competencias con cobertura débil

### 3. Odds Agent
- construye `odds_canonical`
- define el universo real apostable
- regla vigente: un partido no debe llegar al analista sin cuotas

### 4. Stats Agent
- agrega tabla, posición, GF/GC, forma y otros datos verificables
- evita contaminación entre competencias

### 5. Journalist Agent
- descubre videos y fuentes de contexto recientes
- usa cache y bypass para ahorrar consumo cuando ya existe trabajo previo

### 6. Web Agent
- agrega investigación web cuando YouTube no alcanza
- sirve de respaldo contextual

### 7. Insights Agent
- fusiona señales desde:
  - YouTube
  - Web
  - noticias manuales
  - historial persistente
- atomiza, sanea y estructura señales
- hoy es uno de los núcleos del sistema

### 8. Normalizer Agent
- arma `match_contexts` canónicos
- cruza fixtures, odds, stats e insights
- reinyecta historial persistente con filtros de higiene

### 9. Gate Agent
- controla calidad y riesgo informativo antes del análisis
- clasifica partidos como:
  - `clean`
  - `degraded`
  - `observation`
  - `dropped`

### 10. Analyst Agent
- genera predicción 1X2 y score estimado
- usa el `match_context` ya validado
- puede apoyarse en verificaciones web puntuales

### 11. Bettor Agent
- compara probabilidad del analista vs mercado
- detecta edge / value bets
- propone stakes y recomendaciones
- incluye una extensión UI para optimizar bankroll a partir de una boleta Betano

## Capacidades relevantes actuales
- pipeline multiagente orquestado con `LangGraph`
- UI Streamlit para operación y auditoría
- soporte para `noticia manual` en texto libre, texto guiado y JSON válido
- persistencia de señales por equipo
- mantenedor UI de señales persistentes
- carga manual de cuotas desde imagen
- optimizador `Betano Optimizer`:
  - OCR de cuotas 1X2
  - cruce con predicciones vigentes
  - calibración simple de probabilidad
  - distribución de bankroll
  - simples + combinadas limitadas

## Interfaz
La UI principal está en:
- `app.py`

Pestañas relevantes:
- `Pronósticos`
- `Predicciones`
- `Resultados`
- `Rastreo de Agentes`
- `Trace Report`
- `Insights Persistentes`
- `Cuotas Manuales`
- `Betano Optimizer`
- `Logs`

## Estructura principal
- `app.py`: dashboard Streamlit
- `graph_pipeline.py`: grafo principal del pipeline
- `run_pipeline.py`: ejecución principal por ligas
- `run_bettor.py`: ejecución del bettor on-demand
- `agents/`: agentes del sistema
- `utils/`: normalización, calibración, partición de señales, reporter, etc.
- `prompts/`: prompts reutilizables
- `bitacora.md`: log de desarrollo y decisiones
- `agentes_flow.md`: arquitectura operativa del flujo

## Configuración
Crear un `.env` local a partir de `.env.example` y definir las claves necesarias según el modo de uso.

Claves típicas:
- `OPENAI_API_KEY`
- `GEMINI_API_KEY` o `GOOGLE_API_KEY`
- `ODDS_API_KEY`
- `FOOTBALL_DATA_API_KEY`

No se deben versionar:
- `.env`
- caches locales
- historial operativo generado por usuario
- noticias manuales
- boletas/capturas subidas

El repositorio ya contiene exclusiones en `.gitignore` para evitar subir esos artefactos.

## Ejecución rápida
### Streamlit
```powershell
streamlit run app.py
```

### Pipeline principal
```powershell
python run_pipeline.py
```

### Bettor on-demand
```powershell
python run_bettor.py
```

## Documentación complementaria
- `agentes_flow.md`: descripción operativa del pipeline
- `README_PIPELINE.md`: detalles de ejecución y componentes
- `bitacora.md`: historial de cambios y decisiones técnicas

## Estado del proyecto
El sistema está en evolución activa. La arquitectura actual prioriza:
- trazabilidad
- control de calidad
- saneamiento de señales
- flexibilidad para operar con fuentes API, web y manuales

No asume que toda fuente externa sea confiable ni que toda señal deba pasar al analista sin filtros.
