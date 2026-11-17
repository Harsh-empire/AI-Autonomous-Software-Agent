"""
Unit tests for the AEGIS Verified-Only Defense Playbook.
"""

import os
import sys
import tempfile
import pytest

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from agent.playbook import PlaybookManager


def test_unverified_patches_are_refused():
    with tempfile.TemporaryDirectory() as tmp_dir:
        pm = PlaybookManager(playbook_dir=tmp_dir)
        
        # 1. Unverified patch (verified=False)
        unverified_poc = {
            "route": "/login",
            "method": "POST",
            "payload": "' OR 1=1 --",
            "verified": False
        }
        with pytest.raises(ValueError) as exc:
            pm.add_verified_entry(
                vuln_type="SQL Injection",
                pattern_desc="Use parameterized query",
                safe_snippet="User.query.filter_by(username=u).first()",
                poc=unverified_poc
            )
        assert "GATE REJECTION" in str(exc.value)

        # 2. Missing verification field
        with pytest.raises(ValueError):
            pm.add_verified_entry(
                vuln_type="XSS",
                pattern_desc="Escape HTML",
                safe_snippet="escape(val)",
                poc={"route": "/search", "payload": "<script>"}
            )


def test_verified_patch_storage_and_retrieval():
    with tempfile.TemporaryDirectory() as tmp_dir:
        pm = PlaybookManager(playbook_dir=tmp_dir)
        
        verified_poc = {
            "route": "/login",
            "method": "POST",
            "payload": "' OR 1=1 --",
            "verified": True
        }
        entry_id = pm.add_verified_entry(
            vuln_type="SQL Injection",
            pattern_desc="Use ORM filter_by instead of raw SQL concatenation",
            safe_snippet="User.query.filter_by(username=u).first()",
            poc=verified_poc,
            model="test-model"
        )
        assert entry_id.startswith("pb_")

        entries = pm.list_entries()
        assert len(entries) == 1
        assert entries[0]["id"] == entry_id
        assert entries[0]["vuln_type"] == "SQL Injection"


def test_disabled_entries_not_injected():
    with tempfile.TemporaryDirectory() as tmp_dir:
        pm = PlaybookManager(playbook_dir=tmp_dir)
        
        verified_poc = {
            "route": "/search",
            "method": "GET",
            "payload": "{{7*7}}",
            "verified": True
        }
        entry_id = pm.add_verified_entry(
            vuln_type="Template Injection SSTI",
            pattern_desc="Avoid render_template_string on user input",
            safe_snippet="render_template('index.html', q=q)",
            poc=verified_poc
        )

        # Active entry is retrieved
        relevant = pm.get_relevant_entries("search template injection", top_k=3)
        assert len(relevant) == 1
        assert relevant[0]["id"] == entry_id

        # Disable entry
        success = pm.set_entry_enabled(entry_id, False)
        assert success is True

        # Disabled entry must NOT be retrieved
        relevant_after = pm.get_relevant_entries("search template injection", top_k=3)
        assert len(relevant_after) == 0


def test_playbook_env_switch(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_dir:
        pm = PlaybookManager(playbook_dir=tmp_dir)
        
        verified_poc = {"route": "/api", "method": "GET", "verified": True}
        pm.add_verified_entry(
            vuln_type="Auth Bypass",
            pattern_desc="Check session before route handler",
            safe_snippet="if 'user_id' not in session: return redirect('/login')",
            poc=verified_poc
        )

        # PLAYBOOK=on
        monkeypatch.setenv("PLAYBOOK", "on")
        assert len(pm.get_relevant_entries("auth login", top_k=3)) == 1

        # PLAYBOOK=off
        monkeypatch.setenv("PLAYBOOK", "off")
        assert len(pm.get_relevant_entries("auth login", top_k=3)) == 0
