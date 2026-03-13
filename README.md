# ⚽ Agente de Apuestas IA

Este proyecto es un ecosistema multi-agente diseñado para encontrar valor en apuestas deportivas de fútbol mediante el análisis avanzado de datos e Inteligencia Artificial.

💻 **Repositorio Oficial:** [ArriagadaInc/Multiagentes-Bet](https://github.com/ArriagadaInc/Multiagentes-Bet)

## 🚀 Resumen del Proyecto
El sistema procesa múltiples fuentes de datos (cuotas de mercado, estadísticas en tiempo real e insights tácticos de YouTube) utilizando agentes especializados coordinados por **LangGraph**. El objetivo final es identificar el "Edge" o ventaja teórica sobre las casas de apuestas para sugerir pronósticos con alta probabilidad de éxito.

## ⚙️ Funcionamiento General

El pipeline se divide en agentes con roles específicos:

1.  **📊 Agente de Cuotas**: Establece la fuente de verdad y el `match_key` determinista.
2.  **📈 Agente de Estadísticas (Modular)**: Estructura multifuente (ESPN, UEFA, FBref) validada por Pydantic.
3.  **🎙️ Agente Periodista**: Descubrimiento dinámico de análisis táctico en YouTube.
4.  **🧠 Agente de Insights**: Extracción de claves tácticas y bajas mediante transcripciones e IA.
5.  **🔗 Normalizador**: Cruza consolidado de datos usando identificadores únicos.
6.  **🛡️ Gate Agent**: Filtro de seguridad que valida la calidad de datos antes del análisis.
7.  **🔮 Agente Analista (IAG)**: Generación de predicciones de alta fidelidad.
8.  **💰 Agente Apostador**: Cálculo de valor (EV) y gestión de Stake.

## 🛠️ Inicio Rápido (Windows)

Para ejecutar el dashboard interactivo de Streamlit:

1.  Asegúrate de tener tu archivo `.env` configurado con las API Keys necesarias.
2.  Haz doble clic en: `iniciar_proyecto.bat`
3.  El navegador se abrirá automáticamente con el Dashboard.

## 📂 Estructura Principal
- `app.py`: Interfaz de usuario (Streamlit).
- `graph_pipeline.py`: Lógica de coordinación de los agentes.
- `agents/`: Carpeta con el código individual de cada agente.
- `bitacora.md`: Historial de desarrollo y cambios recientes.

---
*Desarrollado para Álvaro por Germán.*
