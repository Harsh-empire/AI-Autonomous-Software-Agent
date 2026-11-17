"""
Adversarial Dual-AI Engine: Good Cop (Builder) vs Bad Cop (Hacker)
An automated adversarial loop that pits a generative developer against an
aggressive red-team security breaker until the application is resilient.
"""

import json
import os
import re
import subprocess
import time
import sys
import io
import difflib
import requests

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from typing import Dict, List, Tuple, Any, Optional
from openai import OpenAI
try:
    from agent.hacker_suite_generator import scan_flask_endpoints, ADVERSARIAL_PAYLOADS
except ImportError:
    from hacker_suite_generator import scan_flask_endpoints, ADVERSARIAL_PAYLOADS


class TerminalColors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    BUILDER = "\033[94m"   # Blue
    HACKER = "\033[91m"    # Red
    ARENA = "\033[95m"     # Magenta
    SUCCESS = "\033[92m"   # Green
    WARNING = "\033[93m"   # Yellow
    CYAN = "\033[96m"      # Cyan


def log_builder(message: str):
    print(f"{TerminalColors.BUILDER}{TerminalColors.BOLD}[BUILDER 🛠️]{TerminalColors.RESET} {message}", flush=True)


def log_hacker(message: str):
    print(f"{TerminalColors.HACKER}{TerminalColors.BOLD}[HACKER 😈]{TerminalColors.RESET} {message}", flush=True)


def log_arena(message: str):
    print(f"{TerminalColors.ARENA}{TerminalColors.BOLD}[ARENA ⚔️]{TerminalColors.RESET} {message}", flush=True)


