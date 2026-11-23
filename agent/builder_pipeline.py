"""
AEGIS Builder Pipeline
Robust requirement analysis, plan validation, code generation,
verification gate, bounded self-repair, and progress telemetry.
"""

import os
import sys
import re
import ast
import json
import time
import shutil
import asyncio
import subprocess
import importlib.util
from typing import Dict, List, Any, Optional, Tuple, Callable

import requests
import jinja2

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Allowed extensions in project plan
ALLOWED_EXTENSIONS = {".py", ".html", ".css", ".js", ".txt", ".md", ".json"}
PLAN_SLUG_REGEX = re.compile(r"^[a-z0-9_]{3,40}$")


def validate_plan(plan: Any, app_code: Optional[str] = None) -> Tuple[bool, str]:
    """
    Validates the generated development plan according to AEGIS Phase 3 rules:
    - Must be a dictionary.
    - project_name: slug matching [a-z0-9_]{3,40}.
    - files: non-empty list, max 12 items.
    - files relative paths only (no '..', no absolute paths, no drive letters).
    - allowed extensions: .py, .html, .css, .js, .txt, .md, .json.
    - must contain 'app.py'.
    - every template used by app.py must be in files (if app_code is provided).
    """
    if not isinstance(plan, dict):
        return False, "Plan must be a valid JSON object."

    # 1. Project Name validation
    project_name = plan.get("project_name")
    if not project_name or not isinstance(project_name, str):
        return False, "Plan missing 'project_name' string."
    
    slug = project_name.strip().lower()
    if not PLAN_SLUG_REGEX.match(slug):
        return False, f"Invalid project_name '{project_name}': must be a slug matching [a-z0-9_]{{3,40}}."

    # 2. Files list validation
    files = plan.get("files")
    if not files or not isinstance(files, list):
        return False, "Plan must contain a non-empty 'files' list."

    if len(files) > 12:
        return False, f"Plan contains too many files ({len(files)}). Maximum allowed is 12."

    has_app_py = False
    normalized_files = set()

    for f in files:
        if not isinstance(f, str) or not f.strip():
            return False, "Each item in 'files' must be a non-empty string path."
        
        path_clean = f.strip().replace("\\", "/")

        # Check for path traversal, absolute paths, or drive letters
        if ".." in path_clean:
            return False, f"File path '{f}' contains invalid relative traversal '..'."
        if path_clean.startswith("/") or path_clean.startswith("\\"):
            return False, f"File path '{f}' must be relative, not absolute."
        if re.match(r"^[a-zA-Z]:", path_clean):
            return False, f"File path '{f}' contains a drive letter; only relative paths are allowed."

        # Extension check
        ext = os.path.splitext(path_clean)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return False, f"File '{f}' has disallowed extension '{ext}'. Allowed: {sorted(list(ALLOWED_EXTENSIONS))}."

        if path_clean == "app.py" or path_clean.endswith("/app.py"):
            has_app_py = True

        normalized_files.add(path_clean)

    if not has_app_py:
        return False, "Plan must contain 'app.py' as the main application entrypoint."

    # 3. If app_code is provided, verify template references
    if app_code:
        # Extract render_template('...') calls
        rendered_templates = re.findall(r"render_template\s*\(\s*['\"]([^'\"]+)['\"]", app_code)
        for tpl in rendered_templates:
            tpl_clean = tpl.replace("\\", "/").strip()
            # Accept either "index.html" or "templates/index.html"
            possible = {tpl_clean, f"templates/{tpl_clean}"}
            if not any(p in normalized_files for p in possible):
                return False, f"Template '{tpl}' referenced in app.py is missing from plan files."

    return True, ""


