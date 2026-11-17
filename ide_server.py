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
import zipfile
import io

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Ensure imports work from agent module
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from agent.adversarial_duel import BuilderAgent, HackerAgent, AdversarialArena
from agent.hacker_suite_generator import scan_flask_endpoints, ADVERSARIAL_PAYLOADS
from agent.run_adversarial_arena import find_python_executable
from agent.main import analyze_requirements, create_project_structure, generate_code
from agent.llm_client import get_llm_client, OLLAMA_BASE_URL


app = FastAPI(title="AEGIS Dual-AI Web IDE")

# Mount web assets
web_dir = os.path.join(current_dir, "web")
app.mount("/static", StaticFiles(directory=web_dir), name="static")

DEFAULT_MODEL = "qwen2.5-coder:7b"

# Active target server process
target_server_process = None
target_server_lock = threading.Lock()


def safe_join(base: str, *parts: str) -> str:
    """
    Safely joins path parts to a base directory and ensures the resulting
    resolved path stays strictly within the base directory to prevent path traversal attacks.
    """
    base = os.path.realpath(base)
    path = os.path.realpath(os.path.join(base, *parts))
    try:
        if os.path.commonpath([path, base]) != base:
            raise HTTPException(status_code=400, detail="Invalid path: Path traversal detected")
    except ValueError:
        # Raised on Windows when paths are on different drives (e.g. C: vs E:)
        raise HTTPException(status_code=400, detail="Invalid path: Cross-drive access detected")
    return path


def ensure_target_server_running(project_dir: str):
    """Ensures the project's application (Flask or Node) is running on port 5000."""
    global target_server_process
    try:
        project_dir = safe_join(current_dir, os.path.relpath(project_dir, current_dir))
    except Exception:
        return

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
    """Discovers available Ollama local models and lists real cloud frontier models."""
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
        {
            "id": "gemini-1.5-flash",
            "name": "Gemini 1.5 Flash (Google)",
            "configured": bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
        },
        {
            "id": "gemini-2.0-flash",
            "name": "Gemini 2.0 Flash (Google)",
            "configured": bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
        },
        {
            "id": "claude-3-5-sonnet-20241022",
            "name": "Claude 3.5 Sonnet (Anthropic)",
            "configured": bool(os.environ.get("ANTHROPIC_API_KEY"))
        },
        {
            "id": "gpt-4o",
            "name": "GPT-4o (OpenAI)",
            "configured": bool(os.environ.get("OPENAI_API_KEY"))
        },
        {
            "id": "gpt-4o-mini",
            "name": "GPT-4o Mini (OpenAI)",
            "configured": bool(os.environ.get("OPENAI_API_KEY"))
        }
    ]

    return {
        "ollama": ollama_models,
        "cloud": [m["id"] for m in cloud_models],
        "cloud_details": cloud_models,
        "selected": ollama_models[0] if ollama_models else "qwen2.5-coder:7b"
    }


@app.get("/api/projects")
async def get_projects():
    """Lists project directories found in workspace."""
    projects = []
    for item in os.listdir(current_dir):
        try:
            full_path = safe_join(current_dir, item)
            if os.path.isdir(full_path) and not item.startswith((".", "_", "agent", "web", "instance", "docs", "tests")):
                if os.path.exists(os.path.join(full_path, "app.py")):
                    projects.append(item)
        except HTTPException:
            continue
    if not projects:
        projects = ["simple_task_management_app"]
    return {"projects": projects}


@app.get("/api/project-files")
async def get_project_files(project: str = Query("simple_task_management_app")):
    """Returns a list of editable project files safely."""
    proj_dir = safe_join(current_dir, project)
    if not os.path.isdir(proj_dir):
        raise HTTPException(status_code=404, detail="Project not found")
    
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
async def get_file_content(project: str = Query("simple_task_management_app"), file: str = Query(...)):
    """Returns the text content of a requested file safely."""
    proj_dir = safe_join(current_dir, project)
    if not os.path.isdir(proj_dir):
        raise HTTPException(status_code=404, detail="Project not found")
    file_path = safe_join(proj_dir, file)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


