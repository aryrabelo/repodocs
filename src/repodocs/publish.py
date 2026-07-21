"""repodocs.publish -- internal module (see the repodocs package)."""

import json
import re
import shutil
import subprocess
import sys
import tempfile

from pathlib import Path

from ._util import die
from .backend import failure_detail
from .citations import enforce_citations
from .gitlinks import _git_out, _github_slug, citations_safe, github_base, rewrite_citation_links, wiki_remote_url
from .render import md_title


def _pages_for(planpath: Path, present: set[str]) -> list[dict]:
    pages, seen = [], set()
    if planpath.is_file():
        try:
            for e in json.loads(planpath.read_text()):
                if isinstance(e, dict) and e.get("slug") in present:
                    pages.append({"slug": e["slug"], "title": e.get("title") or e["slug"]})
                    seen.add(e["slug"])
        except (OSError, json.JSONDecodeError):
            pass
    for s in sorted(present):
        if s not in seen:
            pages.append({"slug": s, "title": s})
    return pages


def stage_publish(out: Path, staging: Path) -> list[str]:
    """Copy the publishable wiki tree from `out` into `staging` (pure fs; no git/network).
    Symlinked files/directories are rejected before any read or copy. Returns the
    sorted list of staged relative paths."""
    staged: list[str] = []

    def put_file(src: Path, rel: str):
        if src.is_symlink():
            raise ValueError(f"refusing to stage symlink: {rel}")
        dst = staging / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        staged.append(rel)

    def put_dir(src: Path, rel: str):
        if src.is_symlink():
            raise ValueError(f"refusing to stage symlink: {rel}")
        for f in sorted(src.rglob("*")):
            frel = f"{rel}/{f.relative_to(src).as_posix()}"
            if f.is_symlink():
                raise ValueError(f"refusing to stage symlink: {frel}")
            if f.is_file():
                put_file(f, frel)

    def put_wiki(src_dir: Path, prefix: str):
        if not (src_dir / "wiki.html").is_file():
            return
        put_file(src_dir / "wiki.html", f"{prefix}index.html")
        if (src_dir / "assets").is_dir():
            put_dir(src_dir / "assets", f"{prefix}assets")
        for md in sorted(src_dir.glob("*.md")):
            put_file(md, f"{prefix}{md.name}")
        if (src_dir / "plan.json").is_file():
            put_file(src_dir / "plan.json", f"{prefix}plan.json")

    put_wiki(out, "")
    for sub in sorted(p for p in out.iterdir() if p.is_dir() and p.name != "assets"):
        if sub.is_symlink():
            raise ValueError(f"refusing to stage symlink: {sub.name}")
        put_wiki(sub, f"{sub.name}/")
    (staging / ".nojekyll").write_text("")
    staged.append(".nojekyll")
    return sorted(staged)


def publish_push(repo: Path, staging: Path, branch: str, remote: str):
    """Push the staged tree as one orphan commit to <remote>/<branch> via a throwaway
    detached worktree -- never touches the user's working tree or current branch."""
    parent = Path(tempfile.mkdtemp(prefix="repodocs-wt-"))
    wt = parent / "wt"  # must not pre-exist: `git worktree add` creates it
    try:
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach", str(wt)],
                       check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(wt), "checkout", "--orphan", branch],
                       check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(wt), "rm", "-rf", "--quiet", "."],
                       capture_output=True, text=True)  # clear the orphan index + tree
        for f in sorted(staging.rglob("*")):
            if f.is_file():
                dst = wt / f.relative_to(staging)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
        subprocess.run(["git", "-C", str(wt), "add", "-A"], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(wt), "commit", "-m", "docs: publish repo wiki (repodocs)"],
                       check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(wt), "push", "-f", remote, f"HEAD:{branch}"],
                       check=True, capture_output=True, text=True)
    finally:
        subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(wt)],
                       capture_output=True, text=True)
        subprocess.run(["git", "-C", str(repo), "worktree", "prune"], capture_output=True, text=True)
        shutil.rmtree(parent, ignore_errors=True)


PROTECTED_PUBLISH_BRANCHES = {"main", "master", "trunk"}


PUBLISH_SECRET_PATTERNS = (
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("cloud/API key", re.compile(r"\b(?:AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,})\b")),
)


def staged_secret_findings(staging: Path) -> list[tuple[str, int, str]]:
    """Return path/line/pattern only; never echo the matching value."""
    findings = []
    for path in sorted(p for p in staging.rglob("*") if p.is_file()):
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        rel = str(path.relative_to(staging))
        for line_no, line in enumerate(text.splitlines(), 1):
            for label, pattern in PUBLISH_SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append((rel, line_no, label))
    return findings


