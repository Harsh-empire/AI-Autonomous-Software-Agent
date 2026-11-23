"""
Unit and integration tests for AEGIS Builder Pipeline (Phases 0-9).
Tests plan validation, folder collision, timeout/error propagation,
missing import checks, repair loop, cancellation, and concurrency control.
"""

import os
import sys
import json
import time
import shutil
import pytest
from openai import OpenAI

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, ".."))
for p in (root_dir, current_dir):
    if p not in sys.path:
        sys.path.insert(0, p)

pytest.importorskip("httpx")
from fastapi.testclient import TestClient

import ide_server
from agent.builder_pipeline import (
    validate_plan,
    get_unique_project_dir,
    check_python_syntax,
    check_jinja_syntax,
    check_missing_imports,
    start_and_wait_for_server,
    smoke_test_app,
)
from stub_llm import (
    start_stub_llm,
    set_custom_reply,
    clear_recorded_requests,
    get_recorded_requests,
    PLAN,
    INDEX_HTML,
    SAFE_APP,
    VULNERABLE_APP,
)


@pytest.fixture
def stub_server():
    server, base_url = start_stub_llm()
    yield server, base_url
    set_custom_reply(None)
    clear_recorded_requests()
    server.shutdown()


def test_plan_validation_rules():
    """Validates Phase 3 plan validation rules across Windows & Linux paths."""
    # Valid plan
    valid = {
        "project_name": "valid_app_slug",
        "files": ["app.py", "templates/index.html", "requirements.txt"]
    }
    ok, err = validate_plan(valid)
    assert ok, err

    # Non-dict
    ok, err = validate_plan("not a dict")
    assert not ok and "must be a valid JSON object" in err

    # Bad slug
    bad_slug = dict(valid, project_name="Invalid Name With Spaces")
    ok, err = validate_plan(bad_slug)
    assert not ok and "must be a slug" in err

    # Slug too short / too long
    ok, _ = validate_plan(dict(valid, project_name="ab"))
    assert not ok
    ok, _ = validate_plan(dict(valid, project_name="a" * 45))
    assert not ok

    # Files empty
    ok, err = validate_plan(dict(valid, files=[]))
    assert not ok and "non-empty" in err

    # Files > 12
    too_many = dict(valid, files=[f"file_{i}.py" for i in range(13)] + ["app.py"])
    ok, err = validate_plan(too_many)
    assert not ok and "Maximum allowed is 12" in err

    # Missing app.py
    no_app = dict(valid, files=["templates/index.html", "style.css"])
    ok, err = validate_plan(no_app)
    assert not ok and "must contain 'app.py'" in err

    # Disallowed extension (.exe / .sh)
    bad_ext = dict(valid, files=["app.py", "malicious.exe"])
    ok, err = validate_plan(bad_ext)
    assert not ok and "disallowed extension" in err

    # Path traversal with '..'
    traversal = dict(valid, files=["app.py", "../secret.py"])
    ok, err = validate_plan(traversal)
    assert not ok and "relative traversal" in err

    # Absolute path (Linux)
    abs_linux = dict(valid, files=["app.py", "/etc/passwd"])
    ok, err = validate_plan(abs_linux)
    assert not ok and "must be relative" in err

    # Absolute path / drive letter (Windows)
    drive_win = dict(valid, files=["app.py", "C:\\Windows\\system32.py"])
    ok, err = validate_plan(drive_win)
    assert not ok and ("drive letter" in err or "relative" in err)

    # Template missing from files
    code_with_missing_tpl = "from flask import Flask, render_template\napp=Flask(__name__)\n@app.route('/')\ndef idx(): return render_template('missing.html')"
    ok, err = validate_plan(valid, app_code=code_with_missing_tpl)
    assert not ok and "missing.html" in err


