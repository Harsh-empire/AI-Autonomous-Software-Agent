"""
AEGIS benchmark engine.

Everything in here produces MEASURED numbers by actually running the pipeline:
generate an app with the local LLM, start it, probe it with the Hacker fuzzer, run the
Builder/Hacker duel (or a baseline), re-probe, and run Bandit. Nothing is simulated.
If a step fails, the row is recorded with an error status and empty metrics; the
summary reports failures separately instead of hiding them.

Configurations (see bench/README section in the main README):
  A  no duel: raw single-pass generated code, measured only
  B  Builder/Hacker duel, PLAYBOOK=off
  C  duel + verified playbook (playbook built from the TRAIN prompts only; the app is
     also generated with the playbook in the prompt)
  D  Bandit-only static scan of the raw generated code (no fixing)
  E  single-shot LLM "make this code secure" (no duel), judged by the same gate

Held-out evaluation: the playbook is trained on `train` prompts and evaluated on
`held_out_test` prompts. Each C run works on a throw-away copy of the trained playbook,
so held-out apps never leak into it.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import platform
import re
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import requests

TARGET_HOST = "127.0.0.1"
TARGET_PORT = 5000
MAX_TIER = 5  # the Hacker has tiers 1..5; the duel is run for the same number of rounds

FIELDS = [
    "prompt_id", "split", "run", "config", "status",
    "initial_breaches", "verified_fixes", "unresolved", "fix_rate",
    "residual_breaches", "bandit_initial", "bandit_findings",
    "duration_sec", "model", "timestamp",
]

CONFIG_DESCRIPTIONS = {
    "A": "No duel (raw single-pass generated code)",
    "B": "Adversarial duel without playbook (`PLAYBOOK=off`)",
    "C": "Adversarial duel with verified playbook (`PLAYBOOK=on`, trained on the train split)",
    "D": "Bandit-only static scan (no fixing)",
    "E": "Single-shot LLM 'make this code secure' (no duel)",
}


class BenchmarkError(RuntimeError):
    """Raised for problems that make a measurement impossible (not for 'bad results')."""


class AppStartError(BenchmarkError):
    """The generated app did not start (missing dependency, crash on import, ...)."""


# ----------------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------------
def port_in_use(port: int = TARGET_PORT, host: str = TARGET_HOST) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


@contextlib.contextmanager
def temp_env(**values: Optional[str]) -> Iterator[None]:
    """Temporarily set (or unset, when the value is None) environment variables."""
    old = {k: os.environ.get(k) for k in values}
    try:
        for k, v in values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextlib.contextmanager
def chdir(path: str) -> Iterator[None]:
    prev = os.getcwd()
    os.makedirs(path, exist_ok=True)
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


@contextlib.contextmanager
def quiet(log_path: Optional[str] = None) -> Iterator[None]:
    """Silences the (very chatty) agent output; optionally keeps it in a log file."""
    if log_path:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        sink: Any = open(log_path, "a", encoding="utf-8")
    else:
        sink = io.StringIO()
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            yield
    finally:
        if log_path:
            sink.close()


def strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


# ----------------------------------------------------------------------------
# running the generated app
# ----------------------------------------------------------------------------
class AppRunner:
    """Starts `python app.py` for a generated project and can stop/restart the whole process tree."""

    def __init__(self, project_dir: str, port: int = TARGET_PORT,
                 startup_timeout: float = 25.0, log_path: Optional[str] = None):
        self.project_dir = project_dir
        self.port = port
        self.startup_timeout = startup_timeout
        self.log_path = log_path
        self._proc: Optional[subprocess.Popen] = None

    def start(self) -> bool:
        self.stop()
        if not os.path.exists(os.path.join(self.project_dir, "app.py")):
            return False
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
        kwargs: Dict[str, Any] = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        if self.log_path:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        log = open(self.log_path, "ab") if self.log_path else subprocess.DEVNULL
        try:
            self._proc = subprocess.Popen(
                [sys.executable, "app.py"], cwd=self.project_dir, env=env,
                stdout=log, stderr=subprocess.STDOUT, **kwargs,
            )
        finally:
            if self.log_path:
                log.close()  # type: ignore[union-attr]

        deadline = time.time() + self.startup_timeout
        while time.time() < deadline:
            if self._proc.poll() is not None:
                return False  # exited during startup
            try:
                requests.get(f"http://{TARGET_HOST}:{self.port}/", timeout=1.5, allow_redirects=False)
                return True
            except requests.RequestException:
                time.sleep(0.4)
        return False

    def alive(self) -> bool:
        if self._proc is None or self._proc.poll() is not None:
            return False
        try:
            requests.get(f"http://{TARGET_HOST}:{self.port}/", timeout=2, allow_redirects=False)
            return True
        except requests.RequestException:
            return False

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                   capture_output=True)
                else:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            try:
                proc.wait(timeout=3)
            except Exception:
                pass
        # wait for the port to be released so the next start can bind it
        deadline = time.time() + 6
        while port_in_use(self.port) and time.time() < deadline:
            time.sleep(0.2)

    def restart(self) -> bool:
        self.stop()
        return self.start()

    def __enter__(self) -> "AppRunner":
        if not self.start():
            self.stop()
            raise AppStartError("generated app did not start")
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()


# ----------------------------------------------------------------------------
# measurements
# ----------------------------------------------------------------------------
def probe_all(hacker: Any, project_dir: str, max_tier: Optional[int] = None) -> List[Dict[str, Any]]:
    """Runs every Hacker tier against the running app and returns the unique breaches."""
    seen = set()
    breaches: List[Dict[str, Any]] = []
    with quiet():
        for tier in range(1, (max_tier or MAX_TIER) + 1):
            for b in hacker.run_attack_round(project_dir, round_tier=tier):
                key = (b.get("type"), b.get("route"), b.get("method"))
                if key not in seen:
                    seen.add(key)
                    breaches.append(b)
    return breaches


# Evidence written by the verified patch gate (not part of the app) must never count as findings:
# regression tests contain `assert` statements, which Bandit would flag.
EVIDENCE_PATHS = ("verification", "regression_test.py", "poc.json", "__pycache__")


def run_bandit(target_dir: str) -> Optional[int]:
    """Independent static metric on the APP code only. Returns None when Bandit is unavailable
    (never a fake 0)."""
    excludes = [os.path.join(target_dir, p) for p in EVIDENCE_PATHS]
    try:
        res = subprocess.run(
            [sys.executable, "-m", "bandit", "-r", target_dir, "-f", "json", "-q",
             "-x", ",".join(excludes)],
            capture_output=True, text=True, timeout=60,
        )
        if res.stdout.strip():
            return len(json.loads(res.stdout).get("results", []))
    except Exception:
        pass
    return None


SINGLE_SHOT_SYSTEM = (
    "You are a senior application security engineer. You output only the raw, complete, "
    "updated Python source code of the file, with no explanations and no markdown fences."
)
SINGLE_SHOT_USER = """Make the following Flask application secure.

