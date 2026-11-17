from openai import OpenAI
import json
import os
import subprocess
import time
import venv
import ast
import threading
import queue
import urllib.request
import urllib.error
import urllib.parse
import http.cookiejar
import re
import sys

# Ensure parent directory is in sys.path when run as 'python agent/main.py'
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

try:
    from agent.adversarial_duel import AdversarialArena
except ImportError:
    from adversarial_duel import AdversarialArena




try:
    from agent.llm_client import get_llm_client
except ImportError:
    from llm_client import get_llm_client

# ============================================================
# LLM CONNECTION (Local Ollama, Gemini, Claude, or OpenAI)
# ============================================================

MODEL = os.environ.get("AEGIS_MODEL", "qwen2.5-coder:7b")
try:
    client, MODEL = get_llm_client(MODEL)
except Exception:
    client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")

MAX_REPAIR_ATTEMPTS = 3


# ============================================================
# STEP 1: REQUIREMENT ANALYZER
# ============================================================

def analyze_requirements(project_prompt):

    system_prompt = """
You are the Requirement Analyzer of an Autonomous Software Development Agent.

Analyze the user's software project request and convert it into
a structured development plan.

Return ONLY valid JSON.

The JSON must contain exactly these fields:

{
    "project_name": "",
    "description": "",
    "technology_stack": [],
    "dependencies": [],
    "features": [],
    "files": [],
    "run_command": "",
    "test_cases": []
}

Rules:
- Choose technologies appropriate for the requested project (Python/Flask, or React/Vite/Node if modern JS/React is preferred).
- Keep the first version fully functional, clean, and runnable immediately.
- List every important file that must be created (including backend server, frontend components/templates, styling, and database/storage).
- List all required external dependencies clearly.
- Give a command that can run the application (e.g., 'python app.py' or 'npm run dev').
- Give practical test cases.
- Do not write source code here; define the architecture.
- For Flask web apps, include all templates and static/style.css files required.
- For React/Vite/Express web apps, include package.json, server.js (or api routes), and component files.
- Return valid JSON only.
"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": project_prompt
            }
        ],
        temperature=0
    )

    content = response.choices[0].message.content.strip()

    return clean_json_response(content)


# ============================================================
# CLEAN AI JSON RESPONSE
# ============================================================

def clean_json_response(content):

    content = content.strip()

    if content.startswith("```"):

        lines = content.splitlines()

        if lines and lines[0].startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        content = "\n".join(lines).strip()

    return json.loads(content)


# ============================================================
# STEP 2: SAVE PROJECT PLAN
# ============================================================

def save_project_plan(plan):

    with open(
        "project_plan.json",
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            plan,
            file,
            indent=4
        )

    print("\n✅ Project plan saved to project_plan.json")


# ============================================================
# STEP 3: CREATE PROJECT STRUCTURE
# ============================================================

def create_project_structure(plan):

    project_name = plan["project_name"]

    project_dir = (
        project_name
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )

    os.makedirs(
        project_dir,
        exist_ok=True
    )

    for file_path in plan["files"]:

        full_path = os.path.join(
            project_dir,
            file_path
        )

        directory = os.path.dirname(
            full_path
        )

        if directory:

            os.makedirs(
                directory,
                exist_ok=True
            )

    print(
        f"✅ Project structure created: {project_dir}"
    )

    return project_dir


# ============================================================
# STEP 4: AI CODE GENERATOR
# ============================================================

def generate_code(file_path, plan):

    playbook_prompt = ""
    try:
        from agent.playbook import PlaybookManager
        pm = PlaybookManager()
        if pm.is_enabled():
            relevant = pm.get_relevant_entries(f"{file_path} {plan.get('description', '')}", top_k=3)
            playbook_prompt = pm.format_playbook_for_prompt(relevant)
    except Exception:
        pass

    system_prompt = f"""
You are the Code Generator of an Autonomous Software Development Agent.

Generate the COMPLETE source code for one requested file.

PROJECT PLAN:

{json.dumps(plan, indent=4)}
{playbook_prompt}
IMPORTANT RULES:

