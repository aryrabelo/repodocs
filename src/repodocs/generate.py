"""repodocs.generate -- internal module (see the repodocs package)."""

import hashlib
import json
import subprocess
import sys

from pathlib import Path

from ._util import die, log
from .backend import backend_name, failure_detail, jobs_count, missing_resource_message, parallel_llm
from .citations import lint_citations
from .plan import load_plan


def page_prompt(page: dict, repo: Path | None = None) -> str:
    files = "\n".join(f"  - {f}" for f in page.get("files", [])) or "  (none detected)"
    graph_hint = ""
    if repo is not None and (repo / "graphify-out" / "graph.json").is_file():
        graph_hint = (
            "A precomputed knowledge graph exists at graphify-out/graph.json "
            "(tree-sitter nodes/edges with file:line locations). Use it to locate "
            "the relevant symbols and sections first, then read only those slices.\n\n"
        )
    return (
        f"Write the wiki page `{page['slug']}` titled \"{page['title']}\".\n"
        f"Purpose: {page.get('purpose', '')}\n\n"
        f"Candidate source files (read the ones you cite, cite only what you read):\n"
        f"{files}\n\n"
        f"{graph_hint}"
        "Context economy: analyze in small pieces -- read files in slices (a few "
        "hundred lines at a time), only the sections relevant to this page; never "
        "read whole large files or files outside the candidate list unless a "
        "citation requires it.\n\n"
        "Follow your AGENTS.md contract for page format and citations. "
        "Emit only the final markdown -- no preamble, no fences around the whole document."
    )


