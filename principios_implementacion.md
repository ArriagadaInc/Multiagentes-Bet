# Principios de Implementación - EvaluaPro (Futbol)

Este documento establece las reglas de oro para cualquier modificación o expansión del sistema de predicción. Estos principios garantizan la robustez, trazabilidad y honorabilidad científica del pipeline.

---

### 1. Fuente de verdad del pipeline
La estructura canónica debe vivir aguas arriba, no dentro de los agentes finales.
- `match_context` es la fuente de verdad absoluta del partido.
- La partición de señales (`signals_clean`, `signals_suspicious`, `signals_summary`) debe nacer y persistirse **antes** del Analyst.
- El Analyst debe ser un **consumidor** de esta lógica, no su constructor principal.

### 2. Separación de responsabilidades
No mezclar funciones entre capas:
- **Normalizer / utils**: Limpian, enriquecen y estructuran los datos crudos.
- **Gate Agent**: Mide la calidad y el riesgo epistemológico (higiene del contexto).
- **Analyst Agent**: Razona y genera la convicción predictiva.
- **Bettor Agent**: Decide la prudencia financiera (stakes, edges, caps).
- **Evaluator Agent**: Mide resultados reales y preserva la integridad del histórico.

### 3. Compatibilidad hacia atrás
Cada cambio nuevo debe intentar no romper el pipeline existente.
- Si existe un fallback legacy, mantenerlo temporalmente.
- Dejar **warnings explícitos** en logs cuando se use una ruta de fallback.
- No utilizar rutas legacy como solución silenciosa normal.

### 4. Nada de efectos laterales invisibles
Si un nodo enriquece objetos:
- Preferir devolver estructuras enriquecidas de forma clara y explícita.
- Evitar mutar objetos globales o de estado de forma silenciosa.
- Las funciones de recálculo deben declarar si respetan la metadata previa o la sobreescriben.

### 5. Trazabilidad obligatoria
Todo lo importante debe quedar visible en artefactos o logs:
- Diferenciación clara entre señales limpias vs. sospechosas.
- Razones explícitas de sospecha (tags).
- Scores de calidad (`signal_quality_score`) y niveles de riesgo (`signal_risk_level`).
- Ajustes financieros del Bettor justificados por el riesgo detectado.
- Comparativa `confidence_raw` vs. `confidence_calibrated`.

### 6. No introducir lógica “mágica”
Toda heurística sensible debe estar encapsulada en:
- Funciones pequeñas y atómicas.
- Nombres de función descriptivos.
- Constantes configurables (no valores "a fuego" en el código).
- Comentarios mínimos útiles. **Nada de lógica compleja enterrada en prompts.**

### 7. No cambiar comportamiento financiero sin permiso explícito
- Mientras la calibración esté en **shadow mode**, el Bettor debe seguir usando exclusivamente la confianza original.
- No reemplazar silenciosamente `confidence` por versiones experimentales.
- No alterar stakes, edges o criterios de skip de forma indirecta por nuevas métricas de prueba.

### 8. Logging útil, no decorativo
Cuando el sistema tome decisiones sensibles, el log debe explicar el **porqué**.
- Registro de uso de fallbacks.
- Justificación de "Skip por severe signal risk".
- Notificación de "Stake cap aplicado" con su motivo.
- Detección de discrepancias fuertes entre confianza raw y calibrada.

### 9. Testear el cambio + el “no cambio”
Cada micro-tarea requiere:
- **Test de novedad**: Verificar que la nueva funcionalidad cumple su objetivo.
- **Test de no regresión**: Asegurar que el comportamiento base previo sigue intacto.

### 10. Regla Maestra
1. Primero ordenamos la **Verdad** que entra al sistema (Datos).
2. Después mejoramos cómo **Decide** el modelo (Lógica).
3. Solo al final afinamos cómo **Apuesta** (Dinero).

---
**Si una implementación viola este espíritu, debe corregirse antes de avanzar.**
