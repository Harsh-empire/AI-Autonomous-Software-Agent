"""
End-to-end test of the web IDE duel (WebSocket /ws) with a stubbed LLM.

It checks that the UI duel uses the same Verified Patch Gate as the CLI arena, keeps evidence
for each verified fix, writes security_audit.json and reports a measured result. Numbers come
from a canned stub (test fixtures), not from a real model.
"""

import json
import os
import shutil
import sys

import pytest

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, ".."))
for p in (root_dir, current_dir):
    if p not in sys.path:
        sys.path.insert(0, p)

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

import ide_server  # noqa: E402
from bench import benchmark_core as core  # noqa: E402
from stub_llm import INDEX_HTML, VULNERABLE_APP, start_stub_llm  # noqa: E402


@pytest.mark.skipif(core.port_in_use(core.TARGET_PORT), reason="port 5000 is busy")
def test_web_duel_uses_verified_gate(tmp_path, monkeypatch):
    from openai import OpenAI

    proj = tmp_path / "examples" / "stub_shop"
    (proj / "templates").mkdir(parents=True)
    (proj / "app.py").write_text(VULNERABLE_APP, encoding="utf-8")
    (proj / "templates" / "index.html").write_text(INDEX_HTML, encoding="utf-8")

    server, base_url = start_stub_llm()
    try:
        client = OpenAI(base_url=base_url, api_key="stub")
        monkeypatch.setattr(ide_server, "current_dir", str(tmp_path))
        monkeypatch.setattr(ide_server, "get_llm_client", lambda name: (client, "stub-model"))
        monkeypatch.setenv("PLAYBOOK_DIR", str(tmp_path / "playbook"))

        events = []
        with TestClient(ide_server.app) as tc, tc.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"action": "start_duel", "project": "stub_shop",
                                     "model": "stub-model", "rounds": 2}))
            for _ in range(400):
                msg = ws.receive_json()
                events.append(msg)
                if msg.get("type") in ("duel_all_verified", "duel_completed", "error"):
                    break

        final = events[-1]
        assert final["type"] == "duel_all_verified", final
        assert final["unresolved"] == 0 and final["score"] == 100
        assert "All probes passed" in final["text"]
        assert "FORTIFIED" not in json.dumps(final).upper()

        # the vulnerable app was patched and the evidence of each verified fix is kept
        assert "except ValueError" in (proj / "app.py").read_text(encoding="utf-8")
        vdir = proj / "verification"
        assert sorted(f for f in os.listdir(vdir) if f.startswith("poc_"))
        audit = json.loads((proj / "security_audit.json").read_text(encoding="utf-8"))
        assert audit["verified_fixes"] >= 1 and audit["unresolved"] == 0
        assert audit["total_breaches_detected"] == audit["verified_fixes"]
        # the playbook was written to the temp dir, never into the repository
        assert os.listdir(tmp_path / "playbook")
    finally:
        server.shutdown()
        proc = getattr(ide_server, "target_server_process", None)
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        shutil.rmtree(tmp_path / "playbook", ignore_errors=True)
