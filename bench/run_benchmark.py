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
from typing import Dict, List, Any, Optional, Tuple

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


def check_llm_ready(model_name: str) -> Tuple[bool, str]:
    """Checks that the selected provider can answer. Local Ollama is probed for free; a cloud provider
    gets ONE tiny test request (it counts against your quota)."""
    from agent.llm_client import LLMQuotaError, get_llm_client, provider_for
    provider = provider_for(model_name)
    if provider == "ollama":
        if check_ollama_reachable():
            return True, f"Ollama is reachable at {OLLAMA_BASE_URL} (model: {model_name})"
        return False, f"The local LLM server (Ollama) is unreachable at {OLLAMA_BASE_URL}."
    try:
        client, model = get_llm_client(model_name)
    except ValueError as exc:
        return False, str(exc)
    try:
        client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": "Reply with the single word OK."}],
            max_tokens=8, temperature=0,
        )
    except LLMQuotaError as exc:
        return False, f"{provider} is rate-limiting this key right now. {exc}"
    except Exception as exc:
        return False, f"{provider} request failed ({type(exc).__name__}): {str(exc)[:200]}"
    return True, f"{provider} is reachable with model '{model}' (1 test request was used)"


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
    parser.add_argument("--model", default=None,
                        help="Model name, overrides AEGIS_MODEL: qwen2.5-coder:7b (local), gemini-2.5-flash, "
                             "openrouter:<model id>, ...")
    parser.add_argument("--min-interval", type=float, default=None,
                        help="Minimum seconds between LLM calls (pacing for rate-limited free cloud tiers)")
    parser.add_argument("--resume", action="store_true",
                        help="Keep successful rows from an earlier run in --out and only do the rest")
    parser.add_argument("--dry-run-check", action="store_true", help="Check prerequisites and exit")
    args = parser.parse_args()

    if args.model:
        os.environ["AEGIS_MODEL"] = args.model
    if args.min_interval is not None:
        os.environ["AEGIS_LLM_MIN_INTERVAL"] = str(args.min_interval)
    from agent.llm_client import provider_for
    model_name = os.environ.get("AEGIS_MODEL", "qwen2.5-coder:7b")
    provider = provider_for(model_name)

    # =========================================================================
    # LOUD HONESTY CHECK: refuse to run if the selected LLM is not available
    # =========================================================================
    ready, detail = check_llm_ready(model_name)
    if not ready:
        print("\n" + "!" * 80)
        print("[BENCHMARK ABORTED - HONESTY & EMPIRICAL INTEGRITY POLICY]")
        print(detail)
        print("AEGIS strictly forbids fabricating, mocking, or hard-coding benchmark numbers.")
        if provider == "ollama":
            print("To run the empirical benchmark:")
            print("  1. Start Ollama: 'ollama serve'")
            print("  2. Pull the default model: 'ollama pull qwen2.5-coder:7b'")
            print("  3. Run: python bench/run_benchmark.py --config ALL --runs 1")
        else:
            print("Check the API key environment variable, the exact model id and your quota.")
        print("!" * 80 + "\n")
        sys.exit(1)
    print(f"LLM check: {detail}")
    if provider != "ollama":
        print(f"NOTE: prompts and generated code are sent to {provider}. Free tiers can use them to improve the "
              "provider's products and have request limits. Results are only comparable with other runs that "
              "used the same model; report the model next to the numbers.")

    configs = list("ABCDE") if args.config == "ALL" else [args.config]

    if not _bandit_available():
        _abort("Bandit is not installed (it is the independent security metric).\n"
               "Install it with: pip install -r bench/requirements.txt")
    needs_app = any(c in configs for c in "ABCE")
    if needs_app and core.port_in_use(core.TARGET_PORT):
        _abort(f"Port {core.TARGET_PORT} is already in use. The benchmark starts each generated app on "
               f"{core.TARGET_PORT}; stop the IDE's preview server or any other app using it and retry.")

    if args.dry_run_check:
        print("✅ LLM is reachable, Bandit is installed and the app port is free. Prerequisites satisfied.")
        sys.exit(0)

    with open(args.prompts, encoding="utf-8") as fh:
        prompts = json.load(fh)

    print("🚀 Starting AEGIS Empirical Benchmark...")
    print(f"   configs={configs} runs={args.runs} rounds={args.rounds} "
          f"held-out limit={args.limit or 'all'} -> {args.out}")
    runner = core.BenchmarkRunner(
        out_dir=args.out, prompts=prompts, configs=configs, runs=args.runs, rounds=args.rounds,
        limit=args.limit, train_limit=args.train_limit, skip_train=args.skip_train, resume=args.resume,
    )
    quota_error = None
    try:
        records = runner.run()
    except KeyboardInterrupt:
        print("\nInterrupted: partial results were saved.")
        records = runner.records
    except core.LLMQuotaError as exc:
        quota_error = exc
        records = runner.records

    if records:
        write_results_markdown(records, os.path.join(args.out, "results.md"))
        generate_results_chart(runner.csv_path, os.path.join(args.out, "comparison.png"))
        ok = sum(1 for r in records if core._is_ok(r))
        print(f"\nDone: {len(records)} row(s), {ok} successful, {len(records) - ok} failed.")
        print(f"Results: {runner.csv_path}\n         {os.path.join(args.out, 'results.md')}")
    else:
        print("No rows were produced.")

    if quota_error:
        print("\n" + "!" * 80)
        print("[STOPPED: LLM RATE LIMIT / QUOTA]")
        print(str(quota_error))
        print("Partial results were saved. Continue later (after the quota resets) with the same command plus --resume.")
        print("!" * 80)
        sys.exit(3)


if __name__ == "__main__":
    main()
