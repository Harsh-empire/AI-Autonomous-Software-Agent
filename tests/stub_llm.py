"""
A tiny OpenAI-compatible LLM stub used ONLY by the pipeline integration test.

It returns canned responses so the benchmark machinery (generate -> run -> probe ->
duel -> baselines -> CSV/markdown/chart) can be tested end to end in CI without Ollama.
Numbers produced with this stub are test fixtures, never benchmark results.
"""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PLAN = {
    "project_name": "stub_shop",
    "description": "stub shop",
    "technology_stack": ["Python", "Flask"],
    "dependencies": ["Flask"],
    "features": ["add item"],
    "files": ["app.py", "templates/index.html"],
    "run_command": "python app.py",
    "test_cases": ["home page loads"],
}

INDEX_HTML = """<!doctype html>
<html><body><h1>Stub shop</h1>
<form action="/add" method="post">
  <input name="title"><input name="qty"><button>Add</button>
</form></body></html>
"""

VULNERABLE_APP = '''from flask import Flask, request, render_template

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/add", methods=["POST"])
def add():
    title = request.form["title"].strip()
    qty = int(request.form["qty"])  # crashes (HTTP 500) on empty / non-numeric input
    return f"added {title} x {qty}"


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
'''

SAFE_APP = '''from flask import Flask, request, render_template

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/add", methods=["POST"])
def add():
    title = request.form.get("title", "").strip()
    try:
        qty = int(request.form.get("qty", ""))
    except ValueError:
        return "invalid quantity", 400
    if not title or len(title) > 200 or not 0 < qty < 10000:
        return "invalid input", 400
    return f"added {title[:200]} x {qty}"


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
'''


def _reply(messages):
    system = " ".join(m["content"] for m in messages if m["role"] == "system")
    user = " ".join(m["content"] for m in messages if m["role"] == "user")
    if "Requirement Analyzer" in system:
        return json.dumps(PLAN)
    if "The Hacker" in system:
        return "Nice try, Builder."
    if "You are The Builder" in user or "Make the following Flask application secure" in user:
        return SAFE_APP
    if "Generate the complete contents of" in user:
        return INDEX_HTML if "index.html" in user else VULNERABLE_APP
    return "ok"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"object": "list", "data": [{"id": "stub-model", "object": "model"}]})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(length) or b"{}")
        content = _reply(req.get("messages", []))
        self._send({
            "id": "stub", "object": "chat.completion", "created": 0, "model": req.get("model", "stub-model"),
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })


def start_stub_llm():
    """Starts the stub on a free port. Returns (server, base_url_with_/v1)."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{port}/v1"
