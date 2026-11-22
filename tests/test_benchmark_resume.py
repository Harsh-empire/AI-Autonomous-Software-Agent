"""
Tests for the benchmark runner's behaviour with rate-limited cloud LLMs:
- an exhausted quota stops the run but keeps the partial results,
- --resume keeps successful rows, skips finished work and retries failed rows.
Uses config D (Bandit only) so no LLM, app or port is needed.
"""

import csv
import json
import os
import sys

import pytest

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

pytest.importorskip("bandit")

from agent.llm_client import LLMQuotaError  # noqa: E402
from bench import benchmark_core as core  # noqa: E402

PROMPTS = {
    "train": [],
    "held_out_test": [
        {"id": "test_01", "name": "one", "prompt": "p1"},
        {"id": "test_02", "name": "two", "prompt": "p2"},
    ],
}


@pytest.fixture()
def project(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    (d / "app.py").write_text("print('hello')\n", encoding="utf-8")
    return str(d)


def _runner(tmp_path, **kw):
    runner = core.BenchmarkRunner(out_dir=str(tmp_path / "out"), prompts=PROMPTS, configs=["D"],
                                  runs=1, log=lambda m: None, **kw)
    runner._llm = lambda: (None, "stub-model")  # no LLM needed for config D
    runner._model = "stub-model"
    return runner


def _rows(tmp_path):
    with open(tmp_path / "out" / "results.csv", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_quota_error_stops_the_run_and_keeps_partial_results(tmp_path, project, monkeypatch):
    calls = []

    def fake_generate(self, prompt, tag, use_playbook, playbook_dir):
        calls.append(tag)
        if len(calls) == 2:
            raise LLMQuotaError("daily quota exhausted")
        return project

    monkeypatch.setattr(core.BenchmarkRunner, "_generate", fake_generate)
    runner = _runner(tmp_path)
    with pytest.raises(LLMQuotaError):
        runner.run()

    rows = _rows(tmp_path)
    assert [r["prompt_id"] for r in rows] == ["test_01"] and rows[0]["status"] == "ok"
    meta = json.loads((tmp_path / "out" / "run_metadata.json").read_text(encoding="utf-8"))
    assert meta["provider"] == "ollama" and meta["model"] == "stub-model"


def test_resume_skips_finished_work_and_retries_failed_rows(tmp_path, project, monkeypatch):
    # first run: prompt 1 succeeds, prompt 2 fails with an ordinary error (recorded, run continues)
    state = {"n": 0}

    def flaky_generate(self, prompt, tag, use_playbook, playbook_dir):
        state["n"] += 1
        if "test_02" in tag:
            raise RuntimeError("model returned garbage")
        return project

    monkeypatch.setattr(core.BenchmarkRunner, "_generate", flaky_generate)
    _runner(tmp_path).run()
    rows = _rows(tmp_path)
    assert {r["prompt_id"]: r["status"] for r in rows}["test_01"] == "ok"
    assert {r["prompt_id"]: r["status"] for r in rows}["test_02"].startswith("error: generation failed")

    # resume: only the failed prompt is generated again; the good row is kept untouched
    seen = []

    def resume_generate(self, prompt, tag, use_playbook, playbook_dir):
        seen.append(tag)
        return project

    monkeypatch.setattr(core.BenchmarkRunner, "_generate", resume_generate)
    _runner(tmp_path, resume=True).run()
    assert all("test_02" in t for t in seen) and seen
    rows = _rows(tmp_path)
    assert sorted(r["prompt_id"] for r in rows) == ["test_01", "test_02"]
    assert all(r["status"] == "ok" for r in rows)

    # a third resume has nothing left to do and must not call the LLM at all
    def must_not_run(self, *a, **k):
        raise AssertionError("nothing should be regenerated")

    monkeypatch.setattr(core.BenchmarkRunner, "_generate", must_not_run)
    _runner(tmp_path, resume=True).run()
    assert len(_rows(tmp_path)) == 2