def publish_branch_safe(branch: str) -> bool:
    return branch.lower() not in PROTECTED_PUBLISH_BRANCHES


def cmd_publish(repo: Path, out: Path, branch: str, remote: str, dry_run: bool,
                allow_public: bool = False) -> int:
    wiki = out / "wiki.html"
    if not wiki.is_file():
        die(f"{wiki} not found; run `repodocs html {repo} --vendor` first", 1)
    if not publish_branch_safe(branch):
        die(f"refusing to force-push protected branch {branch!r}; use a docs branch", 1)
    url = _git_out(repo, "remote", "get-url", remote).strip()
    if not url:
        die(f"remote '{remote}' not found; add it or pass --remote <name>", 1)
    slug = _github_slug(url)
    if "cdn.jsdelivr.net" in wiki.read_text():
        print("warning: wiki.html uses CDN tags (works when hosted; not offline) -- "
              "rebuild with `repodocs html ... --vendor` for a self-contained page", file=sys.stderr)
    enforce_citations(repo, out, subdirs=True, cmd="publish")
    staging = Path(tempfile.mkdtemp(prefix="repodocs-stage-"))
    try:
        staged = stage_publish(out, staging)
        findings = staged_secret_findings(staging)
        if findings:
            details = ", ".join(f"{path}:{line} ({label})" for path, line, label in findings[:10])
            die(f"publish blocked: possible secrets in staged wiki: {details}", 1)
        langs = sorted(r.split("/")[0] for r in staged if r.endswith("/index.html"))
        if dry_run:
            print(f"target: {remote} ({url}) branch {branch}")
            for r in staged:
                print(f"  {r}")
            print(f"\n(dry run) {len(staged)} file(s); rerun with --allow-public to push")
            if slug:
                owner, name = slug.split("/", 1)
                print(f"would publish -> https://{owner}.github.io/{name}/")
            return 0
        if not allow_public:
            die("refusing public push without --allow-public; run --dry-run and review first", 1)
        publish_push(repo, staging, branch, remote)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    if slug:
        owner, name = slug.split("/", 1)
        base = f"https://{owner}.github.io/{name}/"
        print(base)
        for lg in langs:
            print(f"{base}{lg}/")
        print(f"first publish? enable Pages: repo Settings -> Pages -> deploy from branch {branch} / root")
    else:
        print(f"pushed to {remote}/{branch} ({url}); GitHub Pages URL only derivable for github remotes")
    return 0


def stage_wiki(out: Path, staging: Path, base: str | None) -> list[str]:
    """Copy generated wiki pages from `out` into `staging` in GitHub-Wiki layout
    (pure fs; no git/network). overview.md becomes Home.md; index.md is the
    fallback Home source when overview.md is missing, and is never itself
    staged as a page. A _Sidebar.md is generated from plan.json order/titles
    (falling back to each page's own `# heading` when the plan has no title).
    Citation links are rewritten to absolute `base` blob URLs when given.
    Symlinked source files are rejected before any read. Returns the sorted
    list of staged relative paths."""
    staged: list[str] = []
    staging.mkdir(parents=True, exist_ok=True)
    mds = sorted(p for p in out.glob("*.md") if p.name != "index.md")
    present = {p.stem for p in mds}
    home = out / "overview.md"
    if not home.is_file():
        home = out / "index.md" if (out / "index.md").is_file() else None

    def read(src: Path, rel: str) -> str:
        if src.is_symlink():
            raise ValueError(f"refusing to stage symlink: {rel}")
        return src.read_text()

    def put(text: str, name: str):
        (staging / name).write_text(rewrite_citation_links(text, base))
        staged.append(name)

    if home is not None:
        put(read(home, "Home.md"), "Home.md")
    for p in mds:
        if p.stem == "overview":
            continue  # already staged as Home.md
        put(read(p, f"{p.stem}.md"), f"{p.stem}.md")

    pages = _pages_for(out / "plan.json", present)
    lines = ["# Pages", ""]
    if home is not None:
        lines.append("- [Home](Home)")
    for pg in pages:
        if pg["slug"] == "overview":
            continue
        title = pg["title"]
        if title == pg["slug"]:  # plan had no title for this page -> use its own heading
            src = out / f"{pg['slug']}.md"
            if src.is_file():
                title = md_title(read(src, f"{pg['slug']}.md")) or title
        lines.append(f"- [{title}]({pg['slug']})")
    put("\n".join(lines) + "\n", "_Sidebar.md")
    return sorted(staged)


class WikiNotInitialized(RuntimeError):
    """Raised when a repo's GitHub Wiki has no page yet, so it can't be cloned."""


