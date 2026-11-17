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

from agent.adversarial_duel import AdversarialArena


class MockClient:
    pass


def test_arena_honest_scoring_when_patches_fail_retest():
    arena = AdversarialArena(client=MockClient(), model="mock-model", max_rounds=2)
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Simulate a duel where 2 breaches occurred
        arena.total_breaches = 2
        
        # Suppose 1 patch passed re-test, but 1 patch failed re-test
        arena.verified_patches = 1
        arena.unresolved_breaches = 1
        
        arena.generate_security_audit_scorecard(tmp_dir)
        
        audit_file = os.path.join(tmp_dir, "security_audit.json")
        assert os.path.exists(audit_file)
        
        with open(audit_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        # Score must be 1/2 = 50%, NOT 100%!
        assert data["final_shield_health_score"] == "50%"
        assert data["verified_patches"] == 1
        assert data["unresolved_breaches"] == 1
        # Verdict must NOT be FORTIFIED because an unresolved breach remains!
        assert data["audit_verdict"] != "FORTIFIED"
        assert data["audit_verdict"] == "PARTIALLY_FORTIFIED"


def test_arena_verdict_fortified_only_when_zero_unresolved():
    arena = AdversarialArena(client=MockClient(), model="mock-model", max_rounds=1)
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Case A: 2 breaches, all 2 verified sealed
        arena.total_breaches = 2
        arena.verified_patches = 2
        arena.unresolved_breaches = 0
        
        arena.generate_security_audit_scorecard(tmp_dir)
        
        with open(os.path.join(tmp_dir, "security_audit.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
            
        assert data["final_shield_health_score"] == "100%"
        assert data["audit_verdict"] == "FORTIFIED"


def test_arena_verdict_vulnerable_when_all_fail():
    arena = AdversarialArena(client=MockClient(), model="mock-model", max_rounds=1)
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Case: 2 breaches, 0 verified, 2 unresolved
        arena.total_breaches = 2
        arena.verified_patches = 0
        arena.unresolved_breaches = 2
        
        arena.generate_security_audit_scorecard(tmp_dir)
        
        with open(os.path.join(tmp_dir, "security_audit.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
            
        assert data["final_shield_health_score"] == "0%"
        assert data["audit_verdict"] == "VULNERABLE"
