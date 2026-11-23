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
import shutil

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Ensure imports work from agent module
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from agent.adversarial_duel import (
    BuilderAgent, HackerAgent, AdversarialArena, verify_patch, save_verification_artifacts,
)
from agent.hacker_suite_generator import scan_flask_endpoints, ADVERSARIAL_PAYLOADS
from agent.run_adversarial_arena import find_python_executable
from agent.main import analyze_requirements, create_project_structure, generate_code
from agent.llm_client import get_llm_client, OLLAMA_BASE_URL, format_llm_error
from agent.playbook import PlaybookManager
from agent.builder_pipeline import (
    validate_plan,
    get_unique_project_dir,
    check_python_syntax,
    check_jinja_syntax,
    check_missing_imports,
    smoke_test_app,
    start_and_wait_for_server,
    get_log_tail,
    identify_failing_file,
    rollback_file,
    remove_backup,
    repair_file_with_llm,
    kill_port_listener,
)


app = FastAPI(title="AEGIS Dual-AI Web IDE")

# Mount web assets
web_dir = os.path.join(current_dir, "web")
app.mount("/static", StaticFiles(directory=web_dir), name="static")

DEFAULT_MODEL = "qwen2.5-coder:7b"

# Active target server process
target_server_process = None
target_server_lock = threading.Lock()
current_running_project_dir: Optional[str] = None


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


def get_allowed_projects() -> List[str]:
    """Scans and returns the allowed project names from examples/ and root workspace."""
    projects = set()
    # 1. Check examples directory
    examples_dir = os.path.join(current_dir, "examples")
    if os.path.isdir(examples_dir):
        for item in os.listdir(examples_dir):
            p_dir = os.path.join(examples_dir, item)
            if os.path.isdir(p_dir) and not item.startswith((".", "_")):
                if os.path.exists(os.path.join(p_dir, "app.py")) or os.path.exists(os.path.join(p_dir, "package.json")):
                    projects.add(item)
    # 2. Check root workspace for created projects
    for item in os.listdir(current_dir):
        p_dir = os.path.join(current_dir, item)
        if os.path.isdir(p_dir) and not item.startswith((".", "_", "agent", "web", "instance", "docs", "tests", "examples", "bench", "playbook")):
            if os.path.exists(os.path.join(p_dir, "app.py")) or os.path.exists(os.path.join(p_dir, "package.json")):
                projects.add(item)
    if not projects:
        projects.add("simple_task_management_app")
    return sorted(list(projects))


def resolve_project_dir(project: str) -> str:
    """
    Validates project is in the allowed projects list and returns its safe path.
    Raises HTTPException(400) if project leaves base or is not in allowed projects list.
    """
    if not project or ".." in project or "/" in project or "\\" in project:
        raise HTTPException(status_code=400, detail="Invalid path: Path traversal detected")

    allowed = get_allowed_projects()
    if project not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid project: '{project}' is not in allowed projects list")

    # Check examples/
    examples_path = os.path.join(current_dir, "examples", project)
    if os.path.isdir(examples_path):
        return safe_join(os.path.join(current_dir, "examples"), project)

    # Check root workspace
    root_path = os.path.join(current_dir, project)
    if os.path.isdir(root_path):
        return safe_join(current_dir, project)

    raise HTTPException(status_code=404, detail=f"Project '{project}' directory not found")


