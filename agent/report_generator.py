"""
AEGIS Report & SARIF Generator
Produces human-readable markdown reports (report.md) and machine-readable
SARIF 2.1.0 (security_audit.sarif / audit_sarif.json) for audited projects.
"""

import os
import json
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple


def generate_markdown_report(project_dir: str, audit_data: Dict[str, Any]) -> str:
    """Generates a comprehensive report.md for an audited project."""
    project_name = audit_data.get("target_project") or os.path.basename(project_dir)
    ts = audit_data.get("timestamp", time.time())
    dt_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    score = audit_data.get("final_shield_health_score", "N/A")
    verdict = audit_data.get("audit_verdict", "N/A")
    total_breaches = audit_data.get("total_breaches_detected", 0)
    verified_fixes = audit_data.get("verified_fixes", 0)
    unresolved = audit_data.get("unresolved", 0)
    rounds = audit_data.get("total_duel_rounds", 1)
    
    duel_logs = audit_data.get("duel_logs", [])
    all_breaches: List[Dict[str, Any]] = []
    for log_entry in duel_logs:
        for b in log_entry.get("breaches", []):
            all_breaches.append(b)

    # Read poc.json if present for additional patch diff info
    poc_file = os.path.join(project_dir, "poc.json")
    poc_data = {}
    if os.path.exists(poc_file):
        try:
            with open(poc_file, "r", encoding="utf-8") as f:
                poc_data = json.load(f)
        except Exception:
            pass

    lines = [
        f"# AEGIS Security Audit & Verification Report",
        f"",
        f"**Target Project:** `{project_name}`  ",
        f"**Audit Timestamp:** {dt_str}  ",
        f"**Duel Rounds Executed:** {rounds}  ",
        f"**Measured Shield Score:** {score}  ",
        f"**Audit Verdict:** `{verdict}`  ",
        f"",
        f"---",
        f"",
        f"## Executive Summary",
        f"",
        f"| Metric | Measured Value |",
        f"|---|---|",
        f"| Total Breaches Detected | `{total_breaches}` |",
        f"| Verified Defensive Fixes | `{verified_fixes}` |",
        f"| Unresolved Breaches | `{unresolved}` |",
        f"| Patch Verification Gate Status | {'PASSED (Zero unresolved)' if unresolved == 0 and total_breaches > 0 else ('NO BREACHES FOUND' if total_breaches == 0 else 'ACTION REQUIRED (Unresolved items remain)')} |",
        f"",
        f"---",
        f"",
        f"## 1. Discovered Vulnerability Vectors",
        f""
    ]

    if not all_breaches:
        lines.append("_No breaches or crashes were triggered during the probe suite._\n")
    else:
        lines.append("| # | Vulnerability Type | Route | Method | Payload / Probe | Initial Status | Verification Status |")
        lines.append("|---|---|---|---|---|---|---|")
        for idx, b in enumerate(all_breaches, 1):
            v_type = b.get("type", "Unknown")
            route = b.get("route", "/")
            method = b.get("method", "GET")
            raw_payload = str(b.get("payload") or "N/A").replace("|", "\\|").replace("\n", " ")
            if len(raw_payload) > 35:
                raw_payload = raw_payload[:32] + "..."
            status_code = b.get("status_code", "Crash / 500")
            status = b.get("status", "UNRESOLVED")
            lines.append(f"| {idx} | {v_type} | `{route}` | {method} | `{raw_payload}` | {status_code} | **{status}** |")
        lines.append("")

    lines.extend([
        f"---",
        f"",
        f"## 2. Verified Defensive Fixes",
        f""
    ])

    verified_list = [b for b in all_breaches if b.get("status") == "VERIFIED_PATCHED"]
    if not verified_list:
        if total_breaches == 0:
            lines.append("_No breaches detected, no defensive patches required._\n")
        else:
            lines.append("_No patches successfully passed the Verified Patch Gate in this run._\n")
    else:
        for idx, vb in enumerate(verified_list, 1):
            lines.append(f"### Fix #{idx}: {vb.get('type')}")
            lines.append(f"- **Target Route:** `{vb.get('method', 'GET')} {vb.get('route', '/')}`")
            lines.append(f"- **Triggering Payload:** `{vb.get('payload')}`")
            lines.append(f"- **Verification Criteria Passed:**")
            lines.append(f"  - [x] Syntax check (`ast.parse`) verified patch compiles without errors.")
            lines.append(f"  - [x] Replay probe check: original payload no longer reproduces crash / breach.")
            lines.append(f"  - [x] Legitimate behavior test passed without functional regression.")
            if os.path.exists(os.path.join(project_dir, "regression_test.py")):
                lines.append(f"- **Regression Test Artifact:** [`regression_test.py`](./regression_test.py) generated.")
            lines.append("")

    lines.extend([
        f"---",
        f"",
        f"## 3. Unresolved Breaches & Manual Developer Action",
        f""
    ])

    unresolved_list = [b for b in all_breaches if b.get("status") != "VERIFIED_PATCHED"]
    if not unresolved_list:
        lines.append("All detected probes were successfully mitigated and verified. No unresolved items remain from this test run.\n")
    else:
        lines.append(f"> [!WARNING]")
        lines.append(f"> **{len(unresolved_list)} vulnerability vector(s) remain unresolved.** Manual developer intervention is required.\n")
        for idx, ub in enumerate(unresolved_list, 1):
            lines.append(f"### Unresolved #{idx}: {ub.get('type')}")
            lines.append(f"- **Endpoint:** `{ub.get('method', 'GET')} {ub.get('route', '/')}`")
            lines.append(f"- **Trigger Payload:** `{ub.get('payload')}`")
            lines.append(f"- **Failure Details:** {ub.get('details', 'Crash on probe')}")
            lines.append(f"- **Recommended Manual Remediation:**")
            vtype = ub.get("type", "").lower()
            if "sql" in vtype:
                lines.append(f"  - Replace raw SQL string formatting with parameterized queries or ORM models (`filter_by`, parameterized SQLAlchemy).")
            elif "xss" in vtype:
                lines.append(f"  - Sanitize user output using proper Jinja2 autoescaping (`markupsafe.escape`) or context-aware escaping.")
            elif "ssti" in vtype or "template" in vtype:
                lines.append(f"  - Never invoke `render_template_string` on unvalidated user input. Use static template files with strict variable binding.")
            elif "traversal" in vtype or "path" in vtype:
                lines.append(f"  - Use `os.path.realpath` and `os.path.commonpath` verification (e.g. `safe_join`) to ensure file requests stay confined to the root.")
            else:
                lines.append(f"  - Implement strict request payload schema validation, bounds checking, and structured exception handling (`try...except`).")
            lines.append("")

    lines.extend([
        f"---",
        f"",
        f"## 4. Scope & Limitations of This Audit",
        f"",
        f"### Probes Evaluated",
        f"The Hacker agent evaluated the following probe categories:",
        f"- 404 Route & Boundary Handling",
        f"- Empty Form & Whitespace Probes",
        f"- Unicode & Buffer Overflow Probes",
        f"- Authentication Bypass & Session Tampering",
        f"- SQL Injection Probes (Basic Pattern Checks)",
        f"- Reflected Cross-Site Scripting (XSS Reflection Checks)",
        f"- Server-Side Template Injection (SSTI Evaluation Checks)",
        f"- IDOR / Object Access Boundary Probes",
        f"- Auth Concurrency & Burst DoS Probes",
        f"",
        f"### Known Limitations",
        f"- **Fuzzer Mechanics:** Hacker AI is a rule-based HTTP payload fuzzer with heuristic detection (primarily identifying HTTP 500 crashes and specific reflection patterns). It does not conduct deep symbolic execution or taint tracking.",
        f"- **No Proof of Absence:** A score of 'all probes passed' indicates resilience against the specific payload suite executed; it does NOT constitute a formal proof of security or an exhaustive OWASP certification.",
        f"- **Code Execution Sandbox Requirement:** Applications and fuzzing probes run active Python server code. Always execute within isolated Docker containers or sandboxed environments.",
        f""
    ])

    report_content = "\n".join(lines)
    report_path = os.path.join(project_dir, "report.md")
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)
    except Exception:
        pass

    return report_content


