"""
Tests for the Verified Patch Gate (agent/adversarial_duel.py).

A patch is "verified" only if (a) the exact breach request no longer reproduces the
breach AND (b) legitimate requests still behave like they did before the patch.
A patch that makes the breach disappear by REMOVING the route (404) or by breaking
the app must be rejected. These tests run against a real, tiny Flask server so the
gate is exercised end to end (no mocked HTTP).
"""

import json
import os
import socket
import sys
import tempfile
import threading

import pytest
from flask import Flask
from werkzeug.serving import make_server

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from agent.adversarial_duel import (  # noqa: E402
    BuilderAgent,
    HackerAgent,
    save_verification_artifacts,
    verify_patch,
)


# ----------------------------------------------------------------------------
# Pure logic: before/after status comparison
# ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "before,after,expected",
    [
        (200, 200, True),    # unchanged
        (200, 302, True),    # patch added a login redirect: still a working route
        (302, 302, True),
        (405, 405, True),    # POST-only route stays POST-only
        (500, 200, True),    # the crashing route was fixed
        (200, 404, False),   # route removed
        (302, 404, False),
        (200, 500, False),   # patch broke the page
        (200, 400, False),   # a working page now errors
        (405, 404, False),   # existing route disappeared
        (404, 404, True),    # was already missing, still missing
        (200, None, False),  # server unreachable after the patch
        (None, 200, True),   # no baseline: only "does not crash" is required
    ],
)
def test_legit_status_ok(before, after, expected):
    assert HackerAgent.legit_status_ok(before, after) is expected


# ----------------------------------------------------------------------------
# End to end against a live Flask app whose behaviour we can switch ("patch")
# ----------------------------------------------------------------------------
@pytest.fixture()
def live_app():
    state = {"mode": "vulnerable"}
    app = Flask(__name__)

    @app.route("/")
    def home():
        if state["mode"] == "broke_home":
            return ("home broken", 500)
        if state["mode"] == "blank_home":
            return ""  # still 200, but the page content is gone
        return "home ok"

    @app.route("/search")
    def search():
        mode = state["mode"]
        if mode == "removed_route":
            return ("not found", 404)
        if mode == "vulnerable" and "q" in __import__("flask").request.args:
            return ("crash", 500)  # the breach: a probe payload crashes the route
        return "search ok"

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = make_server("127.0.0.1", port, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


BREACH = {
    "type": "Unhandled Exception",
    "route": "/search",
    "method": "GET",
    "payload": "<probe>",
    "status_code": 500,
    "details": "Server 500 crash on probe",
}


def _gate(base_url, state, mode):
    """Capture baseline on the vulnerable app, switch to the 'patched' behaviour, run the gate."""
    hacker = HackerAgent(client=None, model="mock", base_url=base_url)
    state["mode"] = "vulnerable"
    baseline = hacker.capture_baseline("/search")
    assert hacker.replay_breach(BREACH) is True  # sanity: the breach really reproduces
    state["mode"] = mode
    return verify_patch(hacker, ".", BREACH, baseline)


def test_genuine_fix_is_verified(live_app):
    state, url = live_app
    verified, reason = _gate(url, state, "fixed")
    assert (verified, reason) == (True, "verified")


def test_patch_that_does_not_fix_breach_is_rejected(live_app):
    state, url = live_app
    verified, reason = _gate(url, state, "vulnerable")
    assert (verified, reason) == (False, "breach_persists")


def test_patch_that_removes_the_route_is_rejected(live_app):
    """The breach 'disappears' (404, no more 500) but the feature is gone: must not count."""
    state, url = live_app
    verified, reason = _gate(url, state, "removed_route")
    assert (verified, reason) == (False, "regression")


def test_patch_that_breaks_homepage_is_rejected(live_app):
    state, url = live_app
    verified, reason = _gate(url, state, "broke_home")
    assert verified is False
    assert reason == "regression"


def test_patch_that_blanks_a_page_is_rejected(live_app):
    """Status stays 200 but the page content disappears: must be rejected as a regression."""
    state, url = live_app
    verified, reason = _gate(url, state, "blank_home")
    assert (verified, reason) == (False, "regression")


# ----------------------------------------------------------------------------
# Rollback: only verified patches stay
# ----------------------------------------------------------------------------
class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _MockClient:
    def __init__(self, text):
        self.text = text
        self.chat = type("Chat", (), {"completions": self})()

    def create(self, **kwargs):
        return _Resp(self.text)


def test_rollback_restores_original_code():
    builder = BuilderAgent(client=_MockClient("print('patched')\n"), model="mock")
    with tempfile.TemporaryDirectory() as tmp:
        app_path = os.path.join(tmp, "app.py")
        original = "print('original')\n"
        with open(app_path, "w", encoding="utf-8") as f:
            f.write(original)

        repaired = builder.generate_targeted_defense(
            tmp, {"type": "X", "route": "/", "method": "GET", "payload": None, "details": "d"}
        )
        assert repaired is True
        with open(app_path, encoding="utf-8") as f:
            assert f.read() != original  # patch applied

        assert builder.rollback_last_patch() is True
        with open(app_path, encoding="utf-8") as f:
            assert f.read() == original  # rolled back

        assert builder.rollback_last_patch() is False  # nothing left to roll back


# ----------------------------------------------------------------------------
# Evidence is kept for EVERY verified fix, not only the last one
# ----------------------------------------------------------------------------
def test_artifacts_kept_for_every_verified_fix(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as pb:
        monkeypatch.setenv("PLAYBOOK_DIR", pb)
        for i, route in enumerate(["/a", "/b"], start=1):
            save_verification_artifacts(
                tmp,
                {"type": f"T{i}", "route": route, "method": "GET", "payload": "p", "details": "d"},
                baseline={"/": 200, route: 200},
            )
        vdir = os.path.join(tmp, "verification")
        assert sorted(os.listdir(vdir)) == [
            "poc_01.json", "poc_02.json", "regression_test_01.py", "regression_test_02.py",
        ]
        with open(os.path.join(vdir, "poc_01.json"), encoding="utf-8") as f:
            assert json.load(f)["route"] == "/a"
        with open(os.path.join(vdir, "poc_02.json"), encoding="utf-8") as f:
            poc2 = json.load(f)
        assert poc2["route"] == "/b" and poc2["baseline_status"]["/b"] == 200
        # The generated regression test must be valid Python and baseline-aware.
        with open(os.path.join(vdir, "regression_test_02.py"), encoding="utf-8") as f:
            code = f.read()
        compile(code, "regression_test_02.py", "exec")
        assert "BASELINE" in code and "disappeared" in code
