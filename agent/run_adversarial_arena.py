"""
Adversarial Arena CLI Runner
Allows standalone execution of the Good Cop (Builder) vs Bad Cop (Hacker)
adversarial loop on an existing project.
"""

import argparse
import os
import subprocess
import sys
import io
import time
import threading

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from openai import OpenAI
try:
    from agent.adversarial_duel import AdversarialArena, log_arena
except ImportError:
    from adversarial_duel import AdversarialArena, log_arena



def find_python_executable(project_dir: str) -> str:
    """Locates the project's virtualenv python executable or falls back to sys.executable."""
    venv_paths = [
        os.path.join(project_dir, ".venv", "Scripts", "python.exe"),
        os.path.join(project_dir, ".venv", "bin", "python"),
        os.path.join(project_dir, "venv", "Scripts", "python.exe"),
        os.path.join(project_dir, "venv", "bin", "python"),
    ]
    for p in venv_paths:
        if os.path.exists(p):
            return p
    return sys.executable


def drain_stdout(process):
    def _reader():
        try:
            for _ in iter(process.stdout.readline, ''):
                pass
        except Exception:
            pass
    t = threading.Thread(target=_reader, daemon=True)
    t.start()


def start_server(project_dir: str, python_exe: str, app_file: str = "app.py"):
    app_path = os.path.join(project_dir, app_file)
    if not os.path.exists(app_path):
        raise FileNotFoundError(f"Cannot find {app_file} in {project_dir}")
    
    cmd = [python_exe, app_file]
    log_arena(f"Launching application server: {' '.join(cmd)}")
    process = subprocess.Popen(
        cmd,
        cwd=project_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    drain_stdout(process)
    time.sleep(3)
    return process


def stop_server(process):
    if process and process.poll() is None:
        log_arena("Shutting down target server...")
        process.terminate()
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()


def main():
    parser = argparse.ArgumentParser(description="Run Dual-AI Adversarial Combat Arena (Builder vs Hacker)")
    parser.add_argument("--project", default="simple_task_management_app", help="Path to project directory")
    parser.add_argument("--rounds", type=int, default=3, help="Number of adversarial combat rounds")
    parser.add_argument("--model", default="qwen2.5-coder:7b", help="Ollama model name")
    parser.add_argument("--port", type=int, default=5000, help="Target application port")
    args = parser.parse_args()

    project_dir = os.path.abspath(args.project)
    if not os.path.exists(project_dir):
        print(f"❌ Project directory not found: {project_dir}")
        sys.exit(1)

    python_exe = find_python_executable(project_dir)
    try:
        from agent.llm_client import get_llm_client
    except ImportError:
        from llm_client import get_llm_client

    try:
        client, resolved_model = get_llm_client(args.model)
    except Exception as e:
        print(f"❌ Error configuring LLM client: {e}")
        sys.exit(1)

    print(f"🎯 Target Project: {project_dir}")
    print(f"🐍 Python Interpreter: {python_exe}")
    print(f"🤖 Model: {resolved_model}")

    current_process = start_server(project_dir, python_exe)

    def restart_callback():
        nonlocal current_process
        stop_server(current_process)
        time.sleep(1)
        current_process = start_server(project_dir, python_exe)
        return current_process

    try:
        arena = AdversarialArena(client=client, model=args.model, max_rounds=args.rounds)
        arena.conduct_duel(project_dir, restart_server_callback=restart_callback)
    finally:
        stop_server(current_process)


if __name__ == "__main__":
    main()
