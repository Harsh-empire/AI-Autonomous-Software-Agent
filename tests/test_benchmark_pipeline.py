"""
End-to-end test of the benchmark machinery with a stubbed LLM (see tests/stub_llm.py).

This proves the runner really generates an app, starts it, probes it, runs the duel and the
baselines, and writes results. The numbers are fixtures of a canned stub, NOT benchmark results.
"""

import csv
import json
import os
import sys

import pytest

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, ".."))
for p in (root_dir, current_dir):
    if p not in sys.path:
        sys.path.insert(0, p)

pytest.importorskip("matplotlib")
pytest.importorskip("bandit")

from bench import benchmark_core as core  # noqa: E402
from bench.run_benchmark import generate_results_chart, write_results_markdown  # noqa: E402
from stub_llm import start_stub_llm  # noqa: E402


@pytest.mark.skipif(core.port_in_use(core.TARGET_PORT), reason="port 5000 is busy")
def test_runner_end_to_end_with_stub_llm(tmp_path, monkeypatch):
    import agent.llm_client as llm_client

    server, base_url = start_stub_llm()
    try:
        monkeypatch.setattr(llm_client, "OLLAMA_BASE_URL", base_url)
        monkeypatch.setattr(core, "MAX_TIER", 2)  # keep the test fast
        playbook_default = os.path.join(root_dir, "playbook")
        before = sorted(os.listdir(playbook_default)) if os.path.isdir(playbook_default) else []

        prompts = {
            "train": [{"id": "train_01", "name": "stub_a", "prompt": "Build a stub shop"}],
            "held_out_test": [{"id": "test_01", "name": "stub_b", "prompt": "Build a stub shop"}],
        }
        out = str(tmp_path / "bench_out")
        runner = core.BenchmarkRunner(out_dir=out, prompts=prompts, configs=list("ABCDE"),
                                      runs=1, rounds=2, log=lambda m: None)
        records = runner.run()

        by_cfg = {r["config"]: r for r in records}
        assert sorted(by_cfg) == list("ABCDE")
        for cfg, row in by_cfg.items():
            assert row["status"] == "ok", (cfg, row["status"])

        # A: raw app is measured and the stub app really is breakable
        assert int(by_cfg["A"]["initial_breaches"]) >= 1
        assert by_cfg["A"]["verified_fixes"] == 0
        # B and C: duel verified at least one fix and nothing got worse
        for cfg in "BC":
            assert int(by_cfg[cfg]["verified_fixes"]) >= 1
            assert int(by_cfg[cfg]["residual_breaches"]) <= int(by_cfg[cfg]["initial_breaches"])
        # D: static scan only, no dynamic fields
        assert by_cfg["D"]["initial_breaches"] == "" and by_cfg["D"]["fix_rate"] == ""
        # The gate's evidence files (assert-based regression tests) must not inflate Bandit findings:
        # B/C/E all end with the same safe app code, so their static findings must match.
        assert by_cfg["B"]["bandit_findings"] == by_cfg["E"]["bandit_findings"] == by_cfg["C"]["bandit_findings"]
        # E: single-shot rewrite judged by the same gate
        assert int(by_cfg["E"]["verified_fixes"]) >= 1

        # train phase produced a playbook from VERIFIED fixes only, outside the repo playbook dir
        trained = os.path.join(out, "playbook_trained")
        assert os.path.isdir(trained) and os.listdir(trained)
        after = sorted(os.listdir(playbook_default)) if os.path.isdir(playbook_default) else []
        assert before == after, "benchmark must not write into the repository playbook"

        # outputs
        assert os.path.exists(os.path.join(out, "results.csv"))
        meta = json.load(open(os.path.join(out, "run_metadata.json"), encoding="utf-8"))
        assert meta["configs"] == list("ABCDE") and meta["runs"] == 1
        write_results_markdown(records, os.path.join(out, "results.md"))
        generate_results_chart(runner.csv_path, os.path.join(out, "comparison.png"))
        md = open(os.path.join(out, "results.md"), encoding="utf-8").read()
        assert "Playbook effect on the FIRST generated version" in md and "test_01" in md
        assert os.path.getsize(os.path.join(out, "comparison.png")) > 0
        with open(os.path.join(out, "results.csv"), newline="", encoding="utf-8") as fh:
            assert len(list(csv.DictReader(fh))) == 5

        # nothing is left running on the target port
        assert not core.port_in_use(core.TARGET_PORT)
    finally:
        server.shutdown()
