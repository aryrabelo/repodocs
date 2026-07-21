# Contributing

RepoDocs uses Python 3.10+ and the standard library only. Clone the repository; no dependency installation is required.

## Verification

```bash
python3 repodocs --selftest
```

For backend changes, also run `repodocs plan` and generate one page against a small fixture with every affected authenticated CLI. Never commit generated `repo-docs/` output, `graphify-out/`, credential databases, or private repository content.

## Pull requests

Keep changes scoped, explain the observable behavior, and include exact verification commands and results. Use English Conventional Commit titles.
