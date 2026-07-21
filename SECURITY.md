# Security Policy

## Reporting a vulnerability

Do not open a public issue for vulnerabilities involving credential exposure, prompt injection, command execution, or unsafe repository publishing. Report them privately through GitHub Security Advisories for this repository.

Include the affected command, reproduction steps, impact, and suggested mitigation. Never include real API keys, OAuth tokens, credential databases, or private repository contents.

## Trust boundary

Treat every documented repository as untrusted input. RepoDocs disables target-repository agent customizations and restricts LLM backends to read-only repository inspection. `repodocs setup` installs prompt files only and never copies credentials automatically.

Generated documentation can contain sensitive business or implementation details even when it contains no machine-detectable secret. Review output before publishing.
