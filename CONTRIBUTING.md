# Contributing to RepoDocs

Thanks for helping improve RepoDocs. Keep pull requests focused on one change.

## Prerequisites

- Python 3.10 or newer
- Git and [uv](https://docs.astral.sh/uv/)
- At least one supported agent CLI for live generation: OMP, Claude Code, or Codex
- Graphify only when running the default `repodocs all` pipeline without `--no-graph`

RepoDocs itself uses only the Python standard library.

## Setup

```bash
git clone https://github.com/aryrabelo/repodocs.git
cd repodocs
uvx --from . repodocs --selftest
```

`uvx --from .` builds the package from the local checkout and runs it without installing anything persistent. It does not copy credentials.

## Development workflow

1. Create a branch from `main`.
2. Make the smallest change that solves one problem.
3. Run `uvx --from . repodocs --selftest`.
4. For backend changes, exercise the affected CLI against a small local repository.
5. Update `README.md` and `CHANGELOG.md` when user-visible behavior changes.
6. Open a pull request using the repository template.

## Scope

Good contributions improve repository scanning, page planning, cited wiki generation, translation, publishing safety, or compatibility with supported agent CLIs. RepoDocs is intentionally a single-file, standard-library tool; discuss new runtime dependencies before implementing them.

## Code of Conduct

Be respectful, constructive, and specific. Harassment, discrimination, and abusive behavior are not accepted. Maintainers may edit or remove contributions or participation that violate these expectations.

Report conduct concerns privately to [aryrabelo@gmail.com](mailto:aryrabelo@gmail.com).
