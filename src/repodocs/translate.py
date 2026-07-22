"""repodocs.translate -- internal module (see the repodocs package)."""

import json
import re
import subprocess
import sys

from pathlib import Path

from ._util import die
from .backend import backend_name, failure_detail, missing_resource_message, parallel_llm, run_llm
from .citations import FULL_CITATION_RE, lint_citations
from .generate import write_index
from .plan import parse_pages
from .publish import _pages_for
from .render import LANG_NAMES


def translate_prompt(md: str, lang: str = "pt") -> str:
    name = LANG_NAMES.get(lang, lang)
    return (
        f"Translate this wiki page to {name}. Preserve EXACTLY: all markdown "
        "structure, code blocks and inline code, file paths, URLs, mermaid blocks, "
        "and every `Sources:` line (do not translate or alter citation links). "
        "Translate only the prose, headings, and table cells that are natural "
        "language. Emit ONLY the translated markdown.\n\n" + md
    )


SOURCES_HEADING = {"pt": "## Arquivos-fonte relevantes"}


LANG_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def localize_headings(md: str, lang: str) -> str:
    """Replace the '## Relevant source files' H2 with its localized heading.
    Only an actual H2 line (line starts with the heading, ignoring surrounding
    whitespace) is replaced, and never inside a fenced ``` code block -- so the
    literal text surviving in an example/snippet is left untouched."""
    repl = SOURCES_HEADING.get(lang)
    if not repl:
        return md
    lines = md.split("\n")
    in_fence = False
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and stripped.startswith("## Relevant source files"):
            lines[i] = ln.replace("## Relevant source files", repl, 1)
            break
    return "\n".join(lines)


def translate_plan_prompt(reduced: list[dict], lang: str = "pt") -> str:
    name = LANG_NAMES.get(lang, lang)
    return (
        f'Translate the "title" and "purpose" fields of each object in this JSON '
        f'array to {name}. Keep "slug" unchanged. Output ONLY a JSON array of '
        '{"slug","title","purpose"}. No prose, no code fences.\n\n'
        + json.dumps(reduced, indent=2, ensure_ascii=False)
    )


def translate_plan_file(repo: Path, src: Path, dest: Path, lang: str) -> bool:
    """Translate plan.json title/purpose (one LLM call); on failure copy
    untranslated. Returns True on a real translation, False when the
    untranslated fallback copy was used (so callers can flag the failure)."""
    try:
        original = json.loads(src.read_text())
        if not isinstance(original, list):
            raise ValueError(f"plan.json root is {type(original).__name__}, not a list")
        reduced = [{"slug": e["slug"], "title": e.get("title", ""), "purpose": e.get("purpose", "")}
                   for e in original if isinstance(e, dict) and e.get("slug")]
        r = run_llm(repo, translate_plan_prompt(reduced, lang))
        if r.returncode != 0:
            raise ValueError(f"{backend_name()} exit {r.returncode}: {failure_detail(r)}")
        tmap = {e["slug"]: e for e in parse_pages(r.stdout) if isinstance(e, dict) and e.get("slug")}
        if not tmap:
            raise ValueError("no translated entries")
        merged = []
        for e in original:  # preserve original order and copy files lists verbatim
            if not isinstance(e, dict):
                continue
            t = tmap.get(e.get("slug"), {})
            merged.append({**e, "title": t.get("title") or e.get("title"),
                           "purpose": t.get("purpose") or e.get("purpose")})
        dest.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError, OSError) as ex:
        print(f"plan.json translation failed ({ex}); copied untranslated", file=sys.stderr)
        dest.write_text(src.read_text())
        return False


def _citation_drift(out: Path, dest: Path, pages: list[dict]) -> list[str]:
    """Full `[path:La-Lb](href)` citations present in the source page that the
    translated page dropped or altered. Comparing the full link (not just the
    label) catches both removal and href tampering."""
    problems = []
    for p in pages:
        src_p = out / f"{p['slug']}.md"
        dst_p = dest / f"{p['slug']}.md"
        if not src_p.is_file() or not dst_p.is_file():
            continue
        src_cites = set(FULL_CITATION_RE.findall(src_p.read_text()))
        if not src_cites:
            continue
        missing = src_cites - set(FULL_CITATION_RE.findall(dst_p.read_text()))
        if missing:
            problems.append(f"{p['slug']}.md: {len(missing)} citation(s) dropped or altered")
    return problems


def cmd_translate(repo: Path, out: Path, lang: str, only: set[str] | None, force: bool) -> int:
    if not LANG_RE.match(lang):
        die(f"invalid --lang {lang!r}; expected a plain language code (letters, digits, '_', '-')", 1)
    srcs = sorted(p for p in out.glob("*.md") if p.name != "index.md")
    if not srcs:
        die(f"no .md pages in {out}; run `repodocs generate {repo}` first", 1)
    if only:
        srcs = [p for p in srcs if p.stem in only]
        if not srcs:
            die(f"no pages match --pages {sorted(only)}; run `repodocs html {repo}` to see slugs")
    dest = out / lang
    dest.mkdir(parents=True, exist_ok=True)
    failed = 0
    # Phase 1 (main thread): presence-skip; collect pages to translate.
    # ponytail: presence-skip only -- translations aren't source-hash tracked; --force to redo.
    todo = []
    for p in srcs:
        if (dest / p.name).is_file() and not force:
            print(f"[skip] {p.stem} (exists; --force to retranslate)", file=sys.stderr)
            continue
        todo.append(p)
    # Phase 2: translate in a bounded pool; only the main thread writes files.
    items = [(p.name, translate_prompt(p.read_text(), lang)) for p in todo]
    for name, res in parallel_llm(repo, items,
                                  lambda k: print(f"[translate] {Path(k).stem} -> {lang}", file=sys.stderr)):
        stem = Path(name).stem
        if isinstance(res, FileNotFoundError):
            die(missing_resource_message(res), 1)
        if isinstance(res, subprocess.TimeoutExpired):
            print(f"  {stem}: timeout (set REPODOCS_TIMEOUT to raise)", file=sys.stderr)
            failed += 1
            continue
        if isinstance(res, Exception):
            print(f"  {stem}: {res}", file=sys.stderr)
            failed += 1
            continue
        if res.returncode != 0:
            print(f"  {stem}: {backend_name()} exit {res.returncode}: {failure_detail(res)}", file=sys.stderr)
            failed += 1
            continue
        (dest / name).write_text(localize_headings(res.stdout, lang))
        print(f"[done] {stem}", file=sys.stderr)
    src_plan = out / "plan.json"
    if src_plan.is_file() and not translate_plan_file(repo, src_plan, dest / "plan.json", lang):
        failed += 1
    present = {p.stem for p in dest.glob("*.md") if p.name != "index.md"}
    pages = _pages_for(dest / "plan.json", present)
    lint_citations(repo, dest, pages)  # warns on citations pointing at invalid line ranges
    drift = _citation_drift(out, dest, pages)
    if drift:
        details = "; ".join(drift[:5])
        more = "" if len(drift) <= 5 else f" (+{len(drift) - 5} more)"
        die(f"translate blocked: citations dropped or altered in translation -- {details}{more}", 1)
    write_index(repo, dest, pages)
    return 1 if failed else 0
