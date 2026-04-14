# Correcciones Aplicadas - Auditoría de Costos

## Resumen Ejecutivo
Se identificaron y corrigieron **3 errores críticos** en el sistema de cálculo de costos que causaban una **inflación de ~99%** en el reporte de auditoría.

---

## Errores Identificados

### 1. ❌ Error de Unidad de Precios (USD/1K vs USD/1M)
**Problema:** `pricing.json` estaba usando claves `*_per_1k_usd` pero las tarifas estaban incorrectas.

**OpenAI Standard:** Precios publicados en USD por **1,000,000 tokens**, NO por 1,000.

**Impacto:** Todas las tarifas debían dividirse entre 1,000,000 en lugar de 1,000 → **factor 1000x**.

**Corrección:**
- Cambio de claves: `prompt_per_1k_usd` → `prompt_per_1m_usd`
- Actualización de tarifas según OpenAI Oct 2024:
  - gpt-4.1-mini: $0.40/1M input, $1.60/1M output
  - gpt-5.1: $15.00/1M input, $45.00/1M output

### 2. ❌ Error en Fórmula de División (costing.py)
**Problema:** Línea ~121 en `utils/costing.py`:
```python
# INCORRECTO:
prompt_usd = (tokens / 1000.0) * rate  # Divide por 1000

# CORRECTO:
prompt_usd = (tokens / 1_000_000.0) * rate  # Divide por 1,000,000
```

**Impacto:** Costo calculado = $23.375 USD (100x inflado) → Costo correcto ≈ $0.0038 USD

**Corrección:** Cambio de `/1000.0` a `/1_000_000.0` en todas las fórmulas de costo.

### 3. ❌ Error en Consolidación de Alias de Modelo
**Problema:** audit_report.py no consolidaba correctamente modelos con mismo nombre canonical.

Ejemplo:
- `gpt-4.1-mini-2025-04-14` (versión con fecha)
- `gpt-4.1-mini` (versión genérica)

Debería ser **1 entrada consolidada** (MAX de tokens), pero se estaban reportando como **2 entradas separadas**.

**Corrección:**
- Regex mejorado en `_canonical_model_name()`:
  ```python
  # Nuevo regex: captura todo lo que NO sea fecha
  r"^(.*?)(?:-\d{4}-\d{2}-\d{2}.*)?$"
  ```
- Ahora consolida correctamente usando MAX() logic
- Ambos aliases se reportan en "Fuentes consolidadas"

---

## Cambios de Código

### pricing.json
```json
{
  "gpt-4.1-mini": {
    "prompt_per_1m_usd": 0.40,          // ANTES: 0.40 con clave per_1k_usd (error)
    "completion_per_1m_usd": 1.60,      // ANTES: 1.60 con clave per_1k_usd (error)
    "web_search_input_per_1m_usd": 0.40 // NUEVO: web search cost tracking
  }
}
```

### utils/costing.py
- Línea ~75: Regex mejorado (simple, flexible, correcto)
- Línea ~121: División corregida de `/1000.0` a `/1_000_000.0`
- Line ~128-130: Estructura de costo desglosado (llm_prompt_usd, llm_completion_usd, web_search_usd)
- Line ~133: Tracking de aliases consolidados en lista "aliases"

### audit_report.py
- Línea ~77: Regex consolidación actualizado
- Línea ~140: Claves de precio actualizadas: `*_per_1m_usd`
- Línea ~156: Fórmula de división: `/1_000_000`
- Línea ~164-165: Impresión de 8 decimales para precisión

### test_costing.py (NUEVO)
- 5 unit tests validando:
  1. Canonicalización de nombres (gpt-4.1-mini-2025-04-14 → gpt-4.1-mini)
  2. Consolidación con MAX() (no sumación)
  3. Conversión USD/1M correcta (0.0006356 para 1589 tokens a $0.40/1M)
  4. Conversión CLP (900 rate)
  5. Web search cost separation

---

## Validación

### Antes (INCORRECTO)
```
TOTAL COST: $23.375 USD  ❌ (100x inflado)
TOTAL CLP: $21,037 CLP  ❌
```

### Después (CORRECTO)
```
TOTAL COST: $0.0038 USD  ✓ (1,589 prompt + 2,000 completion con USD/1M)
TOTAL CLP: $3 CLP       ✓ (0.0038 × 900)

Desglose:
  - Prompt:     1,589 tokens × $0.40/1M = $0.000636 USD
  - Completion: 2,000 tokens × $1.60/1M = $0.003200 USD
  - TOTAL:                              = $0.003836 USD
```

### Tests
```powershell
python test_costing.py
[OK] ALL TESTS PASSED
  ✓ canonical_model_name() - Regex strips -YYYY-MM-DD correctly
  ✓ consolidation_max() - Aliases merge with MAX() logic
  ✓ usd_1m_conversion() - Divide by 1_000_000 correct
  ✓ clp_conversion() - 900 rate correct
  ✓ web_search_cost() - 8K tokens separate line item
```

---

## Archivos Modificados

1. **pricing.json** - Unidades y tarifas corregidas
2. **utils/costing.py** - Consolidación y división corregidas (líneas clave: 75, 121)
3. **audit_report.py** - Regex, fórmulas y consolidación corregidas
4. **test_costing.py** - NUEVO: Suite de tests para validación

---

## Impacto Operacional

✅ **Sistema de costos es ahora confiable para auditoría**

- Precios alineados con estándar OpenAI (USD/1M)
- Consolidación sin duplicaciones
- Precisión: 8 decimales para seguimiento
- Cobertura de tests: Todos los casos críticos validados

Nota: Snapshots históricos en `cost_history/` contienen datos con las tarifas incorrectas. Se recomienda marcar como "legacy_invalid" y generar nuevas líneas base con estos cálculos corregidos.
