"""repodocs._util -- internal module (see the repodocs package)."""

import os
import re
import sys
import time

from pathlib import Path


SRC_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go", ".rb", ".java", ".kt",
    ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".php", ".swift", ".scala",
    ".sh", ".lua", ".ex", ".exs", ".dart", ".vue", ".svelte",
}


MANIFESTS = ["package.json", "pyproject.toml", "Cargo.toml", "go.mod", "Gemfile", "composer.json"]


SKIP_DIRS = {".git", "node_modules", "dist", "build", "__pycache__", "vendor", ".venv", "venv"}


MAX_DEPTH = 5


MAX_COMPONENTS = 6


CANDIDATES_PER_PAGE = 12


SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def die(msg: str, code: int = 1):
    print(msg, file=sys.stderr)
    sys.exit(code)


def log(msg: str):
    """Timestamped progress line to stderr."""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr)


def is_source(p: Path) -> bool:
    if p.suffix in SRC_EXTS:
        return True
    if p.suffix or not p.is_file():
        return False
    try:  # extension-less script with a shebang (e.g. `hat`, `repodocs`)
        with p.open("rb") as f:
            return f.read(2) == b"#!"
    except OSError:
        return False


def is_test(rel: str) -> bool:
    name = Path(rel).name
    parts = Path(rel).parts
    return (
        "tests" in parts or "test" in parts
        or name.startswith("test_")
        or re.search(r"_test\.[a-z]+$", name) is not None
        or re.search(r"\.(test|spec)\.[a-z]+$", name) is not None
    )


def count_lines(p: Path) -> int:
    try:
        with p.open("rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def safe_repo_file(repo: Path, rel: str) -> Path | None:
    """Resolve repo-relative `rel` under `repo`, following symlinks. Return the
    real path only when it is a regular file that stays inside the repo; None for
    absolute paths, `..` traversal, symlink escapes, NUL bytes, symlink loops, or
    non-files."""
    if not rel or os.path.isabs(rel) or "\x00" in rel:
        return None
    try:
        root = repo.resolve()
        target = (root / rel).resolve()
        target.relative_to(root)
    except (ValueError, OSError, RuntimeError):
        return None
    return target if target.is_file() else None


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "component"


def dedup(items: list[str]) -> list[str]:
    seen, out = set(), []
    for i in items:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out
