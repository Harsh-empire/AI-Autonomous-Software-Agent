# AEGIS: Dual-AI Adversarial Hardening Platform

AEGIS is an experimental local development environment that couples a generative developer (**Builder AI**) with an automated red-team fuzzer (**Hacker AI**) to synthesize, test, and harden web applications through empirical probe-and-patch cycles.

To my knowledge, AEGIS is among the first open-source developer environments to enforce a **Verified Patch Gate**—guaranteeing that defensive patches are counted as fixed only after automated syntax parsing, exact payload replay verification, and regression testing against legitimate application functionality.

---

## ⚡ Quickstart (Run from Fresh Clone in 3 Commands)

```bash
git clone https://github.com/Harsh-empire/AI-Autonomous-Software-Agent.git && cd AI-Autonomous-Software-Agent
pip install -r requirements.txt
python ide_server.py
```
*(Or via Docker Sandbox: `docker compose up -d`)*

### Expected Output
```text
INFO:     Started server process [PID]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```
Navigate to **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.

### Common Errors & Solutions
- **Ollama daemon not running (`Connection refused: 127.0.0.1:11434`):**
  Start Ollama in a separate terminal: `ollama serve` (or launch the Ollama system tray application).
- **Model not pulled (`model 'qwen2.5-coder:7b' not found`):**
  Pull the required coding model: `ollama pull qwen2.5-coder:7b`.
- **Docker daemon not installed or stopped:**
  Ensure Docker Desktop / daemon is active, or use local Python execution via `python ide_server.py`.

---

## What AEGIS Is and Is NOT

### What AEGIS Is
- **An Empirical Hardening Loop:** An automated iterative arena where web applications are probed for common injection, crash, and boundary vulnerabilities, followed by targeted defensive code synthesis.
- **A Verified Patch Gate:** An architectural gate ensuring code modifications pass abstract syntax tree (`ast.parse`) validation, fail to reproduce the original exploit payload upon re-test, and preserve legitimate route behavior.
- **A Verified-Only Defense Playbook:** A pattern retrieval cache that stores proven defensive mitigations to inoculate newly generated applications against previously encountered vulnerability classes.
- **A Sandboxed Local IDE:** A browser-based interface running on `127.0.0.1:8000` with unified diff viewing, automated regression test generation, and SARIF 2.1.0 report export.

### What AEGIS Is NOT
- **NOT an accredited OWASP compliance scanner:** AEGIS evaluates specific heuristic probes; passing all probes does **not** certify an application as OWASP compliant or secure against determined human adversaries.
- **NOT an autonomous cognitive exploit synthesizer:** The Hacker agent operates as a **rule-based HTTP payload fuzzer**. The underlying LLM is utilized exclusively for taunts, natural-language commentary, and builder repair suggestions—not for generating novel exploits.
- **NOT "bulletproof" or "unhackable":** Vulnerability detection primarily flags HTTP 500 server crashes, unhandled exceptions, and basic string reflections (e.g., `<script>` reflection, `{{7*7}} -> 49`, and `root:` in path traversal). Passing probes proves resilience against tested payloads, not the absolute absence of bugs.
- **NOT safe for public exposure without containerization:** The Builder AI synthesizes and executes Python code directly. The IDE binds to `127.0.0.1` by default and must never be exposed on public interfaces (`0.0.0.0`) without virtualization.

---

## Architecture: The Dual-AI Loop & Verified Patch Gate