def ensure_target_server_running(project_dir: str):
    """Ensures the project's application (Flask or Node) is running on port 5000."""
    global target_server_process, current_running_project_dir
    with target_server_lock:
        norm_dir = os.path.normpath(os.path.abspath(project_dir))
        if target_server_process and target_server_process.poll() is None:
            if current_running_project_dir == norm_dir:
                return
            # Running a different project! Terminate it.
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(target_server_process.pid)], capture_output=True)
                else:
                    target_server_process.terminate()
            except Exception:
                pass
            target_server_process = None
            try:
                kill_port_listener(5000)
            except Exception:
                pass

        app_file = os.path.join(norm_dir, "app.py")
        server_js = os.path.join(norm_dir, "server.js")
        
        cmd = None
        if os.path.exists(app_file):
            python_exe = find_python_executable(norm_dir)
            cmd = [python_exe, "app.py"]
        elif os.path.exists(server_js):
            cmd = ["node", "server.js"]
        elif os.path.exists(os.path.join(norm_dir, "package.json")):
            cmd = ["npm", "start"]

        if not cmd:
            return

        try:
            target_server_process = subprocess.Popen(
                cmd,
                cwd=norm_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            current_running_project_dir = norm_dir
            time.sleep(2)
        except Exception as e:
            print(f"Error launching target app: {e}")


def stop_target_server():
    """Stops the target application if running."""
    global target_server_process, current_running_project_dir
    with target_server_lock:
        if target_server_process and target_server_process.poll() is None:
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(target_server_process.pid)], capture_output=True)
                else:
                    target_server_process.terminate()
                target_server_process.wait(timeout=3)
            except Exception:
                try:
                    target_server_process.kill()
                except Exception:
                    pass
        target_server_process = None
        current_running_project_dir = None
        try:
            kill_port_listener(5000)
        except Exception:
            pass


def restart_target_server(project_dir: str):
    """Restarts the target application."""
    stop_target_server()
    ensure_target_server_running(project_dir)


class BuildSession:
    def __init__(self):
        self.is_running: bool = False
        self.task: Optional[asyncio.Task] = None
        self.cancelled: bool = False
        self.project_dir: Optional[str] = None
        self.created_files: List[str] = []


active_build = BuildSession()
active_duel_running = False


