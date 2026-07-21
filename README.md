# RepoDocs

RepoDocs generates source-cited repository wikis with OMP, Claude Code, or Codex CLI. It scans a codebase deterministically, asks an LLM to plan feature-level pages, generates Markdown with line citations, and builds a self-contained HTML viewer.

The driver is a single Python 3.10+ standard-library script. The planner and writer contracts are vendored in this repository, so output format does not depend on the target repository's agent instructions.

## Contents

- [Features](#features)
- [Non-goals](#non-goals)
- [Install](#install)
- [Quick start](#quick-start)
- [Choose an LLM backend](#choose-an-llm-backend)
- [Pipeline commands](#pipeline-commands)
- [Publishing safety](#publishing-safety)
- [Architecture](#architecture)
- [Development](#development)
- [Release policy](#release-policy)
- [License](#license)

## Features

- OMP, Claude Code, and Codex CLI backends
- Claude Sonnet 5 support through OMP or Claude Code
- Deterministic repository inventory and heuristic fallback plan
- Parallel page generation with SHA-256 incremental rebuilds
- Source citation linting
- Optional translation
- Offline `wiki.html` with vendored assets
- Guarded GitHub Pages publishing

## Non-goals

RepoDocs does not host generated wikis, replace source code review, or guarantee that generated documentation is safe to publish without human review. It also does not manage credentials for the supported agent CLIs.

## Install

```bash
git clone https://github.com/aryrabelo/repodocs ~/Sites/repodocs
cd ~/Sites/repodocs
./install.sh
repodocs --selftest
```

`install.sh` creates `~/.local/bin/repodocs` and `~/.local/bin/repodocs-all` symlinks. Ensure `~/.local/bin` is on `PATH`.

## Quick start

```bash
cd /path/to/project
repodocs-all .
```

`repodocs-all` runs the full pipeline: graphify update, scan, plan, generate, and vendored HTML. Install graphify with `uv tool install graphifyy`, or skip it:

```bash
repodocs-all . --no-graph
repodocs-all . --force       # replan and regenerate every page
```

Output is written to `repo-docs/`; open `repo-docs/wiki.html` in a browser.

## Choose an LLM backend

Set `REPODOCS_BACKEND` to `omp`, `claude`, or `codex`. `REPODOCS_MODEL` is passed to the selected CLI and therefore uses that CLI's model naming.

### OMP with Claude Sonnet 5

```bash
export REPODOCS_BACKEND=omp
export REPODOCS_MODEL=anthropic/claude-sonnet-5
repodocs setup
omp --profile=repo-docs
# Run /login inside OMP once, then exit.
```

OMP is the default backend. RepoDocs applies a one-process isolation overlay that disables target discovery providers, rules, skills, and extensions; only read, grep, and glob tools are available.

### Claude Code with Claude Sonnet 5

```bash
export REPODOCS_BACKEND=claude
export REPODOCS_MODEL=claude-sonnet-5
claude
# Run /login inside Claude Code once, then exit.
```

Claude Code runs in safe mode with no session persistence and only read, grep, and glob tools.

### Codex CLI

```bash
export REPODOCS_BACKEND=codex
unset REPODOCS_MODEL       # use the Codex default
codex login
```

Codex runs in an ephemeral read-only sandbox rooted outside the target repository. The repository is exposed through a read-only path and its agent instruction files are not loaded as the run contract.

## Pipeline commands

```bash
repodocs scan .                         # deterministic inventory
repodocs plan .                         # write repo-docs/plan.json
repodocs generate .                     # generate changed Markdown pages
repodocs translate . --lang pt          # optional translation
repodocs html . --vendor                # build offline wiki.html
repodocs publish . --dry-run            # review public payload
repodocs publish . --allow-public       # force-push gh-pages after review
```

`REPODOCS_JOBS` controls parallel generation from 1 to 16 workers (default 4). `REPODOCS_TIMEOUT` controls each LLM subprocess timeout in seconds (default 600).

Run `repodocs <command> --help` for command-specific options.

## Publishing safety

Publishing stages files in a temporary worktree, refuses `main`, `master`, and `trunk`, scans generated output for common private-key and token patterns, and requires `--allow-public`. Always run `--dry-run` first. The generated `gh-pages` history is disposable and force-pushed; the source working tree is not changed.

Generated documentation can still reveal sensitive source-level information that does not match a token pattern. Review the complete dry-run file list and generated pages before publishing a private repository's wiki.

## Architecture

- `repodocs` — stdlib-only driver and built-in selftest
- `repo-docs-profile/AGENTS.md` — shared output discipline
- `repo-docs-profile/isolation.yml` — OMP discovery-provider isolation
- `repo-docs-profile/agents/wiki-planner.md` — planner JSON contract
- `repo-docs-profile/agents/wiki-writer.md` — page and citation contract
- `install.sh` — local command installation

## Development

```bash
python3 repodocs --selftest
```

For backend changes, also generate one page against a small fixture with every affected authenticated CLI. See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## Release policy

RepoDocs follows [Semantic Versioning](https://semver.org/). User-visible changes are recorded in [CHANGELOG.md](CHANGELOG.md); `repodocs --version` prints the installed version. Security fixes target the latest release and `main`.

## License

MIT. See [LICENSE](LICENSE).
