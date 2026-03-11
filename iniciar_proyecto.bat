@echo off
echo Iniciando Agente de Apuestas IA (Streamlit)...
cd /d "%~dp0"
if not exist "venv\Scripts\activate" (
    echo [ERROR] No se encontró el entorno virtual en 'venv'.
    echo Por favor, asegúrate de que el entorno virtual esté correctamente configurado.
    pause
    exit /b
)
call venv\Scripts\activate
streamlit run app.py
pause