def compute_file_hash(path: Path) -> str:
    """SHA-256 of a file, read in 64KB chunks."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_hashes(out: Path) -> dict:
    """slug -> {"files": {relpath: sha256hex}}. Missing/corrupt = empty (regenerate all)."""
    p = out / ".hashes.json"
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_hashes(out: Path, hashes: dict):
    (out / ".hashes.json").write_text(json.dumps(hashes, indent=2) + "\n")


def generate_decision(md_exists: bool, stored_files: dict, current_hashes: dict) -> tuple[str, str]:
    """Pure: decide whether a page needs (re)generation. Returns (action, reason)."""
    if not md_exists:
        return ("generate", "new")
    cur, sto = set(current_hashes), set(stored_files)
    added, removed = cur - sto, sto - cur
    if added:
        return ("generate", f"changed: {sorted(added)[0]} (added)")
    if removed:
        return ("generate", f"changed: {sorted(removed)[0]} (removed)")
    for f in sorted(cur):
        if current_hashes[f] != stored_files[f]:
            return ("generate", f"changed: {f}")
    return ("skip", "unchanged")


def decide_page(repo: Path, out: Path, page: dict, hashes: dict, force: bool,
                hcache: dict | None = None) -> tuple[str, str, dict]:
    """Resolve a page's action against the on-disk hash store. Returns (action, reason, current_hashes).
    hcache memoizes file hashes across pages (shared files hashed once per run)."""
    hcache = hcache if hcache is not None else {}
    current = {}
    for f in page.get("files", []):
        fp = repo / f
        if not fp.is_file():
            continue
        if f not in hcache:
            hcache[f] = compute_file_hash(fp)
        current[f] = hcache[f]
    if force:
        return ("generate", "forced", current)
    md_exists = (out / f"{page['slug']}.md").is_file()
    stored_files = hashes.get(page["slug"], {}).get("files", {})
    action, reason = generate_decision(md_exists, stored_files, current)
    return (action, reason, current)


def cmd_generate(repo: Path, out: Path, only: set[str] | None, dry_run: bool, force: bool) -> int:
    pages = load_plan(repo, out, allow_omp=not dry_run)
    if only:
        pages = [p for p in pages if p["slug"] in only]
        if not pages:
            die(f"no planned pages match --pages {sorted(only)}; run `repodocs plan {repo}` to see slugs")

    hashes = load_hashes(out)
    hcache: dict[str, str] = {}

    if dry_run:
        for p in pages:
            action, reason, _ = decide_page(repo, out, p, hashes, force, hcache)
            print(f"[{action}] {p['slug']} ({reason}) -> {out / (p['slug'] + '.md')}")
            print(page_prompt(p, repo))
            print()
        print(f"(dry run) {len(pages)} page(s); drop --dry-run to invoke {backend_name()}", file=sys.stderr)
        return 0

    out.mkdir(parents=True, exist_ok=True)
    failed = 0
    # Phase 1 (main thread): decide each page against the current hashes; skip immediately.
    todo, reasons, curmap, pagemap = [], {}, {}, {}
    for p in pages:
        action, reason, current = decide_page(repo, out, p, hashes, force, hcache)
        if action == "skip":
            print(f"[skip] {p['slug']} (unchanged)", file=sys.stderr)
            continue
        todo.append(p["slug"])
        reasons[p["slug"]], curmap[p["slug"]], pagemap[p["slug"]] = reason, current, p
    # Phase 2: generate in a bounded pool; only the main thread writes files + hashes.
    items = [(s, page_prompt(pagemap[s], repo)) for s in todo]
    if todo:
        log(f"generate: {len(todo)} page(s) to write, {jobs_count()} parallel job(s)")
    done_ct = 0
    for slug, res in parallel_llm(repo, items,
                                  lambda k: log(f"[start] {k} ({reasons[k]})")):
        if isinstance(res, FileNotFoundError):
            die(missing_resource_message(res), 1)
        if isinstance(res, subprocess.TimeoutExpired):
            print(f"  {slug}: timeout (set REPODOCS_TIMEOUT to raise)", file=sys.stderr)
            failed += 1
            continue
        if isinstance(res, Exception):
            print(f"  {slug}: {res}", file=sys.stderr)
            failed += 1
            continue
        if res.returncode != 0:
            print(f"  {slug}: {backend_name()} exit {res.returncode}: {failure_detail(res)}", file=sys.stderr)
            failed += 1
            continue
        (out / f"{slug}.md").write_text(res.stdout)
        hashes[slug] = {"files": curmap[slug]}
        done_ct += 1
        log(f"[done {done_ct}/{len(todo)}] {slug}")
        save_hashes(out, hashes)  # crash-resume: persist after each completion

    save_hashes(out, hashes)
    written = [p for p in pages if (out / f"{p['slug']}.md").is_file()]
    lint_citations(repo, out, written)
    write_index(repo, out, written)
    _gitignore_notice(repo, out)
    if not written:
        print(f"no pages written; check {backend_name()} errors above", file=sys.stderr)
    return 1 if failed else 0


def _gitignore_notice(repo: Path, out: Path):
    """One-line heads-up when the output dir sits untracked inside a git repo."""
    try:
        rel = out.resolve().relative_to(repo.resolve())
    except ValueError:
        return
    gi = repo / ".gitignore"
    entry = f"{rel.parts[0]}/"
    if (repo / ".git").exists() and (not gi.is_file() or entry not in gi.read_text()):
        tracked = subprocess.run(["git", "-C", str(repo), "ls-files", str(rel)],
                                 capture_output=True, text=True)
        if tracked.stdout.strip():
            return  # docs are deliberately committed; no nag
        print(f"note: {entry} is untracked in {repo.name}; add it to .gitignore or commit it deliberately",
              file=sys.stderr)


def write_index(repo: Path, out: Path, pages: list[dict]):
    lines = [f"# {repo.resolve().name} Wiki", "", "## Pages", ""]
    lines += [f"- [{p['title']}]({p['slug']}.md)" for p in pages]
    lines.append("")
    (out / "index.md").write_text("\n".join(lines))


def render_plan_table(pages: list[dict]) -> str:
    rows = [("SLUG", "TITLE", "FILES", "PURPOSE")]
    for p in pages:
        rows.append((p["slug"], p["title"], str(len(p.get("files", []))), p.get("purpose", "")))
    w = [max(len(r[i]) for r in rows) for i in range(3)]
    out = []
    for i, r in enumerate(rows):
        out.append(f"{r[0]:<{w[0]}}  {r[1]:<{w[1]}}  {r[2]:>{w[2]}}  {r[3]}")
        if i == 0:
            out.append(f"{'-'*w[0]}  {'-'*w[1]}  {'-'*w[2]}  {'-'*7}")
    return "\n".join(out)