def generate_sarif_report(project_dir: str, audit_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generates a SARIF 2.1.0 compliant report for integration with
    GitHub Code Scanning, CI/CD pipelines, and security dashboards.
    """
    rules: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []
    rule_ids = set()

    duel_logs = audit_data.get("duel_logs", [])
    for log_entry in duel_logs:
        for b in log_entry.get("breaches", []):
            vtype = b.get("type", "SecurityProbe")
            rule_id = "AEGIS-" + "".join(c if c.isalnum() else "_" for c in vtype).strip("_")
            if rule_id not in rule_ids:
                rule_ids.add(rule_id)
                rules.append({
                    "id": rule_id,
                    "name": vtype,
                    "shortDescription": {
                        "text": f"AEGIS probe detected vulnerability: {vtype}"
                    },
                    "fullDescription": {
                        "text": f"Automated probe vector on endpoint '{b.get('route')}' triggered breach condition: {b.get('details', '')}"
                    },
                    "defaultConfiguration": {
                        "level": "error" if b.get("status") != "VERIFIED_PATCHED" else "note"
                    }
                })

            is_verified = (b.get("status") == "VERIFIED_PATCHED")
            results.append({
                "ruleId": rule_id,
                "level": "note" if is_verified else "error",
                "message": {
                    "text": f"[{'MITIGATED' if is_verified else 'UNRESOLVED'}] {b.get('type')} on {b.get('method')} {b.get('route')}. Payload: {b.get('payload')}"
                },
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": "app.py"
                            },
                            "region": {
                                "startLine": 1
                            }
                        }
                    }
                ],
                "properties": {
                    "route": b.get("route"),
                    "method": b.get("method"),
                    "status": b.get("status"),
                    "details": b.get("details")
                }
            })

    sarif_doc = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "AEGIS-Adversarial-Arena",
                        "semanticVersion": "2.0.0",
                        "informationUri": "https://github.com/Harsh-empire/AI-Autonomous-Software-Agent",
                        "rules": rules
                    }
                },
                "results": results
            }
        ]
    }

    # Write both audit_sarif.json and security_audit.sarif
    for fname in ["audit_sarif.json", "security_audit.sarif"]:
        out_path = os.path.join(project_dir, fname)
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(sarif_doc, f, indent=2)
        except Exception:
            pass

    return sarif_doc


def generate_project_report(project_dir: str, audit_data: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Generates both Markdown report and SARIF 2.1.0 document."""
    md_content = generate_markdown_report(project_dir, audit_data)
    sarif_doc = generate_sarif_report(project_dir, audit_data)
    return md_content, sarif_doc
