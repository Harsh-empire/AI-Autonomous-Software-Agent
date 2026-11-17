"""
Unit & Regression tests for Adversarial Duel truthful scoring and verification.
"""

import os
import sys
import tempfile
import json
import pytest

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from agent.adversarial_duel import AdversarialArena, BuilderAgent


class MockMessage:
    def __init__(self, content):
        self.content = content


class MockChoice:
    def __init__(self, message):
        self.message = message


class MockResponse:
    def __init__(self, content):
        self.choices = [MockChoice(MockMessage(content))]


class MockLLMClient:
    def __init__(self, response_text):
        self.response_text = response_text
        self.chat = type("Chat", (), {"completions": self})()

    def create(self, **kwargs):
        return MockResponse(self.response_text)


def test_arena_honest_scoring_when_patches_fail_retest():
    arena = AdversarialArena(client=MockLLMClient(""), model="mock-model", max_rounds=2)
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Simulate a duel where 2 breaches occurred
        arena.total_breaches = 2
        
        # 1 patch verified, 1 patch unresolved
        arena.verified_fixes = 1
        arena.unresolved = 1
        
        arena.generate_security_audit_scorecard(tmp_dir)
        
        audit_file = os.path.join(tmp_dir, "security_audit.json")
        assert os.path.exists(audit_file)
        
        with open(audit_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        # Score must be 50%, NOT 100%!
        assert data["final_shield_health_score"] == "50%"
        assert data["verified_fixes"] == 1
        assert data["unresolved"] == 1
        assert data["audit_verdict"] == "1 unresolved"


def test_arena_verdict_all_probes_passed_only_when_zero_unresolved():
    arena = AdversarialArena(client=MockLLMClient(""), model="mock-model", max_rounds=1)
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        arena.total_breaches = 2
        arena.verified_fixes = 2
        arena.unresolved = 0
        
        arena.generate_security_audit_scorecard(tmp_dir)
        
        with open(os.path.join(tmp_dir, "security_audit.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
            
        assert data["final_shield_health_score"] == "100%"
        assert data["audit_verdict"] == "all probes passed"


def test_arena_zero_breaches_reports_no_breaches():
    arena = AdversarialArena(client=MockLLMClient(""), model="mock-model", max_rounds=1)
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        arena.total_breaches = 0
        arena.verified_fixes = 0
        arena.unresolved = 0
        
        arena.generate_security_audit_scorecard(tmp_dir)
        
        with open(os.path.join(tmp_dir, "security_audit.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
            
        assert data["final_shield_health_score"] == "no breaches found"
        assert data["audit_verdict"] == "no breaches found"


def test_builder_rejects_syntax_error_patch():
    # LLM returns invalid python code with a syntax error
    bad_code = "def invalid_func( broken syntax"
    mock_client = MockLLMClient(bad_code)
    builder = BuilderAgent(client=mock_client, model="mock-model")

    with tempfile.TemporaryDirectory() as tmp_dir:
        app_path = os.path.join(tmp_dir, "app.py")
        original_code = "print('valid code')\n"
        with open(app_path, "w", encoding="utf-8") as f:
            f.write(original_code)

        breach = {
            "type": "SQL Injection",
            "route": "/login",
            "method": "POST",
            "payload": "' OR 1=1 --",
            "details": "Crash on input"
        }

        # Must return False because ast.parse fails
        repaired = builder.generate_targeted_defense(tmp_dir, breach)
        assert repaired is False

        # Original code must not be modified
        with open(app_path, "r", encoding="utf-8") as f:
            assert f.read() == original_code


def test_verification_artifacts_saved():
    arena = AdversarialArena(client=MockLLMClient(""), model="mock-model")
    with tempfile.TemporaryDirectory() as tmp_dir:
        breach = {
            "type": "Unhandled 404 Route",
            "route": "/probe_endpoint",
            "method": "GET",
            "payload": None,
            "status_code": 500,
            "details": "Server 500 crash"
        }
        arena._save_verification_artifacts(tmp_dir, breach)

        # Check poc.json
        poc_path = os.path.join(tmp_dir, "poc.json")
        assert os.path.exists(poc_path)
        with open(poc_path, "r", encoding="utf-8") as f:
            poc = json.load(f)
        assert poc["vuln_type"] == "Unhandled 404 Route"
        assert poc["verified"] is True

        # Check regression_test.py
        reg_path = os.path.join(tmp_dir, "regression_test.py")
        assert os.path.exists(reg_path)
        with open(reg_path, "r", encoding="utf-8") as f:
            code = f.read()
        assert "def test_regression():" in code
        assert "/probe_endpoint" in code
