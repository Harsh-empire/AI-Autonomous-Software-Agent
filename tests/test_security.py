"""
Security regression tests for the local IDE:
- WebSocket Origin / Host checks (no hostile web page may drive the IDE),
- dependency-install policy (no arbitrary packages, URLs, paths or pip options),
- exact-port handling (no substring matches, no killing foreign processes by default).
"""

import os
import sys

import pytest

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

import ide_server  # noqa: E402
from agent import security  # noqa: E402
from agent.security import (  # noqa: E402
    build_pip_command,
    parse_netstat_listeners,
    resolve_install_request,
    ws_origin_allowed,
)


# ---------------------------------------------------------------- origin check
@pytest.mark.parametrize("origin,host,expected", [
    (None, "127.0.0.1:8000", True),                         # not a browser (curl, scripts)
    ("http://127.0.0.1:8000", "127.0.0.1:8000", True),      # the IDE's own page
    ("http://localhost:8000", "localhost:8000", True),
    ("http://[::1]:8000", "[::1]:8000", True),
    ("http://evil.example", "127.0.0.1:8000", False),       # hostile web page
    ("https://evil.example:8000", "127.0.0.1:8000", False),
    ("http://127.0.0.1:3000", "127.0.0.1:8000", False),     # another local app / other port
    ("http://localhost:8000", "127.0.0.1:8000", False),     # different host name than the request
    ("http://127.0.0.1.evil.example", "127.0.0.1", False),  # look-alike host
    ("null", "127.0.0.1:8000", False),                      # sandboxed iframe / file://
    ("file://", "127.0.0.1:8000", False),
    ("", "127.0.0.1:8000", False),
])
def test_ws_origin_allowed(origin, host, expected):
    assert ws_origin_allowed(origin, host, extra_allowed=[]) is expected


def test_ws_origin_extra_allowed_list():
    assert ws_origin_allowed("http://my-lan-box:8000", "my-lan-box:8000", extra_allowed=[]) is False
    assert ws_origin_allowed("http://my-lan-box:8000", "my-lan-box:8000",
                             extra_allowed=["http://my-lan-box:8000"]) is True


# ---------------------------------------------------------------- live server behaviour
# Starlette's TestClient.websocket_connect always sends "Host: testserver", so the browser's
# Host/Origin pair is set explicitly here.
BROWSER = {"host": "127.0.0.1:8000", "origin": "http://127.0.0.1:8000"}


def test_hostile_origin_cannot_open_the_websocket():
    client = TestClient(ide_server.app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"host": "127.0.0.1:8000",
                                                      "origin": "http://evil.example"}):
            pass


def test_other_local_site_cannot_open_the_websocket():
    client = TestClient(ide_server.app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"host": "127.0.0.1:8000",
                                                      "origin": "http://localhost:3000"}):
            pass


def test_same_origin_page_can_open_the_websocket():
    client = TestClient(ide_server.app)
    with client.websocket_connect("/ws", headers=dict(BROWSER)) as ws:
        ws.send_json({"action": "no_such_action"})  # connection is accepted and stays usable


def test_dns_rebinding_host_is_rejected():
    client = TestClient(ide_server.app, base_url="http://evil.example")
    assert client.get("/health").status_code == 400
    with pytest.raises(Exception):
        with client.websocket_connect("/ws", headers={"host": "evil.example"}):
            pass


def test_health_still_works_on_loopback():
    client = TestClient(ide_server.app, base_url="http://127.0.0.1:8000")
    assert client.get("/health").status_code == 200


# ---------------------------------------------------------------- dependency install policy
OFFERED = ["flask_wtf", "PIL", "dotenv", "left_pad_evil"]


def test_allowlisted_offered_packages_map_to_pypi_names():
    pip, rejected = resolve_install_request(["flask_wtf", "PIL", "dotenv", "flask_wtf"], OFFERED)
    assert pip == ["Flask-WTF", "pillow", "python-dotenv"] and rejected == []


@pytest.mark.parametrize("payload", [
    "--index-url=http://evil.example/simple",   # pip option injection
    "-r requirements.txt",
    "-e .",
    "git+https://github.com/evil/repo.git",     # VCS reference
    "https://evil.example/pkg.whl",             # URL
    "../../evil",                               # path
    "C:\\evil\\pkg",
    "evil-package==1.0; rm -rf /",
    "flask_wtf --extra-index-url http://evil",
])
def test_hostile_install_requests_are_rejected(payload):
    pip, rejected = resolve_install_request([payload], offered=[payload])  # even if "offered"
    assert pip == [] and rejected


