"""
Security helpers for the local AEGIS IDE.

The IDE generates code with an LLM and RUNS it on your machine, so every entry point must
be safe against hostile web pages and malformed input:

* WebSocket Origin check: a browser lets ANY web page open ws://127.0.0.1:<port>/ws. Without
  an Origin check, a page you merely visit could drive the IDE (build apps, install packages).
* Dependency installs: only packages that this build reported as missing AND that are on a small
  allowlist are installed, never arbitrary names, URLs, paths or pip options from a message.
* Port handling: find the owner of the preview port by EXACT port match and never kill a
  foreign process unless the user opted in.
"""

from __future__ import annotations

import os
import re
import signal
import socket
import subprocess
import sys
import time
from typing import Iterable, List, Optional, Set, Tuple
from urllib.parse import urlparse

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


# ----------------------------------------------------------------------------
# WebSocket / Host validation
# ----------------------------------------------------------------------------
def _extra_origins_from_env() -> Set[str]:
    raw = os.environ.get("AEGIS_ALLOWED_ORIGINS", "")
    return {o.strip().lower().rstrip("/") for o in raw.split(",") if o.strip()}


def allowed_hosts() -> List[str]:
    """Host names the HTTP server answers to (blocks DNS-rebinding). Override with AEGIS_ALLOWED_HOSTS."""
    raw = os.environ.get("AEGIS_ALLOWED_HOSTS", "")
    hosts = [h.strip() for h in raw.split(",") if h.strip()]
    return hosts or ["127.0.0.1", "localhost", "[::1]"]


def ws_origin_allowed(origin: Optional[str], host_header: Optional[str],
                      extra_allowed: Optional[Iterable[str]] = None) -> bool:
    """
    True if a WebSocket handshake may proceed.

    - No Origin header: not a browser (curl, scripts, tests); browsers always send it. Allowed.
    - Otherwise the page must be served by this very server (same host:port as the Host header)
      and from a loopback host, or be listed in AEGIS_ALLOWED_ORIGINS.
    """
    if origin is None:
        return True
    origin = origin.strip()
    if not origin or origin.lower() == "null":
        return False
    extra = {o.lower().rstrip("/") for o in extra_allowed} if extra_allowed is not None \
        else _extra_origins_from_env()
    if origin.lower().rstrip("/") in extra:
        return True
    try:
        parsed = urlparse(origin)
        hostname = (parsed.hostname or "").lower()
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or hostname not in LOOPBACK_HOSTS:
        return False
    return parsed.netloc.lower() == (host_header or "").strip().lower()


# ----------------------------------------------------------------------------
# Dependency installation policy
# ----------------------------------------------------------------------------
# import name -> PyPI distribution name. Only these can be installed from the IDE.
IMPORT_TO_PACKAGE = {
    "flask": "Flask",
    "werkzeug": "Werkzeug",
    "jinja2": "Jinja2",
    "markupsafe": "MarkupSafe",
    "itsdangerous": "itsdangerous",
    "click": "click",
    "flask_sqlalchemy": "Flask-SQLAlchemy",
    "sqlalchemy": "SQLAlchemy",
    "flask_login": "Flask-Login",
    "flask_wtf": "Flask-WTF",
    "wtforms": "WTForms",
    "email_validator": "email-validator",
    "flask_migrate": "Flask-Migrate",
    "flask_cors": "Flask-Cors",
    "flask_mail": "Flask-Mail",
    "flask_bcrypt": "Flask-Bcrypt",
    "bcrypt": "bcrypt",
    "requests": "requests",
    "dotenv": "python-dotenv",
    "markdown": "Markdown",
    "bleach": "bleach",
    "PIL": "pillow",
    "dateutil": "python-dateutil",
    "pytz": "pytz",
    "stripe": "stripe",
}
MAX_INSTALL_PACKAGES = 10