```
                     +-------------------------------+
                     |    User Requirement Prompt    |
                     +-------------------------------+
                                     |
                                     v
                     +-------------------------------+
                     |      Builder AI Scaffolder    |
                     |  (Inoculated by Playbook API) |
                     +-------------------------------+
                                     |
                                     v
       +-------------------------------------------------------------+
       |                ADVERSARIAL DUEL ARENA                       |
       |                                                             |
       |  +--------------------+             +--------------------+  |
       |  |     HACKER AI      | HTTP Probes |   TARGET APP       |  |
       |  | (Rule-Based Fuzzer)| ----------> | (Port 5000/Sandbx) |  |
       |  +--------------------+             +--------------------+  |
       |           |                                    ^            |
       |           | Breach Payload                     |            |
       |           v                                    |            |
       |  +--------------------+     AST-Verified Patch |            |
       |  |     BUILDER AI     | -----------------------+            |
       |  | (Defensive Coder)  |                                     |
       |  +--------------------+                                     |
       |           |                                                 |
       |           v                                                 |
       |  +=======================================================+  |
       |  |              VERIFIED PATCH GATE                      |  |
       |  |  [1] AST Syntax Validation (ast.parse)                |  |
       |  |  [2] Replay Probe: Re-test must NOT reproduce crash   |  |
       |  |  [3] Legitimate Behavior: Non-exploit routes work     |  |
       |  +=======================================================+  |
       |           |                             |                   |
       |       [PASSED]                       [FAILED]               |
       |           v                             v                   |
       |  Save poc.json,               Increment unresolved count.   |
       |  regression_test.py,          Keep breach open. Score       |
       |  Ingest into Playbook.        reflects verified/total.      |
       +-------------------------------------------------------------+
                                     |
                                     v
                     +-------------------------------+
                     |       AEGIS WEB IDE (:8000)   |
                     |  - Measured Shield Score      |
                     |  - Side-by-side Diff Viewer   |
                     |  - report.md & SARIF Export   |
                     |  - Verified Inoculation Stats |
                     +-------------------------------+
```

### The Three Invariants of the Verified Patch Gate
1. **Syntactic Integrity:** The generated patch must parse cleanly under Python's `ast.parse`. If syntax is invalid, the patch is discarded and the original source is preserved.
2. **Exploit Negation:** The exact HTTP request (route, method, payload) that triggered the breach is replayed against the restarted server. It must no longer trigger an HTTP 500 crash or vulnerability signature.
3. **Functional Non-Regression:** The fuzzer checks standard application baseline routes (e.g. `GET /`). If the patch disabled or broke legitimate functionality, the fix is marked **UNRESOLVED**.

Only patches satisfying all three criteria increment `verified_fixes` and are ingested into the Defense Playbook.

---

## Hardware Requirements & Prerequisites

- **OS:** Linux, macOS, or Windows (WSL2 or PowerShell).
- **RAM:** 16 GB minimum recommended for running local 7B parameter models.
- **VRAM / GPU:** NVIDIA GPU with 8+ GB VRAM recommended for fast inference; CPU inference supported via Ollama with modest latency.
- **Python:** Python 3.10, 3.11, or 3.12 (tested on 3.11 and 3.14).
- **Docker:** (Optional but recommended) Docker and Docker Compose v2+.

---

## Quickstart

### Option 1: Docker Compose (Recommended Sandbox Setup)

The container runs with non-root privileges (`aegis`), read-only filesystem root, CPU and memory limits, and a 512 MB tmpfs:

```bash
# Clone the repository
git clone https://github.com/Harsh-empire/AI-Autonomous-Software-Agent.git
cd AI-Autonomous-Software-Agent

# Launch IDE and local Ollama service in isolated containers
docker compose up -d

# Pull the default coding model inside the ollama container
docker compose exec ollama ollama pull qwen2.5-coder:7b
```

Access the Web IDE at: **http://127.0.0.1:8000**

---

### Option 2: Local Python Environment

