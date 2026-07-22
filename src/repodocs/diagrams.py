"""repodocs.diagrams -- internal module (see the repodocs package).

Optional, clone-time step: render each ```mermaid``` block in the generated
pages to a pastel PNG (via tools/diagram_poster.ts, a Bun + playwright tool)
and replace the block with an image embed. GitHub's wiki mermaid renderer
intermittently fails to load; a committed PNG always shows. Requires Bun; not
part of the zero-dependency Python core.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from ._util import die, log
from .render import md_title

_MERMAID_RE = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)


def tool_path() -> Path | None:
    """tools/diagram_poster.ts relative to the repodocs source checkout, or None
    when running from an installed wheel that didn't ship the dev tool."""
    p = Path(__file__).resolve().parents[2] / "tools" / "diagram_poster.ts"
    return p if p.is_file() else None


def _poster_yaml(title: str, slug: str, mermaid: str, i: int, n: int) -> str:
    """Minimal pastel-poster YAML wrapping one mermaid block. JSON-encodes the
    text scalars (valid YAML) so titles with quotes/colons can't break parsing."""
    kicker = f"REPODOCS · {slug.upper()}"
    if n > 1:
        kicker += f" · DIAGRAM {i}/{n}"
    body = "\n".join("  " + ln for ln in mermaid.splitlines())
    return (
        f"title: {json.dumps(title)}\n"
        f"kicker: {json.dumps(kicker)}\n"
        f"headline: {json.dumps(title)}\n"
        f"mermaid: |\n{body}\n"
        f"footer:\n  left: \"REPODOCS\"\n  right: {json.dumps(slug)}\n"
    )


def _render_png(tool: Path, out: Path, stem: str, i: int, yaml_text: str) -> bool:
    """Render one poster YAML to out/<stem>-diagram-<i>.png; return True on a
    non-empty PNG. Intermediate .yaml/.html are removed either way."""
    base = out / f"{stem}-diagram-{i}"
    yaml_path = base.with_suffix(".yaml")
    png = base.with_suffix(".png")
    yaml_path.write_text(yaml_text)
    try:
        r = subprocess.run(["bun", str(tool), str(yaml_path), "--png"],
                           capture_output=True, text=True)
        ok = r.returncode == 0 and png.is_file() and png.stat().st_size > 0
        if not ok and r.stderr:
            print(f"    {png.name}: {r.stderr.strip().splitlines()[-1]}", file=sys.stderr)
    finally:
        yaml_path.unlink(missing_ok=True)
        base.with_suffix(".html").unlink(missing_ok=True)
    return ok


def process_page(md: Path, out: Path, tool: Path) -> tuple[int, int]:
    """Render every mermaid block in one page and swap it for an image embed.
    Blocks that fail to render keep their raw ```mermaid``` fence. Returns
    (rendered, failed)."""
    text = md.read_text()
    blocks = list(_MERMAID_RE.finditer(text))
    if not blocks:
        return (0, 0)
    title = md_title(text) or md.stem
    n = len(blocks)
    pngs: list[str | None] = []
    for i, m in enumerate(blocks, 1):
        yaml_text = _poster_yaml(title, md.stem, m.group(1).strip(), i, n)
        png = f"{md.stem}-diagram-{i}.png"
        pngs.append(png if _render_png(tool, out, md.stem, i, yaml_text) else None)

    seq = iter(range(n))

    def repl(_m: "re.Match[str]") -> str:
        k = next(seq)
        png = pngs[k]
        if png is None:
            return _m.group(0)  # render failed -> leave the raw mermaid block
        cap = f"{title} — diagram {k + 1}" if n > 1 else f"{title} diagram"
        return f"![{cap}]({png})"

    md.write_text(_MERMAID_RE.sub(repl, text))
    return (sum(1 for p in pngs if p), sum(1 for p in pngs if p is None))


def cmd_render_diagrams(repo: Path, out: Path) -> int:
    tool = tool_path()
    if tool is None:
        die("diagram tool not found (expected tools/diagram_poster.ts); "
            "run render-diagrams from a repodocs clone", 1)
    if shutil.which("bun") is None:
        die("bun not found; install Bun (https://bun.sh), then `cd tools && bun install` "
            "and `bunx playwright install chromium`", 1)
    pages = sorted(p for p in out.glob("*.md") if p.name != "index.md")
    total_r = total_f = 0
    for md in pages:
        r, f = process_page(md, out, tool)
        if r or f:
            note = f"{r} rendered" + (f", {f} failed" if f else "")
            log(f"[diagrams] {md.name}: {note}")
        total_r += r
        total_f += f
    print(f"rendered {total_r} diagram(s) into {out}"
          + (f"; {total_f} failed (kept as mermaid)" if total_f else ""))
    return 1 if total_f else 0
