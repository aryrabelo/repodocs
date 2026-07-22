"""repodocs -- generate a DeepWiki/cubic.dev-style repository wiki.

Pipeline:
  scan      deterministic inventory of the repo
  plan      an LLM planner turns the inventory into a feature-level page list
  generate  one LLM writer call per page, with SHA-256 incremental rebuilds
  translate translate generated pages to another language
  html      bundle pages into a self-contained wiki.html viewer
  publish   push the built wiki to a GitHub Pages branch
  publish-wiki export generated pages to the repo's GitHub Wiki
  all       graphify + scan + plan + generate + vendored html in one command

Usage:
    repodocs scan [repo] [--json] [--heuristic]
    repodocs plan [repo] [--out DIR] [--dry-run] [--force]
    repodocs generate [repo] [--out DIR] [--pages a,b] [--dry-run] [--force]
    repodocs translate [repo] [--lang pt] [--out DIR] [--pages a,b] [--force]
    repodocs html [repo] [--out DIR] [--vendor]
    repodocs publish [repo] [--out DIR] [--branch gh-pages] [--remote origin] [--dry-run]
    repodocs publish-wiki [repo] [--out DIR] [--remote origin] [--dry-run | --allow-public]
    repodocs all [repo] [--out DIR] [--force] [--no-graph]
    repodocs setup [--force]
    repodocs help | -h | --help
    repodocs <subcommand> --help
    repodocs --version

`repodocs` and `repodocs-all` are installed as console scripts (see
`pyproject.toml`); `repodocs-all` dispatches to `repodocs all` automatically.

LLM backend configuration:
    REPODOCS_BACKEND=omp|claude|codex   default: claude
    REPODOCS_MODEL=<backend model id>   optional; default: claude-sonnet-5 for claude, backend default otherwise
    REPODOCS_TIMEOUT=<seconds>          default: 600
    REPODOCS_JOBS=<1..16>               default: 4

OMP uses the vendored repo-docs profile installed by `repodocs setup`. Claude
Code and Codex receive the same vendored output contract explicitly, so page
format and citations do not depend on the target repository's agent files.

The deterministic heuristic plan is used whenever the planner is unavailable or
returns invalid output. Stdlib only; runs via the installed `repodocs`
command, `uvx --from . repodocs`, or `python -m repodocs`.
"""

import json
import shutil
import subprocess
import sys

from pathlib import Path

from . import VERSION
from ._util import die
from .backend import PROFILE_SOURCE, require_backend
from .generate import cmd_generate, render_plan_table
from .plan import llm_plan, plan_pages
from .publish import cmd_publish, cmd_publish_wiki
from .render import build_html
from .scan import scan, scan_inventory
from .translate import cmd_translate


SCAN_HELP = """repodocs scan [repo] [--json] [--heuristic]

Deterministic inventory of a repository (default: current dir): source files,
manifests, README headings, tests, CI, CHANGELOG. Human summary by default;
--json for the machine form (feeds the planner). --heuristic instead prints the
deterministic fallback page list (add --json for its array form)."""


PLAN_HELP = """repodocs plan [repo] [--out DIR] [--dry-run] [--force]

Run the repo-docs planner over the scan inventory to produce a full feature-level
page list, validate it (slug ^[a-z0-9-]+$, files must exist -- bad entries
dropped with a warning), write <out>/plan.json (default <repo>/repo-docs), and
print a table. Idempotent: when the scan inventory is unchanged since the last
run (<out>/.plan.hash), the existing plan.json is reused without calling the
LLM; --force replans anyway. --dry-run prints the planner prompt instead of
calling the configured backend. On planner failure/unparseable output: heuristic fallback, exit 0."""


GEN_HELP = """repodocs generate [repo] [--out DIR] [--pages a,b] [--dry-run] [--force]

Read <out>/plan.json (auto-runs plan if missing) and run the repo-docs writer
once per page -> <out>/<slug>.md. Incremental: a page is regenerated when its
.md is missing or any source file's SHA-256 changed (or files were added/removed
from its plan entry), else skipped -- tracked in <out>/.hashes.json. --force
regenerates all. --pages limits to slugs; --dry-run prints per-page decisions +
prompts. Pages are generated in parallel (env REPODOCS_JOBS, default 4, clamped
1..16; =1 is serial). After: citation lint (warnings) + index.md nav. Exit
nonzero if any configured-backend call failed."""


