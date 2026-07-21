# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `publish-wiki` command: exports generated Markdown to a repository's GitHub Wiki, maps `overview.md` to `Home.md`, generates `_Sidebar.md` from plan order, rewrites source citations to commit-pinned GitHub blob URLs, and preserves unrelated manual wiki pages.

### Changed

- Claude Code with `claude-sonnet-5` is now the default backend. Running `repodocs-all .` after authenticating Claude Code requires no environment variables. OMP and Codex remain supported via `REPODOCS_BACKEND=omp|codex`.
- Distribution now uses standard Python packaging with `uvx`/`uv tool install`, exposing `repodocs` and `repodocs-all` console commands without a persistent source clone.

## [0.1.0] - 2026-07-21

### Added

- Deterministic repository scanning and feature-level wiki planning.
- Cited page generation through OMP, Claude Code, or Codex.
- Incremental rebuilds, translation, and a self-contained HTML viewer.
- Safe GitHub Pages publishing with branch and secret checks.
- Standalone installer, vendored agent contracts, and self-test.

[Unreleased]: https://github.com/aryrabelo/repodocs/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/aryrabelo/repodocs/releases/tag/v0.1.0