1. **Install Ollama & Pull Model:**
   Download Ollama from [ollama.ai](https://ollama.ai), start the service, and pull the required model:
   ```bash
   ollama pull qwen2.5-coder:7b
   ```

2. **Setup Python Environment:**
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/macOS:
   source .venv/bin/activate

   pip install -r requirements.txt
   ```

3. **Launch with Helper Script:**
   - On Windows: Run `start.bat`
   - On Linux/macOS: Run `chmod +x start.sh && ./start.sh`

   Or run directly:
   ```bash
   python ide_server.py
   ```

---

## Verified-Only Defense Playbook

The Defense Playbook (`agent/playbook.py`) retains verified mitigations to prevent recurring vulnerabilities.

- **Gate Enforcement:** Calling `add_verified_entry()` with `verified: False` raises a `ValueError` rejection.
- **Environment Toggle:** Enable or disable playbook retrieval via the `PLAYBOOK` variable:
  ```bash
  export PLAYBOOK=on   # default
  export PLAYBOOK=off  # disable playbook injection
  ```
- **REST API & CLI:**
  - `GET /api/playbook`: List all stored defensive patterns.
  - `POST /api/playbook/{id}/toggle`: Toggle pattern active/disabled status.
  - `DELETE /api/playbook/{id}`: Delete an entry.

---

## Benchmarking & Empirical Baselines

AEGIS includes a standardized benchmarking harness (`bench/run_benchmark.py`) with 20 application-generation prompts:
- **10 Training Prompts:** Used to seed and evaluate initial playbook entries.
- **10 Held-out Test Prompts:** Never used during playbook construction to test generalization.

### Evaluated Configurations
- **Config A:** Generative baseline (No adversarial duel).
- **Config B:** Adversarial duel without playbook.
- **Config C:** Adversarial duel + Verified Defense Playbook.
- **Config D:** Static analysis baseline (Bandit scan on baseline generation).
- **Config E:** Single-shot LLM prompt ("make this code secure" without duel).

### Strict Real-Run Policy
The benchmark runner strictly adheres to empirical verification:
- If Ollama is unreachable at `http://127.0.0.1:11434`, the runner **fails loudly** with an explicit error and exit code `1`. It never generates synthetic or placeholder benchmark metrics.
- Output artifacts are saved to `bench/results/results.csv`, `bench/results/summary.md`, and `bench/results/comparison.png`.

To run the benchmark suite on a machine with live Ollama:
```bash
python bench/run_benchmark.py --config A B C D E --rounds 3
```

*(Note: If Ollama is offline or the model is not loaded, the script will output a connection error instructing the user to start `ollama serve` and pull `qwen2.5-coder:7b`.)*

---

## Audit Reports & SARIF 2.1.0 Export

Every completed adversarial audit generates:
1. `security_audit.json`: Machine scorecard with measured shield score (`verified_fixes / total_breaches`) and breach logs. Never defaults to 100% or FORTIFIED without verification.
2. `report.md`: Human-readable audit report detailing discovered vectors, verified fixes, diffs, regression test status, manual remediation recommendations, and scope limitations.
3. `security_audit.sarif` / `audit_sarif.json`: Standard SARIF 2.1.0 document compatible with GitHub Code Scanning and enterprise security dashboards.
4. `poc.json` & `regression_test.py`: Reproducible proof-of-concept payload and regression test script saved in the project directory for every verified mitigation.

---

## Related Work & Academic Context

AEGIS builds upon and compares against recent literature in autonomous agent security and program repair:
- **RvB (Red vs Blue LLM Multi-Agent Framework):** *arXiv:2601.19726* — Explores competitive multi-agent dynamics between attacker and defender LLMs.
- **Co-RedTeam (Collaborative LLM Red-Teaming Architectures):** *arXiv:2602.02164* — Investigates coordinated adversarial probing strategies against target interfaces.
- **MemRepair / Retrieval-Augmented Program Repair:** Evaluates the efficacy of verified memory retention and episodic patch retrieval across recurring software vulnerability classes.

---

## Honest Limitations

1. **Rule-Based Fuzzing Engine:** The Hacker agent executes predefined heuristic payloads across 9 tiers (boundary tests, SQLi strings, XSS script tags, SSTI expressions, traversal sequences). It does not conduct deep symbolic execution, dynamic taint analysis, or multi-step session hijacking.
2. **Crash-Centric Detection:** Breaches are primarily detected when an endpoint returns HTTP 500 or an unhandled exception. Silent logic errors (e.g. improper access control returning 200 with unauthorized data) may not be detected unless explicit assertion probes are configured.
3. **No Proof of Complete Security:** A measured shield score of 100% signifies that 100% of *detected breaches* in that specific run were verified as patched against the *tested probe suite*. It does not prove the absence of undiscovered vulnerabilities.
4. **Sandboxing is Mandatory:** Because the Builder AI generates executable Python code, production or multi-tenant deployments must enforce strict micro-VM or container isolation. Never expose the web IDE or preview ports publicly without network isolation.

---

## Continuous Integration & Testing

Run all unit and regression tests locally:
```bash
pytest tests/ -v
```

CI runs automatically via GitHub Actions (`.github/workflows/ci.yml`) across **Ubuntu** and **Windows** on Python 3.11 and 3.12, enforcing zero tolerance for path-traversal regressions.

---

## License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.
