"""repodocs.plan -- internal module (see the repodocs package)."""

import hashlib
import json
import os
import re
import subprocess
import sys
import time

from pathlib import Path

from ._util import CANDIDATES_PER_PAGE, MAX_COMPONENTS, SLUG_RE, dedup, is_test, log, safe_repo_file, slugify
from .backend import backend_name, failure_detail, llm_label, run_llm
from .scan import scan, scan_inventory


def top_candidates(files: list[str], line_counts: dict[str, int]) -> list[str]:
    return sorted(files, key=lambda r: -line_counts.get(r, 0))[:CANDIDATES_PER_PAGE]


def plan_pages(repo: Path, facts: dict) -> list[dict]:
    """Deterministic fallback page list. Same schema as the planner: files key."""
    src, lc = facts["src_files"], facts["line_counts"]
    pages: list[dict] = []
    readme = "README.md" if (repo / "README.md").is_file() else ("readme.md" if (repo / "readme.md").is_file() else None)

    pages.append({
        "slug": "overview", "title": "Overview",
        "purpose": "What this repository is, what it does, and how its pieces fit together.",
        "files": dedup([f for f in [readme, *facts["manifests"]] if f] + top_candidates(src, lc)[:6])[:CANDIDATES_PER_PAGE],
    })
    if readme or facts["manifests"]:
        pages.append({
            "slug": "installation", "title": "Installation & Setup",
            "purpose": "How to install, configure, and run the project.",
            "files": dedup([f for f in [readme, *facts["manifests"]] if f])[:CANDIDATES_PER_PAGE],
        })
    if len(src) >= 2:
        pages.append({
            "slug": "architecture", "title": "Architecture",
            "purpose": "The high-level structure, main modules, and how data/control flows between them.",
            "files": top_candidates(src, lc),
        })

    comps: list[dict] = []
    dir_comps = {k: v for k, v in facts["top_dirs"].items() if k != "." and len(v) >= 2}
    if dir_comps:
        for name in sorted(dir_comps, key=lambda k: -len(dir_comps[k])):
            comps.append({
                "slug": "component-" + slugify(name), "title": "Component: " + name,
                "purpose": f"How the `{name}` component is organized and what it is responsible for.",
                "files": top_candidates(dir_comps[name], lc),
            })
    else:
        for rel in sorted((r for r in src if lc.get(r, 0) >= 100 and not is_test(r)), key=lambda r: -lc.get(r, 0)):
            comps.append({
                "slug": "component-" + slugify(Path(rel).stem), "title": "Module: " + Path(rel).name,
                "purpose": f"What `{rel}` implements and how it is used.", "files": [rel],
            })
    pages.extend(comps[:MAX_COMPONENTS])

    if facts["has_contributing"] or facts["tests"] or facts["ci"]:
        dev = (["CONTRIBUTING.md"] if facts["has_contributing"] else []) + facts["ci"] + facts["tests"]
        pages.append({
            "slug": "development", "title": "Development & Testing",
            "purpose": "How to contribute, run the tests, and understand the CI pipeline.",
            "files": dedup(dev)[:CANDIDATES_PER_PAGE],
        })
    if facts["has_changelog"]:
        pages.append({
            "slug": "changelog", "title": "Changelog",
            "purpose": "Notable changes across releases, summarized from the changelog.",
            "files": ["CHANGELOG.md"],
        })
    return pages