1. Generate ONLY source code.
2. Do not use markdown fences.
3. Do not explain anything.
4. The generated project must work with the other files.
6. For Flask applications:
   - Every route used in HTML forms or links must exist.
   - Use url_for() whenever practical.
   - If Flask-SQLAlchemy is used, initialize the database using db.create_all() inside app.app_context().
   - Do NOT use app.before_first_request (deprecated in Flask 2.3+).
   - Make authentication and database models consistent.
7. For JavaScript / React / Express applications:
   - Ensure package.json defines all required dependencies and start/dev scripts.
   - Ensure all frontend API fetch routes match the Express / backend routes.
   - Write clean, modern, responsive CSS/Tailwind designs.
8. Make sure imported external packages are actually needed.
9. Generate a runnable and internally consistent implementation with zero placeholders.
"""

    user_prompt = f"""
Generate the complete contents of:

{file_path}
"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],
        temperature=0.1
    )

    content = response.choices[0].message.content.strip()

    if content.startswith("```"):

        lines = content.splitlines()

        if lines and lines[0].startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        content = "\n".join(lines)

    return content


# ============================================================
# WRITE GENERATED CODE
# ============================================================

def write_generated_code(project_dir, plan):

    print("\n" + "=" * 70)
    print("STEP 4: GENERATE CODE")
    print("=" * 70)

    for file_path in plan["files"]:

        print(f"\n📝 Generating: {file_path}")

        full_path = os.path.join(
            project_dir,
            file_path
        )

        code = generate_code(
            file_path,
            plan
        )

        directory = os.path.dirname(full_path)

        if directory:

            os.makedirs(
                directory,
                exist_ok=True
            )

        with open(
            full_path,
            "w",
            encoding="utf-8"
        ) as file:

            file.write(code)

        print(f"✅ Generated: {file_path}")

    print("\n✅ CODE GENERATION COMPLETED")


# ============================================================
# AUTOMATIC DEPENDENCY DETECTION
# ============================================================

def detect_code_dependencies(project_dir):

    print(
        "\n🔍 Analyzing generated code for required dependencies..."
    )

    package_map = {

        "flask": "Flask",

        "flask_sqlalchemy":
            "Flask-SQLAlchemy",

        "sqlalchemy":
            "SQLAlchemy",

        "requests":
            "requests",

        "pandas":
            "pandas",

        "numpy":
            "numpy",

        "sklearn":
            "scikit-learn",

        "bs4":
            "beautifulsoup4",

        "dotenv":
            "python-dotenv",

        "jwt":
            "PyJWT",

        "cryptography":
            "cryptography",

        "fastapi":
            "fastapi",

        "uvicorn":
            "uvicorn",

        "pydantic":
            "pydantic",

        "openpyxl":
            "openpyxl",

        "matplotlib":
            "matplotlib",

        "seaborn":
            "seaborn",

        "PIL":
            "Pillow",

        "cv2":
            "opencv-python"
    }

    detected_modules = set()

    for root, dirs, files in os.walk(project_dir):

        if ".venv" in dirs:
            dirs.remove(".venv")

        if "__pycache__" in dirs:
            dirs.remove("__pycache__")

        for filename in files:

            if not filename.endswith(".py"):
                continue

            filepath = os.path.join(
                root,
                filename
            )

            try:

                with open(
                    filepath,
                    "r",
                    encoding="utf-8"
                ) as file:

                    source = file.read()

                tree = ast.parse(source)

                for node in ast.walk(tree):

                    if isinstance(node, ast.Import):

                        for alias in node.names:

                            module_name = (
                                alias.name
                                .split(".")[0]
                            )

                            detected_modules.add(
                                module_name
                            )

                    elif isinstance(
                        node,
                        ast.ImportFrom
                    ):

                        if node.module:

                            module_name = (
                                node.module
                                .split(".")[0]
                            )

                            detected_modules.add(
                                module_name
                            )

            except Exception:

                pass

    detected_dependencies = set()

    for module in detected_modules:

        if module in package_map:

            detected_dependencies.add(
                package_map[module]
            )

    print(
        "\n📦 Dependencies detected from generated code:"
    )

    if detected_dependencies:

        for dependency in sorted(
            detected_dependencies
        ):

            print(f"   • {dependency}")

    else:

        print(
            "   • No known external dependencies detected."
        )

    return sorted(
        detected_dependencies
    )


