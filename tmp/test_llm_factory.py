import os
import json
from pydantic import BaseModel, Field
from utils.llm_factory import get_llm
from langchain_core.tools import tool

class AnalisisPartido(BaseModel):
    resultado: str = Field(description="El resultado del partido")
    confianza: float = Field(description="Nivel de confianza entre 0 y 1")

@tool
def sumar(a: int, b: int) -> int:
    """Suma dos números."""
    return a + b

def test_mode(mode: str):
    print(f"\n--- PROBANDO MODO: {mode} ---")
    os.environ["EXPENSIVE_MODE"] = mode
    
    llm = get_llm(temperature=0)
    print(f"Instancia generada: {type(llm).__name__}")
    
    # 1. Test Invocación simple
    resp = llm.invoke("Di hola muy corto")
    print(f"Simple invoke OK: {resp.content}")
    
    # 2. Test bind_tools
    llm_with_tools = llm.bind_tools([sumar])
    resp_tools = llm_with_tools.invoke("Cuánto es 2 + 2?")
    print(f"Tools bound OK. Tool calls generadas: {resp_tools.tool_calls}")
    
    # 3. Test structured output
    llm_structured = llm.with_structured_output(AnalisisPartido)
    resp_struct = llm_structured.invoke("El Real Madrid ganará 2-0 con alta seguridad")
    print(f"Structured output OK: Resultado='{resp_struct.resultado}', Confianza={resp_struct.confianza}")
    
print("Iniciando pruebas de humo...")
# Asegurar apiKey para Gemini
if not os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
    print("WARNING: SETEANDO GOOGLE_API_KEY FALSO PARA DEBUG (no funcionará HTTP real si no está exportada)")

try:
    test_mode("true")
except Exception as e:
    print(f"Error en modo CARO: {e}")

try:
    test_mode("false")
except Exception as e:
    print(f"Error en modo ECONOMICO: {e}")