HTML_HELP = """repodocs html [repo] [--out DIR] [--vendor]

Build <out>/wiki.html: a single self-contained, cubic.dev-style DARK wiki viewer
that renders the generated <out>/*.md pages client-side (markdown embedded inline,
works from file://). Features: top bar with GitHub breadcrumb + View-on-GitHub
link, grouped searchable sidebar, right-hand "On this page" TOC, collapsible
"Relevant source files", prev/next footer, syntax highlighting, and citation
links rewritten to github.com/<o>/<r>/blob/<sha> when the repo has a github origin.

By default the JS/CSS libs (marked, mermaid, highlight.js) load from a pinned CDN,
so the DEFAULT page needs internet. --vendor downloads them into <out>/assets/ and
rewrites the tags to relative paths, making the page fully offline. Exit 1 if no
.md pages exist yet (run `repodocs generate`). If --out points at a translated dir
(e.g. <out>/pt), the UI labels are localized from the dir name (pt supported)."""


TRANSLATE_HELP = """repodocs translate [repo] [--lang pt] [--out DIR] [--pages a,b] [--force]

Translate the generated <out>/*.md pages to another language (default pt =
Brazilian Portuguese) via one configured-backend call per page, writing <out>/<lang>/<slug>.md.
Markdown structure, code, paths, URLs, mermaid, and `Sources:` citation lines are
preserved; only natural-language prose/headings/table cells are translated.
plan.json titles+purposes are translated in one call (files lists copied verbatim;
on failure the plan is copied untranslated with a warning). Existing translated
pages are skipped unless --force (presence check). Afterwards runs citation lint
against the translated pages (verifying citations survived) and writes index.md.
Then `repodocs html <repo> --out <out>/<lang>` renders the localized wiki.
Exit nonzero if any configured-backend call failed."""


ALL_HELP = """repodocs all [repo] [--out DIR] [--force] [--no-graph]

Run the complete local pipeline: graphify update, scan, plan, generate, and
html --vendor. graphify is required unless --no-graph is passed. --force
replans and regenerates every page. The `repodocs-all` console entry point dispatches here.
"""


PUBLISH_HELP = """repodocs publish [repo] [--out DIR] [--branch gh-pages] [--remote origin]
                         [--dry-run | --allow-public]

Publish the built wiki to a GitHub Pages branch. Requires <out>/wiki.html (run
`repodocs html <repo> --vendor` first) and the named remote. Protected branches
main/master/trunk are always refused. The staged wiki is scanned for common
private-key, GitHub-token, and cloud/API-key patterns before either preview or
push. A real push requires --allow-public; run --dry-run and review first.

Stages a tempdir and pushes it as a single orphan commit through a throwaway
detached worktree. The working tree and current branch are not changed. The docs
branch is force-pushed because its history is disposable."""


PUBLISH_WIKI_HELP = """repodocs publish-wiki [repo] [--out DIR] [--remote origin]
                              [--dry-run | --allow-public]

Export the built <out>/*.md pages into the repo's GitHub Wiki (a separate git
repo at github.com/<owner>/<repo>.wiki.git, in the same ssh/https scheme as the
named remote). overview.md becomes Home.md (index.md is used instead when
overview.md is missing); index.md itself is never staged as a page. A
_Sidebar.md is generated from plan.json order/titles. Citation links are
rewritten to absolute github.com/<o>/<r>/blob/<sha> URLs when the working tree
is clean and HEAD is pushed. The staged tree is scanned for common private-key,
GitHub-token, and cloud/API-key patterns before either preview or push.

A real push clones the wiki into a tempdir, overwrites only the exported
filenames (any other, manually-added wiki pages are left untouched), commits
only if something changed, and pushes normally -- never force. The source
working tree and current branch are never touched. GitHub wikis need at least
one page before they can be cloned: if the wiki has never been initialized,
enable it (repo Settings -> Features -> Wikis) and create the first Home page
in the GitHub UI, then retry. --dry-run lists the staged files and target
without pushing; a real push requires --allow-public."""


SETUP_HELP = """repodocs setup [--force]

Install the vendored repo-docs omp profile (bundled at repo-docs-profile/ next to
this script) into ~/.omp/profiles/repo-docs/agent/, creating dirs as needed, so a
fresh clone reproduces the tuned planner/writer prompts.

Per file: missing at destination -> installed; byte-identical -> up to date;
differs -> kept local (use --force to overwrite). Prints a per-file summary.

Authenticate the isolated profile directly after setup by running
`omp --profile=repo-docs` and using `/login`. repodocs never copies the user's
global credential database."""