def test_project_folder_collision_avoidance(tmp_path):
    """Verifies Phase 3 collision avoidance appending _2, _3."""
    # First candidate
    name1 = get_unique_project_dir("my_store", base_dir=str(tmp_path))
    assert name1 == "my_store"
    (tmp_path / name1).mkdir()

    # Second candidate
    name2 = get_unique_project_dir("my_store", base_dir=str(tmp_path))
    assert name2 == "my_store_2"
    (tmp_path / name2).mkdir()

    # Third candidate
    name3 = get_unique_project_dir("my_store", base_dir=str(tmp_path))
    assert name3 == "my_store_3"


def test_invalid_json_plan_fails_after_retries(tmp_path, monkeypatch, stub_server):
    """Phase 9 test: invalid JSON plan 3 times -> error event, no project folder, no fallback app."""
    server, base_url = stub_server
    client = OpenAI(base_url=base_url, api_key="stub")

    # Force stub to return non-JSON text for requirement analyzer
    def bad_reply(req):
        return "This is just explanatory text, not JSON."

    set_custom_reply(bad_reply)

    monkeypatch.setattr(ide_server, "current_dir", str(tmp_path))
    monkeypatch.setattr(ide_server, "get_llm_client", lambda name: (client, name))

    with TestClient(ide_server.app) as tc, tc.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({
            "action": "start_build",
            "prompt": "Create an impossible app",
            "model": "stub-model"
        }))

        events = []
        for _ in range(50):
            msg = ws.receive_json()
            events.append(msg)
            if msg.get("type") in ("error", "speech"):
                if "built and running" in msg.get("text", "") or msg.get("type") == "error":
                    break

        # Must receive error event
        err_events = [e for e in events if e.get("type") == "error"]
        assert len(err_events) >= 1
        assert "invalid JSON" in err_events[0]["text"]

        # No fallback app "Cart & Checkout" or project directory was created
        created_dirs = [d for d in os.listdir(tmp_path) if os.path.isdir(tmp_path / d)]
        assert len(created_dirs) == 0


def test_file_generation_failure_stops_build(tmp_path, monkeypatch, stub_server):
    """Phase 9 test: file generation fails -> error event, no placeholder file, no success message."""
    server, base_url = stub_server
    client = OpenAI(base_url=base_url, api_key="stub")

    # Custom responder: plan works, but app.py generation fails/throws
    def reply_with_fail(req):
        sys_prompt = " ".join(m.get("content", "") for m in req.get("messages", []) if m.get("role") == "system")
        user_prompt = " ".join(m.get("content", "") for m in req.get("messages", []) if m.get("role") == "user")
        if "Requirement Analyzer" in sys_prompt:
            return json.dumps({
                "project_name": "broken_gen_app",
                "files": ["app.py", "requirements.txt"]
            })
        if "Generate the complete contents of" in user_prompt:
            # Produce invalid syntax that ast.parse will reject on retry too
            return "def broken_syntax(:"
        return "ok"

    set_custom_reply(reply_with_fail)
    monkeypatch.setattr(ide_server, "current_dir", str(tmp_path))
    monkeypatch.setattr(ide_server, "get_llm_client", lambda name: (client, name))

    with TestClient(ide_server.app) as tc, tc.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({
            "action": "start_build",
            "prompt": "Build an app",
            "model": "stub-model"
        }))

        events = []
        for _ in range(50):
            msg = ws.receive_json()
            events.append(msg)
            if msg.get("type") in ("error", "speech"):
                if "built and running" in msg.get("text", "") or msg.get("type") == "error":
                    break

        errs = [e for e in events if e.get("type") == "error"]
        assert len(errs) >= 1
        assert "Failed generating app.py" in errs[0]["text"] or "SyntaxError" in errs[0]["text"]
        # Never announce success
        assert not any("built and running" in json.dumps(e) for e in events)


def test_model_name_sent_by_ui_is_received_by_stub(tmp_path, monkeypatch, stub_server):
    """Phase 9 test: the model name sent by the UI is the one the stub receives."""
    server, base_url = stub_server
    client = OpenAI(base_url=base_url, api_key="stub")

    chosen_model = "my-custom-test-model:14b"
    clear_recorded_requests()

    monkeypatch.setattr(ide_server, "current_dir", str(tmp_path))
    monkeypatch.setattr(ide_server, "get_llm_client", lambda name: (client, name))

    with TestClient(ide_server.app) as tc, tc.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({
            "action": "start_build",
            "prompt": "Test model passing",
            "model": chosen_model
        }))

        for _ in range(20):
            msg = ws.receive_json()
            if msg.get("type") in ("build_folder_created", "error"):
                break

    # Check recorded requests to the stub LLM
    requests = get_recorded_requests()
    assert len(requests) >= 1
    models_received = [r.get("model") for r in requests]
    assert chosen_model in models_received


