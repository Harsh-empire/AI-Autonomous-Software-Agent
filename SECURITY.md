# Security Policy

## Supported Versions

Only the latest release on the primary development branch is actively supported with security updates.

| Version | Supported          |
| ------- | ------------------ |
| 2.0.x   | :white_check_mark: |
| < 2.0   | :x:                |

## Reporting a Vulnerability

We take the security of AEGIS seriously. Because AEGIS executes LLM-generated code locally, proper sandboxing and access controls are critical.

If you believe you have found a security vulnerability (such as a path traversal flaw, sandbox escape, or remote execution risk):

1. **Do NOT open a public GitHub issue.**
2. Send an email to the maintainers at **`security-report@example.com`** with:
   - A description of the vulnerability and its potential impact.
   - Minimal steps or a Proof-of-Concept (PoC) script to reproduce the issue.
   - Any suggested remediations or mitigations.
3. You will receive an acknowledgment within 48 hours.
4. We ask that you adhere to coordinated disclosure guidelines and give the maintainers reasonable time to issue a fix before publishing details publicly.

## Security Practices for Users

- **Local Execution:** Always run the AEGIS web IDE bound to `127.0.0.1` (the default) or inside the provided Docker Compose sandbox.
- **Untrusted Prompts:** Never expose the web IDE to public untrusted networks, as it generates and runs Python applications.