# ============================================================
# STEP 5: CREATE ISOLATED ENVIRONMENT
# ============================================================

def setup_project_environment(
    project_dir,
    plan
):

    print("\n" + "=" * 70)
    print("STEP 5: SETTING UP PROJECT ENVIRONMENT")
    print("=" * 70)

    project_venv = os.path.join(
        project_dir,
        ".venv"
    )

    if os.path.exists(project_venv):

        print(
            "\n✅ Project .venv already exists."
        )

    else:

        print(
            "\n🐍 Creating isolated Python environment..."
        )

        venv.create(
            project_venv,
            with_pip=True
        )

        print(
            "✅ Project .venv created."
        )

    if os.name == "nt":

        python_executable = os.path.join(
            project_venv,
            "Scripts",
            "python.exe"
        )

    else:

        python_executable = os.path.join(
            project_venv,
            "bin",
            "python"
        )

    plan_dependencies = plan.get(
        "dependencies",
        []
    )

    code_dependencies = detect_code_dependencies(
        project_dir
    )

    all_dependencies = sorted(
        set(
            plan_dependencies
            + code_dependencies
        )
    )

    print(
        "\n📦 FINAL DEPENDENCY LIST:"
    )

    if all_dependencies:

        for dependency in all_dependencies:

            print(f"   • {dependency}")

    else:

        print(
            "   • No external dependencies required."
        )

        return python_executable

    print("\n⬆️ Updating pip...")

    subprocess.run(
        [
            python_executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pip"
        ],
        check=True
    )

    print(
        "\n📥 Installing all required dependencies..."
    )

    subprocess.run(
        [
            python_executable,
            "-m",
            "pip",
            "install",
            *all_dependencies
        ],
        check=True
    )

    print(
        "\n✅ All project dependencies installed."
    )

    return python_executable


# ============================================================
# PROCESS OUTPUT READER
# ============================================================

def start_output_reader(process):

    output_queue = queue.Queue()

    def reader():

        try:

            for line in iter(
                process.stdout.readline,
                ""
            ):

                if line:

                    output_queue.put(line)

        except Exception:

            pass

    thread = threading.Thread(
        target=reader,
        daemon=True
    )

    thread.start()

    return output_queue


# ============================================================
# COLLECT PROCESS OUTPUT
# ============================================================

def collect_process_output(output_queue):

    lines = []

    while True:

        try:

            line = output_queue.get_nowait()

            lines.append(line)

        except queue.Empty:

            break

    return "".join(lines)


# ============================================================
# START APPLICATION
# ============================================================

def start_application(
    project_dir,
    python_executable,
    plan
):

    run_command = plan.get(
        "run_command",
        ""
    ).strip()

    if not run_command:

        print(
            "\n❌ No run command was provided."
        )

        return None, None

    print(
        "\n🚀 Run command from project plan:"
    )

    print(f"   {run_command}")

    command_parts = run_command.split()

    if command_parts:

        if command_parts[0].lower() in (
            "python",
            "python3",
            "py"
        ):

            command_parts[0] = (
                python_executable
            )

    print("\n▶️ Starting application...")

    try:

        process = subprocess.Popen(
            command_parts,
            cwd=project_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        output_queue = start_output_reader(
            process
        )

        print(
            "\n⏳ Waiting for application to start..."
        )

        time.sleep(3)

        startup_output = collect_process_output(
            output_queue
        )

        if startup_output:

            print(
                startup_output,
                end=""
            )

        if process.poll() is not None:

            return None, startup_output

        print(
            "\n✅ APPLICATION STARTED SUCCESSFULLY"
        )

        print("-" * 70)

        print(
            "🌐 Application address:"
        )

        print(
            "   http://127.0.0.1:5000"
        )

        return process, output_queue

    except Exception as e:

        return None, str(e)


# ============================================================
# HTTP CLIENT WITH COOKIE SUPPORT
# ============================================================

def create_http_client():

    cookie_jar = http.cookiejar.CookieJar()

    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(
            cookie_jar
        )
    )

    return opener