def get_unique_project_dir(project_name: str, base_dir: Optional[str] = None) -> str:
    """
    Avoids project folder name collisions by appending _2, _3, etc.,
    if the directory already exists.
    """
    work_dir = base_dir or root_dir
    slug = re.sub(r"[^a-z0-9_]", "_", project_name.lower().strip())
    slug = re.sub(r"_+", "_", slug).strip("_")
    if len(slug) < 3:
        slug = f"app_{slug}"
    if len(slug) > 36:
        slug = slug[:36]

    candidate = slug
    counter = 2
    
    while os.path.exists(os.path.join(work_dir, candidate)) or os.path.exists(os.path.join(work_dir, "examples", candidate)):
        candidate = f"{slug}_{counter}"
        counter += 1

    return candidate


def check_python_syntax(file_path: str, code: Optional[str] = None) -> Tuple[bool, str]:
    """Validates Python syntax via ast.parse."""
    try:
        source = code if code is not None else open(file_path, "r", encoding="utf-8").read()
        ast.parse(source)
        return True, ""
    except SyntaxError as e:
        return False, f"SyntaxError in {file_path}:{e.lineno}: {e.msg}"
    except Exception as e:
        return False, f"Error parsing {file_path}: {str(e)}"


def check_jinja_syntax(template_path: str, content: Optional[str] = None) -> Tuple[bool, str]:
    """Validates Jinja2 template syntax."""
    try:
        source = content if content is not None else open(template_path, "r", encoding="utf-8").read()
        env = jinja2.Environment()
        env.parse(source)
        return True, ""
    except jinja2.TemplateSyntaxError as e:
        return False, f"TemplateSyntaxError in {template_path}:{e.lineno}: {e.message}"
    except Exception as e:
        return False, f"Error parsing template {template_path}: {str(e)}"


def check_missing_imports(project_dir: str) -> List[str]:
    """
    Extracts top-level imports from all .py files in project_dir
    and checks if they are installed and importable.
    Returns list of missing packages.
    """
    # Standard library module names commonly used
    std_lib_cache = getattr(sys, "stdlib_module_names", set())
    missing = set()
    local_files = {os.path.splitext(f)[0] for f in os.listdir(project_dir) if f.endswith(".py")}

    for root, _, files in os.walk(project_dir):
        for f in files:
            if f.endswith(".py"):
                full_path = os.path.join(root, f)
                try:
                    with open(full_path, "r", encoding="utf-8") as f_in:
                        tree = ast.parse(f_in.read(), filename=full_path)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                pkg = alias.name.split(".")[0]
                                if pkg and pkg not in std_lib_cache and pkg not in local_files:
                                    if importlib.util.find_spec(pkg) is None:
                                        missing.add(pkg)
                        elif isinstance(node, ast.ImportFrom):
                            if node.module and node.level == 0:
                                pkg = node.module.split(".")[0]
                                if pkg and pkg not in std_lib_cache and pkg not in local_files:
                                    if importlib.util.find_spec(pkg) is None:
                                        missing.add(pkg)
                except Exception:
                    pass

    return sorted(list(missing))


