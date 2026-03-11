
import os

entry = """
### Fase 3: Interfaz Gráfica (Web UI) (19:00)
- **Objetivo**: Crear dashboard local para evitar uso de terminal.
- **Implementación**: `app.py` con Streamlit.
- **Funcionalidades**:
  - Botón de ejecución de pipeline.
  - Visualización de KPIs y Tablas de Apuestas.
  - Inspector de JSONs.
- **Estado**: Listo para despliegue local.
"""

with open("bitacora.md", "a", encoding="utf-8") as f:
    f.write(entry)