# ============================================================
# HTTP REQUEST
# ============================================================

def http_request(
    opener,
    url,
    method="GET",
    data=None
):

    try:

        encoded_data = None

        if data is not None:

            encoded_data = urllib.parse.urlencode(
                data
            ).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=encoded_data,
            method=method
        )

        response = opener.open(
            request,
            timeout=5
        )

        body = response.read().decode(
            "utf-8",
            errors="ignore"
        )

        return (
            response.status,
            body,
            None,
            response.geturl()
        )

    except urllib.error.HTTPError as e:

        try:

            body = e.read().decode(
                "utf-8",
                errors="ignore"
            )

        except Exception:

            body = ""

        return (
            e.code,
            body,
            str(e),
            url
        )

    except Exception as e:

        return (
            None,
            "",
            str(e),
            url
        )


# ============================================================
# DISCOVER FLASK ROUTES FROM SOURCE CODE
# ============================================================

def discover_flask_routes(project_dir):

    routes = []

    app_file = os.path.join(
        project_dir,
        "app.py"
    )

    if not os.path.exists(app_file):

        return routes

    try:

        with open(
            app_file,
            "r",
            encoding="utf-8"
        ) as file:

            source = file.read()

        pattern = (
            r"@app\.route\(\s*"
            r"['\"]([^'\"]+)['\"]"
        )

        matches = re.findall(
            pattern,
            source
        )

        for route in matches:

            if route not in routes:

                routes.append(route)

    except Exception:

        pass

    return routes


# ============================================================
# DISCOVER HTML FORM ACTIONS
# ============================================================

def discover_form_actions(project_dir):

    actions = []

    templates_dir = os.path.join(
        project_dir,
        "templates"
    )

    if not os.path.exists(
        templates_dir
    ):

        return actions

    for root, dirs, files in os.walk(
        templates_dir
    ):

        for filename in files:

            if not filename.endswith(
                ".html"
            ):

                continue

            filepath = os.path.join(
                root,
                filename
            )

            try:

                with open(
                    filepath,
                    "r",
                    encoding="utf-8"
                ) as file:

                    content = file.read()

                matches = re.findall(
                    r"<form[^>]*action=[\"']([^\"']+)",
                    content,
                    re.IGNORECASE
                )

                for action in matches:

                    if action not in actions:

                        actions.append(action)

            except Exception:

                pass

    return actions


# ============================================================
# DETECT IMPORTANT ROUTES
# ============================================================

def find_route(routes, keywords):

    for route in routes:

        route_lower = route.lower()

        for keyword in keywords:

            if keyword in route_lower:

                return route

    return None


# ============================================================
# TEST SINGLE ROUTE
# ============================================================

def test_route(
    opener,
    base_url,
    route
):

    url = base_url + route

    return http_request(
        opener,
        url
    )


# ============================================================
# STEP 7: AUTOMATIC APPLICATION TESTING
# ============================================================

