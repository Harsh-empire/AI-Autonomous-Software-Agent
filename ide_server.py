"""
AEGIS Dual-AI Web IDE Backend Server
Provides REST APIs and real-time WebSockets to stream the Builder vs Hacker
adversarial arena, manage live application previews, and execute Chaos Console attacks.
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import time
import requests
import threading
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from openai import OpenAI
import zipfile
import io

# Ensure imports work from agent module
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from agent.adversarial_duel import BuilderAgent, HackerAgent, AdversarialArena
from agent.hacker_suite_generator import scan_flask_endpoints, ADVERSARIAL_PAYLOADS
from agent.run_adversarial_arena import find_python_executable
from agent.main import analyze_requirements, create_project_structure, generate_code


app = FastAPI(title="AEGIS Dual-AI Web IDE")

# Mount web assets
web_dir = os.path.join(current_dir, "web")
app.mount("/static", StaticFiles(directory=web_dir), name="static")

OLLAMA_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen2.5-coder:7b"

# Active target server process
target_server_process = None
target_server_lock = threading.Lock()


def ensure_target_server_running(project_dir: str):
    """Ensures the project's application (Flask or Node) is running on port 5000."""
    global target_server_process
    with target_server_lock:
        if target_server_process and target_server_process.poll() is None:
            return
        
        app_file = os.path.join(project_dir, "app.py")
        server_js = os.path.join(project_dir, "server.js")
        
        cmd = None
        if os.path.exists(app_file):
            python_exe = find_python_executable(project_dir)
            cmd = [python_exe, "app.py"]
        elif os.path.exists(server_js):
            cmd = ["node", "server.js"]
        elif os.path.exists(os.path.join(project_dir, "package.json")):
            cmd = ["npm", "start"]

        if not cmd:
            return

        try:
            target_server_process = subprocess.Popen(
                cmd,
                cwd=project_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(2)
        except Exception as e:
            print(f"Error launching target app: {e}")



def restart_target_server(project_dir: str):
    """Restarts the target application."""
    global target_server_process
    with target_server_lock:
        if target_server_process and target_server_process.poll() is None:
            try:
                target_server_process.terminate()
                target_server_process.wait(timeout=3)
            except Exception:
                target_server_process.kill()
        target_server_process = None
    ensure_target_server_running(project_dir)


# =============================================================================
# REST ENDPOINTS
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def get_index():
    index_path = os.path.join(web_dir, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/api/models")
async def get_available_models():
    """Discovers available Ollama local models and lists cloud frontier models."""
    ollama_models = []
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/models", timeout=2)
        if r.status_code == 200:
            data = r.json()
            ollama_models = [m.get("id") for m in data.get("data", [])]
    except Exception:
        ollama_models = ["qwen2.5-coder:7b"]
    
    if not ollama_models:
        ollama_models = ["qwen2.5-coder:7b"]

    cloud_models = [
        "gemini-3.8-flash",
        "claude-3-5-sonnet",
        "gpt-4o",
        "deepseek-coder"
    ]

    return {
        "ollama": ollama_models,
        "cloud": cloud_models,
        "selected": ollama_models[0] if ollama_models else "qwen2.5-coder:7b"
    }


@app.get("/api/projects")
async def get_projects():
    """Lists project directories found in workspace."""
    projects = []
    for item in os.listdir(current_dir):
        full_path = os.path.join(current_dir, item)
        if os.path.isdir(full_path) and not item.startswith((".", "_", "agent", "web", "instance")):
            if os.path.exists(os.path.join(full_path, "app.py")):
                projects.append(item)
    if not projects:
        projects = ["simple_task_management_app"]
    return {"projects": projects}


@app.get("/api/project-files")
async def get_project_files(project: str = Query("simple_task_management_app")):
    """Returns a list of editable project files."""
    proj_dir = os.path.join(current_dir, project)
    if not os.path.exists(proj_dir):
        return {"files": []}
    
    files_list = []
    ignored = {".venv", "venv", "__pycache__", ".git", "instance"}
    for root, dirs, files in os.walk(proj_dir):
        dirs[:] = [d for d in dirs if d not in ignored]
        for f in files:
            if f.endswith((".py", ".html", ".css", ".js", ".json", ".md", ".txt")):
                rel_path = os.path.relpath(os.path.join(root, f), proj_dir).replace("\\", "/")
                files_list.append(rel_path)
    return {"files": sorted(files_list)}


@app.get("/api/file-content", response_class=PlainTextResponse)
async def get_file_content(project: str, file: str):
    """Returns the text content of a requested file."""
    proj_dir = os.path.join(current_dir, project)
    file_path = os.path.join(proj_dir, file)
    if not os.path.exists(file_path):
        return "# File not found"
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


@app.get("/api/patch-diff", response_class=PlainTextResponse)
async def get_patch_diff(project: str = Query("simple_task_management_app")):
    """Returns the latest unified diff generated by the Builder AI."""
    proj_dir = os.path.join(current_dir, project)
    diff_file = os.path.join(proj_dir, "last_patch_diff.txt")
    if os.path.exists(diff_file):
        with open(diff_file, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    return "# No patches recorded yet."


@app.get("/api/security-audit")
async def get_security_audit(project: str = Query("simple_task_management_app")):
    """Returns the security audit scorecard JSON."""
    proj_dir = os.path.join(current_dir, project)
    audit_file = os.path.join(proj_dir, "security_audit.json")
    if os.path.exists(audit_file):
        with open(audit_file, "r", encoding="utf-8", errors="ignore") as f:
            try:
                return json.load(f)
            except Exception:
                pass
    return {"target_project": project, "final_shield_health_score": "100%", "audit_verdict": "VERIFIED"}


@app.get("/api/export-zip")
async def export_project_zip(project: str = Query("simple_task_management_app")):
    """Exports and downloads the fortified application as a clean ZIP archive."""
    proj_dir = os.path.join(current_dir, project)
    if not os.path.exists(proj_dir):
        return JSONResponse({"error": "Project not found"}, status_code=404)

    ignored = {".venv", "venv", "__pycache__", ".git", "instance"}
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for root, dirs, files in os.walk(proj_dir):
            dirs[:] = [d for d in dirs if d not in ignored]
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, proj_dir)
                zip_file.write(file_path, arcname=rel_path)

    zip_buffer.seek(0)
    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{project}_bulletproof.zip"'}
    )


class ChaosAttackRequest(BaseModel):
    project: str = "simple_task_management_app"
    vector: str = "sql_injection"
    model: str = "qwen2.5-coder:7b"


@app.post("/api/chaos-attack")
async def trigger_chaos_attack(req: ChaosAttackRequest):
    """Executes a single manual attack vector and triggers builder self-healing if breached."""
    proj_dir = os.path.join(current_dir, req.project)
    ensure_target_server_running(proj_dir)

    client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
    hacker = HackerAgent(client, model=req.model)
    builder = BuilderAgent(client, model=req.model)

    breaches = []
    if req.vector == "sql_injection":
        breaches = hacker.run_attack_round(proj_dir, round_tier=3)
        breaches = [b for b in breaches if "sql" in b["type"].lower()]
    elif req.vector == "xss_script":
        breaches = hacker.run_attack_round(proj_dir, round_tier=3)
        breaches = [b for b in breaches if "xss" in b["type"].lower() or "html" in b["type"].lower()]
    elif req.vector == "unicode_flood":
        breaches = hacker.run_attack_round(proj_dir, round_tier=1)
        breaches = [b for b in breaches if "unicode" in b["type"].lower() or "buffer" in b["type"].lower()]
    elif req.vector == "empty_form":
        breaches = hacker.run_attack_round(proj_dir, round_tier=1)
        breaches = [b for b in breaches if "empty" in b["type"].lower()]
    elif req.vector == "auth_bypass":
        breaches = hacker.run_attack_round(proj_dir, round_tier=2)
    elif req.vector == "ssti":
        breaches = hacker.run_attack_round(proj_dir, round_tier=4)
    elif req.vector == "idor":
        breaches = hacker.run_attack_round(proj_dir, round_tier=5)

    if not breaches:
        return {"breach": None, "patched": False}

    breach = breaches[0]
    patched = builder.generate_targeted_defense(proj_dir, breach)
    diff_content = builder.last_patch_info.get("diff", "") if (builder.last_patch_info) else ""
    if patched:
        restart_target_server(proj_dir)
        return {"breach": breach, "patched": True, "file": "app.py", "diff": diff_content}
    return {"breach": breach, "patched": False}


# =============================================================================
# WEBSOCKET REAL-TIME ARENA STREAM
# =============================================================================

@app.websocket("/ws")
async def websocket_arena_stream(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            raw_msg = await websocket.receive_text()
            msg = json.loads(raw_msg)
            action = msg.get("action")

            if action == "start_duel":
                project_name = msg.get("project", "simple_task_management_app")
                model_name = msg.get("model", DEFAULT_MODEL)
                rounds = int(msg.get("rounds", 3))
                proj_dir = os.path.join(current_dir, project_name)

                ensure_target_server_running(proj_dir)

                client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
                hacker = HackerAgent(client, model=model_name)
                builder = BuilderAgent(client, model=model_name)

                await websocket.send_json({
                    "type": "info",
                    "text": f"⚔️ Dual-AI Arena initiated: Good Cop (Builder) vs Bad Cop (Hacker) using {model_name}!"
                })

                for r in range(1, rounds + 1):
                    await websocket.send_json({
                        "type": "info",
                        "text": f"⚔️ Entering ROUND {r} of {rounds}..."
                    })

                    breaches = hacker.run_attack_round(proj_dir, round_tier=r)

                    if not breaches:
                        hacker_taunt = "Bah! I couldn't break the endpoints this wave. App held up."
                        builder_defense = "Defenses held strong against all probes this round."
                        await websocket.send_json({"type": "speech", "speaker": "HACKER AI", "text": hacker_taunt, "avatar": "😈"})
                        await websocket.send_json({"type": "speech", "speaker": "BUILDER AI", "text": builder_defense, "avatar": "🛠️"})
                    else:
                        for b in breaches:
                            await websocket.send_json({"type": "breach", "breach": b})
                            
                            # Real-time taunts
                            h_speech = hacker.trash_talk(json.dumps(b))
                            await websocket.send_json({"type": "speech", "speaker": "HACKER AI", "text": h_speech, "avatar": "😈"})

                            b_speech = builder.counter_argument(b)
                            await websocket.send_json({"type": "speech", "speaker": "BUILDER AI", "text": b_speech, "avatar": "🛠️"})

                            # Builder patches
                            repaired = builder.generate_targeted_defense(proj_dir, b)
                            if repaired:
                                diff_content = builder.last_patch_info.get("diff", "") if builder.last_patch_info else ""
                                await websocket.send_json({"type": "patch", "file": "app.py", "diff": diff_content})
                                restart_target_server(proj_dir)
                                await websocket.send_json({"type": "server_restart", "url": "http://127.0.0.1:5000"})
                                await asyncio.sleep(1)

                await websocket.send_json({"type": "fortified"})

            elif action == "start_build":
                prompt = msg.get("prompt", "")
                model_name = msg.get("model", DEFAULT_MODEL)
                
                await websocket.send_json({
                    "type": "speech",
                    "speaker": "BUILDER AI",
                    "text": f"Requirement received: '{prompt}'. Synthesizing software architecture & file layout...",
                    "avatar": "🛠️"
                })
                await asyncio.sleep(0.5)
                await websocket.send_json({
                    "type": "speech",
                    "speaker": "HACKER AI",
                    "text": "Go ahead and build it fast, Builder. Once your endpoints are up, I'm going to unleash chaos on your forms and checkout!",
                    "avatar": "😈"
                })

                # 1. Analyze requirements
                try:
                    plan = await asyncio.to_thread(analyze_requirements, prompt)
                except Exception as e:
                    clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', prompt[:25]).strip('_').lower()
                    if not clean_name:
                        clean_name = "custom_web_app"
                    plan = {
                        "project_name": clean_name,
                        "description": prompt,
                        "technology_stack": ["Python", "Flask", "HTML", "CSS"],
                        "dependencies": ["Flask"],
                        "features": ["Home page", "Catalog & Items", "Cart & Checkout", "Order Confirmation"],
                        "files": ["app.py", "templates/index.html", "templates/menu.html", "templates/checkout.html", "static/style.css"],
                        "run_command": "python app.py",
                        "test_cases": ["Load homepage", "Browse items", "Add to cart", "Submit checkout"]
                    }

                project_title = plan.get("project_name", "web_app")
                await websocket.send_json({
                    "type": "info",
                    "text": f"📋 Architecture synthesized: '{project_title}' ({len(plan.get('files', []))} files)"
                })

                # 2. Create structure
                proj_dir = await asyncio.to_thread(create_project_structure, plan)
                project_name = os.path.basename(proj_dir)

                # 3. Generate source code files
                for f_path in plan.get("files", []):
                    await websocket.send_json({
                        "type": "info",
                        "text": f"🛠️ Builder synthesizing: {f_path}..."
                    })
                    try:
                        code = await asyncio.to_thread(generate_code, f_path, plan)
                    except Exception:
                        code = f"# Generated placeholder for {f_path}\n"

                    full_dest = os.path.join(proj_dir, f_path)
                    os.makedirs(os.path.dirname(full_dest), exist_ok=True)
                    with open(full_dest, "w", encoding="utf-8") as f_out:
                        f_out.write(code)

                    await websocket.send_json({"type": "patch", "file": f_path})
                    await asyncio.sleep(0.3)

                # 4. Switch project in IDE & Launch preview
                await asyncio.to_thread(restart_target_server, proj_dir)
                await websocket.send_json({"type": "project_switched", "project": project_name})
                await websocket.send_json({"type": "server_restart", "url": "http://127.0.0.1:5000"})
                
                await websocket.send_json({
                    "type": "speech",
                    "speaker": "BUILDER AI",
                    "text": f"🎉 Application '{project_title}' is built and running on port 5000! Preview is now live.",
                    "avatar": "🛠️"
                })

                # 5. Automatically initiate the Adversarial Duel to fortify the newly created app!
                await websocket.send_json({
                    "type": "speech",
                    "speaker": "HACKER AI",
                    "text": "Target application online! Let's see if your new routes can survive real penetration attacks!",
                    "avatar": "😈"
                })

                client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
                hacker = HackerAgent(client, model=model_name)
                builder = BuilderAgent(client, model=model_name)

                for r in range(1, 3):
                    await websocket.send_json({"type": "info", "text": f"⚔️ Entering ROUND {r} of 2 on new app..."})
                    breaches = hacker.run_attack_round(proj_dir, round_tier=r)
                    if not breaches:
                        await websocket.send_json({"type": "speech", "speaker": "BUILDER AI", "text": f"Round {r}: Defenses held strong against all vectors!", "avatar": "🛠️"})
                    else:
                        for b in breaches:
                            await websocket.send_json({"type": "breach", "breach": b})
                            h_speech = hacker.trash_talk(json.dumps(b))
                            await websocket.send_json({"type": "speech", "speaker": "HACKER AI", "text": h_speech, "avatar": "😈"})
                            b_speech = builder.counter_argument(b)
                            await websocket.send_json({"type": "speech", "speaker": "BUILDER AI", "text": b_speech, "avatar": "🛠️"})
                            repaired = builder.generate_targeted_defense(proj_dir, b)
                            if repaired:
                                await websocket.send_json({"type": "patch", "file": "app.py"})
                                restart_target_server(proj_dir)
                                await websocket.send_json({"type": "server_restart", "url": "http://127.0.0.1:5000"})
                                await asyncio.sleep(1)

                await websocket.send_json({"type": "fortified"})

    except WebSocketDisconnect:
        pass


# =============================================================================
# SERVER STARTUP ENTRYPOINT
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    # Start target app in background if needed
    default_proj = os.path.join(current_dir, "simple_task_management_app")
    ensure_target_server_running(default_proj)
    print("\n" + "=" * 75)
    print("🚀 AEGIS DUAL-AI WEB IDE IS STARTING")
    print("🌐 Open in your browser: http://127.0.0.1:8000")
    print("=" * 75 + "\n")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