class WikiPublishError(RuntimeError):
    """Raised when a git operation against the (already-initialized) wiki
    clone fails -- add/status/commit/push/rev-parse. Distinct from
    WikiNotInitialized, which is the 'wiki doesn't exist yet' case raised
    by the initial clone."""


def _wiki_git(clone: Path, *args: str, label: str) -> subprocess.CompletedProcess:
    """Run a git command against the wiki clone; on nonzero exit raise
    WikiPublishError with bounded stderr/stdout only -- never the raw argv,
    which could otherwise leak a credential-bearing remote URL."""
    result = subprocess.run(["git", "-C", str(clone), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise WikiPublishError(f"git {label} failed: {failure_detail(result)}")
    return result


def publish_wiki_push(wiki_url: str, staged: list[str], staging: Path) -> str | None:
    """Clone `wiki_url` into a tempdir, overwrite only the staged filenames (any
    other, manually-added wiki pages are left untouched), commit only if the
    tree changed, and push normally -- never force. Never touches the source
    repo's working tree. Returns the new commit sha, or None if nothing
    changed. Raises WikiNotInitialized when the wiki has no pages to clone,
    or WikiPublishError for any other git failure along the way."""
    clone = Path(tempfile.mkdtemp(prefix="repodocs-wiki-"))
    try:
        result = subprocess.run(["git", "clone", "--depth", "1", wiki_url, str(clone)],
                                capture_output=True, text=True)
        if result.returncode != 0:
            raise WikiNotInitialized(
                f"could not clone {wiki_url}: {failure_detail(result)}\n"
                "the GitHub Wiki has no pages yet -- enable it (repo Settings -> "
                "Features -> Wikis) and create the first Home page in the GitHub "
                "UI, then retry `repodocs publish-wiki`"
            )
        for rel in staged:
            dst = clone / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(staging / rel, dst)
        _wiki_git(clone, "add", "-A", "--", *staged, label="add")
        status = _wiki_git(clone, "status", "--porcelain", "--", *staged, label="status").stdout
        if not status.strip():
            return None
        _wiki_git(clone, "commit", "-m", "docs: publish repo wiki (repodocs)", label="commit")
        _wiki_git(clone, "push", "origin", "HEAD", label="push")
        sha = _wiki_git(clone, "rev-parse", "HEAD", label="rev-parse").stdout.strip()
        if not sha:
            raise WikiPublishError("git rev-parse HEAD returned no commit sha after push")
        return sha
    finally:
        shutil.rmtree(clone, ignore_errors=True)


def cmd_publish_wiki(repo: Path, out: Path, remote: str, dry_run: bool, allow_public: bool = False) -> int:
    mds = [p for p in out.glob("*.md") if p.name != "index.md"]
    if not mds:
        die(f"no .md pages in {out}; run `repodocs generate {repo}` first", 1)
    url = _git_out(repo, "remote", "get-url", remote).strip()
    if not url:
        die(f"remote '{remote}' not found; add it or pass --remote <name>", 1)
    wiki_url = wiki_remote_url(url)
    if not wiki_url:
        die(f"remote '{remote}' ({url}) is not a github.com remote; wiki publish needs github", 1)
    base = github_base(repo)
    if base:
        ok, why = citations_safe(_git_out(repo, "status", "--porcelain"),
                                 _git_out(repo, "branch", "-r", "--contains", "HEAD"))
        if not ok:
            print(f"citations left relative: {why}", file=sys.stderr)
            base = None
    enforce_citations(repo, out, subdirs=False, cmd="publish-wiki")
    staging = Path(tempfile.mkdtemp(prefix="repodocs-wikistage-"))
    try:
        staged = stage_wiki(out, staging, base)
        findings = staged_secret_findings(staging)
        if findings:
            details = ", ".join(f"{path}:{line} ({label})" for path, line, label in findings[:10])
            die(f"publish-wiki blocked: possible secrets in staged wiki: {details}", 1)
        if dry_run:
            print(f"target: {wiki_url}")
            for r in staged:
                print(f"  {r}")
            print(f"\n(dry run) {len(staged)} file(s); rerun with --allow-public to push")
            return 0
        if not allow_public:
            die("refusing public push without --allow-public; run --dry-run and review first", 1)
        try:
            sha = publish_wiki_push(wiki_url, staged, staging)
        except (WikiNotInitialized, WikiPublishError) as ex:
            die(str(ex), 1)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    if sha is None:
        print("wiki already up to date; nothing to push")
    else:
        print(f"pushed {sha[:12]} to {wiki_url}")
    return 0