def run_automatic_tests(
    process,
    output_queue,
    plan,
    project_dir
):

    print("\n" + "=" * 70)
    print("STEP 7: AUTOMATIC APPLICATION TESTING")
    print("=" * 70)

    base_url = (
        "http://127.0.0.1:5000"
    )

    failures = []

    opener = create_http_client()

    routes = discover_flask_routes(
        project_dir
    )

    print(
        "\n🔎 Discovered application routes:"
    )

    if routes:

        for route in routes:

            print(f"   • {route}")

    else:

        print(
            "   ⚠️ Could not automatically discover routes."
        )

        routes = ["/"]

    # --------------------------------------------------------
    # BASIC ROUTE TESTING
    # --------------------------------------------------------

    for route in routes:

        # Skip dynamic routes
        if "<" in route or ">" in route:
            continue

        print(
            f"\n🧪 Testing route: {route}"
        )

        status, body, error, final_url = (
            test_route(
                opener,
                base_url,
                route
            )
        )

        time.sleep(0.3)

        server_output = collect_process_output(
            output_queue
        )

        if server_output:

            print(
                server_output,
                end=""
            )

        if status is not None and status >= 500:

            print(
                f"   ❌ Server error: HTTP {status}"
            )

            failures.append(
                {
                    "route": route,
                    "status": status,
                    "error": "HTTP 500 server error",
                    "body": body[-2000:]
                }
            )

        elif error and status is None:

            print(
                f"   ❌ Request failed: {error}"
            )

            failures.append(
                {
                    "route": route,
                    "status": status,
                    "error": error
                }
            )

        else:

            print(
                f"   ✅ HTTP {status}"
            )

    # --------------------------------------------------------
    # TEST REGISTRATION
    # --------------------------------------------------------

    register_route = find_route(
        routes,
        ["register", "signup", "sign_up"]
    )

    if register_route:

        print(
            "\n🧪 Testing registration..."
        )

        username = (
            f"testuser{int(time.time())}"
        )

        registration_data = {
            "username": username,
            "password": "TestPassword123"
        }

        status, body, error, final_url = (
            http_request(
                opener,
                base_url + register_route,
                method="POST",
                data=registration_data
            )
        )

        print(
            f"   Registration HTTP {status}"
        )

        if status is not None and status >= 500:

            failures.append(
                {
                    "route": register_route,
                    "status": status,
                    "error": "Registration caused server error",
                    "body": body[-2000:]
                }
            )

    # --------------------------------------------------------
    # TEST LOGIN
    # --------------------------------------------------------

    login_route = find_route(
        routes,
        ["login", "signin", "sign_in"]
    )

    if login_route:

        print(
            "\n🧪 Testing login..."
        )

        login_data = {
            "username": username
            if register_route
            else "testuser",
            "password": "TestPassword123"
        }

        status, body, error, final_url = (
            http_request(
                opener,
                base_url + login_route,
                method="POST",
                data=login_data
            )
        )

        print(
            f"   Login HTTP {status}"
        )

        if status is not None and status >= 500:

            failures.append(
                {
                    "route": login_route,
                    "status": status,
                    "error": "Login caused server error",
                    "body": body[-2000:]
                }
            )

    # --------------------------------------------------------
    # FIND TASK-RELATED ROUTE
    # --------------------------------------------------------

    task_route = find_route(
        routes,
        ["task", "dashboard", "home"]
    )

    if task_route:

        print(
            f"\n🧪 Testing main task route: {task_route}"
        )

        status, body, error, final_url = (
            http_request(
                opener,
                base_url + task_route
            )
        )

        print(
            f"   HTTP {status}"
        )

        if status is not None and status >= 500:

            failures.append(
                {
                    "route": task_route,
                    "status": status,
                    "error": "Task page server error",
                    "body": body[-2000:]
                }
            )

    # --------------------------------------------------------
    # COLLECT FINAL SERVER OUTPUT
    # --------------------------------------------------------

    time.sleep(0.5)

    final_output = collect_process_output(
        output_queue
    )

    if final_output:

        print(
            "\n📋 SERVER OUTPUT:"
        )

        print(
            final_output
        )

    if (
        "Traceback (most recent call last)"
        in final_output
    ):

        failures.append(
            {
                "route": "server",
                "status": 500,
                "error": "Python traceback detected",
                "server_output": final_output
            }
        )

    if failures:

        print(
            "\n❌ AUTOMATIC TESTING FOUND PROBLEMS"
        )

        print(
            f"   Problems detected: {len(failures)}"
        )

        return (
            False,
            failures,
            final_output
        )

    print(
        "\n✅ AUTOMATIC TESTING PASSED"
    )

    return (
        True,
        [],
        final_output
    )


# ============================================================
# READ PROJECT FILES
# ============================================================