def graph_digest(repo: Path, max_nodes: int = 25, max_files: int = 15) -> str:
    """Compact digest of an OPTIONAL graphify graph (<repo>/graphify-out/graph.json,
    NetworkX node-link). Returns "" when absent/unreadable -- repodocs never
    requires graphify; this only sharpens the planner when a graph exists."""
    p = repo / "graphify-out" / "graph.json"
    try:
        g = json.loads(p.read_text())
        nodes = g["nodes"]
        links = g.get("links") or g.get("edges") or []
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return ""
    if not isinstance(nodes, list) or not isinstance(links, list) or not links:
        return ""
    byid = {n.get("id"): n for n in nodes if isinstance(n, dict) and n.get("id")}
    deg: dict = {}
    imported: dict = {}
    for edge in links:
        if not isinstance(edge, dict):
            continue
        for k in ("source", "target"):
            nid = edge.get(k)
            if nid in byid:
                deg[nid] = deg.get(nid, 0) + 1
        if edge.get("relation") in ("imports", "imports_from"):
            t = byid.get(edge.get("target"))
            if t and t.get("source_file"):
                f = t["source_file"]
                imported[f] = imported.get(f, 0) + 1
    god = sorted(deg, key=lambda n: -deg[n])[:max_nodes]
    god_lines = [
        f"  - {byid[n].get('label', n)} ({deg[n]} connections; {byid[n].get('source_file', '?')})"
        for n in god
    ]
    # NB: counts are approximate (one import statement can emit both an
    # `imports` and an `imports_from` edge) -- a relative ranking signal only.
    imp_lines = [
        f"  - {f} (imported {c}x)"
        for f, c in sorted(imported.items(), key=lambda kv: -kv[1])[:max_files]
    ]
    if not god_lines:
        return ""
    out = [
        "Dependency-graph digest (precomputed via tree-sitter AST; PREFER this over "
        "exploring files -- open a file only to confirm a page's scope):",
        "Most-connected concepts (god nodes):",
        *god_lines,
    ]
    if imp_lines:
        out += ["Most-imported files (likely core modules / integration seams):", *imp_lines]
    return "\n".join(out) + "\n\n"


def planner_prompt(repo: Path, inv: dict) -> str:
    files = "\n".join("  - " + f for f in inv["source_files"][:200]) or "  (no source files detected)"
    heads = "\n".join("  " + h for h in inv["readme_headings"][:40]) or "  (no README headings)"
    mandatory = ["overview"]
    if inv["has_readme"] or inv["manifests"]:
        mandatory.append("installation")
    if inv["source_file_count"] >= 2:
        mandatory.append("architecture")
    if inv["has_changelog"]:
        mandatory.append("changelog")
    if inv["has_security"]:
        mandatory.append("security")
    if inv["has_contributing"]:
        mandatory.append("contributing")
    if inv["tests"] or inv["ci"] or inv["has_contributing"]:
        mandatory.append("development")
    return (
        "Plan the wiki pages for this repository, at DeepWiki/cubic.dev granularity.\n\n"
        "Granularity rule: ONE page per feature -- do NOT merge related features. "
        "If a feature has its own README heading, state machine, subcommand, tool, "
        "config surface, integration, or storage format, it gets its OWN page. "
        "Splitting too fine beats merging; a substantial repo yields 15-30 pages.\n\n"
        "Beyond the per-feature pages, also include when the repo supports them: "
        "'security' (threat model / trust boundaries), 'limitations' (known issues "
        "and workarounds), one page per external system integration, and 'migration' "
        "(legacy data / upgrade paths).\n\n"
        f"MANDATORY slugs for this repo (detected facts): {', '.join(mandatory)}.\n\n"
        f"Repository: {inv['name']}\n"
        f"Manifests: {', '.join(inv['manifests']) or 'none'}\n"
        f"CHANGELOG.md: {'yes' if inv['has_changelog'] else 'no'}; "
        f"CONTRIBUTING.md: {'yes' if inv['has_contributing'] else 'no'}; "
        f"SECURITY.md: {'yes' if inv['has_security'] else 'no'}; "
        f"CI configs: {len(inv['ci'])}; test files: {len(inv['tests'])}\n"
        f"README headings:\n{heads}\n\n"
        f"{graph_digest(repo)}"
        f"Source files:\n{files}\n\n"
        "Follow your AGENTS.md wiki-planner contract. Output ONLY a JSON array of "
        'objects {"slug":"kebab-case","title":"...","purpose":"one sentence",'
        '"files":["repo/relative/path", ...]}. Slugs match ^[a-z0-9-]+$. '
        "No prose, no code fences."
    )


