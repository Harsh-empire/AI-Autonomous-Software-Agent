"""
AEGIS Benchmark Suite: Empirical Evaluation with Baselines
Evaluates AEGIS across 5 configurations on held-out test application prompts:
- Config A: No duel (raw single-pass generation)
- Config B: Adversarial Duel without playbook (PLAYBOOK=off)
- Config C: Adversarial Duel with verified defense playbook (PLAYBOOK=on)
- Config D: Static Analysis Baseline (Bandit-only vulnerability scan on initial app)
- Config E: Single-shot LLM "Make this code secure" refactor (no duel loop)

CRITICAL INTEGRITY POLICY:
Never invent or hard-code results. If Ollama is unreachable, fail loudly.

Usage (from the project root, with Ollama running and `ollama pull qwen2.5-coder:7b` done):
    pip install -r bench/requirements.txt
    python bench/run_benchmark.py --dry-run-check
    python bench/run_benchmark.py --config ALL --runs 1 --limit 2     # quick smoke run
    python bench/run_benchmark.py --config ALL --runs 3               # full run (hours)
Results are written to bench/results/ (results.csv, results.md, comparison.png, run_metadata.json).
"""

import os
import sys
import json
import time
import argparse
import subprocess
import requests
from typing import Dict, List, Any, Optional

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from bench import benchmark_core as core
from agent.llm_client import OLLAMA_BASE_URL


def check_ollama_reachable(base_url: str = OLLAMA_BASE_URL) -> bool:
    """Checks if Ollama server is reachable."""
    try:
        r = requests.get(f"{base_url}/models", timeout=2)
        return r.status_code == 200
    except Exception:
        # Also try Ollama standard tag endpoint
        try:
            raw_url = base_url.replace("/v1", "")
            r2 = requests.get(f"{raw_url}/api/tags", timeout=2)
            return r2.status_code == 200
        except Exception:
            return False


def run_bandit_scan(target_dir: str) -> int:
    """Independent static metric (Bandit). Returns the number of findings; 0 if Bandit is unavailable."""
    found = core.run_bandit(target_dir)
    return 0 if found is None else found


def generate_results_chart(csv_path: str, output_png_path: str):
    """Writes the comparison chart from a results CSV (empty cells and failed rows are skipped)."""
    try:
        core.write_chart(csv_path, output_png_path)
        print(f"📊 Benchmark chart generated: {output_png_path}")
    except Exception as e:
        print(f"⚠️ Could not generate chart: {e}")


def write_results_markdown(records: List[Dict[str, Any]], md_path: str):
    """Writes the results.md report (summary, paired playbook effect, failures, detail, limitations)."""
    core.write_markdown(records, md_path)


def _bandit_available() -> bool:
    try:
        res = subprocess.run([sys.executable, "-m", "bandit", "--version"], capture_output=True, timeout=20)
        return res.returncode == 0
    except Exception:
        return False


def _abort(message: str, code: int = 2):
    print("\n" + "!" * 80)
    print("[BENCHMARK ABORTED]")
    print(message)
    print("!" * 80 + "\n")
    sys.exit(code)


def main():
    parser = argparse.ArgumentParser(description="AEGIS Empirical Benchmark Suite")
    parser.add_argument("--prompts", default=os.path.join(current_dir, "prompts.json"), help="Path to prompts.json")
    parser.add_argument("--config", default="ALL", choices=["A", "B", "C", "D", "E", "ALL"], help="Config to run")
    parser.add_argument("--runs", type=int, default=1, help="Number of repetitions per held-out prompt")
    parser.add_argument("--rounds", type=int, default=core.MAX_TIER,
                        help="Duel rounds (default: all attack tiers, so duel and measurement cover the same probes)")
    parser.add_argument("--limit", type=int, default=0, help="Only the first N held-out prompts (0 = all)")
    parser.add_argument("--train-limit", type=int, default=0, help="Only the first N train prompts (0 = all)")
    parser.add_argument("--skip-train", action="store_true", help="Reuse an existing trained playbook")
    parser.add_argument("--out", default=os.path.join(current_dir, "results"), help="Output directory")
    parser.add_argument("--dry-run-check", action="store_true", help="Check prerequisites and exit")
    args = parser.parse_args()

    # =========================================================================
    # LOUD HONESTY CHECK: Refuse to run if Ollama is unreachable
    # =========================================================================
    if not check_ollama_reachable():
        print("\n" + "!" * 80)
        print("[BENCHMARK ABORTED - HONESTY & EMPIRICAL INTEGRITY POLICY]")
        print(f"The LLM server is unreachable at {OLLAMA_BASE_URL}.")
        print("AEGIS strictly forbids fabricating, mocking, or hard-coding benchmark numbers.")
        print("To run the empirical benchmark:")
        print("  1. Start Ollama: 'ollama serve'")
        print("  2. Pull the default model: 'ollama pull qwen2.5-coder:7b'")
        print("  3. Run: python bench/run_benchmark.py --config ALL --runs 1")
        print("!" * 80 + "\n")
        sys.exit(1)

    configs = list("ABCDE") if args.config == "ALL" else [args.config]

    if not _bandit_available():
        _abort("Bandit is not installed (it is the independent security metric).\n"
               "Install it with: pip install -r bench/requirements.txt")
    needs_app = any(c in configs for c in "ABCE")
    if needs_app and core.port_in_use(core.TARGET_PORT):
        _abort(f"Port {core.TARGET_PORT} is already in use. The benchmark starts each generated app on "
               f"{core.TARGET_PORT}; stop the IDE's preview server or any other app using it and retry.")

    if args.dry_run_check:
        print("✅ Ollama is reachable, Bandit is installed and the app port is free. Prerequisites satisfied.")
        sys.exit(0)

    with open(args.prompts, encoding="utf-8") as fh:
        prompts = json.load(fh)

    print("🚀 Starting AEGIS Empirical Benchmark...")
    print(f"   configs={configs} runs={args.runs} rounds={args.rounds} "
          f"held-out limit={args.limit or 'all'} -> {args.out}")
    runner = core.BenchmarkRunner(
        out_dir=args.out, prompts=prompts, configs=configs, runs=args.runs, rounds=args.rounds,
        limit=args.limit, train_limit=args.train_limit, skip_train=args.skip_train,
    )
    try:
        records = runner.run()
    except KeyboardInterrupt:
        print("\nInterrupted: partial results were saved.")
        records = runner.records

    if records:
        write_results_markdown(records, os.path.join(args.out, "results.md"))
        generate_results_chart(runner.csv_path, os.path.join(args.out, "comparison.png"))
        ok = sum(1 for r in records if core._is_ok(r))
        print(f"\nDone: {len(records)} row(s), {ok} successful, {len(records) - ok} failed.")
        print(f"Results: {runner.csv_path}\n         {os.path.join(args.out, 'results.md')}")
    else:
        print("No rows were produced.")


if __name__ == "__main__":
    main()