BACKEND_HELP = """
Backends:
  REPODOCS_BACKEND=omp     OMP profile installed by `repodocs setup`
  REPODOCS_BACKEND=claude  Claude Code print mode; vendored contract injected (default; model default: claude-sonnet-5)
  REPODOCS_BACKEND=codex   Codex exec read-only mode; vendored contract injected
Set REPODOCS_MODEL to override the model identifier for the selected CLI."""


PROFILE_DEST = Path.home() / ".omp" / "profiles" / "repo-docs" / "agent"


def setup_install(src_root: Path, dest_root: Path, force: bool) -> list[tuple[str, str]]:
    """Install every file under src_root into dest_root, returning [(relpath,
    action)]. Pure w.r.t. its arguments -- touches only src_root/dest_root, so the
    test suite can drive it against tempdirs without touching HOME."""
    results: list[tuple[str, str]] = []
    for src in sorted(p for p in src_root.rglob("*") if p.is_file()):
        rel = str(src.relative_to(src_root))
        dest = dest_root / rel
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            action = "installed"
        elif src.read_bytes() == dest.read_bytes():
            action = "up to date"
        elif force:
            shutil.copyfile(src, dest)
            action = "overwritten"
        else:
            action = "differs, kept local (use --force to overwrite)"
        results.append((rel, action))
    return results


def cmd_setup(args: list[str]):
    if "--help" in args or "-h" in args:
        print(SETUP_HELP)
        return
    backend = require_backend()
    if backend != "omp":
        print(f"setup not needed for REPODOCS_BACKEND={backend}")
        return
    if not PROFILE_SOURCE.is_dir():
        die(f"vendored profile not found: {PROFILE_SOURCE}", 1)
    results = setup_install(PROFILE_SOURCE, PROFILE_DEST, "--force" in args)
    print(f"repo-docs profile -> {PROFILE_DEST}")
    for rel, action in results:
        print(f"  {rel}: {action}")
    if not (PROFILE_DEST / "agent.db").exists():
        print("\nprofile has no credentials. Run `omp --profile=repo-docs`, then use `/login`.")


def cmd_all(args: list[str]) -> int:
    if "--help" in args or "-h" in args:
        print(ALL_HELP + BACKEND_HELP)
        return 0
    require_backend()
    repo = parse_repo_and_flags(args)
    out = Path(get_flag(args, "--out") or (repo / "repo-docs"))
    if "--no-graph" not in args:
        graphify = shutil.which("graphify")
        if not graphify:
            die(
                "graphify not found; install with `uv tool install graphifyy` "
                "or pass --no-graph",
                1,
            )
        result = subprocess.run([graphify, "update", str(repo)])
        if result.returncode != 0:
            return result.returncode
    cmd_scan([str(repo)])
    pages = llm_plan(repo, out, force="--force" in args)
    print(render_plan_table(pages))
    result = cmd_generate(repo, out, None, False, "--force" in args)
    if result:
        return result
    dest = build_html(repo, out, vendor=True)
    print(f"wrote {dest} with vendored assets. Open it in a browser.")
    return 0


def get_flag(args: list[str], name: str) -> str | None:
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            return args[i + 1]
    for a in args:
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def parse_repo_and_flags(args: list[str]) -> Path:
    flags_with_val = {"--out", "--pages", "--lang", "--branch", "--remote"}
    positional = []
    skip = False
    for i, a in enumerate(args):
        if skip:
            skip = False
            continue
        if a in flags_with_val:
            skip = True
            continue
        if not a.startswith("-"):
            positional.append(a)
    repo = Path(positional[0]) if positional else Path(".")
    if not repo.is_dir():
        die(f"repo path not a directory: {repo}", 1)
    return repo


def cmd_scan(args: list[str]):
    if "--help" in args or "-h" in args:
        print(SCAN_HELP)
        return
    repo = parse_repo_and_flags(args)
    if "--heuristic" in args:
        pages = plan_pages(repo, scan(repo))
        if "--json" in args:
            print(json.dumps(pages, indent=2))
        else:
            print(render_plan_table(pages))
            print(f"\n{len(pages)} heuristic page(s). Next: repodocs plan {repo}")
        return
    inv = scan_inventory(repo)
    if "--json" in args:
        print(json.dumps(inv, indent=2))
    else:
        print(f"{inv['name']}: {inv['source_file_count']} source file(s)")
        print(f"  manifests:    {', '.join(inv['manifests']) or '-'}")
        print(f"  README:       {'yes' if inv['has_readme'] else 'no'} ({len(inv['readme_headings'])} headings)")
        print(f"  CONTRIBUTING: {'yes' if inv['has_contributing'] else 'no'}")
        print(f"  CHANGELOG:    {'yes' if inv['has_changelog'] else 'no'}")
        print(f"  CI configs:   {len(inv['ci'])}")
        print(f"  test files:   {len(inv['tests'])}")
        print(f"\nNext: repodocs plan {repo}   (or scan --heuristic for the fallback page list)")