@app.get("/api/patch-diff", response_class=PlainTextResponse)
async def get_patch_diff(project: str = Query("simple_task_management_app")):
    """Returns the latest unified diff generated by the Builder AI safely."""
    proj_dir = safe_join(current_dir, project)
    if not os.path.isdir(proj_dir):
        raise HTTPException(status_code=404, detail="Project not found")
    diff_file = safe_join(proj_dir, "last_patch_diff.txt")
    if os.path.exists(diff_file):
        with open(diff_file, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    return "# No patches recorded yet."


@app.get("/api/security-audit")
async def get_security_audit(project: str = Query("simple_task_management_app")):
    """Returns the security audit scorecard JSON safely."""
    proj_dir = safe_join(current_dir, project)
    if not os.path.isdir(proj_dir):
        raise HTTPException(status_code=404, detail="Project not found")
    audit_file = safe_join(proj_dir, "security_audit.json")
    if os.path.exists(audit_file):
        with open(audit_file, "r", encoding="utf-8", errors="ignore") as f:
            try:
                return json.load(f)
            except Exception:
                pass
    return {
        "status": "no audit yet",
        "target_project": project,
        "final_shield_health_score": None,
        "audit_verdict": "NO_AUDIT"
    }


@app.get("/api/export-zip")
async def export_project_zip(project: str = Query("simple_task_management_app")):
    """Exports and downloads the fortified application as a clean ZIP archive safely."""
    proj_dir = safe_join(current_dir, project)
    if not os.path.isdir(proj_dir):
        raise HTTPException(status_code=404, detail="Project not found")

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
    proj_dir = safe_join(current_dir, req.project)
    if not os.path.isdir(proj_dir):
        raise HTTPException(status_code=404, detail="Project not found")
    ensure_target_server_running(proj_dir)

    try:
        client, resolved_model = get_llm_client(req.model)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    hacker = HackerAgent(client, model=resolved_model)
    builder = BuilderAgent(client, model=resolved_model)

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

                try:
                    proj_dir = safe_join(current_dir, project_name)
                    if not os.path.isdir(proj_dir):
                        await websocket.send_json({"type": "error", "text": f"Project '{project_name}' not found."})
                        continue
                except HTTPException:
                    await websocket.send_json({"type": "error", "text": "Invalid project path: traversal detected."})
                    continue

                ensure_target_server_running(proj_dir)

                try:
                    client, resolved_model = get_llm_client(model_name)
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "text": f"Model configuration error: {str(e)}"
                    })
                    continue

                hacker = HackerAgent(client, model=resolved_model)
                builder = BuilderAgent(client, model=resolved_model)

                await websocket.send_json({
                    "type": "info",
                    "text": f"⚔️ Dual-AI Arena initiated: Good Cop (Builder) vs Bad Cop (Hacker) using {resolved_model}!"
                })

                total_breaches_count = 0
                verified_patches_count = 0
                unresolved_count = 0

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
                        total_breaches_count += len(breaches)
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

                                # Verify if patch held
                                re_breaches = hacker.run_attack_round(proj_dir, round_tier=r)
                                still_vulnerable = any(rb["type"] == b["type"] for rb in re_breaches)
                                if not still_vulnerable:
                                    verified_patches_count += 1
                                    await websocket.send_json({
                                        "type": "speech",
                                        "speaker": "BUILDER AI",
                                        "text": f"Patch verified! Defense held against re-test.",
                                        "avatar": "🛠️"
                                    })
                                else:
                                    unresolved_count += 1
                                    await websocket.send_json({
                                        "type": "speech",
                                        "speaker": "HACKER AI",
                                        "text": "Haha! Your fix was incomplete, the hole is still there!",
                                        "avatar": "😈"
                                    })
                            else:
                                unresolved_count += 1

                score = 100 if total_breaches_count == 0 else int((verified_patches_count / total_breaches_count) * 100)
                if unresolved_count == 0:
                    await websocket.send_json({
                        "type": "fortified",
                        "score": score,
                        "text": f"Application Fortified! All {verified_patches_count} breach(es) verified and sealed (Score: {score}%)."
                    })
                else:
                    await websocket.send_json({
                        "type": "duel_completed",
                        "score": score,
                        "unresolved": unresolved_count,
                        "text": f"Duel concluded with {unresolved_count} unresolved vulnerability/vulnerabilities (Score: {score}%)."
                    })

            elif action == "start_build":
                prompt = msg.get("prompt", "")
                model_name = msg.get("model", DEFAULT_MODEL)
                
                try:
                    client, resolved_model = get_llm_client(model_name)
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "text": f"Model configuration error: {str(e)}"
                    })
                    continue

                await websocket.send_json({
                    "type": "speech",
                    "speaker": "BUILDER AI",
                    "text": f"Requirement received: '{prompt}'. Synthesizing software architecture & file layout with {resolved_model}...",
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

                hacker = HackerAgent(client, model=resolved_model)
                builder = BuilderAgent(client, model=resolved_model)

                verified_new = 0
                unresolved_new = 0
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
                                re_breaches = hacker.run_attack_round(proj_dir, round_tier=r)
                                if not any(rb["type"] == b["type"] for rb in re_breaches):
                                    verified_new += 1
                                else:
                                    unresolved_new += 1
                            else:
                                unresolved_new += 1

                total_new = verified_new + unresolved_new
                score_new = 100 if total_new == 0 else int((verified_new / total_new) * 100)
                await websocket.send_json({
                    "type": "fortified" if unresolved_new == 0 else "duel_completed",
                    "score": score_new,
                    "text": f"Duel concluded on {project_title} (Shield Score: {score_new}%)."
                })

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
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    print("\n" + "=" * 75)
    print("🚀 AEGIS DUAL-AI WEB IDE IS STARTING")
    print(f"🌐 Open in your browser: http://{host}:{port}")
    print("=" * 75 + "\n")
    uvicorn.run(app, host=host, port=port, log_level="info")