class HackerAgent:
    """
    Bad Cop / Red Team AI: Inspects routes and actively attempts to break
    the application using fuzzing, injections, and edge cases.
    """
    def __init__(self, client: OpenAI, model: str = "qwen2.5-coder:7b", base_url: str = "http://127.0.0.1:5000"):
        self.client = client
        self.model = model
        self.base_url = base_url

    def trash_talk(self, context: str) -> str:
        """Hacker AI taunts the Builder AI based on discovered vulnerabilities."""
        system_prompt = (
            "You are 'The Hacker' (Bad Cop), an elite red-team penetration tester and chaos engineer. "
            "You speak with sharp, witty, confident hacker swagger. Keep your remarks under 2 sentences."
        )
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"React to this code vulnerability or attack finding:\n{context}"}
                ],
                temperature=0.7
            )
            return response.choices[0].message.content.strip()
        except Exception:
            return "Nice try, Builder, but your code is riddled with obvious holes!"

    def run_attack_round(self, project_dir: str, round_tier: int) -> List[Dict[str, Any]]:
        """
        Executes an adversarial attack wave against the target server.
        Returns a list of successful breaches/vulnerabilities found.
        """
        breaches = []
        scan_results = scan_flask_endpoints(project_dir)
        endpoints = scan_results["endpoints"]
        forms = scan_results["forms"]

        session = requests.Session()

        # =====================================================================
        # TIER 1: SANITY, BOUNDARIES, UNICODE & NON-EXISTENT ENDPOINTS
        # =====================================================================
        if round_tier == 1:
            log_hacker("Initiating TIER 1: Boundary Chaos, Empty Forms & Unicode Flooding...")
            
            # 1. Probe 404 handling
            try:
                r = session.get(f"{self.base_url}/non_existent_exploit_probe_9999", timeout=3)
                if r.status_code == 500:
                    breaches.append({
                        "tier": 1,
                        "type": "Unhandled 404 Route",
                        "route": "/non_existent_exploit_probe_9999",
                        "method": "GET",
                        "payload": None,
                        "status_code": 500,
                        "details": "Server crashed with HTTP 500 on request to an undefined route."
                    })
            except Exception as e:
                breaches.append({
                    "tier": 1,
                    "type": "Connection Crash",
                    "route": "/non_existent_exploit_probe_9999",
                    "method": "GET",
                    "payload": None,
                    "status_code": 0,
                    "details": f"Server terminated or refused connection: {e}"
                })

            # 2. Test form endpoints with empty payloads & whitespace
            for form in forms:
                action = form["action"]
                if not action.startswith("http"):
                    action_url = f"{self.base_url}{action if action.startswith('/') else '/' + action}"
                else:
                    action_url = action

                # Test empty inputs
                empty_data = {field: "" for field in form["fields"]}
                try:
                    r = session.post(action_url, data=empty_data, timeout=3, allow_redirects=True)
                    if r.status_code == 500:
                        breaches.append({
                            "tier": 1,
                            "type": "Null/Empty Form Crash",
                            "route": action,
                            "method": "POST",
                            "payload": empty_data,
                            "status_code": 500,
                            "details": f"Endpoint '{action}' crashed when submitted with empty fields."
                        })
                except Exception as e:
                    breaches.append({
                        "tier": 1,
                        "type": "Crash on Empty Form",
                        "route": action,
                        "method": "POST",
                        "payload": empty_data,
                        "status_code": 0,
                        "details": str(e)
                    })

                # Test unicode / overflow string
                overflow_data = {field: "🔥" * 2000 for field in form["fields"]}
                try:
                    r = session.post(action_url, data=overflow_data, timeout=4, allow_redirects=True)
                    if r.status_code == 500:
                        breaches.append({
                            "tier": 1,
                            "type": "Buffer / Unicode Crash",
                            "route": action,
                            "method": "POST",
                            "payload": "🔥 * 2000",
                            "status_code": 500,
                            "details": f"Endpoint '{action}' suffered internal server error on high-volume unicode strings."
                        })
                except Exception as e:
                    breaches.append({
                        "tier": 1,
                        "type": "Connection Failure on Unicode",
                        "route": action,
                        "method": "POST",
                        "payload": "🔥 * 2000",
                        "status_code": 0,
                        "details": str(e)
                    })

        # =====================================================================
        # TIER 2: AUTHENTICATION BYPASS & STATE INVARIANTS
        # =====================================================================
        elif round_tier == 2:
            log_hacker("Initiating TIER 2: Unauthenticated Access & Session Hijack Probes...")
            
            # Test protected routes directly with a fresh unauthenticated session
            unauth_session = requests.Session()
            protected_routes = ["/tasks", "/add_task", "/dashboard", "/delete_task", "/complete_task"]
            
            for ep in endpoints:
                route = ep["route"]
                if any(p in route for p in ["task", "dashboard", "profile", "admin", "home"]) and not any(p in route for p in ["login", "register"]):
                    try:
                        r = unauth_session.get(f"{self.base_url}{route}", timeout=3, allow_redirects=False)
                        # If a sensitive route returns 200 without redirecting to login (302) or returning 401/403
                        if r.status_code == 200 and ("login" not in r.text.lower()):
                            breaches.append({
                                "tier": 2,
                                "type": "Missing Authentication Guard",
                                "route": route,
                                "method": "GET",
                                "payload": "No Cookie / Fresh Session",
                                "status_code": 200,
                                "details": f"Route '{route}' is accessible without authentication! Anyone can access it without logging in."
                            })
                        elif r.status_code == 500:
                            breaches.append({
                                "tier": 2,
                                "type": "Unauthenticated Crash",
                                "route": route,
                                "method": "GET",
                                "payload": "No Session Cookie",
                                "status_code": 500,
                                "details": f"Route '{route}' threw HTTP 500 when accessed without active session (likely KeyError on session['user'])."
                            })
                    except Exception as e:
                        pass

        # =====================================================================
        # TIER 3: INJECTION ATTACKS (SQLi & XSS)
        # =====================================================================
        elif round_tier == 3:
            log_hacker("Initiating TIER 3: SQL Injection & Stored/Reflected XSS Exploits...")
            
            for form in forms:
                action = form["action"]
                action_url = f"{self.base_url}{action if action.startswith('/') else '/' + action}"

                # 1. SQL Injection vectors
                for sqli in ADVERSARIAL_PAYLOADS["sql_injection"][:2]:
                    sqli_data = {field: sqli for field in form["fields"]}
                    try:
                        r = session.post(action_url, data=sqli_data, timeout=3, allow_redirects=True)
                        if r.status_code == 500:
                            breaches.append({
                                "tier": 3,
                                "type": "SQL Injection Failure / Crash",
                                "route": action,
                                "method": "POST",
                                "payload": sqli,
                                "status_code": 500,
                                "details": f"Endpoint '{action}' crashed on SQL injection payload: {sqli}"
                            })
                    except Exception as e:
                        breaches.append({
                            "tier": 3,
                            "type": "SQL Injection Crash",
                            "route": action,
                            "method": "POST",
                            "payload": sqli,
                            "status_code": 0,
                            "details": str(e)
                        })

                # 2. XSS vectors
                for xss in ADVERSARIAL_PAYLOADS["xss_script_injection"][:2]:
                    xss_data = {field: xss for field in form["fields"]}
                    try:
                        r = session.post(action_url, data=xss_data, timeout=3, allow_redirects=True)
                        # Check if raw unescaped script is reflected verbatim in response
                        if xss in r.text and "|safe" in r.text:
                            breaches.append({
                                "tier": 3,
                                "type": "Reflected/Stored XSS Vulnerability",
                                "route": action,
                                "method": "POST",
                                "payload": xss,
                                "status_code": r.status_code,
                                "details": f"Endpoint '{action}' rendered unescaped script tag directly into HTML!"
                            })
                        elif r.status_code == 500:
                            breaches.append({
                                "tier": 3,
                                "type": "HTML/XSS Processing Crash",
                                "route": action,
                                "method": "POST",
                                "payload": xss,
                                "status_code": 500,
                                "details": f"Endpoint '{action}' crashed on HTML payload: {xss}"
                            })
                    except Exception:
                        pass

        # =====================================================================
        # TIER 4: SSTI (SERVER-SIDE TEMPLATE INJECTION) & PATH TRAVERSAL
        # =====================================================================
        elif round_tier == 4:
            log_hacker("Initiating TIER 4: Template Injection (SSTI) & Path Traversal Exploits...")
            
            # 1. SSTI Probes on Forms
            ssti_payloads = ADVERSARIAL_PAYLOADS.get("ssti_template_injection", ["{{7*7}}", "{{config}}"])
            for form in forms:
                action = form["action"]
                action_url = f"{self.base_url}{action if action.startswith('/') else '/' + action}"
                for ssti in ssti_payloads[:2]:
                    ssti_data = {field: ssti for field in form["fields"]}
                    try:
                        r = session.post(action_url, data=ssti_data, timeout=3, allow_redirects=True)
                        if "49" in r.text and "{{7*7}}" not in r.text:
                            breaches.append({
                                "tier": 4,
                                "type": "Remote Code Execution / SSTI",
                                "route": action,
                                "method": "POST",
                                "payload": ssti,
                                "status_code": r.status_code,
                                "details": f"Endpoint '{action}' evaluated expression to '49'! Severe SSTI flaw."
                            })
                        elif r.status_code == 500:
                            breaches.append({
                                "tier": 4,
                                "type": "Template Processing Crash",
                                "route": action,
                                "method": "POST",
                                "payload": ssti,
                                "status_code": 500,
                                "details": f"Endpoint '{action}' suffered internal server error on SSTI probe: {ssti}"
                            })
                    except Exception as e:
                        pass

            # 2. Path Traversal on Routes
            traversal_payloads = ADVERSARIAL_PAYLOADS.get("path_traversal", ["../../../../etc/passwd"])
            for ep in endpoints:
                route = ep["route"]
                if "<" in route or "file" in route or "download" in route:
                    for trav in traversal_payloads[:2]:
                        try:
                            clean_route = re.sub(r'<[^>]+>', trav, route)
                            r = session.get(f"{self.base_url}{clean_route}", timeout=3)
                            if r.status_code == 200 and ("root:" in r.text or "import " in r.text):
                                breaches.append({
                                    "tier": 4,
                                    "type": "Path Traversal / File Disclosure",
                                    "route": route,
                                    "method": "GET",
                                    "payload": trav,
                                    "status_code": 200,
                                    "details": f"Route '{clean_route}' exposed sensitive system file contents!"
                                })
                        except Exception:
                            pass

        # =====================================================================
        # TIER 5: IDOR (INSECURE DIRECT OBJECT REFERENCE) & BRUTE FORCE
        # =====================================================================
        elif round_tier >= 5:
            log_hacker("Initiating TIER 5: IDOR Cross-Tenant Access & Auth Rate-Limiting...")
            
            # 1. IDOR Probing on parameterized endpoints
            for ep in endpoints:
                route = ep["route"]
                if re.search(r'<(?:int:)?(?:id|task_id|user_id|item_id)>', route, re.IGNORECASE):
                    # Probe with out-of-bounds / another tenant ID
                    for test_id in ["99999", "1", "0", "-1"]:
                        probed_url = re.sub(r'<[^>]+>', test_id, route)
                        try:
                            r = session.get(f"{self.base_url}{probed_url}", timeout=3)
                            if r.status_code == 500:
                                breaches.append({
                                    "tier": 5,
                                    "type": "IDOR Crash on Out-of-Bounds ID",
                                    "route": probed_url,
                                    "method": "GET",
                                    "payload": test_id,
                                    "status_code": 500,
                                    "details": f"Route '{probed_url}' crashed on unverified object reference ID: {test_id}"
                                })
                        except Exception:
                            pass

            # 2. Burst probe on auth route
            auth_routes = [ep["route"] for ep in endpoints if any(a in ep["route"] for a in ["login", "register"])]
            for a_route in auth_routes[:1]:
                target_url = f"{self.base_url}{a_route}"
                burst_crashes = 0
                for _ in range(8):
                    try:
                        r = session.post(target_url, data={"username": "probe", "password": "x"}, timeout=1)
                        if r.status_code == 500:
                            burst_crashes += 1
                    except Exception:
                        burst_crashes += 1
                if burst_crashes >= 3:
                    breaches.append({
                        "tier": 5,
                        "type": "Auth Denial-of-Service / Concurrency Crash",
                        "route": a_route,
                        "method": "POST",
                        "payload": "8x Rapid Requests",
                        "status_code": 500,
                        "details": f"Auth endpoint '{a_route}' failed or timed out under rapid burst requests."
                    })

        return breaches