def smoke_test_app(project_dir: str, base_url: str = "http://127.0.0.1:5000") -> Tuple[bool, str]:
    """
    Performs smoke tests on target application:
    1. GET /
    2. Inspects app.py for static GET routes (e.g. @app.route('/about')) and sends GET requests.
    3. Checks for url_for mismatches in templates.
    """
    session = requests.Session()
    
    # 1. Base URL /
    try:
        r = session.get(f"{base_url}/", timeout=3)
        if r.status_code >= 500:
            return False, f"Root endpoint '/' returned HTTP {r.status_code}"
    except Exception as e:
        return False, f"Root endpoint '/' failed to respond: {str(e)}"

    # 2. Extract GET routes from app.py
    app_file = os.path.join(project_dir, "app.py")
    routes_to_test = []
    view_functions = set()

    if os.path.exists(app_file):
        try:
            with open(app_file, "r", encoding="utf-8") as f_app:
                tree = ast.parse(f_app.read())
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    view_functions.add(node.name)
                    for decorator in node.decorator_list:
                        if isinstance(decorator, ast.Call):
                            func = decorator.func
                            is_route = False
                            if isinstance(func, ast.Attribute) and func.attr == "route":
                                is_route = True
                            if is_route and decorator.args:
                                first_arg = decorator.args[0]
                                if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                                    route_path = first_arg.value
                                    # Skip dynamic routes with params like <int:id>
                                    if "<" not in route_path and route_path != "/":
                                        # Check methods keyword arg if specified
                                        methods = {"GET"}
                                        for kw in decorator.keywords:
                                            if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                                                methods = {m.value.upper() for m in kw.value.elts if isinstance(m, ast.Constant)}
                                        if "GET" in methods:
                                            routes_to_test.append(route_path)
        except Exception:
            pass

    for route in routes_to_test:
        try:
            url = f"{base_url}{route if route.startswith('/') else '/' + route}"
            r = session.get(url, timeout=3)
            if r.status_code == 404:
                return False, f"Route '{route}' returned 404 Not Found"
            if r.status_code >= 500:
                return False, f"Route '{route}' crashed with HTTP {r.status_code}"
        except Exception as e:
            return False, f"Route '{route}' failed to respond: {str(e)}"

    # 3. Check templates for url_for endpoint mismatches
    templates_dir = os.path.join(project_dir, "templates")
    if os.path.isdir(templates_dir) and view_functions:
        for t_file in os.listdir(templates_dir):
            if t_file.endswith(".html"):
                t_path = os.path.join(templates_dir, t_file)
                try:
                    with open(t_path, "r", encoding="utf-8") as tf:
                        content = tf.read()
                    url_for_calls = re.findall(r"url_for\s*\(\s*['\"]([^'\"]+)['\"]", content)
                    for ep in url_for_calls:
                        # Exclude static
                        if ep != "static" and ep not in view_functions:
                            return False, f"Template '{t_file}' references undefined endpoint '{ep}' in url_for()"
                except Exception:
                    pass

    return True, "Smoke tests passed successfully"


def start_and_wait_for_server(
    project_dir: str,
    port: int = 5000,
    timeout_sec: float = 20.0
) -> Tuple[bool, Optional[subprocess.Popen], str]:
    """
    Launches target application with stdout/stderr piped to app.log.
    Waits up to timeout_sec for an HTTP response on '/'.
    Returns (success, process, error_or_log_tail).
    """
    app_file = os.path.join(project_dir, "app.py")
    if not os.path.exists(app_file):
        return False, None, f"Cannot start: {app_file} does not exist"

    log_path = os.path.join(project_dir, "app.log")
    log_file = open(log_path, "w", encoding="utf-8", errors="replace")

    # Use sys.executable (the virtualenv python)
    python_exe = sys.executable
    cmd = [python_exe, "app.py"]

    env = os.environ.copy()
    env["PORT"] = str(port)
    env["HOST"] = "127.0.0.1"

    process = subprocess.Popen(
        cmd,
        cwd=project_dir,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=env,
        text=True
    )

    base_url = f"http://127.0.0.1:{port}"
    start_time = time.time()
    
    while time.time() - start_time < timeout_sec:
        # Check if process terminated early
        ret = process.poll()
        if ret is not None:
            log_file.flush()
            log_tail = get_log_tail(log_path, lines=40)
            return False, None, f"Application server exited prematurely with return code {ret}:\n{log_tail}"

        try:
            r = requests.get(f"{base_url}/", timeout=1)
            if r.status_code < 500:
                return True, process, ""
        except Exception:
            pass

        time.sleep(0.5)

    # Timed out waiting for server
    try:
        process.terminate()
        process.wait(timeout=2)
    except Exception:
        process.kill()

    log_file.flush()
    log_tail = get_log_tail(log_path, lines=40)
    return False, None, f"Application failed to respond within {timeout_sec}s:\n{log_tail}"


def get_log_tail(log_path: str, lines: int = 40) -> str:
    """Reads the last N lines of a log file."""
    if not os.path.exists(log_path):
        return "(No log file found)"
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
            return "".join(all_lines[-lines:])
    except Exception as e:
        return f"(Error reading log: {e})"


