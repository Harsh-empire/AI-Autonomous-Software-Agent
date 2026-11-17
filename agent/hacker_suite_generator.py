"""
Hacker Attack Vector Generator & Security Fuzzer
Generates red-team adversarial attack payloads and scans application endpoints.
"""

import ast
import os
import re
from typing import List, Dict, Any


# Standard adversarial payloads used by the Hacker AI (OWASP Top 10)
ADVERSARIAL_PAYLOADS = {
    "sql_injection": [
        "' OR '1'='1",
        "admin' --",
        "' UNION SELECT 1, 'admin', 'password' --",
        "1; DROP TABLE tasks; --",
        "' OR 1=1#"
    ],
    "xss_script_injection": [
        "<script>alert('PWNED')</script>",
        "<img src=x onerror=alert('PWNED')>",
        "\"><script>document.location='http://evil.com'</script>",
        "javascript:alert(1)"
    ],
    "ssti_template_injection": [
        "{{7*7}}",
        "{{config}}",
        "{{self.__init__.__globals__.__builtins__}}",
        "${7*7}",
        "<%= 7*7 %>"
    ],
    "command_injection": [
        "; whoami",
        "| whoami",
        "& echo PWNED &",
        "`id`",
        "$(whoami)"
    ],
    "path_traversal": [
        "../../../../etc/passwd",
        "..\\..\\..\\windows\\system32\\cmd.exe",
        "....//....//....//etc/shadow",
        "../../../app.py"
    ],
    "fuzzing_boundary": [
        "",                     # Empty string
        "   ",                  # Pure whitespace
        "A" * 5000,             # Overflow string
        "🚀💥🔥☠️👻🤖👾",       # Multi-byte UTF-8 emojis
        "\x00\x01\x02\x03",     # Null bytes and control characters
        "-9999999999",          # Extreme negative numbers
        "999999999999999999999",# Extreme integer overflow
        "None",                 # Literal 'None' string
        "NaN",                  # Float NaN
        "true",                 # Boolean string
        "1e308"                 # Float limit
    ],
    "traversal_and_malicious": [
        "../../../../etc/passwd",
        "..\\..\\..\\windows\\system32\\cmd.exe",
        "https://evil-phishing-site.com",
        "{{7*7}}"               # Jinja template injection probe
    ]
}



def scan_flask_endpoints(project_dir: str) -> List[Dict[str, Any]]:
    """
    Statically analyzes project files to discover all routes, accepted HTTP methods,
    and parameter names from form inputs.
    """
    endpoints = []
    
    ignored_dirs = {".venv", "venv", "__pycache__", ".git"}

    # 1. Scan python files for @app.route
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in ignored_dirs]
        for file in files:
            if not file.endswith(".py"):
                continue
            py_path = os.path.join(root, file)
            try:
                with open(py_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    
                # Match @app.route('...', methods=[...])
                matches = re.finditer(r"@\w+\.route\(\s*['\"]([^'\"]+)['\"](?:\s*,\s*methods\s*=\s*(\[[^\]]+\]))?", content)
                for m in matches:
                    route = m.group(1)
                    methods_str = m.group(2)
                    methods = ["GET"]
                    if methods_str:
                        methods = [verb.strip(" '\"") for verb in methods_str.strip("[]").split(",") if verb.strip()]
                    endpoints.append({
                        "route": route,
                        "methods": methods,
                        "source_file": file
                    })
            except Exception:
                continue

    # 2. Scan HTML templates for form inputs and actions
    forms = []
    templates_dir = os.path.join(project_dir, "templates")
    if os.path.exists(templates_dir):
        for root, dirs, files in os.walk(templates_dir):
            dirs[:] = [d for d in dirs if d not in ignored_dirs]
            for file in files:
                if not file.endswith(".html"):
                    continue
                html_path = os.path.join(root, file)
                try:
                    with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
                        html_content = f.read()
                    
                    # Extract input names
                    input_names = re.findall(r'<input[^>]+name=[\'"]([^\'"]+)[\'"]', html_content, re.IGNORECASE)
                    textarea_names = re.findall(r'<textarea[^>]+name=[\'"]([^\'"]+)[\'"]', html_content, re.IGNORECASE)
                    all_fields = list(set(input_names + textarea_names))
                    
                    # Extract form action and method using robust attribute regex
                    form_tags = re.findall(r'<form\b([^>]+)>', html_content, re.IGNORECASE)
                    for attrs in form_tags:
                        action_match = re.search(r'action=(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))', attrs, re.IGNORECASE)
                        method_match = re.search(r'method=(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))', attrs, re.IGNORECASE)
                        
                        raw_action = ""
                        if action_match:
                            raw_action = action_match.group(1) or action_match.group(2) or action_match.group(3) or ""
                        
                        raw_method = "POST"
                        if method_match:
                            m_val = method_match.group(1) or method_match.group(2) or method_match.group(3) or "POST"
                            raw_method = m_val.upper()
                        
                        # Resolve url_for('name')
                        resolved_action = raw_action
                        url_for_match = re.search(r"url_for\(\s*['\"]([^'\"]+)['\"]", raw_action)
                        if url_for_match:
                            func_name = url_for_match.group(1)
                            resolved_action = f"/{func_name}" if func_name != "index" else "/"
                        elif not resolved_action:
                            resolved_action = "/"

                        forms.append({
                            "action": resolved_action,
                            "method": raw_method,
                            "fields": all_fields,
                            "template": file
                        })
                except Exception:
                    continue

    return {
        "endpoints": endpoints,
        "forms": forms
    }