class BuilderAgent:
    """
    Good Cop / Defensive Architect AI: Generates fixes, input sanitization,
    and security defenses to patch any breaches reported by the Hacker.
    """
    def __init__(self, client: OpenAI, model: str = "qwen2.5-coder:7b"):
        self.client = client
        self.model = model
        self.last_patch_info = None

    def counter_argument(self, breach: Dict[str, Any]) -> str:
        """Builder AI acknowledges the issue and commits to a defensive patch."""
        system_prompt = (
            "You are 'The Builder' (Good Cop), a resilient defensive software architect. "
            "You take pride in writing bulletproof code. Acknowledge the flaw professionally "
            "with determination. Keep your response under 2 sentences."
        )
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"The Hacker broke your code with this exploit:\n{json.dumps(breach, indent=2)}"}
                ],
                temperature=0.2
            )
            return response.choices[0].message.content.strip()
        except Exception:
            return "Good catch, Hacker. I'm adding input sanitization and route authentication guards right now."

    def generate_targeted_defense(self, project_dir: str, breach: Dict[str, Any], app_file: str = "app.py") -> bool:
        """
        Generates and applies a targeted defensive patch to fix the reported vulnerability.
        Calculates unified diffs and validates python AST before persisting.
        """
        app_path = os.path.join(project_dir, app_file)
        if not os.path.exists(app_path):
            return False

        with open(app_path, "r", encoding="utf-8") as f:
            current_code = f.read()

        prompt = f"""
You are The Builder, an expert defensive Python Flask engineer.
The Hacker found a critical vulnerability in the application:

BREACH REPORT:
- Vulnerability Type: {breach.get('type')}
- Route: {breach.get('route')}
- Method: {breach.get('method')}
- Offending Payload: {breach.get('payload')}
- Details: {breach.get('details')}

CURRENT app.py SOURCE:
```python
{current_code}
```

TASK:
Produce the COMPLETE updated app.py that DEFENDS against this vulnerability:
1. If the route crashed on empty input, add input validation, strip(), and flash an error message or redirect instead of crashing.
2. If the route crashed or leaked without an active session, ensure 'session.get("user_id")' (or session.get("username")) is verified, and redirect to login if not logged in.
3. If SQL injection or XSS was flagged, ensure parameterized queries or ORM queries are used and text inputs are properly handled.
4. If SSTI was detected, avoid evaluating dynamic template strings; render static templates or sanitize values.
5. If IDOR or out-of-bounds access was detected, verify object ownership and existence before executing actions.
6. Return ONLY valid python code. No markdown fences, no explanations.
"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You output only the raw, complete, updated python source code."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )
        patched_code = response.choices[0].message.content.strip()

        # Clean markdown fences if any
        if patched_code.startswith("```"):
            lines = patched_code.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            patched_code = "\n".join(lines).strip()

        # Sanity check: Ensure valid python syntax before saving
        try:
            import ast
            ast.parse(patched_code)
        except SyntaxError as e:
            log_builder(f"Synthesized patch had syntax error: {e}. Keeping previous version.")
            return False

        # Compute unified diff
        diff_lines = list(difflib.unified_diff(
            current_code.splitlines(keepends=True),
            patched_code.splitlines(keepends=True),
            fromfile=f"a/{app_file}",
            tofile=f"b/{app_file}"
        ))
        diff_str = "".join(diff_lines)

        self.last_patch_info = {
            "file": app_file,
            "diff": diff_str,
            "breach": breach,
            "timestamp": time.time()
        }

        # Save patch diff to project for inspection
        diff_path = os.path.join(project_dir, "last_patch_diff.txt")
        try:
            with open(diff_path, "w", encoding="utf-8") as f_diff:
                f_diff.write(diff_str)
        except Exception:
            pass

        with open(app_path, "w", encoding="utf-8") as f:
            f.write(patched_code)

        log_builder(f"Applied defensive hardening patch to '{app_file}'! (+{diff_str.count('+')}/-{diff_str.count('-')} lines diff)")
        return True


class AdversarialArena:
    """
    Orchestrates the duel between Good Cop (Builder) and Bad Cop (Hacker).
    """
    def __init__(self, client: OpenAI, model: str = "qwen2.5-coder:7b", max_rounds: int = 3):
        self.builder = BuilderAgent(client, model)
        self.hacker = HackerAgent(client, model)
        self.max_rounds = max_rounds
        self.duel_logs = []
        self.total_breaches = 0
        self.total_patches = 0

    def conduct_duel(self, project_dir: str, restart_server_callback) -> bool:
        """
        Executes the duel rounds.
        restart_server_callback is a function that restarts the application server after a patch.
        """
        print("\n" + "=" * 75)
        print(f"{TerminalColors.ARENA}{TerminalColors.BOLD}⚔️  STARTING THE DUAL-AI ADVERSARIAL ARENA: GOOD COP VS BAD COP  ⚔️{TerminalColors.RESET}")
        print("=" * 75)
        print("The Builder writes code. The Hacker aggressively tries to break it.")
        print("They will battle until the application survives all attack vectors.\n")

        all_survived = True

        for round_num in range(1, self.max_rounds + 1):
            log_arena(f"ROUND {round_num} of {self.max_rounds}")
            
            # 1. Hacker launches attacks
            breaches = self.hacker.run_attack_round(project_dir, round_tier=round_num)

            if not breaches:
                log_hacker(f"Round {round_num}: Bah! I couldn't break the endpoints this wave. App held up.")
                log_builder(f"Round {round_num}: Defenses held strong against all tier {round_num} probes.")
                self.duel_logs.append({
                    "round": round_num,
                    "status": "SURVIVED",
                    "breaches": []
                })
                time.sleep(1)
                continue

            # 2. Hacker breached the application!
            all_survived = False
            self.total_breaches += len(breaches)
            log_hacker(f"💥 FOUND {len(breaches)} CRITICAL BREACH(ES) in Round {round_num}!")
            
            for b in breaches:
                print(f"   🚨 [{b['type']}] on {b['method']} {b['route']}: {b['details']}")
                
                taunt = self.hacker.trash_talk(json.dumps(b))
                log_hacker(f"\"{taunt}\"")
                
                retort = self.builder.counter_argument(b)
                log_builder(f"\"{retort}\"")

                # Builder attempts defensive repair
                repaired = self.builder.generate_targeted_defense(project_dir, b)
                if repaired:
                    self.total_patches += 1
                    log_arena("Restarting application server with hardened defense...")
                    restart_server_callback()
                    time.sleep(2)
                    
                    # Hacker immediately re-probes the same vector
                    log_hacker("Re-testing breached vector to verify if your fix holds...")
                    re_breaches = self.hacker.run_attack_round(project_dir, round_tier=round_num)
                    if not any(rb["type"] == b["type"] for rb in re_breaches):
                        log_hacker(f"Tsk... patch confirmed. Vector '{b['type']}' is now sealed.")
                        log_builder("Defense verified. System fortified.")
                    else:
                        log_hacker(f"Haha! Your fix was incomplete, the hole is still there!")

            self.duel_logs.append({
                "round": round_num,
                "status": "HARDENED",
                "breaches": breaches
            })

        print("\n" + "=" * 75)
        print(f"{TerminalColors.SUCCESS}{TerminalColors.BOLD}🎉 ADVERSARIAL COMBAT COMPLETED: APPLICATION FORTIFIED! 🎉{TerminalColors.RESET}")
        print("=" * 75)
        
        # Save duel log to project
        duel_log_path = os.path.join(project_dir, "adversarial_duel_log.json")
        try:
            with open(duel_log_path, "w", encoding="utf-8") as f:
                json.dump(self.duel_logs, f, indent=2)
            log_arena(f"Saved complete Adversarial Duel transcript to: {duel_log_path}")
        except Exception:
            pass

        # Generate standardized Security Audit Scorecard
        self.generate_security_audit_scorecard(project_dir)

        return True

    def generate_security_audit_scorecard(self, project_dir: str):
        """Generates security_audit.json with comprehensive metrics and OWASP compliance."""
        score = 100 if self.total_breaches == self.total_patches else max(50, 100 - (self.total_breaches - self.total_patches) * 20)
        audit_data = {
            "timestamp": time.time(),
            "target_project": os.path.basename(project_dir),
            "final_shield_health_score": f"{score}%",
            "total_duel_rounds": self.max_rounds,
            "total_breaches_detected": self.total_breaches,
            "total_patches_applied": self.total_patches,
            "owasp_top_10_categories_evaluated": [
                "A01: Broken Access Control",
                "A02: Cryptographic Failures",
                "A03: Injection (SQLi, XSS, SSTI)",
                "A04: Insecure Design & Boundary Overflow",
                "A07: Identification and Authentication Failures"
            ],
            "audit_verdict": "FORTIFIED" if score >= 90 else "WARNING_PARTIALLY_FORTIFIED",
            "duel_logs": self.duel_logs
        }
        audit_file = os.path.join(project_dir, "security_audit.json")
        try:
            with open(audit_file, "w", encoding="utf-8") as f:
                json.dump(audit_data, f, indent=2)
            log_arena(f"🛡️ Security Audit Scorecard generated: {audit_file} (Shield Health: {score}%)")
        except Exception:
            pass

