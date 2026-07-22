# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-07-22

### Added

- `publish-wiki` command: exports generated Markdown to a repository's GitHub Wiki, maps `overview.md` to `Home.md`, generates `_Sidebar.md` from plan order, rewrites source citations to commit-pinned GitHub blob URLs, and preserves unrelated manual wiki pages.
- `render-diagrams` command plus an optional Bun/playwright tool (`tools/diagram_poster.ts`): pre-renders each Markdown `mermaid` block to a committed pastel PNG and swaps the block for an image embed, so a published GitHub wiki shows the diagram even when GitHub's own mermaid renderer fails to load. Kept out of the zero-dependency Python core; `publish-wiki` now stages committed diagram PNGs alongside the pages.
- PyPI Trusted-Publishing release workflow (`.github/workflows/publish.yml`): a `v*` tag builds and publishes `repodocs` to PyPI over OIDC (no stored token), guarded by a tag/VERSION match check.
- `CLAUDE.README.md`: an agent-facing orientation file for coding agents working in the repo.

### Changed

- Claude Code with `claude-sonnet-5` is now the default backend. Running `repodocs-all .` after authenticating Claude Code requires no environment variables. OMP and Codex remain supported via `REPODOCS_BACKEND=omp|codex`.
- Distribution now uses standard Python packaging with `uvx`/`uv tool install`, exposing `repodocs` and `repodocs-all` console commands without a persistent source clone.
- The single-file driver is now a `repodocs` package (`src/repodocs/`, one module per pipeline stage). The former in-module `--selftest` moved to a `tests/` pytest suite so test code no longer ships in the distributed package, and a CI guardrail keeps every shipped module under 500 lines. Run locally with `python -m repodocs`.

### Fixed

- Citation generation self-repairs mechanically-fixable citations before the blocking check, so honest-but-malformed output no longer makes a wiki unpublishable: an end line one past EOF is clamped to the file's real length, labels missing the `L` prefix or written single-line are canonicalized, and a dropped `src/<pkg>/` path prefix is resolved against the unique matching tracked file. Citations that cannot be made honest are still left for the publish gate to block.

### Security

- `publish` and `publish-wiki` now **block** on missing or invalid source citations: a cited path that does not exist, escapes the repository (path traversal or symlink), has an out-of-range or reversed line range, or carries a label whose path/range disagrees with its link target. Previously these were warnings only; the source-cited guarantee is now enforced before any push.
- The offline HTML viewer sanitizes rendered Markdown with DOMPurify, blocking script injection, event-handler attributes, and `javascript:` URLs originating from repository-derived page content.
- Repository scanning no longer ingests RepoDocs' own generated output (`repo-docs/`, `graphify-out/`, and the configured `--out` directory under any name) or files reached through symlinks that escape the repository, so a rerun cannot pull generated assets or out-of-tree files into a wiki.
- Vendored offline assets ship with a `THIRD-PARTY-NOTICES.txt` reproducing the marked, Mermaid, highlight.js, and DOMPurify licenses so published artifacts carry attribution.
- Citation link rewriting now HTML-escapes the link text and percent-escapes the path, so untrusted Markdown cannot inject attributes or tags into the generated `<a>`.
- `publish` and `publish-wiki` staging reject symlinked source pages before any read or copy, and surface bounded errors (never raw `git` command output) when a wiki push fails.
- The offline viewer fails closed when DOMPurify cannot load (it refuses to render rather than showing unsanitized HTML) and runs Mermaid in `securityLevel: "strict"`.

## [0.1.0] - 2026-07-21

### Added

- Deterministic repository scanning and feature-level wiki planning.
- Cited page generation through OMP, Claude Code, or Codex.
- Incremental rebuilds, translation, and a self-contained HTML viewer.
- Safe GitHub Pages publishing with branch and secret checks.
- Standalone installer, vendored agent contracts, and self-test.

[Unreleased]: https://github.com/aryrabelo/repodocs/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/aryrabelo/repodocs/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/aryrabelo/repodocs/releases/tag/v0.1.0