def cmd_plan(args: list[str]):
    if "--help" in args or "-h" in args:
        print(PLAN_HELP)
        return
    require_backend()
    repo = parse_repo_and_flags(args)
    out = Path(get_flag(args, "--out") or (repo / "repo-docs"))
    if "--dry-run" in args:
        llm_plan(repo, out, dry_run=True)
        print("\n(dry run) drop --dry-run to invoke the planner and write plan.json", file=sys.stderr)
        return
    pages = llm_plan(repo, out, force="--force" in args)
    print(render_plan_table(pages))
    print(f"\n{len(pages)} page(s) -> {out / 'plan.json'}. Next: repodocs generate {repo}")


def cmd_generate_cli(args: list[str]):
    if "--help" in args or "-h" in args:
        print(GEN_HELP)
        return
    require_backend()
    repo = parse_repo_and_flags(args)
    out = Path(get_flag(args, "--out") or (repo / "repo-docs"))
    pages_flag = get_flag(args, "--pages")
    only = set(pages_flag.split(",")) if pages_flag else None
    sys.exit(cmd_generate(repo, out, only, "--dry-run" in args, "--force" in args))


def cmd_html(args: list[str]):
    if "--help" in args or "-h" in args:
        print(HTML_HELP)
        return
    repo = parse_repo_and_flags(args)
    out = Path(get_flag(args, "--out") or (repo / "repo-docs"))
    vendor = "--vendor" in args
    dest = build_html(repo, out, vendor)
    n = len([p for p in out.glob("*.md") if p.name != "index.md"])
    extra = " + vendored assets/" if vendor else ""
    print(f"wrote {dest} ({n} page(s){extra}). Open it in a browser.")


def cmd_translate_cli(args: list[str]):
    if "--help" in args or "-h" in args:
        print(TRANSLATE_HELP)
        return
    require_backend()
    repo = parse_repo_and_flags(args)
    out = Path(get_flag(args, "--out") or (repo / "repo-docs"))
    lang = get_flag(args, "--lang") or "pt"
    pages_flag = get_flag(args, "--pages")
    only = set(pages_flag.split(",")) if pages_flag else None
    sys.exit(cmd_translate(repo, out, lang, only, "--force" in args))


def cmd_publish_cli(args: list[str]):
    if "--help" in args or "-h" in args:
        print(PUBLISH_HELP)
        return
    repo = parse_repo_and_flags(args)
    out = Path(get_flag(args, "--out") or (repo / "repo-docs"))
    branch = get_flag(args, "--branch") or "gh-pages"
    remote = get_flag(args, "--remote") or "origin"
    sys.exit(cmd_publish(
        repo, out, branch, remote, "--dry-run" in args, "--allow-public" in args
    ))


def cmd_publish_wiki_cli(args: list[str]):
    if "--help" in args or "-h" in args:
        print(PUBLISH_WIKI_HELP)
        return
    repo = parse_repo_and_flags(args)
    out = Path(get_flag(args, "--out") or (repo / "repo-docs"))
    remote = get_flag(args, "--remote") or "origin"
    sys.exit(cmd_publish_wiki(repo, out, remote, "--dry-run" in args, "--allow-public" in args))


def main(argv: list[str]):
    if not argv:
        print(__doc__)
        return
    cmd, rest = argv[0], argv[1:]
    if cmd in ("help", "-h", "--help"):
        print(__doc__)
    elif cmd == "--version":
        print(VERSION)
    elif cmd == "scan":
        cmd_scan(rest)
    elif cmd == "plan":
        cmd_plan(rest)
    elif cmd == "generate":
        cmd_generate_cli(rest)
    elif cmd == "html":
        cmd_html(rest)
    elif cmd == "translate":
        cmd_translate_cli(rest)
    elif cmd == "publish":
        cmd_publish_cli(rest)
    elif cmd == "publish-wiki":
        cmd_publish_wiki_cli(rest)
    elif cmd == "all":
        sys.exit(cmd_all(rest))
    elif cmd == "setup":
        cmd_setup(rest)
    else:
        die(f"unknown subcommand: {cmd}\n\n{__doc__}", 2)


def cli():
    """Console-script entry point installed as `repodocs`."""
    main(sys.argv[1:])


def cli_all():
    """Console-script entry point installed as `repodocs-all`; dispatches to `repodocs all`."""
    main(["all", *sys.argv[1:]])