def read_project_files(project_dir):

    project_files = {}

    ignored_directories = {
        ".venv",
        "__pycache__",
        ".git"
    }

    allowed_extensions = (
        ".py",
        ".html",
        ".css",
        ".js",
        ".json",
        ".txt"
    )

    for root, dirs, files in os.walk(
        project_dir
    ):

        dirs[:] = [

            directory
            for directory in dirs

            if directory
            not in ignored_directories
        ]

        for filename in files:

            if not filename.endswith(
                allowed_extensions
            ):

                continue

            filepath = os.path.join(
                root,
                filename
            )

            relative_path = os.path.relpath(
                filepath,
                project_dir
            )

            try:

                with open(
                    filepath,
                    "r",
                    encoding="utf-8"
                ) as file:

                    project_files[
                        relative_path
                    ] = file.read()

            except Exception:

                pass

    return project_files


# ============================================================
# EXTRACT ERROR INFORMATION
# ============================================================

def extract_error_information(
    failures,
    server_output
):

    error_text = ""

    for failure in failures:

        error_text += (
            "\n\nTEST FAILURE:\n"
            + json.dumps(
                failure,
                indent=4
            )
        )

    if server_output:

        error_text += (
            "\n\nSERVER OUTPUT:\n"
            + server_output
        )

    if len(error_text) > 20000:

        error_text = error_text[-20000:]

    return error_text


# ============================================================
# STEP 8: AI ERROR ANALYSIS + REPAIR
# ============================================================

def analyze_and_repair(
    project_dir,
    plan,
    failures,
    server_output,
    attempt
):

    print("\n" + "=" * 70)

    print(
        f"STEP 8: AI SELF-HEALING ATTEMPT {attempt}"
    )

    print("=" * 70)

    project_files = read_project_files(
        project_dir
    )

    error_information = extract_error_information(
        failures,
        server_output
    )

    system_prompt = """
You are the Self-Healing Software Engineer inside an
Autonomous Software Development Agent.

A generated project failed startup or automatic testing.

Your task is to diagnose the ACTUAL problem and return corrected
complete source files.

Return ONLY valid JSON exactly in this format:

{
    "diagnosis": "short explanation",
    "changes": [
        {
            "file": "relative/path/to/file",
            "reason": "why it changed"
        }
    ],
    "files": [
        {
            "path": "relative/path/to/file",
            "content": "complete corrected file content"
        }
    ]
}

IMPORTANT RULES:

1. Diagnose the actual error from the provided logs.
2. Do not invent unrelated problems.
3. Preserve all requested functionality.
4. Return COMPLETE file contents.
5. Do not use markdown fences.
6. Do not return text outside JSON.
7. Do not use Flask before_first_request.
8. If Flask-SQLAlchemy is used, database initialization must be:

   with app.app_context():
       db.create_all()

9. Every HTML form action must match an existing Flask route.
10. Every url_for endpoint must match an existing route function.
11. If a template expects tasks as an iterable, pass an actual
    query result or list, not the route function itself.
12. Keep route names and redirects internally consistent.
13. Make the smallest reliable repair.
"""

    user_prompt = f"""
PROJECT PLAN:

{json.dumps(plan, indent=4)}

REPAIR ATTEMPT:

{attempt}

ERROR INFORMATION:

{error_information}

CURRENT PROJECT FILES:

{json.dumps(project_files, indent=4)}

Return corrected files as JSON only.
"""

    try:

        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_prompt
                }
            ],
            temperature=0
        )

        content = (
            response
            .choices[0]
            .message
            .content
            .strip()
        )

        return clean_json_response(
            content
        )

    except json.JSONDecodeError as e:

        print(
            "\n❌ AI returned invalid repair JSON."
        )

        print(
            f"JSON error: {e}"
        )

        return None

    except Exception as e:

        print(
            f"\n❌ AI repair request failed: {e}"
        )

        return None


# ============================================================
# APPLY AI REPAIR
# ============================================================

