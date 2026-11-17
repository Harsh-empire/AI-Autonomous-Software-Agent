# AEGIS Release Checklist

Before tagging and publishing any release of AEGIS, maintainers must verify each of the following release gating requirements:

---

## 1. Automated Test Suite
- [ ] All unit and regression tests pass locally:
  ```bash
  pytest tests/ -v
  ```
- [ ] Critical path-traversal gate tests pass:
  ```bash
  pytest tests/test_path_traversal.py -v
  ```
- [ ] GitHub Actions CI workflow (`.github/workflows/ci.yml`) is completely green across both Ubuntu and Windows matrix jobs.

---

## 2. Secrets & Privacy Scan
- [ ] No API keys, credentials, or personal tokens committed (check `git diff`, `.env`, and test files).
- [ ] No local machine absolute file paths leaked (e.g. `C:\Users\...`, `e:/Moon/...`, or `/home/...`).
- [ ] Verified `.env` is ignored by `.gitignore` and only `.env.example` is tracked.

---

## 3. Empirical Benchmarks & Honesty Check
- [ ] If benchmark numbers or comparison charts are published, they must originate from real, measured executions (`python bench/run_benchmark.py`).
- [ ] No synthetic or mock figures are used.
- [ ] Tone check: Ensure no prohibited marketing words ("bulletproof", "unhackable", "100%", "first ever") are used as ungrounded claims. Use "to my knowledge" for novelty claims.

---

## 4. Licensing & Governance
- [ ] `LICENSE` (MIT) is present in the repository root.
- [ ] `SECURITY.md` contact details and supported versions are up to date.
- [ ] `CONTRIBUTING.md` instructions are accurate.

---

## 5. Version Tagging & Artifact Generation
- [ ] Ensure working directory is clean: `git status`.
- [ ] Create signed git tag:
  ```bash
  git tag -a v2.0.0 -m "AEGIS v2.0.0: Dual-AI Development & Verified Patch Gate"
  ```
- [ ] Push commits and tags to remote:
  ```bash
  git push origin hardening
  git push origin v2.0.0
  ```
