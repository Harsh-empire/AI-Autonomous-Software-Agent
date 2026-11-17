#!/usr/bin/env bash
set -e

echo "==========================================================================="
echo "                 AEGIS Dual-AI Web IDE - Launcher (Unix)                   "
echo "==========================================================================="

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 could not be found. Please install Python 3.10+"
    exit 1
fi

# Check Ollama
if curl -s http://localhost:11434/ > /dev/null; then
    echo "[OK] Ollama is running on localhost:11434."
else
    echo "[WARNING] Ollama is not detected at http://localhost:11434."
    echo "Start it via: ollama serve"
    echo "Pull the default model via: ollama pull qwen2.5-coder:7b"
fi

# Activate venv if exists
if [ -f ".venv/bin/activate" ]; then
    echo "[INFO] Activating .venv..."
    source .venv/bin/activate
fi

# Start IDE server
echo "[INFO] Starting AEGIS Web IDE on http://127.0.0.1:8000..."
python3 ide_server.py
