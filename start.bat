@echo off
setlocal

echo ===========================================================================
echo                  AEGIS Dual-AI Web IDE - Launcher
echo ===========================================================================

REM 1. Check Python installation
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python was not found in PATH. Please install Python 3.10+
    pause
    exit /b 1
)

REM 2. Check Ollama connectivity
curl -s http://localhost:11434/ >nul 2>nul
if %errorlevel% neq 0 (
    echo [WARNING] Ollama is not running on http://localhost:11434.
    echo Please start Ollama with 'ollama serve' or start the Ollama desktop app.
    echo Default model required: ollama pull qwen2.5-coder:7b
    echo.
) else (
    echo [OK] Ollama is running on localhost:11434.
)

REM 3. Activate venv if present
if exist ".venv\Scripts\activate.bat" (
    echo [INFO] Activating virtual environment .venv...
    call .venv\Scripts\activate.bat
)

REM 4. Launch AEGIS IDE server
echo [INFO] Starting AEGIS Web IDE on http://127.0.0.1:8000...
python ide_server.py

endlocal
