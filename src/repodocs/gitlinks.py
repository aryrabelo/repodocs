"""repodocs.gitlinks -- internal module (see the repodocs package)."""

import html
import re
import subprocess
import urllib.parse

from pathlib import Path


_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


_CITE_HREF = re.compile(r"^(?!https?://)([^#)]+)#L(\d+)(?:-L(\d+))?$")


# Real GitHub owner/repo names are limited to alnum, '.', '_', '-'. Anything else in a
# parsed slug means the remote URL isn't a real GitHub path -- reject it rather than let
# HTML/attribute metacharacters (quotes, angle brackets) flow into a generated citation
# href via `base` (see rewrite_citation_links()).
_SLUG_PART = re.compile(r"^[A-Za-z0-9._-]+$")


def _github_slug(url: str) -> str | None:
    """Parse owner/repo from a github remote (ssh or https form). Pure, testable.
    None unless both path segments look like real GitHub owner/repo names."""
    url = url.strip()
    m = (re.match(r"^git@github\.com:([^/]+)/(.+?)(?:\.git)?$", url)
         or re.match(r"^https?://github\.com/([^/]+)/(.+?)(?:\.git)?/?$", url))
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    if not (_SLUG_PART.match(owner) and _SLUG_PART.match(repo)):
        return None
    return f"{owner}/{repo}"


def wiki_remote_url(origin_url: str) -> str | None:
    """<OWNER>/<REPO>.wiki.git clone URL, in the same scheme (ssh/https) as
    `origin_url`. Pure, testable; None for non-github or unparseable remotes."""
    slug = _github_slug(origin_url)
    if not slug:
        return None
    if re.match(r"^git@github\.com:", origin_url.strip()):
        return f"git@github.com:{slug}.wiki.git"
    return f"https://github.com/{slug}.wiki.git"


def github_base(repo: Path) -> str | None:
    """<https://github.com/o/r/blob/HEADsha> if repo has a github origin, else None."""
    try:
        url = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"],
                             capture_output=True, text=True).stdout
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                             capture_output=True, text=True).stdout.strip()
    except (OSError, FileNotFoundError):
        return None
    slug = _github_slug(url)
    if not slug or not re.match(r"^[0-9a-f]{7,40}$", sha):
        return None
    return f"https://github.com/{slug}/blob/{sha}"


def citations_safe(porcelain: str, remote_contains: str, out_rel: str | None = None) -> tuple[bool, str | None]:
    """Pure: blob/<sha> citations are honest only if the tracked tree is clean AND HEAD is
    pushed. An untracked ("??") entry is harmless ONLY when it falls under `out_rel` (the
    repodocs output directory) -- that's a freshly generated page, never a cited source
    file. Any other untracked path might be exactly the file a citation points at, and it
    would not exist in the pushed commit, so it counts as dirty. Without `out_rel`, every
    untracked entry counts as dirty (fail-safe)."""
    def _is_output(ln: str) -> bool:
        if not out_rel or not ln.startswith("??"):
            return False
        path = ln[2:].strip()
        return path == out_rel or path.startswith(out_rel.rstrip("/") + "/")
    dirty = [ln for ln in porcelain.splitlines() if ln.strip() and not _is_output(ln)]
    if dirty:
        return (False, "working tree dirty")
    if not remote_contains.strip():
        return (False, "HEAD not pushed")
    return (True, None)


def _git_out(repo: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True).stdout
    except (OSError, FileNotFoundError):
        return ""


def rewrite_citation_links(md: str, base: str | None) -> str:
    """Rewrite `[text](path#L1-L2)` citation links to absolute github blob URLs.
    Link text is HTML-escaped and the path is URL-quoted, so untrusted markdown
    content (LLM-authored page prose) cannot inject attributes or tags into the
    generated <a> tag."""
    if not base:
        return md
    safe_base = html.escape(base, quote=True)
    def repl(m):
        text, href = m.group(1), m.group(2).strip()
        h = _CITE_HREF.match(href)
        if not h:
            return m.group(0)
        path, a, b = h.group(1), h.group(2), h.group(3)
        anchor = f"#L{a}" + (f"-L{b}" if b else "")
        safe_text = html.escape(text, quote=True)
        safe_path = urllib.parse.quote(path, safe="/")
        return f'<a href="{safe_base}/{safe_path}{anchor}" target="_blank" rel="noopener">{safe_text}</a>'
    return _MD_LINK.sub(repl, md)
