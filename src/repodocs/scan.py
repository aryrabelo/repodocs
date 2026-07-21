"""repodocs.scan -- internal module (see the repodocs package)."""

import os
import re

from pathlib import Path

from ._util import MANIFESTS, MAX_DEPTH, SKIP_DIRS, count_lines, is_source, is_test


def scan(repo: Path, out: Path | None = None) -> dict:
    """Walk the repo once, collecting the facts scan/plan need. RepoDocs' own
    generated trees -- repo-docs/, graphify-out/, and the configured --out dir
    (whatever its name) -- are skipped at the repo root so a rerun never ingests
    its own vendored assets, Markdown, or JSON. Symlinks that escape the repo are
    dropped so a planted link cannot smuggle an out-of-tree file into the wiki."""
    ignore = {"repo-docs", "graphify-out"}
    if out is not None:
        try:
            orel = out.resolve().relative_to(repo.resolve())
            if orel.parts:
                ignore.add(orel.parts[0])
        except ValueError:
            pass  # out lives outside the repo; os.walk never reaches it
    repo_real = repo.resolve()
    src_files: list[str] = []
    line_counts: dict[str, int] = {}
    top_dirs: dict[str, list[str]] = {}

    for root, dirs, files in os.walk(repo):
        rootp = Path(root)
        depth = len(rootp.relative_to(repo).parts)
        if depth >= MAX_DEPTH:
            dirs[:] = []
        dirs[:] = sorted(
            d for d in dirs
            if d not in SKIP_DIRS and not d.startswith(".")
            and not (depth == 0 and d in ignore)
        )
        for f in sorted(files):
            fp = rootp / f
            if fp.is_symlink():
                try:
                    fp.resolve().relative_to(repo_real)
                except (ValueError, OSError):
                    continue  # symlink escapes the repo -> never a source file
            rel = str(fp.relative_to(repo))
            if is_source(fp):
                src_files.append(rel)
                parts = Path(rel).parts
                top_dirs.setdefault(parts[0] if len(parts) > 1 else ".", []).append(rel)
                line_counts[rel] = count_lines(fp)

    def has(name):
        return (repo / name).is_file()
    wf = repo / ".github" / "workflows"
    ci = [str(p.relative_to(repo)) for p in wf.glob("*") if p.is_file()] if wf.is_dir() else []
    return {
        "src_files": sorted(src_files),
        "line_counts": line_counts,
        "top_dirs": top_dirs,
        "has_readme": has("README.md") or has("readme.md"),
        "manifests": [m for m in MANIFESTS if has(m)],
        "has_contributing": has("CONTRIBUTING.md"),
        "has_changelog": has("CHANGELOG.md"),
        "has_security": has("SECURITY.md"),
        "ci": ci,
        "tests": sorted(r for r in src_files if is_test(r)),
    }


def readme_headings(repo: Path) -> list[str]:
    for name in ("README.md", "readme.md"):
        p = repo / name
        if p.is_file():
            out, fenced = [], False
            for ln in p.read_text(errors="ignore").splitlines():
                if ln.lstrip().startswith("```"):
                    fenced = not fenced
                elif not fenced and re.match(r"^#{1,6}\s+\S", ln):
                    out.append(ln.strip())
            return out
    return []


def scan_inventory(repo: Path, out: Path | None = None) -> dict:
    facts = scan(repo, out)
    return {
        "name": repo.resolve().name,
        "source_file_count": len(facts["src_files"]),
        "source_files": facts["src_files"],
        "manifests": facts["manifests"],
        "readme_headings": readme_headings(repo),
        "has_readme": facts["has_readme"],
        "has_contributing": facts["has_contributing"],
        "has_changelog": facts["has_changelog"],
        "has_security": facts["has_security"],
        "ci": facts["ci"],
        "tests": facts["tests"],
    }