# =============================================================================
# REST ENDPOINTS
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint for Docker and monitoring."""
    return {"status": "ok", "service": "aegis-web-ide"}


@app.get("/", response_class=HTMLResponse)
async def get_index():
    index_path = os.path.join(web_dir, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/api/models")
async def get_available_models():
    """Discovers available local Ollama models. Only Ollama models are usable."""
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

    return {
        "ollama": ollama_models,
        "cloud": [],
        "selected": ollama_models[0] if ollama_models else "qwen2.5-coder:7b"
    }


@app.get("/api/ollama/status")
async def get_ollama_status(model: Optional[str] = Query(None)):
    """Health check for Ollama: checks /api/tags (pulled) and /api/ps (loaded)."""
    base_url = OLLAMA_BASE_URL.replace("/v1", "").rstrip("/")
    hint = "The first request loads the model into memory and can take several minutes on CPU."
    try:
        tags_resp = await asyncio.to_thread(requests.get, f"{base_url}/api/tags", timeout=3)
        if tags_resp.status_code != 200:
            return JSONResponse({
                "online": False,
                "model_pulled": False,
                "model_loaded": False,
                "error": f"Ollama returned HTTP {tags_resp.status_code}",
                "hint": hint
            })
        models_data = tags_resp.json().get("models", [])
        installed_names = [m.get("name", "") for m in models_data]

        loaded_names = []
        try:
            ps_resp = await asyncio.to_thread(requests.get, f"{base_url}/api/ps", timeout=3)
            if ps_resp.status_code == 200:
                loaded_models = ps_resp.json().get("models", [])
                loaded_names = [m.get("name", "") for m in loaded_models]
        except Exception:
            pass

        target_model = model or DEFAULT_MODEL
        def matches_model(target, cand):
            if not target or not cand:
                return False
            t_base = target.split(":")[0]
            c_base = cand.split(":")[0]
            return target == cand or t_base == c_base or target in cand or cand in target

        pulled = any(matches_model(target_model, name) for name in installed_names)
        loaded = any(matches_model(target_model, name) for name in loaded_names)

        return JSONResponse({
            "online": True,
            "model": target_model,
            "model_pulled": pulled,
            "model_loaded": loaded,
            "installed_models": installed_names,
            "loaded_models": loaded_names,
            "hint": hint
        })
    except Exception:
        return JSONResponse({
            "online": False,
            "model_pulled": False,
            "model_loaded": False,
            "error": f"Ollama unreachable at {base_url}. Start it with 'ollama serve'.",
            "hint": hint
        })


@app.get("/api/projects")
async def get_projects():
    """Lists allowed project directories."""
    return {"projects": get_allowed_projects()}


@app.get("/api/project-files")
async def get_project_files(project: str = Query("simple_task_management_app")):
    """Returns a list of editable project files safely."""
    proj_dir = resolve_project_dir(project)
    
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
    proj_dir = resolve_project_dir(project)
    file_path = safe_join(proj_dir, file)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


@app.get("/api/patch-diff", response_class=PlainTextResponse)
async def get_patch_diff(project: str = Query("simple_task_management_app")):
    """Returns the latest unified diff generated by the Builder AI safely."""
    proj_dir = resolve_project_dir(project)
    diff_file = safe_join(proj_dir, "last_patch_diff.txt")
    if os.path.exists(diff_file):
        with open(diff_file, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    return "# No patches recorded yet."


@app.get("/api/security-audit")
async def get_security_audit(project: str = Query("simple_task_management_app")):
    """Returns the security audit scorecard JSON safely. Never returns a fake default."""
    proj_dir = resolve_project_dir(project)
    audit_file = safe_join(proj_dir, "security_audit.json")
    if os.path.exists(audit_file):
        with open(audit_file, "r", encoding="utf-8", errors="ignore") as f:
            try:
                return json.load(f)
            except Exception:
                pass
    return JSONResponse(
        status_code=404,
        content={"status": "no audit yet", "target_project": project}
    )


@app.get("/api/export-zip")
async def export_project_zip(project: str = Query("simple_task_management_app")):
    """Exports and downloads the application as a clean ZIP archive safely."""
    proj_dir = resolve_project_dir(project)

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
        headers={"Content-Disposition": f'attachment; filename="{project}.zip"'}
    )


class SelectProjectRequest(BaseModel):
    project: str


@app.post("/api/select-project")
async def select_project(req: SelectProjectRequest):
    """Switches the active project and restarts its application on port 5000."""
    proj_dir = resolve_project_dir(req.project)
    restart_target_server(proj_dir)
    return {"status": "ok", "project": req.project}


class ChaosAttackRequest(BaseModel):
    project: str = "simple_task_management_app"
    vector: str = "sql_injection"
    model: str = "qwen2.5-coder:7b"


@app.post("/api/chaos-attack")
async def trigger_chaos_attack(req: ChaosAttackRequest):
    """Executes a single manual attack vector and triggers builder self-healing if breached."""
    proj_dir = resolve_project_dir(req.project)
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
    baseline = hacker.capture_baseline(breach.get("route", "/"))
    patched = builder.generate_targeted_defense(proj_dir, breach)
    diff_content = builder.last_patch_info.get("diff", "") if (builder.last_patch_info) else ""
    if patched:
        restart_target_server(proj_dir)
        await asyncio.sleep(1)
        verified, reason = verify_patch(hacker, proj_dir, breach, baseline)
        if verified:
            save_verification_artifacts(proj_dir, breach, builder=builder, baseline=baseline)
        elif builder.rollback_last_patch():
            restart_target_server(proj_dir)
        return {"breach": breach, "patched": True, "verified": verified, "reason": reason,
                "rolled_back": not verified, "file": "app.py", "diff": diff_content}
    return {"breach": breach, "patched": False}


# =============================================================================
# DEFENSE PLAYBOOK ENDPOINTS
# =============================================================================

@app.get("/api/playbook")
async def get_playbook_entries():
    """Lists verified defense playbook entries."""
    pm = PlaybookManager()
    return {"entries": pm.list_entries(include_disabled=True), "enabled": pm.is_enabled()}


@app.post("/api/playbook/{entry_id}/toggle")
async def toggle_playbook_entry(entry_id: str, enabled: bool = Query(...)):
    """Enables or disables a verified playbook pattern."""
    pm = PlaybookManager()
    success = pm.set_entry_enabled(entry_id, enabled)
    if not success:
        raise HTTPException(status_code=404, detail="Playbook entry not found")
    return {"status": "updated", "id": entry_id, "enabled": enabled}


@app.delete("/api/playbook/{entry_id}")
async def delete_playbook_entry(entry_id: str):
    """Deletes a playbook entry permanently."""
    pm = PlaybookManager()
    success = pm.delete_entry(entry_id)
    if not success:
        raise HTTPException(status_code=404, detail="Playbook entry not found")
    return {"status": "deleted", "id": entry_id}


# =============================================================================
# BUILDER PIPELINE EXECUTION
# =============================================================================

async def run_builder_pipeline(websocket: WebSocket, prompt: str, client: Any, resolved_model: str):
    global target_server_process, active_build, current_running_project_dir
    start_time = time.time()
    proj_dir = None
    project_title = ""
    current_stage = "analyze"
    heartbeat_task = None

    async def heartbeat_loop():
        while True:
            await asyncio.sleep(5)
            if not active_build.is_running or active_build.cancelled:
                break
            elapsed = round(time.time() - start_time, 1)
            try:
                await websocket.send_json({
                    "type": "heartbeat",
                    "stage": current_stage,
                    "elapsed": elapsed,
                    "text": f"Still generating in stage '{current_stage}' (local CPU inference may take several minutes)..."
                })
            except Exception:
                break

    heartbeat_task = asyncio.create_task(heartbeat_loop())

    try:
        await websocket.send_json({
            "type": "speech",
            "speaker": "BUILDER AI",
            "text": f"Requirement received: '{prompt}'. Synthesizing software architecture & file layout with {resolved_model}...",
            "avatar": "🛠️"
        })

        # STAGE 1: ANALYZE
        current_stage = "analyze"
        elapsed = round(time.time() - start_time, 1)
        await websocket.send_json({
            "type": "build_progress",
            "stage": "analyze",
            "elapsed": elapsed,
            "text": "Synthesizing software architecture..."
        })

        try:
            plan = await asyncio.to_thread(analyze_requirements, prompt, client=client, model=resolved_model)
        except Exception as exc:
            err_msg = format_llm_error(exc, resolved_model)
            await websocket.send_json({"type": "error", "text": err_msg})
            return

        if active_build.cancelled:
            return

        # STAGE 2: PLAN VALIDATION & FOLDER SETUP
        current_stage = "plan"
        elapsed = round(time.time() - start_time, 1)
        await websocket.send_json({
            "type": "build_progress",
            "stage": "plan",
            "elapsed": elapsed,
            "text": "Validating architecture plan..."
        })

        ok, plan_err = validate_plan(plan)
        if not ok:
            await websocket.send_json({
                "type": "error",
                "text": f"Plan validation error: {plan_err}"
            })
            return

        raw_name = plan.get("project_name", "web_app")
        project_title = get_unique_project_dir(raw_name, base_dir=current_dir)
        proj_dir = os.path.join(current_dir, project_title)
        active_build.project_dir = proj_dir

        # Create project folder structure
        plan["project_name"] = project_title
        await asyncio.to_thread(create_project_structure, plan, base_dir=current_dir)

        # Notify UI that folder exists so file tree can switch live
        await websocket.send_json({
            "type": "build_folder_created",
            "project": project_title,
            "files": plan.get("files", [])
        })

        # STAGE 3: CODE GENERATION
        files = plan.get("files", [])
        total_files = len(files)
        for idx, f_path in enumerate(files, start=1):
            if active_build.cancelled:
                return

            current_stage = f"generate {idx}/{total_files}"
            elapsed = round(time.time() - start_time, 1)
            await websocket.send_json({
                "type": "build_progress",
                "stage": current_stage,
                "file": f_path,
                "elapsed": elapsed,
                "text": f"Generating {f_path} ({idx}/{total_files})..."
            })

            try:
                code = await asyncio.to_thread(generate_code, f_path, plan, client=client, model=resolved_model)
            except Exception as exc:
                err_msg = format_llm_error(exc, resolved_model)
                if proj_dir and os.path.exists(proj_dir):
                    shutil.rmtree(proj_dir, ignore_errors=True)
                await websocket.send_json({
                    "type": "error",
                    "text": f"Failed generating {f_path}: {err_msg}"
                })
                return

            full_dest = os.path.join(proj_dir, f_path)
            os.makedirs(os.path.dirname(full_dest), exist_ok=True)
            with open(full_dest, "w", encoding="utf-8") as f_out:
                f_out.write(code)

            active_build.created_files.append(f_path)
            await websocket.send_json({
                "type": "patch",
                "file": f_path,
                "project": project_title
            })
            await asyncio.sleep(0.1)

        if active_build.cancelled:
            return

        # STAGE 4: CHECK (Syntax & Missing Imports)
        current_stage = "check"
        elapsed = round(time.time() - start_time, 1)
        await websocket.send_json({
            "type": "build_progress",
            "stage": "check",
            "elapsed": elapsed,
            "text": "Verifying syntax and dependencies..."
        })

        for f_path in files:
            if f_path.endswith(".py"):
                full_dest = os.path.join(proj_dir, f_path)
                ok, syn_err = check_python_syntax(full_dest)
                if not ok:
                    await websocket.send_json({
                        "type": "error",
                        "text": f"Syntax error in generated file '{f_path}': {syn_err}"
                    })
                    return

        templates_dir = os.path.join(proj_dir, "templates")
        if os.path.isdir(templates_dir):
            for t_file in os.listdir(templates_dir):
                if t_file.endswith(".html"):
                    ok, j_err = check_jinja_syntax(os.path.join(templates_dir, t_file))
                    if not ok:
                        await websocket.send_json({
                            "type": "error",
                            "text": f"Template syntax error in '{t_file}': {j_err}"
                        })
                        return

        missing_pkgs = check_missing_imports(proj_dir)
        if missing_pkgs:
            await websocket.send_json({
                "type": "missing_dependencies",
                "packages": missing_pkgs,
                "text": f"Build requires packages that are not installed: {', '.join(missing_pkgs)}."
            })
            return

        if active_build.cancelled:
            return

        # STAGE 5 & 6: START & SMOKE TEST
        current_stage = "start"
        elapsed = round(time.time() - start_time, 1)
        await websocket.send_json({
            "type": "build_progress",
            "stage": "start",
            "elapsed": elapsed,
            "text": "Starting application server..."
        })

        stop_target_server()

        start_ok, proc, start_err = await asyncio.to_thread(start_and_wait_for_server, proj_dir, 5000, 20.0)
        needs_repair = False
        failure_details = ""

        if not start_ok:
            needs_repair = True
            failure_details = start_err
        else:
            target_server_process = proc
            current_stage = "smoke"
            elapsed = round(time.time() - start_time, 1)
            await websocket.send_json({
                "type": "build_progress",
                "stage": "smoke",
                "elapsed": elapsed,
                "text": "Running smoke tests on routes..."
            })
            smoke_ok, smoke_err = await asyncio.to_thread(smoke_test_app, proj_dir, "http://127.0.0.1:5000")
            if not smoke_ok:
                needs_repair = True
                failure_details = smoke_err

        # STAGE 7: BOUNDED SELF-REPAIR (max 3 iterations)
        if needs_repair:
            current_stage = "repair"
            repair_succeeded = False

            for rep_iter in range(1, 4):
                if active_build.cancelled:
                    return

                elapsed = round(time.time() - start_time, 1)
                await websocket.send_json({
                    "type": "build_progress",
                    "stage": "repair",
                    "iteration": rep_iter,
                    "max_iterations": 3,
                    "elapsed": elapsed,
                    "text": f"Self-repair attempt {rep_iter}/3: {failure_details[:80]}..."
                })

                target_file = identify_failing_file(proj_dir, failure_details)
                rep_ok, rep_res = await asyncio.to_thread(
                    repair_file_with_llm, target_file, failure_details, client, resolved_model
                )

                if not rep_ok:
                    failure_details = rep_res
                    continue

                rel_file = os.path.relpath(target_file, proj_dir).replace("\\", "/")
                await websocket.send_json({
                    "type": "patch",
                    "file": rel_file,
                    "project": project_title
                })

                stop_target_server()
                s_ok, s_proc, s_err = await asyncio.to_thread(start_and_wait_for_server, proj_dir, 5000, 20.0)
                if not s_ok:
                    failure_details = s_err
                    rollback_file(target_file)
                    continue

                target_server_process = s_proc
                sm_ok, sm_err = await asyncio.to_thread(smoke_test_app, proj_dir, "http://127.0.0.1:5000")
                if not sm_ok:
                    failure_details = sm_err
                    rollback_file(target_file)
                    continue

                remove_backup(target_file)
                repair_succeeded = True
                needs_repair = False
                break

            if not repair_succeeded:
                log_path = os.path.join(proj_dir, "app.log")
                log_tail = get_log_tail(log_path, lines=40)
                await websocket.send_json({
                    "type": "error",
                    "text": f"Application failed verification after 3 repair attempts: {failure_details}\n\nLast 40 log lines:\n{log_tail}"
                })
                stop_target_server()
                return

        current_running_project_dir = os.path.normpath(os.path.abspath(proj_dir))
        await websocket.send_json({"type": "project_switched", "project": project_title})
        await websocket.send_json({"type": "server_restart", "url": "http://127.0.0.1:5000"})
        await websocket.send_json({
            "type": "speech",
            "speaker": "BUILDER AI",
            "text": f"Application '{project_title}' is verified, built and running on port 5000.",
            "avatar": "🛠️"
        })

    except asyncio.CancelledError:
        if proj_dir and os.path.exists(proj_dir):
            shutil.rmtree(proj_dir, ignore_errors=True)
    except Exception as exc:
        err_msg = format_llm_error(exc, resolved_model)
        await websocket.send_json({"type": "error", "text": err_msg})
    finally:
        if heartbeat_task and not heartbeat_task.done():
            heartbeat_task.cancel()
        active_build.is_running = False
        active_build.task = None


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
                global active_duel_running
                if active_build.is_running or active_duel_running:
                    await websocket.send_json({"type": "error", "text": "Another build is running"})
                    continue

                active_duel_running = True
                project_name = msg.get("project", "simple_task_management_app")
                model_name = msg.get("model", DEFAULT_MODEL)
                rounds = int(msg.get("rounds", 3))

                try:
                    proj_dir = resolve_project_dir(project_name)
                except HTTPException as e:
                    active_duel_running = False
                    await websocket.send_json({"type": "error", "text": f"Project validation error: {e.detail}"})
                    continue

                ensure_target_server_running(proj_dir)

                try:
                    client, resolved_model = get_llm_client(model_name)
                except Exception as e:
                    active_duel_running = False
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
                duel_logs = []

                for r in range(1, rounds + 1):
                    await websocket.send_json({
                        "type": "info",
                        "text": f"⚔️ Entering ROUND {r} of {rounds}..."
                    })

                    breaches = hacker.run_attack_round(proj_dir, round_tier=r)

                    if not breaches:
                        hacker_taunt = "No breaches discovered this wave. App held up."
                        builder_defense = "Defenses held against tier probes this round."
                        await websocket.send_json({"type": "speech", "speaker": "HACKER AI", "text": hacker_taunt, "avatar": "😈"})
                        await websocket.send_json({"type": "speech", "speaker": "BUILDER AI", "text": builder_defense, "avatar": "🛠️"})
                        duel_logs.append({"round": r, "status": "NO_BREACHES", "breaches": [],
                                          "verified_fixes": 0, "unresolved": 0})
                    else:
                        total_breaches_count += len(breaches)
                        for b in breaches:
                            await websocket.send_json({"type": "breach", "breach": b})
                            
                            # Real-time taunts
                            h_speech = hacker.trash_talk(json.dumps(b))
                            await websocket.send_json({"type": "speech", "speaker": "HACKER AI", "text": h_speech, "avatar": "😈"})

                            b_speech = builder.counter_argument(b)
                            await websocket.send_json({"type": "speech", "speaker": "BUILDER AI", "text": b_speech, "avatar": "🛠️"})

                            # Record legitimate-request behaviour BEFORE patching (regression baseline)
                            baseline = hacker.capture_baseline(b.get("route", "/"))

                            # Builder patches
                            repaired = builder.generate_targeted_defense(proj_dir, b)
                            if repaired:
                                diff_content = builder.last_patch_info.get("diff", "") if builder.last_patch_info else ""
                                await websocket.send_json({"type": "patch", "file": "app.py", "diff": diff_content})
                                restart_target_server(proj_dir)
                                await websocket.send_json({"type": "server_restart", "url": "http://127.0.0.1:5000"})
                                await asyncio.sleep(1)

                                # Verified Patch Gate (same gate as the CLI arena): the exact breach
                                # request must no longer reproduce AND legitimate requests must
                                # behave as before the patch (no removed route, no new errors).
                                verified, reason = verify_patch(hacker, proj_dir, b, baseline)
                                if verified:
                                    verified_patches_count += 1
                                    b["status"] = "VERIFIED_PATCHED"
                                    save_verification_artifacts(proj_dir, b, builder=builder, baseline=baseline)
                                    await websocket.send_json({
                                        "type": "speech",
                                        "speaker": "BUILDER AI",
                                        "text": "Patch verified: the exact probe no longer reproduces and legitimate requests still work.",
                                        "avatar": "🛠️"
                                    })
                                else:
                                    unresolved_count += 1
                                    b["status"] = "UNRESOLVED"
                                    rolled_back = builder.rollback_last_patch()
                                    if rolled_back:
                                        restart_target_server(proj_dir)
                                        await websocket.send_json({"type": "server_restart", "url": "http://127.0.0.1:5000"})
                                    why = ("Fix failed re-test: the probe still reproduces."
                                           if reason == "breach_persists"
                                           else "Patch rejected: it broke or removed legitimate behaviour (regression check failed).")
                                    if rolled_back:
                                        why += " The patch was rolled back."
                                    await websocket.send_json({
                                        "type": "speech",
                                        "speaker": "HACKER AI",
                                        "text": why,
                                        "avatar": "😈"
                                    })
                            else:
                                unresolved_count += 1
                                b["status"] = "FAILED_TO_PATCH"

                        round_unresolved = sum(1 for b in breaches if b.get("status") != "VERIFIED_PATCHED")
                        duel_logs.append({
                            "round": r,
                            "status": "HARDENED" if round_unresolved == 0 else "PARTIAL",
                            "breaches": breaches,
                            "verified_fixes": len(breaches) - round_unresolved,
                            "unresolved": round_unresolved,
                        })

                # Persist security_audit.json + report.md for this UI duel (same as the CLI arena)
                try:
                    arena = AdversarialArena(client=client, model=resolved_model, max_rounds=rounds)
                    arena.total_breaches = total_breaches_count
                    arena.verified_fixes = verified_patches_count
                    arena.unresolved = unresolved_count
                    arena.duel_logs = duel_logs
                    arena.generate_security_audit_scorecard(proj_dir)
                except Exception:
                    pass

                if total_breaches_count == 0:
                    await websocket.send_json({
                        "type": "duel_completed",
                        "score": None,
                        "unresolved": 0,
                        "text": f"No breaches found in {rounds} round(s) of basic probes. This does not prove the app is secure."
                    })
                else:
                    score = int((verified_patches_count / total_breaches_count) * 100)
                    summary = (f"{verified_patches_count}/{total_breaches_count} breach(es) verified fixed, "
                               f"{unresolved_count} unresolved (verified-fix rate: {score}%).")
                    await websocket.send_json({
                        "type": "duel_all_verified" if unresolved_count == 0 else "duel_completed",
                        "score": score,
                        "unresolved": unresolved_count,
                        "text": ("All probes passed: " if unresolved_count == 0 else "Duel finished: ") + summary
                    })
                active_duel_running = False

            elif action == "start_build":
                if active_build.is_running or active_duel_running:
                    await websocket.send_json({
                        "type": "error",
                        "text": "Another build is running"
                    })
                    continue

                prompt = msg.get("prompt", "").strip()
                if not prompt:
                    await websocket.send_json({"type": "error", "text": "Build prompt cannot be empty."})
                    continue

                model_name = msg.get("model", DEFAULT_MODEL)
                try:
                    client, resolved_model = get_llm_client(model_name)
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "text": f"Model configuration error: {str(e)}"
                    })
                    continue

                active_build.is_running = True
                active_build.cancelled = False
                active_build.project_dir = None
                active_build.created_files = []

                # Run build as a background asyncio task so WebSocket loop stays responsive
                active_build.task = asyncio.create_task(
                    run_builder_pipeline(websocket, prompt, client, resolved_model)
                )

            elif action == "cancel_build":
                if active_build.is_running:
                    active_build.cancelled = True
                    if active_build.task and not active_build.task.done():
                        active_build.task.cancel()
                    if active_build.project_dir and os.path.exists(active_build.project_dir):
                        try:
                            shutil.rmtree(active_build.project_dir, ignore_errors=True)
                        except Exception:
                            pass
                    active_build.is_running = False
                    active_build.task = None
                    await websocket.send_json({
                        "type": "build_cancelled",
                        "text": "Build was cancelled. Unfinished project folder discarded."
                    })
                else:
                    await websocket.send_json({
                        "type": "info",
                        "text": "No build is currently running."
                    })

            elif action == "install_dependencies":
                packages = msg.get("packages", [])
                if not packages:
                    await websocket.send_json({"type": "info", "text": "No packages specified for installation."})
                    continue
                await websocket.send_json({"type": "info", "text": f"Installing packages: {', '.join(packages)}..."})
                try:
                    cmd = [sys.executable, "-m", "pip", "install", *packages]
                    res = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=120)
                    if res.returncode == 0:
                        await websocket.send_json({
                            "type": "dependencies_installed",
                            "packages": packages,
                            "text": f"Successfully installed: {', '.join(packages)}."
                        })
                    else:
                        await websocket.send_json({
                            "type": "error",
                            "text": f"Failed to install packages: {res.stderr}"
                        })
                except Exception as exc:
                    await websocket.send_json({"type": "error", "text": f"Installation error: {str(exc)}"})

    except WebSocketDisconnect:
        pass


# =============================================================================
# SERVER STARTUP ENTRYPOINT
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    # Start target app in background if needed
    try:
        default_proj = resolve_project_dir("simple_task_management_app")
        ensure_target_server_running(default_proj)
    except Exception:
        pass

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    print("\n" + "=" * 75)
    print("🚀 AEGIS DUAL-AI WEB IDE IS STARTING")
    print(f"🌐 Open in your browser: http://{host}:{port}")
    print("=" * 75 + "\n")
    uvicorn.run(app, host=host, port=port, log_level="info")
