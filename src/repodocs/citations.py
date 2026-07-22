"""repodocs.citations -- internal module (see the repodocs package)."""

import re
import sys

from pathlib import Path

from ._util import count_lines, die, safe_repo_file
from .gitlinks import _CITE_HREF, _MD_LINK, _git_out


CITATION_RE = re.compile(r"\[([^\]\s]+?):L(\d+)-L(\d+)\]")


def lint_citations(repo: Path, out: Path, pages: list[dict]):
    bad = []
    for p in pages:
        md = out / f"{p['slug']}.md"
        if not md.is_file():
            continue
        for m in CITATION_RE.finditer(md.read_text()):
            path, a, b = m.group(1), int(m.group(2)), int(m.group(3))
            fp = safe_repo_file(repo, path)
            if fp is None:
                bad.append((p["slug"], m.group(0), "file not found or outside repo"))
            else:
                n = count_lines(fp)
                if a < 1 or a > b or b > n:
                    bad.append((p["slug"], m.group(0), f"line range out of bounds (file has {n} lines)"))
    if bad:
        print("citation lint (warnings):", file=sys.stderr)
        for slug, cite, why in bad:
            print(f"  {slug}: {cite} -- {why}", file=sys.stderr)
    else:
        print("citation lint: ok", file=sys.stderr)


FULL_CITATION_RE = re.compile(r"\[([^\]\s]+?):L(\d+)-L(\d+)\]\(([^)\s]+)\)")


_HTML_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")


def _strip_noncounted(text: str) -> str:
    """Remove HTML comments and code (fenced ``` blocks and inline `code`) so a
    citation hidden there can't satisfy the citation gate -- only citations in
    rendered prose count."""
    text = _HTML_COMMENT_RE.sub("", text)
    text = _FENCED_CODE_RE.sub("", text)
    return _INLINE_CODE_RE.sub("", text)


def citation_error(repo: Path, label_path: str, a: int, b: int, href: str) -> str | None:
    """Validate one `[path:La-Lb](href)` citation. Returns a reason string when
    the citation is dishonest, else None. Never echoes file contents."""
    hm = _CITE_HREF.match(href.strip())
    if not hm:
        return f"href {href!r} is not a repo-relative line citation"
    h_path, h_a = hm.group(1), int(hm.group(2))
    h_b = int(hm.group(3)) if hm.group(3) else h_a
    if h_path != label_path:
        return f"label path {label_path!r} does not match href path {h_path!r}"
    if (h_a, h_b) != (a, b):
        return f"label range L{a}-L{b} does not match href range L{h_a}-L{h_b}"
    if a < 1 or a > b:
        return f"invalid line range L{a}-L{b}"
    target = safe_repo_file(repo, label_path)
    if target is None:
        return f"cited path {label_path!r} is missing or escapes the repository"
    n = count_lines(target)
    if b > n:
        return f"line range L{a}-L{b} exceeds {label_path} length ({n} lines)"
    return None


_CITE_LABEL_RE = re.compile(r"^(.+?):L?(\d+)(?:-L?(\d+))?$")


