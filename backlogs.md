# Backlogs: Sistema Multiagente de Apuestas
*Estado al 19-Mar-2026 - Consolidación de Deuda Técnica y Nuevas Ideas*

Este documento centraliza las tareas pendientes y futuras evoluciones del sistema.

---

## 🟢 P0: Estabilidad Operativa y Cimientos (Impacto Inmediato)
- [ ] **1. Blindaje Estructural del Parseo LLM**
  - Aplicar el patrón canónico de normalización de respuestas LLM en `agents/insights_agent.py` y `agents/evaluator_agent.py`.
  - Investigar y entender por qué Gemini Force Function Calling fracciona el output en modo chat.
  - Refactorizar `analyst_web_check.py` con `with_structured_output`.

- [x] **2. Gate Duro: Bloqueo Operativo Exacto** (Completado)
  - Implementación de reglas deterministas de bloqueo por riesgo.

---

## 🔵 P1: Observabilidad, Continuidad de Muestra y Curaduría
- [x] **3. Observabilidad Operativa** (Completado)
  - Reporte ASCII y trazabilidad básica.
- [ ] **4. Continuidad de Muestra (API YouTube Fallback)**
  - Robustecer `yt_dlp` como fallback de cuota.
  - Ejecutar corrida completa con cuota real de YouTube.

---

## 🟡 P2: Política Futura y Afinamientos
- [ ] **5. Política de Calibración Real**
  - Evaluar Brier Score tras >50 muestras para activar calibración bayesiana.
- [ ] **6. Cartera Premium y Afinamientos Finos**
  - Lógica de portafolio de bajo volumen / alta confianza.

---

## 🟣 P3: Blindaje Semántico y Calidad de Datos
- [x] **7. Saneamiento de Fuga Semántica (Caso Muslera)** (Completado)
  - Filtrado de oponentes históricos y regla de validación de entidades en el Analista.
- [ ] **8. Guardián de Plantillas (Roster Validation System)** 💡 *NUEVO*
  - **Objetivo**: Implementar una validación determinista (no solo LLM) de los jugadores mencionados.
  - **Componentes**:
    - `data/knowledge/rosters.json`: Base de datos de plantillas oficiales.
    - `utils/roster_checker.py`: Script que cruza los nombres detectados por el Periodista/Web contra la base de datos oficial.
    - **Acción**: Eliminar automáticamente señales de jugadores que no pertenecen a ninguno de los dos equipos del partido para evitar alucinaciones.

---

## 📜 Historial de Sesiones
*Ver [bitacora.md](file:///c:/desarrollos/apuestas/Futbol/bitacora.md) para el detalle de hitos alcanzados.*
