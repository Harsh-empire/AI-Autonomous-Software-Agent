# AEGIS Benchmark Reproduction Guide

This guide outlines the methodology, configurations, and reproduction steps for the empirical benchmark evaluated in AEGIS.

---

## 1. Prompt Dataset Structure

The benchmark suite is located in `bench/prompts.json` and consists of 20 realistic web application prompts divided into two disjoint subsets:
- **10 Training Prompts (`train_01` through `train_10`):** Used to seed the Defense Playbook and assess iterative in-distribution learning.
- **10 Held-Out Test Prompts (`test_01` through `test_10`):** Never exposed during playbook construction; used to measure generalization and transference of defensive patterns to novel application schemas.

---

## 2. Evaluated Configurations

- **Config A (no duel):** the raw generated app is measured (Hacker fuzzer + Bandit); nothing is fixed.
- **Config B (duel, no playbook):** Builder/Hacker duel with `PLAYBOOK=off`, for as many rounds as there are attack tiers (default 5).
- **Config C (duel + verified playbook):** the app is generated with playbook rules in the prompt, then dueled with `PLAYBOOK=on`. The playbook is built only from the 10 train prompts (verified fixes only). Each C run uses a throw-away copy of it, so held-out apps never feed back into the playbook.
- **Config D (Bandit only):** static scan of the raw generated app; no dynamic probes and no fixing.
- **Config E (single-shot LLM):** one "make this code secure" rewrite of `app.py`; each initial breach is then judged by the same Verified Patch Gate (exact replay + legitimate-behaviour baseline).

All configs of one prompt and run share the same raw generated app (A, B, D, E); config C starts from its own generation because the playbook changes the generation prompt.

---

## 3. Metrics (columns of `results.csv`)

| Column | Meaning |
|---|---|
| `initial_breaches` | Unique breaches the Hacker fuzzer finds on the first generated version (all tiers) |
| `verified_fixes` | Fixes accepted by the Verified Patch Gate (A: 0; E: per initial breach) |
| `unresolved` | Breaches that were not fixed or whose patch failed verification |
| `fix_rate` | `verified_fixes / (verified_fixes + unresolved)` for configs that attempt fixes; empty otherwise |
| `residual_breaches` | Breaches the fuzzer still finds after the pipeline (empty if the app died) |
| `bandit_initial`, `bandit_findings` | Bandit findings on the app code before and after (evidence files written by the gate are excluded) |
| `duration_sec` | Wall-clock time of the duel or rewrite |
| `status` | `ok` or an error status; non-`ok` rows are excluded from the averages |

The summary in `results.md` also contains a paired comparison of first-generation breaches for config A vs C. That comparison asks whether the verified playbook reduces breaches in freshly generated apps; if the difference is small or positive, the playbook did not help on this benchmark.

---

## 4. How to Reproduce

### Prerequisites
1. Start the local Ollama daemon and pull the model:
   ```bash
   ollama serve
   ollama pull qwen2.5-coder:7b
   ```
2. Install the benchmark dependencies: `pip install -r bench/requirements.txt`
3. Make sure port `5000` is free (each generated app is started on it) and that the generated apps' dependencies (Flask, Flask-SQLAlchemy, ...) are installed in the same environment (`pip install -r requirements.txt -r examples/requirements.txt`). Apps that need other packages fail to start and are reported as failed rows.

### Execution
Run from the repository root:

```bash
python bench/run_benchmark.py --dry-run-check
python bench/run_benchmark.py --config ALL --runs 1 --limit 2 --train-limit 2   # smoke run
python bench/run_benchmark.py --config ALL --runs 3                              # full run

# A subset of configurations (C still trains the playbook first):
python bench/run_benchmark.py --config B --runs 3
python bench/run_benchmark.py --config C --runs 3 --skip-train   # reuse an existing trained playbook
```

### Using a cloud LLM
`--model gemini-2.5-flash` (needs `GEMINI_API_KEY`) or `--model "openrouter:<vendor/model>:free"` (needs `OPENROUTER_API_KEY`) replace the local model. Use `--min-interval SECONDS` to pace requests and `--resume` to continue after the quota resets (the runner exits with code `3` when the quota is exhausted and saves partial results). Free tiers have per-minute/per-day limits, may use your prompts to improve the provider's products, and a different model gives numbers that are not comparable with a local run. The model and provider are written to `results.md` and `run_metadata.json`. See the main README for details.

### Truthful Data Policy
- The runner refuses to run (exit code `1`) if the LLM server is unreachable. It never writes synthetic numbers.
- Results are written to `bench/results/`: `results.csv`, `results.md`, `comparison.png`, `run_metadata.json`, `train_runs.csv`, and per-run logs.
- Report the numbers as they come out. The Hacker is a rule-based fuzzer and the apps come from a small local model, so treat differences as indicative, not conclusive.
