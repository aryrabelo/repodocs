# RepoDocs — agent install & run guide

Machine-facing companion to `README.md`. If you are a coding agent (Claude Code,
OMP, Codex, …) asked to install or run RepoDocs, follow this exactly. RepoDocs is
an external CLI you shell out to — it is **not** a Claude Code plugin, so do not
try `/plugin install`.

<agent_workflow>
Step 0 — Prerequisites (verify, don't assume):
  - `uv --version`  → if missing: `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - `python3 --version`  → must be 3.10 or newer (uv will fetch a suitable Python if not).

Step 1 — Run without installing (preferred; no global state):
  - `uvx --from git+https://github.com/aryrabelo/repodocs repodocs-all .`
  - Run this from the ROOT of the target repo (`.` = current repo).

Step 2 — OR install persistently (only if the user wants `repodocs` on PATH):
  - `uv tool install git+https://github.com/aryrabelo/repodocs`
  - `uv tool update-shell`

Step 3 — Verify:
  - `uvx --from git+https://github.com/aryrabelo/repodocs repodocs --version`  (or `repodocs --version` if installed)
  - `repodocs --help` lists the subcommands (scan, plan, generate, translate, html, publish).

Step 4 — Report to the user:
  - Output is written to `repo-docs/`; open `repo-docs/wiki.html` in a browser.
  - Do NOT publish anything: `repodocs publish` requires an explicit `--allow-public`
    and is the user's decision. Run `repodocs publish . --dry-run` only if asked, and
    show the file list — never `--allow-public` without explicit approval.
</agent_workflow>

## Backend selection

Default backend is Claude Code (`claude-sonnet-5`). To change it before running:
- `export REPODOCS_BACKEND=omp` (then `repodocs setup` + `omp --profile=repo-docs`, `/login` once)
- `export REPODOCS_BACKEND=codex` (then `codex login`)
- `REPODOCS_MODEL` overrides the model; `REPODOCS_JOBS` (1–16) sets parallelism.

## Guardrails for agents

- Never run `repodocs publish … --allow-public` without the user's explicit OK.
- Never put tokens, private paths, or client names into generated docs shown publicly.
- A bare `repodocs-all` with no target prints help — that is expected, not an error.