def apply_repair(
    project_dir,
    repair
):

    if not repair:

        return False

    files = repair.get(
        "files",
        []
    )

    if not files:

        print(
            "\n❌ AI did not provide any files to repair."
        )

        return False

    print(
        "\n🧠 AI DIAGNOSIS:"
    )

    print(
        repair.get(
            "diagnosis",
            "No diagnosis provided."
        )
    )

    print(
        "\n🔧 Applying AI-generated repairs..."
    )

    changed_files = 0

    for file_info in files:

        relative_path = file_info.get(
            "path",
            ""
        )

        content = file_info.get(
            "content",
            ""
        )

        if not relative_path:

            continue

        safe_path = os.path.normpath(
            relative_path
        )

        if (
            safe_path.startswith("..")
            or os.path.isabs(safe_path)
        ):

            print(
                f"⚠️ Skipping unsafe path: {relative_path}"
            )

            continue

        full_path = os.path.join(
            project_dir,
            safe_path
        )

        directory = os.path.dirname(
            full_path
        )

        if directory:

            os.makedirs(
                directory,
                exist_ok=True
            )

        with open(
            full_path,
            "w",
            encoding="utf-8"
        ) as file:

            file.write(content)

        print(
            f"   🔧 Repaired: {safe_path}"
        )

        changed_files += 1

    if changed_files == 0:

        print(
            "\n❌ No valid files were changed."
        )

        return False

    print(
        f"\n✅ {changed_files} file(s) repaired."
    )

    return True


# ============================================================
# STOP APPLICATION
# ============================================================

def stop_application(process):

    if process is None:

        return

    if process.poll() is None:

        print(
            "\n🛑 Stopping application..."
        )

        try:

            process.terminate()

            process.wait(
                timeout=5
            )

        except subprocess.TimeoutExpired:

            process.kill()

            process.wait()

        except Exception:

            try:

                process.kill()

            except Exception:

                pass


# ============================================================
# STEP 9: AUTONOMOUS SELF-HEALING LOOP
# ============================================================

