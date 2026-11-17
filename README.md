# AEGIS: Dual-AI Autonomous Software Development & Adversarial Hardening Platform

AEGIS is an experimental developer workspace and agent architecture that pits a **Builder AI** (generative developer) against an automated **Hacker AI** (red-team fuzzer) to construct, test, and harden web applications.

---

## ⚠️ Important Disclaimers & Security Considerations

Before running AEGIS, please review these essential technical truths:

1. **How the "Hacker AI" Works**:
   - The red-team engine is primarily a **rule-based HTTP fuzzer and probe suite**.
   - The LLM is used to generate playful taunts, commentary, and targeted code defense suggestions—not autonomous exploit synthesis.
   - Vulnerability detection relies predominantly on **HTTP 500 crash responses**, unhandled exceptions, and basic heuristic pattern checks:
     - **XSS**: Checks if `<script>` payload is reflected verbatim in the response.
     - **SSTI**: Injects `{{7*7}}` and checks for the string `49`.
     - **Path Traversal**: Probes for `../../../../etc/passwd` and checks for `root:`.
     - **SQL Injection**: Checks for SQL syntax crash errors or bypass responses.
2. **Not Formally OWASP Certified**:
   - This project performs **basic sanity, crash, and heuristic injection probes**. It is **not** an accredited OWASP compliance scanner and does not guarantee complete security coverage.
3. **Arbitrary Code Execution**:
   - The Builder AI generates and executes Python code directly on your local system when spinning up preview servers.
   - **Always run this software inside an isolated Virtual Machine (VM) or Docker container** when generating or testing untrusted code. Never expose the IDE port publicly (`0.0.0.0`).

---

## Architecture

```
                      +-----------------------------+
                      |   User Requirement Prompt   |
                      +-----------------------------+
                                     |
                                     v
                       +---------------------------+
                       |  Multi-Stack Scaffolder   |
                       |      (Flask / Node)       |
                       +---------------------------+
                                     |
                                     v
     +---------------------------------------------------------------+
     |                   ADVERSARIAL DUEL LOOP                       |
     |                                                               |
     |  +--------------------+               +--------------------+  |
     |  |     HACKER AI      |  HTTP Probes  |   TARGET SERVER    |  |
     |  | (Rule-Based Fuzzer)| ------------> |  (Port :5000)      |  |
     |  +--------------------+               +--------------------+  |
     |            |                                    ^             |
     |            | Breach Report                      |             |
     |            v                                    |             |
     |  +--------------------+     AST-Verified Patch  |             |
     |  |     BUILDER AI     | ------------------------+             |
     |  | (Defensive Coder)  |  (Verified via Re-test)               |
     |  +--------------------+                                       |
     +---------------------------------------------------------------+
                                     |
                                     v
               +-------------------------------------------+
               |           AEGIS WEB IDE (:8000)           |
               |  - Live Application Preview               |
               |  - Visual Unified Patch Diff Viewer       |
               |  - Shield Health Score & Audit Log        |
               |  - 1-Click ZIP Archive Export             |
               +-------------------------------------------+
```

---

## Getting Started

### Prerequisites
- Python 3.10+ (tested on Python 3.11 and 3.14)
- (Optional) [Ollama](https://ollama.ai) installed and running locally

### 1. Installation

Clone the repository and install the core dependencies:

```bash
git clone https://github.com/Harsh-empire/AI-Autonomous-Software-Agent.git
cd AI-Autonomous-Software-Agent

# Recommended: create a virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
```

*(Note: If you run sample apps with advanced features like Stripe or Flask-WTF, install `pip install -r requirements-examples.txt`.)*

### 2. Configure Model Providers

AEGIS supports both local offline models and cloud frontier models:

#### Option A: Local Ollama (Default, Free & Offline)
1. Install Ollama from [ollama.ai](https://ollama.ai).
2. Pull the recommended coding model:
   ```bash
   ollama pull qwen2.5-coder:7b
   ```
3. Ensure Ollama is running (`ollama serve` or via system tray).

#### Option B: Cloud Models (Google Gemini, OpenAI GPT-4o, Anthropic Claude)
Set any of the following environment variables (or place them in a `.env` file):

```bash
# Google Gemini (gemini-1.5-flash, gemini-2.0-flash)
export GEMINI_API_KEY="your-gemini-api-key"

# OpenAI (gpt-4o, gpt-4o-mini)
export OPENAI_API_KEY="your-openai-api-key"

# Anthropic Claude (claude-3-5-sonnet)
export ANTHROPIC_API_KEY="your-anthropic-api-key"
```

### 3. Launch the Web IDE

Start the backend server:

```bash
python ide_server.py
```

Open your browser at:
👉 **[http://127.0.0.1:8000](http://127.0.0.1:8000)**

---

## Features

- **Adversarial Arena**: Launch a multi-round duel where the Hacker AI probes endpoints and the Builder AI applies targeted defensive patches.
- **Truthful Security Score**: Scores are strictly calculated based on *verified* patches. If a patch does not survive a re-test, it remains marked as `UNRESOLVED` and prevents a false `FORTIFIED` verdict.
- **Path Traversal Protection**: All filesystem and project access endpoints are protected with strict `safe_join` checks against directory traversal (`../`).
- **Live Visual Diff Viewer**: Watch unified diffs highlight inserted defensive sanitation routines in real-time.
- **Chaos Console**: Manually fire targeted exploits (SQLi, XSS, SSTI, Unicode flooding) and trigger auto-remediation.
- **1-Click ZIP Export**: Export cleanly fortified codebases without virtual environments or temporary files.

---

## Running Automated Tests

Run the regression test suite with `pytest`:

```bash
pytest tests/ -v
```

Tests verify:
- Path traversal prevention on all endpoints and traversal payloads.
- Truthful score calculation in the Adversarial Arena (preventing premature 100% scores).
- Safe file operations.

---

## Known Limitations

- **Heuristic Fuzzing**: Complex multi-step business logic vulnerabilities (e.g. race conditions in checkout, complex token replay attacks) will not be detected by the current single-shot HTTP fuzzer.
- **Local Process Management**: The preview server runs as a local subprocess on port 5000. If port 5000 is occupied by another service, the preview will fail to bind.
- **Single Target Language**: Automated AST verification currently supports Python/Flask applications. Node/Express targets run basic execution probes without AST analysis.
