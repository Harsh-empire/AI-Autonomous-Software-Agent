# AEGIS Benchmark Reproduction Guide

This guide outlines the methodology, configurations, and reproduction steps for the empirical benchmark evaluated in AEGIS.

---

## 1. Prompt Dataset Structure

The benchmark suite is located in `bench/prompts.json` and consists of 20 realistic web application prompts divided into two disjoint subsets:
- **10 Training Prompts (`train_01` through `train_10`):** Used to seed the Defense Playbook and assess iterative in-distribution learning.
- **10 Held-Out Test Prompts (`test_01` through `test_10`):** Never exposed during playbook construction; used to measure generalization and transference of defensive patterns to novel application schemas.

---

## 2. Evaluated Configurations

The benchmark compares five configurations:
- **Config A (Baseline Generative):** Standard Builder AI generation without an adversarial duel loop.
- **Config B (Adversarial Duel - No Playbook):** Builder AI pitted against Hacker AI across multi-round duels, without historical playbook inoculation (`PLAYBOOK=off`).
- **Config C (Adversarial Duel + Verified Playbook):** Builder AI inoculated with verified patterns retrieved from previous successful duel fixes (`PLAYBOOK=on`).
- **Config D (Static Analysis Baseline - Bandit):** Standard Builder AI generation evaluated by Bandit static analysis rather than dynamic fuzzing.
- **Config E (Single-Shot LLM Defense):** Single-shot prompt asking the model: *"Analyze this code and rewrite it to make it secure against vulnerabilities"*, without empirical re-testing.

---

## 3. Evaluated Metrics

For each held-out prompt, the harness records:
1. `initial_breaches`: Total vulnerabilities detected during round 1 probing.
2. `verified_fixes`: Number of patches successfully validated by the Verified Patch Gate.
3. `unresolved`: Number of breaches where candidate patches failed re-test or broke baseline routes.
4. `verification_rate`: `verified_fixes / initial_breaches`.
5. `clean_runs`: Proportion of applications with zero remaining unresolved breaches.
6. `total_time_seconds`: Wall-clock execution time.

---

## 4. How to Reproduce

### Prerequisites
1. Start the local Ollama daemon:
   ```bash
   ollama serve
   ```
2. Pull the default evaluation model:
   ```bash
   ollama pull qwen2.5-coder:7b
   ```

### Execution Command
Run the runner from the repository root:

```bash
# Run all configurations across 3 duel rounds per prompt
python bench/run_benchmark.py --config A B C D E --rounds 3

# Or evaluate a specific subset of configurations:
python bench/run_benchmark.py --config B C --rounds 3
```

### Truthful Data Policy
- The benchmark runner strictly forbids synthetic or mock benchmark values. If Ollama is offline or unreachable on port 11434, the runner will abort with an explicit connection error.
- All real run metrics will be written to:
  - `bench/results/results.csv`
  - `bench/results/summary.md`
  - `bench/results/comparison.png`
