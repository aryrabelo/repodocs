# RepoDocs

**Point RepoDocs at any repo and get a source-cited, always-rebuildable wiki — built by Claude Code, OMP, or Codex.**

<!-- Badges: add PyPI version FIRST once published — https://img.shields.io/pypi/v/repodocs -->
[![CI](https://github.com/aryrabelo/repodocs/actions/workflows/ci.yml/badge.svg)](https://github.com/aryrabelo/repodocs/actions)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![Zero runtime deps](https://img.shields.io/badge/deps-0-brightgreen.svg)

<!-- HERO: replace with a <5MB GIF/screenshot of a generated wiki page showing a source citation to an exact line (see repodocs-gtm/05-demo-asset.md). -->
<!-- ![RepoDocs generating a cited wiki](docs/demo.gif) -->

If RepoDocs is useful to you, please ⭐ the repo — it helps others find it.

RepoDocs is a **DeepWiki / cubic.dev alternative** for AI repo documentation: it
scans a codebase deterministically, drives your coding-agent CLI to plan
feature-level pages, and writes Markdown where **every claim cites a file and
line**. Output is a self-contained `wiki.html` you can open offline. For
maintainers who want docs they can trust — and never hand-write again.

- ✓ Source citations on every page — linked to exact lines
- ✓ Backends: Claude Code (default), OMP, Codex CLI
- ✓ Zero runtime dependencies — Python stdlib only
- ✓ Parallel generation with SHA-256 incremental rebuilds
- ✓ Offline `wiki.html`, optional translation, guarded publishing

## Contents

- [Quick start](#quick-start)
- [Why RepoDocs and not the alternatives](#why-repodocs-and-not-the-alternatives)
- [Choose an LLM backend](#choose-an-llm-backend)
- [Pipeline commands](#pipeline-commands)
- [Publishing safety](#publishing-safety)
- [Upgrading](#upgrading)
- [Non-goals](#non-goals)
- [Development](#development)
- [License](#license)

## Quick start

**Prerequisites:** Python 3.10+, [uv](https://docs.astral.sh/uv/), and graphify (`uv tool install graphifyy`) — or pass `--no-graph` to skip it. No uv yet?
`curl -LsSf https://astral.sh/uv/install.sh | sh`

Run the full pipeline in any repo — no clone, no install:

```bash
cd /path/to/project
uvx --from git+https://github.com/aryrabelo/repodocs repodocs-all .
```

Open `repo-docs/wiki.html` in a browser. That's it.

<!-- After PyPI publish (Phase 2), replace the block above with the friction-free:
```bash
uvx repodocs .            # try without installing
uv tool install repodocs  # install persistently
```
-->

### Install persistently

Keep `repodocs` / `repodocs-all` on `PATH`:

```bash
uv tool install git+https://github.com/aryrabelo/repodocs
uv tool update-shell
repodocs --version
```

### Using it from a coding agent

In Claude Code / OMP / Codex, just ask the agent to run `repodocs-all .` and open
the wiki. RepoDocs is a CLI your agent calls — not an in-process plugin.

## Why RepoDocs and not the alternatives

| | RepoDocs | Hosted DeepWiki/cubic-style |
|---|---|---|
| Runs | Locally, on your machine | Uploads your repo to a service |
| Runtime deps | Zero (stdlib only) | N/A (SaaS) |
| Citations | Every claim → file:line | Varies |
| Output | Offline `wiki.html` you own | Hosted only |
| Backend | Your Claude Code / OMP / Codex login | Their models |
| Private repos | Never leave your machine | Uploaded |

## Choose an LLM backend

Set `REPODOCS_BACKEND` to `claude` (default), `omp`, or `codex`. `REPODOCS_MODEL`
overrides the model. Each backend runs read-only (read/grep/glob only) with no
session persistence.

- **Claude Code (default):** run `claude`, `/login` once; then `repodocs-all .`. Default model `claude-sonnet-5`.
- **OMP:** `export REPODOCS_BACKEND=omp`, `repodocs setup`, `omp --profile=repo-docs`, `/login` once.
- **Codex CLI:** `export REPODOCS_BACKEND=codex`, `codex login`. Ephemeral read-only sandbox.

## Pipeline commands

```bash
repodocs-all .                 # full pipeline: graphify → scan → plan → generate → html
repodocs scan .                # deterministic inventory
repodocs plan .                # write repo-docs/plan.json
repodocs generate .            # generate changed Markdown pages
repodocs translate . --lang pt # optional translation
repodocs html . --vendor       # build offline wiki.html
repodocs publish . --dry-run   # review the public payload (always first)
```

`repodocs <command> --help` lists every flag. `REPODOCS_JOBS` (1–16, default 4)
controls parallelism; `REPODOCS_TIMEOUT` sets each LLM subprocess timeout. A bare
invocation prints help, not a stack trace.

## Publishing safety

Publishing stages files in a temporary worktree, **refuses `main`/`master`/`trunk`**,
scans output for private-key/token patterns, and requires `--allow-public`. Always
`--dry-run` first. Generated docs can still reveal sensitive source detail that
matches no token pattern — **review the dry-run file list before publishing a
private repo's wiki.** GitHub Wiki export (`publish-wiki`) is also supported.

## Upgrading

```bash
uv tool upgrade repodocs                                   # if installed as a tool
# or reinstall from git:
uv tool install --force git+https://github.com/aryrabelo/repodocs
```

## Non-goals

RepoDocs does not host generated wikis, replace source-code review, guarantee
output is safe to publish without human review, or manage credentials for the
agent CLIs.

## Development

Run the checks with `uv run --extra test pytest -q`. Contributions:
[CONTRIBUTING.md](CONTRIBUTING.md) · Security: [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © Ary Rabelo
