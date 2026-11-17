"""
Unit tests for the AEGIS Report & SARIF Generator.
"""

import os
import json
import tempfile
from agent.report_generator import generate_project_report, generate_markdown_report, generate_sarif_report


def test_report_generation_with_unresolved_and_verified_breaches():
    with tempfile.TemporaryDirectory() as tmp_dir:
        audit_data = {
            "timestamp": 1700000000,
            "target_project": "test_app",
            "final_shield_health_score": "50%",
            "total_duel_rounds": 2,
            "total_breaches_detected": 2,
            "verified_fixes": 1,
            "unresolved": 1,
            "audit_verdict": "1 unresolved",
            "duel_logs": [
                {
                    "round": 1,
                    "status": "PARTIAL",
                    "breaches": [
                        {
                            "tier": 3,
                            "type": "SQL Injection",
                            "route": "/login",
                            "method": "POST",
                            "payload": "' OR 1=1 --",
                            "status_code": 500,
                            "status": "VERIFIED_PATCHED",
                            "details": "Crash on SQL injection"
                        },
                        {
                            "tier": 3,
                            "type": "Reflected XSS",
                            "route": "/search",
                            "method": "GET",
                            "payload": "<script>alert(1)</script>",
                            "status_code": 200,
                            "status": "UNRESOLVED",
                            "details": "Payload reflected in DOM"
                        }
                    ]
                }
            ]
        }

        md_content, sarif_doc = generate_project_report(tmp_dir, audit_data)

        # 1. Check report.md exists and contains required sections
        report_file = os.path.join(tmp_dir, "report.md")
        assert os.path.exists(report_file)
        with open(report_file, "r", encoding="utf-8") as f:
            content = f.read()

        assert "AEGIS Security Audit & Verification Report" in content
        assert "50%" in content
        assert "1 unresolved" in content
        assert "SQL Injection" in content
        assert "Reflected XSS" in content
        assert "Verified Defensive Fixes" in content
        assert "Unresolved Breaches & Manual Developer Action" in content
        assert "Known Limitations" in content

        # 2. Check SARIF output
        sarif_file = os.path.join(tmp_dir, "security_audit.sarif")
        assert os.path.exists(sarif_file)
        assert sarif_doc["version"] == "2.1.0"
        results = sarif_doc["runs"][0]["results"]
        assert len(results) == 2
        
        # SQL injection is verified -> level note
        sqli_result = [r for r in results if "SQL_Injection" in r["ruleId"]][0]
        assert sqli_result["level"] == "note"

        # XSS is unresolved -> level error
        xss_result = [r for r in results if "Reflected_XSS" in r["ruleId"]][0]
        assert xss_result["level"] == "error"


def test_report_generation_clean_run():
    with tempfile.TemporaryDirectory() as tmp_dir:
        audit_data = {
            "timestamp": 1700000000,
            "target_project": "clean_app",
            "final_shield_health_score": "no breaches found",
            "total_duel_rounds": 1,
            "total_breaches_detected": 0,
            "verified_fixes": 0,
            "unresolved": 0,
            "audit_verdict": "no breaches found",
            "duel_logs": []
        }

        md_content, sarif_doc = generate_project_report(tmp_dir, audit_data)
        assert "No breaches or crashes were triggered" in md_content
        assert len(sarif_doc["runs"][0]["results"]) == 0
