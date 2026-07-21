# RepoDocs

RepoDocs generates source-cited repository wikis with Claude Code, OMP, or Codex CLI. It scans a codebase deterministically, asks an LLM to plan feature-level pages, generates Markdown with line citations, and builds a self-contained HTML viewer.

The driver is a single Python 3.10+ standard-library script. The planner and writer contracts are vendored in this repository, so output format does not depend on the target repository's agent instructions.

## Contents

- [Features](#features)
- [Non-goals](#non-goals)
- [Install](#install)
- [Quick start](#quick-start)
- [Choose an LLM backend](#choose-an-llm-backend)
- [Pipeline commands](#pipeline-commands)
- [Publishing safety](#publishing-safety)
- [Publishing to GitHub Wiki](#publishing-to-github-wiki)
- [Architecture](#architecture)
- [Development](#development)
- [Release policy](#release-policy)
- [License](#license)

## Features

- Claude Code backend with Claude Sonnet 5 as the zero-configuration default
- OMP and Codex CLI backends for users who prefer them
- Parallel page generation with SHA-256 incremental rebuilds
- Source citation linting, enforced as a blocking gate before publishing
- Optional translation
- Offline `wiki.html` with vendored assets, a sanitized (DOMPurify) viewer, and third-party license notices
- Guarded GitHub Pages publishing
- GitHub Wiki export with Home mapping, sidebar generation, and commit-pinned source citations

## Non-goals

RepoDocs does not host generated wikis, replace source code review, or guarantee that generated documentation is safe to publish without human review. It also does not manage credentials for the supported agent CLIs.

## Install

RepoDocs requires Python 3.10 or newer and [uv](https://docs.astral.sh/uv/).

Run it directly from GitHub — no clone needed:

```bash
uvx --from git+https://github.com/aryrabelo/repodocs repodocs --version
uvx --from git+https://github.com/aryrabelo/repodocs repodocs --selftest
```

To keep `repodocs` and `repodocs-all` on `PATH` without repeating `--from` on
every invocation:

```bash
uv tool install git+https://github.com/aryrabelo/repodocs
uv tool update-shell
repodocs --version
```

## Quick start

Run the complete pipeline in any repository without installing RepoDocs:

```bash
cd /path/to/project
uvx --from git+https://github.com/aryrabelo/repodocs repodocs-all .
```

If you used `uv tool install`, the shorter command is `repodocs-all .`.

`repodocs-all` runs the full pipeline: graphify update, scan, plan, generate, and vendored HTML. Install graphify with `uv tool install graphifyy`, or skip it:

```bash
repodocs-all . --no-graph
repodocs-all . --force       # replan and regenerate every page
```

Output is written to `repo-docs/`; open `repo-docs/wiki.html` in a browser.

## Choose an LLM backend

Set `REPODOCS_BACKEND` to `claude` (default), `omp`, or `codex`. `REPODOCS_MODEL` overrides the model passed to the selected CLI and uses that CLI's naming convention; leave it unset to get the per-backend default.

### Claude Code (default)

Authenticate Claude Code once:

```bash
claude
# Run /login inside Claude Code once, then exit.
```

Then run without any environment variables:

```bash
repodocs-all .
```

Claude Code runs in safe mode with no session persistence and only read, grep, and glob tools. The default model is `claude-sonnet-5`.

### OMP (optional)

```bash
export REPODOCS_BACKEND=omp
export REPODOCS_MODEL=anthropic/claude-sonnet-5   # or any OMP-supported model
repodocs setup
omp --profile=repo-docs
# Run /login inside OMP once, then exit.
```

RepoDocs applies a one-process isolation overlay that disables target discovery providers, rules, skills, and extensions; only read, grep, and glob tools are available.

### Codex CLI (optional)

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

## Publishing to GitHub Wiki

GitHub Wiki export writes Markdown pages to the repository's built-in wiki — a separate Git repository — instead of building a static HTML site on `gh-pages`.

**One-time prerequisite.** GitHub requires at least one page before the wiki can be cloned. Navigate to `https://github.com/OWNER/REPO/wiki` and click "Create the first page" to initialise it. RepoDocs cannot create an empty wiki. See [Adding or editing wiki pages](https://docs.github.com/en/communities/documenting-your-project-with-wikis/adding-or-editing-wiki-pages).

```bash
# 1. Generate docs
repodocs-all .

# 2. Create the first wiki page in GitHub once (browser, not CLI)
#    https://github.com/OWNER/REPO/wiki → "Create the first page"

# 3. Preview — lists exact staged files and target
repodocs publish-wiki . --dry-run

# 4. Push
repodocs publish-wiki . --allow-public
```

What `publish-wiki` does:

- Maps `overview.md` (fallback: `index.md`) to `Home.md` — the wiki landing page
- Generates `_Sidebar.md` from plan page order and titles
- Rewrites source citation links to absolute GitHub blob URLs pinned to the current pushed commit SHA
- Clones `OWNER/REPO.wiki.git` into a temporary directory, overwrites only exported filenames, commits if anything changed, and pushes — unrelated manual wiki pages are preserved
- Wiki visibility follows repository settings; there is no separate access control

If the wiki is uninitialized or disabled, `publish-wiki` exits with an explicit error and instructions to enable it in GitHub.

## Architecture

- `repodocs.py` — stdlib-only driver and built-in selftest
- `pyproject.toml` — Hatchling packaging; publishes the `repodocs` and `repodocs-all` console scripts
- `repo-docs-profile/AGENTS.md` — shared output discipline
- `repo-docs-profile/isolation.yml` — OMP discovery-provider isolation
- `repo-docs-profile/agents/wiki-planner.md` — planner JSON contract
- `repo-docs-profile/agents/wiki-writer.md` — page and citation contract

## Development

```bash
uvx --refresh --from . repodocs --selftest
```

For backend changes, also generate one page against a small fixture with every affected authenticated CLI. See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## Release policy

RepoDocs follows [Semantic Versioning](https://semver.org/). User-visible changes are recorded in [CHANGELOG.md](CHANGELOG.md); `repodocs --version` prints the installed version. Security fixes target the latest release and `main`.

## License

MIT. See [LICENSE](LICENSE).