Fix any problem you can find: crashes on empty or malformed input, SQL injection, XSS,
template injection, missing authentication/authorization checks, path traversal and
insecure direct object references. Keep ALL existing routes and features working.

Return the COMPLETE updated app.py.

CURRENT app.py:
```python
{code}
```
"""


def single_shot_secure(client: Any, model: str, project_dir: str) -> bool:
    """Config E: ask the LLM once to make app.py secure. True if a syntactically valid rewrite was written."""
    import ast
    path = os.path.join(project_dir, "app.py")
    with open(path, encoding="utf-8") as fh:
        code = fh.read()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SINGLE_SHOT_SYSTEM},
            {"role": "user", "content": SINGLE_SHOT_USER.format(code=code)},
        ],
        temperature=0.1,
    )
    new_code = strip_code_fences(resp.choices[0].message.content or "")
    try:
        ast.parse(new_code)
    except SyntaxError:
        return False
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(new_code)
    return True


# ----------------------------------------------------------------------------
# the runner
# ----------------------------------------------------------------------------
class BenchmarkRunner:
    def __init__(self, out_dir: str, prompts: Dict[str, List[Dict[str, str]]], configs: List[str],
                 runs: int = 1, rounds: int = MAX_TIER, limit: int = 0, train_limit: int = 0,
                 skip_train: bool = False, log: Callable[[str], None] = print):
        self.out_dir = os.path.abspath(out_dir)
        self.prompts = prompts
        self.configs = configs
        self.runs = runs
        self.rounds = rounds
        self.limit = limit
        self.train_limit = train_limit
        self.skip_train = skip_train
        self.log = log

        self.work_dir = os.path.join(self.out_dir, "work")
        self.logs_dir = os.path.join(self.out_dir, "logs")
        self.playbook_dir = os.path.join(self.out_dir, "playbook_trained")
        self.csv_path = os.path.join(self.out_dir, "results.csv")
        self.records: List[Dict[str, Any]] = []
        self._client: Any = None
        self._model: str = ""
        self._hacker: Any = None

    # ---- setup -------------------------------------------------------------
    def _llm(self) -> Tuple[Any, str]:
        if self._client is None:
            from agent.llm_client import get_llm_client
            self._client, self._model = get_llm_client(os.environ.get("AEGIS_MODEL", "qwen2.5-coder:7b"))
            from agent.adversarial_duel import HackerAgent
            self._hacker = HackerAgent(self._client, self._model)
            # Generation (agent.main) must use the same backend as the duel and the baselines.
            from agent import main as gen
            gen.client, gen.MODEL = self._client, self._model
        return self._client, self._model

    def _row(self, prompt_id: str, split: str, run: int, config: str, status: str = "ok",
             **metrics: Any) -> Dict[str, Any]:
        row: Dict[str, Any] = {k: "" for k in FIELDS}
        row.update(prompt_id=prompt_id, split=split, run=run, config=config, status=status,
                   model=self._model, timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        for k, v in metrics.items():
            row[k] = "" if v is None else v
        return row

    def _save(self) -> None:
        os.makedirs(self.out_dir, exist_ok=True)
        with open(self.csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(self.records)

    def _copy(self, src: str, name: str) -> str:
        dst = os.path.join(self.work_dir, "copies", name)
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        return dst

    # ---- generation --------------------------------------------------------
    def _generate(self, prompt: str, tag: str, use_playbook: bool, playbook_dir: Optional[str]) -> str:
        """Generates one app with the normal AEGIS pipeline in an isolated workspace."""
        self._llm()
        workspace = os.path.join(self.work_dir, "generated", tag)
        if os.path.exists(workspace):
            shutil.rmtree(workspace)
        log_path = os.path.join(self.logs_dir, f"{tag}_generation.log")
        with temp_env(PLAYBOOK="on" if use_playbook else "off", PLAYBOOK_DIR=playbook_dir), \
                chdir(workspace), quiet(log_path):
            from agent import main as gen
            plan = gen.analyze_requirements(prompt)
            project_dir = gen.create_project_structure(plan)
            gen.write_generated_code(project_dir, plan)
            return os.path.abspath(project_dir)

    # ---- one configuration on one generated app ----------------------------
    def _app(self, project_dir: str, name: str) -> AppRunner:
        return AppRunner(project_dir, log_path=os.path.join(self.logs_dir, f"{name}_app.log"))

    def _cfg_a(self, base: str, name: str) -> Dict[str, Any]:
        work = self._copy(base, name)
        with self._app(work, name):
            found = probe_all(self._hacker, work)
        b = run_bandit(work)
        return dict(initial_breaches=len(found), verified_fixes=0, unresolved=len(found),
                    residual_breaches=len(found), bandit_initial=b, bandit_findings=b)

    def _cfg_d(self, base: str, name: str) -> Dict[str, Any]:
        work = self._copy(base, name)
        b = run_bandit(work)
        return dict(bandit_initial=b, bandit_findings=b)

    def _cfg_duel(self, base: str, name: str, playbook_on: bool,
                  playbook_dir: Optional[str]) -> Dict[str, Any]:
        from agent.adversarial_duel import AdversarialArena
        client, model = self._llm()
        work = self._copy(base, name)
        bandit_initial = run_bandit(work)
        with temp_env(PLAYBOOK="on" if playbook_on else "off", PLAYBOOK_DIR=playbook_dir):
            with self._app(work, name) as app:
                initial = probe_all(self._hacker, work)
                arena = AdversarialArena(client, model, max_rounds=self.rounds)
                t0 = time.time()
                with quiet(os.path.join(self.logs_dir, f"{name}_duel.log")):
                    arena.conduct_duel(work, app.restart)
                duration = round(time.time() - t0, 1)
                alive = app.alive()
                residual = probe_all(self._hacker, work) if alive else None
        attempted = arena.verified_fixes + arena.unresolved
        status = "ok" if alive else "app_dead_after_duel"
        return dict(status=status, initial_breaches=len(initial), verified_fixes=arena.verified_fixes,
                    unresolved=arena.unresolved,
                    fix_rate=round(arena.verified_fixes / attempted, 4) if attempted else None,
                    residual_breaches=None if residual is None else len(residual),
                    bandit_initial=bandit_initial, bandit_findings=run_bandit(work),
                    duration_sec=duration)

    def _cfg_e(self, base: str, name: str) -> Dict[str, Any]:
        from agent.adversarial_duel import verify_patch
        client, model = self._llm()
        work = self._copy(base, name)
        bandit_initial = run_bandit(work)
        with self._app(work, name) as app:
            initial = probe_all(self._hacker, work)
            baselines = {id(b): self._hacker.capture_baseline(b.get("route", "/")) for b in initial}
            t0 = time.time()
            rewrote = single_shot_secure(client, model, work)
            restarted = app.restart() if rewrote else True
            duration = round(time.time() - t0, 1)
            verified = 0
            if restarted:
                for b in initial:
                    ok, _ = verify_patch(self._hacker, work, b, baselines[id(b)])
                    verified += 1 if ok else 0
            residual = probe_all(self._hacker, work) if restarted else None
        return dict(status="ok" if restarted else "rewrite_broke_app", initial_breaches=len(initial),
                    verified_fixes=verified, unresolved=len(initial) - verified,
                    fix_rate=round(verified / len(initial), 4) if initial else None,
                    residual_breaches=None if residual is None else len(residual),
                    bandit_initial=bandit_initial, bandit_findings=run_bandit(work),
                    duration_sec=duration)

    # ---- phases ------------------------------------------------------------
    def _train_playbook(self) -> None:
        """Builds the verified playbook from the TRAIN prompts only."""
        from agent.playbook import PlaybookManager
        train = self.prompts.get("train", [])
        if self.train_limit:
            train = train[: self.train_limit]
        if self.skip_train and os.path.isdir(self.playbook_dir) and os.listdir(self.playbook_dir):
            self.log(f"Reusing existing trained playbook: {self.playbook_dir}")
            return
        if os.path.isdir(self.playbook_dir):
            shutil.rmtree(self.playbook_dir)
        os.makedirs(self.playbook_dir, exist_ok=True)

        self.log(f"=== Training the playbook on {len(train)} train prompt(s) ===")
        train_rows: List[Dict[str, Any]] = []
        for i, p in enumerate(train, 1):
            pid = p["id"]
            self.log(f"[train {i}/{len(train)}] {pid}: {p['name']}")
            status = "ok"
            try:
                base = self._generate(p["prompt"], f"{pid}_plain", use_playbook=False, playbook_dir=None)
                res = self._cfg_duel(base, f"{pid}_train", playbook_on=True, playbook_dir=self.playbook_dir)
                status = res.get("status", "ok")
            except Exception as exc:  # recorded, never hidden
                status = f"error: {type(exc).__name__}: {exc}"[:200]
                self.log(f"   ! {status}")
            train_rows.append({"prompt_id": pid, "status": status})
        with open(os.path.join(self.out_dir, "train_runs.csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["prompt_id", "status"])
            w.writeheader()
            w.writerows(train_rows)
        entries = len(PlaybookManager(self.playbook_dir).list_entries())
        self.log(f"Playbook entries after training: {entries} (verified fixes only)")

    def _evaluate(self) -> None:
        test = self.prompts.get("held_out_test", [])
        if self.limit:
            test = test[: self.limit]
        want_plain = any(c in self.configs for c in "ABDE")
        want_pb = "C" in self.configs
        for run in range(1, self.runs + 1):
            for idx, p in enumerate(test, 1):
                pid = p["id"]
                tag = f"{pid}_r{run}"
                self.log(f"[test run {run}/{self.runs}, prompt {idx}/{len(test)}] {pid}: {p['name']}")

                plain: Optional[str] = None
                plain_err = ""
                if want_plain:
                    try:
                        plain = self._generate(p["prompt"], f"{tag}_plain", False, None)
                    except Exception as exc:
                        plain_err = f"error: generation failed: {type(exc).__name__}: {exc}"[:200]

                pb_copy = os.path.join(self.work_dir, "playbook_copies", tag)
                pb: Optional[str] = None
                pb_err = ""
                if want_pb:
                    if os.path.exists(pb_copy):
                        shutil.rmtree(pb_copy)
                    if os.path.isdir(self.playbook_dir):
                        shutil.copytree(self.playbook_dir, pb_copy)
                    else:
                        os.makedirs(pb_copy)
                    try:
                        pb = self._generate(p["prompt"], f"{tag}_pb", True, pb_copy)
                    except Exception as exc:
                        pb_err = f"error: generation failed: {type(exc).__name__}: {exc}"[:200]

                for cfg in self.configs:
                    base, err = (pb, pb_err) if cfg == "C" else (plain, plain_err)
                    name = f"{tag}_{cfg}"
                    if base is None:
                        row = self._row(pid, "held_out_test", run, cfg, status=err or "error: no app")
                    else:
                        t0 = time.time()
                        try:
                            if cfg == "A":
                                res = self._cfg_a(base, name)
                            elif cfg == "B":
                                res = self._cfg_duel(base, name, False, None)
                            elif cfg == "C":
                                res = self._cfg_duel(base, name, True, pb_copy)
                            elif cfg == "D":
                                res = self._cfg_d(base, name)
                            else:
                                res = self._cfg_e(base, name)
                            res.setdefault("duration_sec", round(time.time() - t0, 1))
                            row = self._row(pid, "held_out_test", run, cfg, **res)
                        except AppStartError:
                            row = self._row(pid, "held_out_test", run, cfg, status="app_failed_to_start")
                        except Exception as exc:
                            row = self._row(pid, "held_out_test", run, cfg,
                                            status=f"error: {type(exc).__name__}: {exc}"[:200])
                    self.records.append(row)
                    self._save()
                    self.log(f"   {cfg}: {row['status']}  initial={row['initial_breaches']} "
                             f"fixed={row['verified_fixes']} residual={row['residual_breaches']} "
                             f"bandit={row['bandit_findings']}")

    def run(self) -> List[Dict[str, Any]]:
        os.makedirs(self.out_dir, exist_ok=True)
        started = datetime.now(timezone.utc)
        try:
            self._llm()
            if "C" in self.configs:
                self._train_playbook()
            self._evaluate()
        finally:
            self._save()
            self._write_metadata(started)
        return self.records

    def _write_metadata(self, started: datetime) -> None:
        commit = ""
        with contextlib.suppress(Exception):
            commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                                    cwd=os.path.dirname(self.out_dir) or ".").stdout.strip()
        meta = {
            "started_utc": started.isoformat(timespec="seconds"),
            "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": self._model,
            "configs": self.configs,
            "runs": self.runs,
            "duel_rounds": self.rounds,
            "held_out_prompts_used": min(len(self.prompts.get("held_out_test", [])), self.limit or 10**9),
            "train_prompts_used": min(len(self.prompts.get("train", [])), self.train_limit or 10**9),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "git_commit": commit,
        }
        with open(os.path.join(self.out_dir, "run_metadata.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)


# ----------------------------------------------------------------------------
# summaries (robust to empty cells and failed rows)
# ----------------------------------------------------------------------------
def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_ok(row: Dict[str, Any]) -> bool:
    return str(row.get("status", "ok") or "ok") == "ok"


def _mean_std(values: List[float]) -> Tuple[Optional[float], Optional[float], int]:
    if not values:
        return None, None, 0
    return (statistics.mean(values),
            statistics.stdev(values) if len(values) > 1 else 0.0, len(values))


def summarize(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Tuple[Optional[float], Optional[float], int]]]:
    """Per config and metric: (mean, std, n). Only successful rows count; empty cells are skipped."""
    metrics = ["initial_breaches", "fix_rate", "residual_breaches", "bandit_initial",
               "bandit_findings", "duration_sec"]
    out: Dict[str, Dict[str, Tuple[Optional[float], Optional[float], int]]] = {}
    for cfg in sorted({str(r.get("config", "")) for r in records if r.get("config")}):
        rows = [r for r in records if str(r.get("config")) == cfg and _is_ok(r)]
        out[cfg] = {}
        for m in metrics:
            vals = [v for v in (_num(r.get(m)) for r in rows) if v is not None]
            # backwards compatible with records that only have `unresolved`
            if m == "residual_breaches" and not vals:
                vals = [v for v in (_num(r.get("unresolved")) for r in rows) if v is not None]
            out[cfg][m] = _mean_std(vals)
    return out


def paired_playbook_effect(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """First-generation breaches, config A (no playbook) vs C (playbook in the prompt), paired by prompt+run."""
    def table(cfg: str) -> Dict[Tuple[str, str], float]:
        t: Dict[Tuple[str, str], float] = {}
        for r in records:
            if str(r.get("config")) == cfg and _is_ok(r):
                v = _num(r.get("initial_breaches"))
                if v is not None:
                    t[(str(r.get("prompt_id")), str(r.get("run")))] = v
        return t
    a, c = table("A"), table("C")
    pairs = sorted(set(a) & set(c))
    diffs = [c[k] - a[k] for k in pairs]
    return {
        "pairs": len(pairs),
        "mean_a": statistics.mean(a[k] for k in pairs) if pairs else None,
        "mean_c": statistics.mean(c[k] for k in pairs) if pairs else None,
        "mean_diff_c_minus_a": statistics.mean(diffs) if diffs else None,
        "c_fewer": sum(1 for d in diffs if d < 0),
        "c_more": sum(1 for d in diffs if d > 0),
        "ties": sum(1 for d in diffs if d == 0),
    }


def _fmt(stat: Tuple[Optional[float], Optional[float], int], pct: bool = False, digits: int = 2) -> str:
    mean, std, n = stat
    if mean is None:
        return "n/a"
    if pct:
        return f"{mean * 100:.1f}% ± {(std or 0) * 100:.1f} (n={n})"
    return f"{mean:.{digits}f} ± {(std or 0):.{digits}f} (n={n})"


def write_markdown(records: List[Dict[str, Any]], md_path: str) -> None:
    summary = summarize(records)
    failed = [r for r in records if not _is_ok(r)]
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# AEGIS Benchmark Results: Empirical Evaluation\n\n")
        f.write(f"Rows: {len(records)} total, {len(records) - len(failed)} successful, "
                f"{len(failed)} failed (failed rows are excluded from the averages below).\n\n")
        f.write("**Configurations Evaluated**:\n")
        for cfg, desc in CONFIG_DESCRIPTIONS.items():
            f.write(f"- **Config {cfg}**: {desc}\n")
        f.write("\n")

        f.write("## Summary (mean ± std over successful held-out runs)\n\n")
        f.write("| Config | First-gen breaches | Verified fix rate | Remaining breaches | "
                "Bandit (first gen) | Bandit (final) | Time (s) |\n|---|---|---|---|---|---|---|\n")
        for cfg, m in summary.items():
            f.write(f"| {cfg} | {_fmt(m['initial_breaches'])} | {_fmt(m['fix_rate'], pct=True)} | "
                    f"{_fmt(m['residual_breaches'])} | {_fmt(m['bandit_initial'])} | "
                    f"{_fmt(m['bandit_findings'])} | {_fmt(m['duration_sec'], digits=1)} |\n")
        f.write("\n")

        eff = paired_playbook_effect(records)
        f.write("## Playbook effect on the FIRST generated version (config A vs C, paired)\n\n")
        if eff["pairs"]:
            f.write(f"Pairs (prompt, run): {eff['pairs']}. Mean first-generation breaches: "
                    f"A = {eff['mean_a']:.2f}, C = {eff['mean_c']:.2f}, "
                    f"difference (C − A) = {eff['mean_diff_c_minus_a']:+.2f}. "
                    f"C had fewer in {eff['c_fewer']} pair(s), more in {eff['c_more']}, "
                    f"equal in {eff['ties']}.\n\n"
                    "This is a small, unrepeated comparison on LLM-generated apps, not a statistical test. "
                    "If the difference is small or positive, the playbook did not help on this benchmark.\n\n")
        else:
            f.write("No complete A/C pairs (run `--config ALL`).\n\n")

        if failed:
            f.write("## Failed runs\n\n| Prompt ID | Config | Run | Status |\n|---|---|---|---|\n")
            for r in failed:
                f.write(f"| {r.get('prompt_id')} | {r.get('config')} | {r.get('run', '')} | {r.get('status')} |\n")
            f.write("\n")

        f.write("## Detailed Run Metrics\n\n")
        f.write("| Prompt ID | Config | Status | First-gen Breaches | Verified Fixes | Unresolved | Fix Rate | "
                "Remaining | Bandit Findings | Time (s) |\n|---|---|---|---|---|---|---|---|---|---|\n")
        for r in records:
            fr = _num(r.get("fix_rate"))
            f.write(f"| {r.get('prompt_id')} | {r.get('config')} | {r.get('status', 'ok')} | "
                    f"{r.get('initial_breaches', '')} | {r.get('verified_fixes', '')} | {r.get('unresolved', '')} | "
                    f"{'' if fr is None else f'{fr * 100:.1f}%'} | {r.get('residual_breaches', '')} | "
                    f"{r.get('bandit_findings', '')} | {r.get('duration_sec', '')} |\n")
        f.write("\n## Limitations\n\n"
                "- The Hacker is a rule-based fuzzer (crashes and a few simple checks); \"remaining breaches\" means "
                "what this fuzzer still finds, not that the app is secure.\n"
                "- Bandit is an independent static metric, but it is only a heuristic.\n"
                "- Apps are generated by a small local model; some fail to start (missing dependencies) and are "
                "reported as failed rows.\n"
                "- Few prompts and repetitions: treat differences as indicative, not conclusive.\n")


def write_chart(csv_path: str, png_path: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with open(csv_path, encoding="utf-8") as fh:
        records = list(csv.DictReader(fh))
    summary = summarize(records)
    if not summary:
        return
    configs = list(summary.keys())

    def means(metric: str, scale: float = 1.0) -> List[float]:
        return [(summary[c][metric][0] or 0.0) * scale for c in configs]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    x = range(len(configs))
    w = 0.27
    ax1.bar([i - w for i in x], means("initial_breaches"), w, label="First-gen breaches (fuzzer)", color="#805ad5")
    ax1.bar(list(x), means("residual_breaches"), w, label="Remaining breaches (fuzzer)", color="#e53e3e")
    ax1.bar([i + w for i in x], means("bandit_findings"), w, label="Bandit findings (static)", color="#dd6b20")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(configs)
    ax1.set_title("Vulnerabilities by configuration (mean)")
    ax1.set_ylabel("Mean count")
    ax1.legend()
    ax1.grid(axis="y", linestyle="--", alpha=0.7)

    ax2.bar(configs, means("fix_rate", 100.0), color="#3182ce")
    ax2.set_title("Verified fix rate (%) - only configs that attempt fixes")
    ax2.set_ylabel("Percent (%)")
    ax2.set_ylim(0, 105)
    ax2.grid(axis="y", linestyle="--", alpha=0.7)

    plt.tight_layout()
    plt.savefig(png_path, dpi=150)
    plt.close()