def test_missing_import_reports_package_without_announcement(tmp_path, monkeypatch, stub_server):
    """Phase 9 test: generated app with a missing import -> message lists the package, no 'running' announcement."""
    server, base_url = stub_server
    client = OpenAI(base_url=base_url, api_key="stub")

    def reply_with_missing_pkg(req):
        user_prompt = " ".join(m.get("content", "") for m in req.get("messages", []) if m.get("role") == "user")
        if "Generate the complete contents of" in user_prompt:
            if "app.py" in user_prompt:
                return "import non_existent_super_rare_package_xyz\nfrom flask import Flask\napp=Flask(__name__)\n"
            return "Flask"
        return json.dumps({
            "project_name": "missing_pkg_app",
            "files": ["app.py", "requirements.txt"]
        })

    set_custom_reply(reply_with_missing_pkg)
    monkeypatch.setattr(ide_server, "current_dir", str(tmp_path))
    monkeypatch.setattr(ide_server, "get_llm_client", lambda name: (client, name))

    with TestClient(ide_server.app) as tc, tc.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({
            "action": "start_build",
            "prompt": "Test missing imports",
            "model": "stub-model"
        }))

        events = []
        for _ in range(30):
            msg = ws.receive_json()
            events.append(msg)
            if msg.get("type") in ("missing_dependencies", "error", "speech"):
                if msg.get("type") == "missing_dependencies" or "built and running" in msg.get("text", ""):
                    break

        dep_events = [e for e in events if e.get("type") == "missing_dependencies"]
        assert len(dep_events) == 1
        assert "non_existent_super_rare_package_xyz" in dep_events[0]["packages"]
        # Never announce "built and running"
        assert not any("built and running" in json.dumps(e) for e in events)


def test_progress_events_cancel_and_concurrency(tmp_path, monkeypatch, stub_server):
    """Phase 9 test: progress events in order, cancel_build works, second build refused."""
    server, base_url = stub_server
    client = OpenAI(base_url=base_url, api_key="stub")

    monkeypatch.setattr(ide_server, "current_dir", str(tmp_path))
    monkeypatch.setattr(ide_server, "get_llm_client", lambda name: (client, name))

    with TestClient(ide_server.app) as tc, tc.websocket_connect("/ws") as ws:
        # 1. Start build
        ws.send_text(json.dumps({
            "action": "start_build",
            "prompt": "Simple counter app",
            "model": "stub-model"
        }))

        # 2. Immediately try to start a second build -> must receive error "Another build is running"
        ws.send_text(json.dumps({
            "action": "start_build",
            "prompt": "Second concurrent build",
            "model": "stub-model"
        }))

        # 3. Send cancel_build
        ws.send_text(json.dumps({
            "action": "cancel_build"
        }))

        events = []
        for _ in range(30):
            msg = ws.receive_json()
            events.append(msg)
            if msg.get("type") == "build_cancelled":
                break

        # Check concurrency error arrived
        err_msgs = [e.get("text", "") for e in events if e.get("type") == "error"]
        assert any("Another build is running" in m for m in err_msgs)

        # Check cancellation confirmed
        assert any(e.get("type") == "build_cancelled" for e in events)