def autonomous_self_healing(
    project_dir,
    python_executable,
    plan
):

    print("\n" + "=" * 70)

    print(
        "🤖 AUTONOMOUS SELF-HEALING DEVELOPMENT LOOP"
    )

    print("=" * 70)

    for attempt in range(
        1,
        MAX_REPAIR_ATTEMPTS + 1
    ):

        print(
            f"\n🔄 DEVELOPMENT ITERATION "
            f"{attempt}/{MAX_REPAIR_ATTEMPTS}"
        )

        # ----------------------------------------------------
        # START APPLICATION
        # ----------------------------------------------------

        process, output_source = start_application(
            project_dir,
            python_executable,
            plan
        )

        if process is None:

            startup_output = ""

            if isinstance(
                output_source,
                str
            ):

                startup_output = output_source

            failures = [
                {
                    "route": "startup",
                    "status": None,
                    "error":
                        "Application failed to start",
                    "server_output":
                        startup_output
                }
            ]

            server_output = startup_output

            print(
                "\n❌ Application failed during startup."
            )

        else:

            output_queue = output_source

            (
                passed,
                failures,
                server_output
            ) = run_automatic_tests(
                process,
                output_queue,
                plan,
                project_dir
            )

            if passed:

                print("\n" + "=" * 70)

                print(
                    "🎉 BASE APPLICATION VERIFIED SUCCESSFULLY"
                )

                print("=" * 70)

                print(
                    "\n✅ Base functional tests passed."
                )

                print(
                    "\n⚔️ LAUNCHING DUAL-AI ADVERSARIAL ARENA (Good Cop vs Bad Cop)..."
                )

                def restart_app_server():
                    nonlocal process, output_queue
                    stop_application(process)
                    time.sleep(1)
                    p, q = start_application(
                        project_dir,
                        python_executable,
                        plan
                    )
                    process = p
                    output_queue = q
                    return process

                try:
                    arena = AdversarialArena(
                        client=client,
                        model=MODEL,
                        max_rounds=3
                    )
                    arena.conduct_duel(
                        project_dir,
                        restart_server_callback=restart_app_server
                    )
                except Exception as duel_err:
                    print(f"⚠️ Adversarial arena notice: {duel_err}")

                print("\n" + "=" * 70)
                print("🎉 DUAL-AI HARDENING & VERIFICATION COMPLETED")
                print("=" * 70)

                return process

            stop_application(process)

        # ----------------------------------------------------
        # FINAL ATTEMPT
        # ----------------------------------------------------

        if attempt >= MAX_REPAIR_ATTEMPTS:

            print(
                "\n❌ MAXIMUM REPAIR ATTEMPTS REACHED."
            )

            print(
                "The agent could not automatically repair "
                "the application."
            )

            return None

        # ----------------------------------------------------
        # AI REPAIR
        # ----------------------------------------------------

        repair = analyze_and_repair(
            project_dir,
            plan,
            failures,
            server_output,
            attempt
        )

        if not repair:

            print(
                "\n❌ AI could not produce a repair."
            )

            continue

        repaired = apply_repair(
            project_dir,
            repair
        )

        if not repaired:

            print(
                "\n❌ Repair could not be applied."
            )

            continue

        # ----------------------------------------------------
        # RECHECK DEPENDENCIES
        # ----------------------------------------------------

        print(
            "\n🔍 Rechecking dependencies after repair..."
        )

        try:

            python_executable = (
                setup_project_environment(
                    project_dir,
                    plan
                )
            )

        except Exception as e:

            print(
                f"\n⚠️ Dependency setup after repair "
                f"failed: {e}"
            )

    return None


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)

    print(
        "        AI AUTONOMOUS SOFTWARE DEVELOPMENT AGENT"
    )

    print("=" * 70)

    project_prompt = input(
        "\nDescribe the project you want to build:\n> "
    )

    try:

        # ====================================================
        # STEP 1: ANALYZE REQUIREMENTS
        # ====================================================

        print(
            "\n🧠 Analyzing requirements...\n"
        )

        plan = analyze_requirements(
            project_prompt
        )

        print(
            "✅ PROJECT PLAN GENERATED"
        )

        print("=" * 70)

        print(
            json.dumps(
                plan,
                indent=4
            )
        )

        # ====================================================
        # STEP 2: SAVE PLAN
        # ====================================================

        save_project_plan(plan)

        # ====================================================
        # STEP 3: CREATE STRUCTURE
        # ====================================================

        project_dir = create_project_structure(
            plan
        )

        # ====================================================
        # STEP 4: GENERATE CODE
        # ====================================================

        write_generated_code(
            project_dir,
            plan
        )

        print("\n" + "=" * 70)

        print(
            "🎉 PROJECT GENERATION FINISHED"
        )

        print("=" * 70)

        print(
            "\n📁 Project location:"
        )

        print(
            os.path.abspath(
                project_dir
            )
        )

        # ====================================================
        # STEP 5: SETUP ENVIRONMENT
        # ====================================================

        python_executable = (
            setup_project_environment(
                project_dir,
                plan
            )
        )

        # ====================================================
        # STEP 6-9:
        # RUN + TEST + REPAIR
        # ====================================================

        final_process = (
            autonomous_self_healing(
                project_dir,
                python_executable,
                plan
            )
        )

        # ====================================================
        # FINAL STATUS
        # ====================================================

        print("\n" + "=" * 70)

        print(
            "🤖 AUTONOMOUS DEVELOPMENT PIPELINE STATUS"
        )

        print("=" * 70)

        print(
            "\n✅ Requirements analyzed"
        )

        print(
            "✅ Project plan generated"
        )

        print(
            "✅ Project structure created"
        )

        print(
            "✅ Source code generated"
        )

        print(
            "✅ Isolated environment created"
        )

        print(
            "✅ Dependencies detected automatically"
        )

        print(
            "✅ Dependencies installed"
        )

        if final_process:

            print(
                "✅ Application started"
            )

            print(
                "✅ Automatic tests passed"
            )

            print(
                "✅ Runtime errors checked"
            )

            print(
                "✅ Application verified"
            )

            print(
                "\n🎉 AUTONOMOUS DEVELOPMENT COMPLETED"
            )

            print(
                "\n🌐 Application:"
            )

            print(
                "   http://127.0.0.1:5000"
            )

        else:

            print(
                "❌ Application could not be fully verified"
            )

    except json.JSONDecodeError:

        print(
            "\n❌ AI returned invalid JSON."
        )

    except subprocess.CalledProcessError as e:

        print(
            f"\n❌ Dependency installation failed: {e}"
        )

    except Exception as e:

        print(
            f"\n❌ Error: {e}"
        )


# ============================================================
# PROGRAM ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()