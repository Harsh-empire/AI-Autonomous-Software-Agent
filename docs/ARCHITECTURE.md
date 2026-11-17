# AEGIS Technical Architecture & Verification Design

This document details the internal design of AEGIS, the mechanics of the **Verified Patch Gate**, the **Verified-Only Defense Playbook**, and how to reproduce empirical evaluations.

---

## 1. System Architecture

```mermaid
flowchart TD
    User["User Prompt / Feature Request"] --> Scaffolder["Builder AI Scaffolding Engine"]
    Playbook[("Verified Defense Playbook")] -->|Top-k Defensive Snippets| Scaffolder
    
    Scaffolder --> TargetApp["Target Web Application (Port 5000)"]
    
    subgraph Arena["Adversarial Duel Loop"]
        Hacker["Hacker AI (Rule-Based Fuzzer)"] -->|Multi-Tier Exploits / Probes| TargetApp
        TargetApp -->|Crash 500 / Breach Output| Hacker
        
        Hacker -->|Breach Report (route, method, payload)| Builder["Builder AI (Defensive Coder)"]
        Builder -->|Synthesizes Targeted Patch| Gate{"Verified Patch Gate"}
        
        Gate -->|Gate 1: AST Parse Fails| Discard["Discard Patch (Keep Original)"]
        Gate -->|Gate 1 Passes| Restart["Restart App on Port 5000"]
        Restart --> Replay["Gate 2: Replay Breach Probe"]
        
        Replay -->|Payload Still Crashes| Unresolved["Mark UNRESOLVED (Hole Remains)"]
        Replay -->|Payload Sealed| Regress["Gate 3: Test Legitimate Baseline Routes"]
        
        Regress -->|Baseline Broken| Unresolved
        Regress -->|Baseline OK| Verified["Mark VERIFIED_PATCHED"]
        
        Verified --> IngestPlaybook["Ingest into Playbook & Save poc.json"]
    end
    
    Arena --> Reports["Scorecard, report.md & SARIF 2.1.0 Export"]
    Arena --> WebIDE["AEGIS Web IDE (:8000) Live Preview & Diffs"]
```

---

## 2. Media & Demo Placeholders

<!-- SCREENSHOT PLACEHOLDER: Main IDE Screen with Live Code Preview, File Explorer, and Unified Diff Viewer -->
> _Screenshot Placeholder: Web IDE showing Unified Diff Viewer and Live Application Preview._
> *(To add: Place image at `docs/images/ide_overview.png` and link here)*

<!-- SCREENSHOT PLACEHOLDER: Adversarial Arena Scorecard & SARIF Findings -->
> _Screenshot Placeholder: Adversarial Duel Scorecard showing truthful verified metrics._
> *(To add: Place image at `docs/images/duel_scorecard.png` and link here)*

<!-- DEMO VIDEO PLACEHOLDER: 3-Minute Walkthrough Video -->
> _Demo Video Placeholder: 3-Minute Technical Walkthrough._
> *(To add: Insert YouTube / Loom video link here once recorded)*

---

## 3. How the Verified Patch Gate Works

Unlike standard generative code-repair agents that assume an LLM's patch is correct simply because it finished generating, AEGIS treats all LLM patches as untrusted candidate proposals until proven by three sequential verification gates:

### Gate 1: Abstract Syntax Tree Validation (`ast.parse`)
- The synthesized patch code is passed to Python's built-in `ast.parse()`.
- If the model generated invalid indentation, truncated code, or syntax errors, the patch is discarded immediately.
- The original application file is left untouched.

### Gate 2: Replay Probe Verification (`replay_breach`)
- The application server is restarted with the candidate patch applied.
- The fuzzer re-issues the **exact** probe (identical HTTP method, endpoint route, and payload) that triggered the initial crash or breach.
- If the server still responds with HTTP 500, a crash traceback, or an injection pattern, the patch is marked **UNRESOLVED**.

### Gate 3: Legitimate Behavior & Regression Check (`test_legitimate_behavior`)
- A common flaw in automated repair is "patching" a vulnerability by commenting out the route or returning an unconditional error response.
- Gate 3 performs automated regression checks on legitimate routes (e.g., standard `GET /` and valid requests).
- If legitimate functionality was broken, the patch fails verification and remains **UNRESOLVED**.

### Measured Outcome Accounting
- `verified_fixes` increments **only** if Gates 1, 2, and 3 pass.
- `unresolved` increments whenever any gate fails.
- Overall shield score is strictly calculated as `verified_fixes / total_breaches`. It **never** defaults to 100% or "FORTIFIED".

---

## 4. How the Defense Playbook Works

When a patch passes all three gates:
1. `poc.json` is generated with `{vuln_type, route, method, payload, status_code, timestamp, verified: True}`.
2. `regression_test.py` is written to the project folder for continuous testing.
3. The mitigation is ingested into `PlaybookManager` in `playbook/`.
4. On future application generations, `get_relevant_entries(prompt)` retrieves matching verified snippets to inoculate the Builder's system prompt prior to code generation.

The Playbook strictly refuses unverified patches (`verified != True`) and can be enabled or disabled via `export PLAYBOOK=on|off`.