def identify_failing_file(project_dir: str, failure_text: str) -> str:
    """Identifies the most likely culprit file from an error message or traceback."""
    # Look for python files mentioned in traceback
    py_matches = re.findall(r'File "([^"]+\.py)"', failure_text)
    for m in reversed(py_matches):
        base = os.path.basename(m)
        cand = os.path.join(project_dir, base)
        if os.path.exists(cand):
            return cand

    # Look for template mentions (e.g. Template 'index.html' or templates/index.html)
    tpl_matches = re.findall(r"['\"]([a-zA-Z0-9_\-]+\.html)['\"]", failure_text)
    for tpl in tpl_matches:
        cand = os.path.join(project_dir, "templates", tpl)
        if os.path.exists(cand):
            return cand

    # Default to app.py
    return os.path.join(project_dir, "app.py")


def rollback_file(file_path: str) -> bool:
    """Restores a file from its .bak backup if one exists."""
    bak = f"{file_path}.bak"
    if os.path.exists(bak):
        shutil.copy2(bak, file_path)
        try:
            os.remove(bak)
        except Exception:
            pass
        return True
    return False


def remove_backup(file_path: str) -> None:
    """Removes a .bak backup file."""
    bak = f"{file_path}.bak"
    if os.path.exists(bak):
        try:
            os.remove(bak)
        except Exception:
            pass


def repair_file_with_llm(
    file_path: str,
    failure_details: str,
    client: Any,
    model: str
) -> Tuple[bool, str]:
    """
    Prompts the LLM to fix the given file based on the traceback/failure details.
    Keeps a .bak backup, checks syntax before returning.
    Returns (success, new_code_or_error).
    """
    if not os.path.exists(file_path):
        return False, f"Target file '{file_path}' does not exist for repair"

    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        current_code = f.read()

    # Backup current file
    bak_path = f"{file_path}.bak"
    shutil.copy2(file_path, bak_path)

    system_prompt = """You are The Builder AI in an autonomous self-repair loop.
An application failed startup or smoke verification.
Analyze the error traceback and current code, then produce the COMPLETE corrected file contents.

STRICT REPAIR RULES:
1. Output ONLY the raw file contents. NEVER wrap in markdown fences (```).
2. Fix all syntax, import, route, or runtime errors identified in the traceback.
3. For Flask applications:
   - Always run with debug=False.
   - Bind to host='127.0.0.1' and read port from os.environ.get('PORT', 5000).
   - Ensure every url_for() referenced in templates corresponds to an actual view function.
   - Validate and length-limit all form input server-side (return 400, never 500).
   - Never use '|safe' on user-controlled inputs.
4. Do not delete essential routes or functionality.
"""

    user_prompt = f"""Target file: {os.path.basename(file_path)}

VERIFICATION FAILURE / TRACEBACK:
{failure_details}

CURRENT CONTENTS:
{current_code}

Fix the bug and return the COMPLETE updated file:"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1
        )

        content = ""
        if hasattr(response, "choices") and response.choices:
            choice = response.choices[0]
            if hasattr(choice, "message") and hasattr(choice.message, "content"):
                content = choice.message.content or ""
            elif isinstance(choice, dict):
                content = choice.get("message", {}).get("content", "")

        content = content.strip()
        if content.startswith("```"):
            lines = content.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        if not content:
            rollback_file(file_path)
            return False, "Builder produced empty code during repair"

        # Check syntax
        if file_path.endswith(".py"):
            ok, syntax_err = check_python_syntax(file_path, content)
            if not ok:
                rollback_file(file_path)
                return False, f"Repaired code has syntax error: {syntax_err}"
        elif file_path.endswith(".html"):
            ok, syntax_err = check_jinja_syntax(file_path, content)
            if not ok:
                rollback_file(file_path)
                return False, f"Repaired template has syntax error: {syntax_err}"

        # Write repaired file
        with open(file_path, "w", encoding="utf-8") as f_out:
            f_out.write(content)

        return True, content

    except Exception as exc:
        rollback_file(file_path)
        return False, f"LLM error during repair: {str(exc)}"

