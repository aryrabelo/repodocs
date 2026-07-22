# Security Policy

## Supported versions

Security fixes are applied to the latest release and the current `main` branch.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability.

Report it through [GitHub private vulnerability reporting](https://github.com/aryrabelo/repodocs/security/advisories/new) or email [aryrabelo@gmail.com](mailto:aryrabelo@gmail.com). Include affected commands, reproduction steps, impact, and any suggested mitigation. Expect an acknowledgement within 72 hours.

## Security scope

RepoDocs:

- reads the target repository and writes generated output under the selected output directory;
- invokes a locally installed OMP, Claude Code, or Codex CLI when generation is requested;
- may invoke Graphify during `repodocs all`;
- accesses the network only through those external tools and when publishing to GitHub Pages;
- refuses direct publishing from `main`, `master`, or `trunk`, scans generated output for common secret patterns, blocks publishing when source citations are missing or resolve outside the repository, and requires `--allow-public` before pushing;
- sanitizes rendered Markdown in the offline viewer with DOMPurify so repository-derived content cannot inject scripts, and ships third-party license notices alongside vendored assets;
- does not copy or bundle agent credentials during setup.

Generated documentation can still expose sensitive repository content. Review the output and repository visibility before publishing it.