def test_not_allowlisted_package_is_rejected_even_if_missing():
    pip, rejected = resolve_install_request(["left_pad_evil"], OFFERED)
    assert pip == [] and "allowlist" in rejected[0]


def test_package_not_reported_missing_by_this_build_is_rejected():
    pip, rejected = resolve_install_request(["requests"], ["flask_wtf"])
    assert pip == [] and "not reported as missing" in rejected[0]


def test_malformed_requests_are_rejected():
    assert resolve_install_request("flask_wtf", OFFERED)[0] == []
    assert resolve_install_request({"a": 1}, OFFERED)[0] == []
    pip, rejected = resolve_install_request([None, 5, ["x"], "  "], OFFERED)
    assert pip == [] and len(rejected) == 4


def test_pip_command_uses_binary_wheels_only():
    cmd = build_pip_command(["Flask-WTF"])
    assert cmd[:3] == [sys.executable, "-m", "pip"]
    assert "--only-binary=:all:" in cmd and cmd[-1] == "Flask-WTF"


def test_install_over_websocket_is_refused_without_running_pip(monkeypatch):
    calls = []
    monkeypatch.setattr(ide_server.subprocess, "run", lambda *a, **k: calls.append(a) or None)
    client = TestClient(ide_server.app)
    with client.websocket_connect("/ws", headers=dict(BROWSER)) as ws:
        for packages in (["--index-url=http://evil.example"], ["requests"], "not-a-list"):
            ws.send_json({"action": "install_dependencies", "packages": packages})
            msg = ws.receive_json()
            assert msg["type"] == "error" and "Install refused" in msg["text"]
    assert calls == [], "pip must never run for refused requests"


# ---------------------------------------------------------------- port handling
NETSTAT = """
  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:5000           0.0.0.0:0              LISTENING       4120
  TCP    [::]:5000              [::]:0                 LISTENING       4120
  TCP    0.0.0.0:50001          0.0.0.0:0              LISTENING       7788
  TCP    127.0.0.1:55000        0.0.0.0:0              LISTENING       9001
  TCP    127.0.0.1:60000        127.0.0.1:5000         ESTABLISHED     3030
  TCP    10.0.0.5:5000          52.1.1.1:443           TIME_WAIT       0
"""


def test_netstat_parser_matches_the_exact_listening_port_only():
    assert parse_netstat_listeners(NETSTAT, 5000) == [4120]       # not 50001, 55000, or client sockets
    assert parse_netstat_listeners(NETSTAT, 50001) == [7788]
    assert parse_netstat_listeners(NETSTAT, 123) == []


@pytest.fixture()
def fake_port(monkeypatch):
    state = {"in_use": True, "killed": [], "owners": [4120]}

    def terminate(pid):
        state["killed"].append(pid)
        state["owners"] = [p for p in state["owners"] if p != pid]
        if not state["owners"]:
            state["in_use"] = False

    monkeypatch.setattr(security, "port_in_use", lambda port, host="127.0.0.1": state["in_use"])
    monkeypatch.setattr(security, "find_port_owners", lambda port: list(state["owners"]))
    monkeypatch.setattr(security, "terminate_tree", terminate)
    monkeypatch.setattr(security, "_wait_free", lambda port, seconds=5.0: not state["in_use"])
    monkeypatch.setattr(security, "_OWN_PIDS", set())
    monkeypatch.delenv("AEGIS_KILL_PORT_OWNER", raising=False)
    return state


def test_free_port_never_kills_a_foreign_process_by_default(fake_port):
    ok, msg = security.free_port(5000)
    assert ok is False and fake_port["killed"] == []
    assert "4120" in msg and "AEGIS_KILL_PORT_OWNER=1" in msg


def test_free_port_stops_our_own_preview(fake_port):
    security.register_own_pid(4120)
    assert security.free_port(5000) == (True, "")
    assert fake_port["killed"] == [4120]


def test_free_port_kills_foreign_process_only_when_opted_in(fake_port, monkeypatch):
    monkeypatch.setenv("AEGIS_KILL_PORT_OWNER", "1")
    assert security.free_port(5000) == (True, "")
    assert fake_port["killed"] == [4120]


def test_free_port_is_a_noop_when_the_port_is_free(fake_port):
    fake_port["in_use"] = False
    assert security.free_port(5000) == (True, "") and fake_port["killed"] == []