def resolve_install_request(requested: object, offered: Iterable[str]) -> Tuple[List[str], List[str]]:
    """
    Maps a requested install list to PyPI names. Returns (pip_names, rejection_reasons).

    A package is accepted only if (1) it is on the allowlist and (2) THIS build reported it as
    missing (`offered`). Anything else, including names starting with '-', URLs, paths and
    VCS references, is rejected and never reaches pip.
    """
    if not isinstance(requested, list):
        return [], ["'packages' must be a list of package names."]
    offered_set = {str(o) for o in offered}
    offered_lower = {o.lower() for o in offered_set}
    pip_names: List[str] = []
    rejected: List[str] = []
    for item in requested[:MAX_INSTALL_PACKAGES * 2]:
        if not isinstance(item, str) or not item.strip():
            rejected.append("Invalid package entry.")
            continue
        key = item.strip()
        if key.lower() not in offered_lower:
            rejected.append(f"'{key[:60]}' was not reported as missing for this build.")
            continue
        pip = IMPORT_TO_PACKAGE.get(key) or IMPORT_TO_PACKAGE.get(key.lower())
        if pip is None:
            rejected.append(f"'{key}' is not on the AEGIS install allowlist. Review it and install it yourself "
                            f"with `pip install ...` if you trust it.")
            continue
        if pip not in pip_names:
            pip_names.append(pip)
    if len(pip_names) > MAX_INSTALL_PACKAGES:
        return [], [f"At most {MAX_INSTALL_PACKAGES} packages can be installed at once."]
    return pip_names, rejected


def build_pip_command(pip_names: List[str]) -> List[str]:
    """Binary wheels only (no setup.py execution) into the interpreter that runs the generated apps."""
    return [sys.executable, "-m", "pip", "install", "--only-binary=:all:",
            "--disable-pip-version-check", *pip_names]


# ----------------------------------------------------------------------------
# Preview port handling (never kill by substring, never kill foreign processes by default)
# ----------------------------------------------------------------------------
_OWN_PIDS: Set[int] = set()


def register_own_pid(pid: int) -> None:
    """Remember a preview process started by this IDE; only those are stopped automatically."""
    _OWN_PIDS.add(int(pid))


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def parse_netstat_listeners(output: str, port: int) -> List[int]:
    """PIDs LISTENING on exactly `port` from `netstat -ano -p TCP` output (local address column only)."""
    pids: Set[int] = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper().startswith("TCP") and parts[3].upper() == "LISTENING":
            local_port = parts[1].rsplit(":", 1)[-1]
            if local_port == str(port) and parts[4].isdigit():
                pids.add(int(parts[4]))
    return sorted(pids)


def find_port_owners(port: int) -> List[int]:
    """PIDs listening on the port ([] if unknown). No shell, exact port match."""
    try:
        if os.name == "nt":
            out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                                 timeout=10).stdout
            return parse_netstat_listeners(out, port)
        try:
            out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                                 capture_output=True, text=True, timeout=10).stdout
            return sorted({int(x) for x in out.split() if x.isdigit()})
        except FileNotFoundError:
            out = subprocess.run(["ss", "-ltnpH", f"sport = :{port}"], capture_output=True, text=True,
                                 timeout=10).stdout
            return sorted({int(m) for m in re.findall(r"pid=(\d+)", out)})
    except Exception:
        return []


def terminate_tree(pid: int) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15)
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception:
        pass


def _wait_free(port: int, seconds: float = 5.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not port_in_use(port):
            return True
        time.sleep(0.2)
    return not port_in_use(port)


def free_port(port: int = 5000) -> Tuple[bool, str]:
    """
    Makes sure the preview port is free. Stops only processes this IDE started. A foreign process is
    stopped only if the user set AEGIS_KILL_PORT_OWNER=1; otherwise the caller gets a clear message.
    """
    if not port_in_use(port):
        return True, ""
    owners = find_port_owners(port)
    for pid in [p for p in owners if p in _OWN_PIDS]:
        terminate_tree(pid)
    if _wait_free(port):
        return True, ""
    foreign = [p for p in find_port_owners(port) if p != os.getpid()]
    if foreign and os.environ.get("AEGIS_KILL_PORT_OWNER") == "1":
        for pid in foreign:
            terminate_tree(pid)
        if _wait_free(port):
            return True, ""
    who = f"process {', '.join(map(str, foreign))}" if foreign else "another program"
    return False, (f"Port {port} is in use by {who}. Close that program and try again "
                   f"(or set AEGIS_KILL_PORT_OWNER=1 to let AEGIS stop it).")
