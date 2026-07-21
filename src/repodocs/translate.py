"""repodocs.translate -- internal module (see the repodocs package)."""

import json
import subprocess
import sys

from pathlib import Path

from ._util import die
from .backend import backend_name, failure_detail, missing_resource_message, parallel_llm, run_llm
from .citations import lint_citations
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


def localize_headings(md: str, lang: str) -> str:
    repl = SOURCES_HEADING.get(lang)
    return md.replace("## Relevant source files", repl, 1) if repl else md


def translate_plan_prompt(reduced: list[dict], lang: str = "pt") -> str:
    name = LANG_NAMES.get(lang, lang)
    return (
        f'Translate the "title" and "purpose" fields of each object in this JSON '
        f'array to {name}. Keep "slug" unchanged. Output ONLY a JSON array of '
        '{"slug","title","purpose"}. No prose, no code fences.\n\n'
        + json.dumps(reduced, indent=2, ensure_ascii=False)
    )


def translate_plan_file(repo: Path, src: Path, dest: Path, lang: str):
    """Translate plan.json title/purpose (one LLM call); on failure copy untranslated."""
    try:
        original = json.loads(src.read_text())
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
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError, OSError) as ex:
        print(f"plan.json translation failed ({ex}); copied untranslated", file=sys.stderr)
        dest.write_text(src.read_text())


def cmd_translate(repo: Path, out: Path, lang: str, only: set[str] | None, force: bool) -> int:
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
    if src_plan.is_file():
        translate_plan_file(repo, src_plan, dest / "plan.json", lang)
    present = {p.stem for p in dest.glob("*.md") if p.name != "index.md"}
    pages = _pages_for(dest / "plan.json", present)
    lint_citations(repo, dest, pages)  # verifies citations survived translation intact
    write_index(repo, dest, pages)
    return 1 if failed else 0