def repair_citations(repo: Path, text: str) -> str:
    """Deterministically canonicalize generated citation links to
    `[path:La-Lb](path#La-Lb)` so honest-but-malformed citations pass
    enforce_citations. For each `[label](href)` whose href is a repo-relative
    line anchor (`path#La[-Lb]`):
      * normalize a label that agrees with the href but is missing the `L`
        prefix or is single-line;
      * resolve a path that doesn't exist but uniquely matches a tracked file
        by suffix (the model dropping a leading `src/<pkg>/` prefix);
      * clamp an end line that overshoots the file's real length.
    Only rewrite when label and href name the same path and range and the result
    resolves to a tracked file with an in-bounds range; anything ambiguous
    (path/range disagreement, no unique file, start past EOF) is left untouched
    for enforce_citations to block."""
    tracked = [t for t in _git_out(repo, "ls-files").split("\n") if t]

    def resolve(path: str, a: int, b: int) -> "tuple[str, int, int] | None":
        if safe_repo_file(repo, path) is None:
            hits = [t for t in tracked if t.endswith("/" + path)]
            if len(hits) != 1:
                return None
            path = hits[0]
        target = safe_repo_file(repo, path)
        if target is None:
            return None
        end = min(b, count_lines(target))
        return (path, a, end) if 1 <= a <= end else None

    def repl(m: "re.Match[str]") -> str:
        hm = _CITE_HREF.match(m.group(2).strip())
        lm = _CITE_LABEL_RE.match(m.group(1).strip())
        if not hm or not lm:
            return m.group(0)  # not a line citation -- leave ordinary links alone
        ha, hb = int(hm.group(2)), int(hm.group(3) or hm.group(2))
        la, lb = int(lm.group(2)), int(lm.group(3) or lm.group(2))
        if lm.group(1) != hm.group(1) or (la, lb) != (ha, hb):
            return m.group(0)  # label/href disagree -- don't guess
        r = resolve(hm.group(1), ha, hb)
        if r is None:
            return m.group(0)
        path, a, b = r
        return f"[{path}:L{a}-L{b}]({path}#L{a}-L{b})"

    return _MD_LINK.sub(repl, text)


def requires_evidence(md_text: str) -> bool:
    """A page needs a citation once it has prose beyond its title and the
    'Relevant source files' bullet list. List items are only exempt inside
    that section -- a body list elsewhere still counts as content needing a
    citation."""
    in_sources_section = False
    for ln in md_text.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#"):
            in_sources_section = s.lstrip("#").strip().lower() == "relevant source files"
            continue
        if s.lower().startswith("sources:"):
            continue
        if in_sources_section and s.startswith(("- ", "* ")):
            continue
        return True
    return False


def citation_problems(repo: Path, mds: list[Path]) -> list[tuple[str, str, str]]:
    """(page, citation-or-'-', reason) for every citation/evidence violation.
    A content page carrying no valid citation is itself a violation. This is the
    blocking gate the 'source-cited' promise rests on -- warnings are not enough.
    HTML comments and code are stripped first so a citation hidden there can't
    count, and every bare `[path:La-Lb]` label lacking a linked href is itself
    a violation (not just unlinked full citations with a bad href)."""
    problems: list[tuple[str, str, str]] = []
    for md in sorted(mds):
        if not md.is_file():
            continue
        text = _strip_noncounted(md.read_text())
        valid = 0
        full_spans = set()
        for m in FULL_CITATION_RE.finditer(text):
            full_spans.add(m.start())
            err = citation_error(repo, m.group(1), int(m.group(2)), int(m.group(3)), m.group(4))
            if err:
                problems.append((md.name, m.group(0), err))
            else:
                valid += 1
        for m in CITATION_RE.finditer(text):
            if m.start() not in full_spans:
                problems.append((md.name, m.group(0), "citation label has no linked href"))
        if valid == 0 and requires_evidence(text):
            problems.append((md.name, "-", "content page has no valid source citation"))
    return problems


def wiki_content_pages(out: Path, subdirs: bool = True) -> list[Path]:
    """Generated content pages under `out` (excludes index.md and assets/). With
    subdirs, also includes one level of translated dirs (e.g. out/pt)."""
    pages = [p for p in out.glob("*.md") if p.name != "index.md"]
    if subdirs and out.is_dir():
        for sub in out.iterdir():
            if sub.is_dir() and sub.name != "assets":
                pages += [p for p in sub.glob("*.md") if p.name != "index.md"]
    return pages


def enforce_citations(repo: Path, out: Path, subdirs: bool, cmd: str):
    """Block publish when any staged content page has missing/invalid citations."""
    problems = citation_problems(repo, wiki_content_pages(out, subdirs))
    if problems:
        details = "; ".join(f"{page} {cite} -- {why}" for page, cite, why in problems[:12])
        more = "" if len(problems) <= 12 else f" (+{len(problems) - 12} more)"
        die(f"{cmd} blocked: citation problems -- {details}{more}", 1)