def parse_pages(text: str) -> list:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n", "", t)
        t = re.sub(r"\n```$", "", t.rstrip())
    i, j = t.find("["), t.rfind("]")
    if i == -1 or j == -1 or j < i:
        raise ValueError("no JSON array found in planner output")
    return json.loads(t[i:j + 1])


def validate_pages(repo: Path, raw) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError("planner output is not a JSON array")
    out, seen = [], set()
    for entry in raw:
        if not isinstance(entry, dict):
            print(f"  drop: non-object entry {entry!r}", file=sys.stderr)
            continue
        slug = str(entry.get("slug", "")).strip()
        if not SLUG_RE.match(slug):
            print(f"  drop: bad slug {slug!r}", file=sys.stderr)
            continue
        if slug in seen:
            print(f"  drop: duplicate slug {slug!r}", file=sys.stderr)
            continue
        files = [f for f in entry.get("files", []) if isinstance(f, str)]
        good = [f for f in files if safe_repo_file(repo, f) is not None]
        for f in files:
            if f not in good:
                print(f"  {slug}: dropped missing file {f}", file=sys.stderr)
        seen.add(slug)
        if not good:  # every candidate was a ghost; anchor the writer on the README
            good = [n for n in ("README.md", "readme.md") if (repo / n).is_file()][:1]
        out.append({
            "slug": slug, "title": str(entry.get("title") or slug),
            "purpose": str(entry.get("purpose", "")), "files": good[:CANDIDATES_PER_PAGE],
        })
    return out


def plan_fingerprint(prompt: str) -> str:
    """Fingerprint of the planner input; the plan is a pure function of it."""
    return hashlib.sha256(prompt.encode()).hexdigest()


def llm_plan(repo: Path, out: Path, dry_run: bool = False, force: bool = False):
    inv = scan_inventory(repo, out)
    prompt = planner_prompt(repo, inv)
    if dry_run:
        print(prompt)
        return None
    fp = plan_fingerprint(prompt)
    fp_file, pj = out / ".plan.hash", out / "plan.json"
    if not force and pj.is_file() and fp_file.is_file() and fp_file.read_text().strip() == fp:
        log(f"plan: inventory unchanged, reusing {pj} (--force to replan)")
        return json.loads(pj.read_text())
    pages, from_llm = None, False
    try:
        model = llm_label()
        timeout = os.environ.get("REPODOCS_TIMEOUT", "600")
        log(f"plan: {inv['source_file_count']} source files; calling planner ({model}, timeout {timeout}s)...")
        t0 = time.time()
        r = run_llm(repo, prompt)
        log(f"plan: planner replied in {time.time() - t0:.0f}s")
        if r.returncode != 0:
            raise ValueError(f"{backend_name()} exit {r.returncode}: {failure_detail(r)}")
        pages = validate_pages(repo, parse_pages(r.stdout))
        if not pages:
            raise ValueError("planner returned no valid pages")
        from_llm = True
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError) as e:
        print(f"planner unavailable ({e}); falling back to heuristic plan", file=sys.stderr)
        pages = plan_pages(repo, scan(repo, out))
    out.mkdir(parents=True, exist_ok=True)
    (out / "plan.json").write_text(json.dumps(pages, indent=2) + "\n")
    if from_llm:  # never cache a heuristic fallback as the settled plan
        fp_file.write_text(fp + "\n")
    elif fp_file.is_file():
        fp_file.unlink()  # stale fingerprint would wrongly validate the fallback plan
    return pages


def load_plan(repo: Path, out: Path, allow_omp: bool = True) -> list[dict]:
    pj = out / "plan.json"
    if pj.is_file():
        return json.loads(pj.read_text())
    if allow_omp:
        print("no plan.json; running plan first", file=sys.stderr)
        return llm_plan(repo, out)
    print("no plan.json; using heuristic plan for dry run", file=sys.stderr)
    return plan_pages(repo, scan(repo, out))