def test_self_repair_loop_fixes_bug(tmp_path, monkeypatch, stub_server):
    """Phase 9 test: generated app with a bug that the repair loop fixes within 3 iterations -> success."""
    server, base_url = stub_server
    client = OpenAI(base_url=base_url, api_key="stub")

    from bench.benchmark_core import port_in_use, TARGET_PORT
    if port_in_use(TARGET_PORT):
        pytest.skip("port 5000 busy")

    first_app_attempt = True

    def reply_with_repair(req):
        nonlocal first_app_attempt
        user_prompt = " ".join(m.get("content", "") for m in req.get("messages", []) if m.get("role") == "user")
        sys_prompt = " ".join(m.get("content", "") for m in req.get("messages", []) if m.get("role") == "system")

        if "Requirement Analyzer" in sys_prompt:
            return json.dumps({
                "project_name": "repaired_app",
                "files": ["app.py", "templates/index.html", "requirements.txt"]
            })
        if "Generate the complete contents of" in user_prompt:
            if "index.html" in user_prompt:
                return INDEX_HTML
            if "requirements.txt" in user_prompt:
                return "Flask\n"
            if "app.py" in user_prompt:
                if first_app_attempt:
                    first_app_attempt = False
                    # Deliberate bug: crashes on import/startup
                    return "import sys\nsys.exit(1)\n"
                return SAFE_APP
        # Repair call
        if "repair" in sys_prompt.lower() or "repair" in user_prompt.lower():
            return SAFE_APP
        return "ok"

    set_custom_reply(reply_with_repair)
    monkeypatch.setattr(ide_server, "current_dir", str(tmp_path))
    monkeypatch.setattr(ide_server, "get_llm_client", lambda name: (client, name))

    try:
        with TestClient(ide_server.app) as tc, tc.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({
                "action": "start_build",
                "prompt": "Self-healing app test",
                "model": "stub-model"
            }))

            events = []
            for _ in range(80):
                msg = ws.receive_json()
                events.append(msg)
                if msg.get("type") in ("speech", "error"):
                    if "is verified, built and running" in msg.get("text", "") or msg.get("type") == "error":
                        break

            # Succeeded via self-repair
            speech = [e for e in events if "is verified, built and running" in e.get("text", "")]
            assert len(speech) >= 1
            # Verified repair stage was triggered
            assert any(e.get("stage") == "repair" for e in events if e.get("type") == "build_progress")
    finally:
        ide_server.stop_target_server()


def test_self_repair_loop_unfixable_reports_honest_failure(tmp_path, monkeypatch, stub_server):
    """Phase 9 test: bug that repair loop cannot fix -> honest failure with log tail, no running announcement."""
    server, base_url = stub_server
    client = OpenAI(base_url=base_url, api_key="stub")

    from bench.benchmark_core import port_in_use, TARGET_PORT
    if port_in_use(TARGET_PORT):
        pytest.skip("port 5000 busy")

    def reply_always_broken(req):
        user_prompt = " ".join(m.get("content", "") for m in req.get("messages", []) if m.get("role") == "user")
        sys_prompt = " ".join(m.get("content", "") for m in req.get("messages", []) if m.get("role") == "system")
        if "Requirement Analyzer" in sys_prompt:
            return json.dumps({
                "project_name": "unfixable_app",
                "files": ["app.py", "requirements.txt"]
            })
        # Always output an app that crashes on start
        if "Generate the complete contents of" in user_prompt or "repair" in sys_prompt.lower():
            return "import sys\nprint('Fatal unfixable database corrupted error', file=sys.stderr)\nsys.exit(2)\n"
        return "ok"

    set_custom_reply(reply_always_broken)
    monkeypatch.setattr(ide_server, "current_dir", str(tmp_path))
    monkeypatch.setattr(ide_server, "get_llm_client", lambda name: (client, name))

    try:
        with TestClient(ide_server.app) as tc, tc.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({
                "action": "start_build",
                "prompt": "Unfixable app test",
                "model": "stub-model"
            }))

            events = []
            for _ in range(80):
                msg = ws.receive_json()
                events.append(msg)
                if msg.get("type") == "error":
                    break

            # Honest failure
            err_events = [e for e in events if e.get("type") == "error"]
            assert len(err_events) >= 1
            assert "failed verification after 3 repair attempts" in err_events[0]["text"]
            # Never announces "built and running"
            assert not any("built and running" in json.dumps(e) for e in events)
    finally:
        ide_server.stop_target_server()

