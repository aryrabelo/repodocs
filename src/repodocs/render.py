"""repodocs.render -- internal module (see the repodocs package)."""

import html
import json
import re
import sys
import urllib.request

from pathlib import Path

from ._util import die
from .gitlinks import _git_out, citations_safe, github_base, rewrite_citation_links


CDN_ASSETS = {
    "marked": "https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js",
    "mermaid": "https://cdn.jsdelivr.net/npm/mermaid@11.16.0/dist/mermaid.min.js",
    "hljs": "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.11.1/highlight.min.js",
    "hljscss": "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.11.1/styles/github-dark.min.css",
    "dompurify": "https://cdn.jsdelivr.net/npm/dompurify@3.4.12/dist/purify.min.js",
}


# Subresource Integrity for the pinned CDN_ASSETS above (sha384, base64), computed from the
# exact pinned files so a tampered/compromised CDN response is rejected by the browser
# instead of executing silently. Vendored/offline mode serves local files under different
# bytes and does not use these -- see _asset_sri_attr()/render_html().
SRI = {
    "marked": "sha384-/TQbtLCAerC3jgaim+N78RZSDYV7ryeoBCVqTuzRrFec2akfBkHS7ACQ3PQhvMVi",
    "mermaid": "sha384-T/0lMUdJpd2S1ZHtRiofG3htU3xPCrFVeAQ1UUE2TJwlEJSV5NUwn30kP28n238E",
    "hljs": "sha384-RH2xi4eIQ/gjtbs9fUXM68sLSi99C7ZWBRX1vDrVv6GQXRibxXLbwO2NGZB74MbU",
    "hljscss": "sha384-wH75j6z1lH97ZOpMOInqhgKzFkAInZPPSPlZpYKYTOqsaizPvhQZmAtLcPKXpLyH",
    "dompurify": "sha384-piCcpDdJ7qVeK4Tv8Z6Hpcr3ZBIgP16TxQTPVfsLFdZ5uDgwc3Y8Ho7oUnqf12qu",
}


VENDOR_FILES = {
    "marked.min.js": CDN_ASSETS["marked"],
    "mermaid.min.js": CDN_ASSETS["mermaid"],
    "highlight.min.js": CDN_ASSETS["hljs"],
    "github-dark.min.css": CDN_ASSETS["hljscss"],
    "purify.min.js": CDN_ASSETS["dompurify"],
}


VENDOR_ASSETS = {
    "marked": "assets/marked.min.js", "mermaid": "assets/mermaid.min.js",
    "hljs": "assets/highlight.min.js", "hljscss": "assets/github-dark.min.css",
    "dompurify": "assets/purify.min.js",
}


LANG_LABELS = {
    "en": {"search": "Search pages...", "toc": "On this page", "github": "View on GitHub",
           "prev": "Previous", "next": "Next",
           "groups": {"Overview": "Overview", "Features": "Features",
                      "Reference": "Reference", "Development": "Development"}},
    "pt": {"search": "Buscar páginas...", "toc": "Nesta página", "github": "Ver no GitHub",
           "prev": "Anterior", "next": "Próxima",
           "groups": {"Overview": "Visão Geral", "Features": "Funcionalidades",
                      "Reference": "Referência", "Development": "Desenvolvimento"}},
}


LANG_NAMES = {"pt": "Brazilian Portuguese"}


def lang_labels(name: str) -> dict:
    """UI label set inferred from an out-dir name (e.g. 'pt'); English fallback."""
    return LANG_LABELS.get(name, LANG_LABELS["en"])


def group_pages(slugs: list[str]) -> list[dict]:
    """Deterministic cubic-style nav grouping, plan order preserved, empty groups omitted."""
    OVERVIEW = {"overview", "installation", "limitations", "changelog"}
    DEV = {"development", "testing", "contributing", "security", "dev-setup"}
    buckets = {"Overview": [], "Features": [], "Reference": [], "Development": []}
    for s in slugs:
        if s in OVERVIEW:
            buckets["Overview"].append(s)
        elif s in DEV:
            buckets["Development"].append(s)
        elif s == "architecture" or "architecture" in s or "interop" in s:
            buckets["Reference"].append(s)
        else:
            buckets["Features"].append(s)
    return [{"name": g, "slugs": buckets[g]}
            for g in ("Overview", "Features", "Reference", "Development") if buckets[g]]


THIRD_PARTY_NOTICES = """RepoDocs vendors the following third-party libraries into
this assets/ directory, redistributed unmodified from the jsDelivr npm CDN. Each
remains under its own license; the notices below are reproduced to satisfy their
attribution requirements and are published alongside the assets.

================================================================================
marked -- assets/marked.min.js  (npm: marked@12, https://github.com/markedjs/marked)
SPDX-License-Identifier: MIT

Copyright (c) 2018+, MarkedJS (https://github.com/markedjs/)
Copyright (c) 2011-2018, Christopher Jeffrey (https://github.com/chjj/)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
================================================================================
Mermaid -- assets/mermaid.min.js  (npm: mermaid@11, https://github.com/mermaid-js/mermaid)
SPDX-License-Identifier: MIT

Copyright (c) 2014 - 2022 Knut Sveidqvist

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
================================================================================
highlight.js -- assets/highlight.min.js, assets/github-dark.min.css
(npm: @highlightjs/cdn-assets@11, https://github.com/highlightjs/highlight.js)
SPDX-License-Identifier: BSD-3-Clause

Copyright (c) 2006, Ivan Sagalaev.
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* Neither the name of the copyright holder nor the names of its
  contributors may be used to endorse or promote products derived from
  this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
================================================================================
DOMPurify -- assets/purify.min.js  (npm: dompurify@3, https://github.com/cure53/DOMPurify)
SPDX-License-Identifier: Apache-2.0 OR MPL-2.0

@license DOMPurify | (c) Cure53 and other contributors | Released under the
Apache License 2.0 and Mozilla Public License 2.0. The vendored purify.min.js
carries this notice inline in its file header. Full license texts:
https://www.apache.org/licenses/LICENSE-2.0 and https://www.mozilla.org/MPL/2.0/
(also github.com/cure53/DOMPurify/blob/main/LICENSE).
================================================================================
"""


def vendor_assets(out: Path):
    """Download the pinned CDN libs into <out>/assets/ for offline use, and write
    the third-party license notices next to them so the published artifact carries
    the attributions (not only the source repository)."""
    ad = out / "assets"
    ad.mkdir(parents=True, exist_ok=True)
    for name, url in VENDOR_FILES.items():
        with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 (pinned jsdelivr https)
            (ad / name).write_bytes(r.read())
    (ad / "THIRD-PARTY-NOTICES.txt").write_text(THIRD_PARTY_NOTICES)


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ Wiki</title>
<link rel="stylesheet" href="__HLJSCSS__"__HLJSCSS_SRI__>
<style>
  :root { --bar:56px; --side:240px; --toc:220px; }
  * { box-sizing:border-box; }
  body { margin:0; background:#0a0a0a; color:#d4d4d8; line-height:1.6;
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
  a { color:#60a5fa; text-decoration:none; }
  a:hover { text-decoration:underline; }
  header.bar { position:fixed; top:0; left:0; right:0; height:var(--bar); z-index:10;
               display:flex; align-items:center; justify-content:space-between;
               padding:0 1.2rem; border-bottom:1px solid #1f1f22; background:#0a0a0a; }
  header.bar .crumb { color:#e4e4e7; font-weight:600; font-size:.95rem; }
  header.bar .ghlink { color:#a1a1aa; font-size:.85rem; }
  aside.side { position:fixed; top:var(--bar); left:0; bottom:0; width:var(--side);
               overflow:auto; padding:1rem .8rem; border-right:1px solid #1f1f22; }
  .repolabel { color:#71717a; font-size:.72rem; text-transform:uppercase; letter-spacing:.05em; margin:.2rem .3rem .6rem; }
  #filter { width:100%; margin-bottom:.8rem; padding:.4rem .6rem; border:1px solid #27272a;
            border-radius:6px; background:#141416; color:#d4d4d8; font-size:.85rem; }
  #filter::placeholder { color:#52525b; }
  .navgroup { margin-bottom:1rem; }
  .navhead { color:#fafafa; font-size:.72rem; font-weight:700; text-transform:uppercase; letter-spacing:.05em; padding:.3rem; }
  .navlink { display:block; padding:.3rem .5rem; border-radius:6px; color:#a1a1aa; font-size:.88rem; }
  .navlink:hover { background:#18181b; color:#d4d4d8; text-decoration:none; }
  .navlink.active { background:#1f1f23; color:#fff; }
  main { margin-left:var(--side); margin-right:var(--toc); padding:calc(var(--bar) + 2rem) 3rem 4rem; }
  article { max-width:720px; margin:0 auto; }
  article h1,article h2,article h3,article h4 { color:#fff; line-height:1.25; }
  article h1 { border-bottom:1px solid #1f1f22; padding-bottom:.4rem; }
  article pre { padding:1rem; overflow:auto; border-radius:8px; background:#141416; border:1px solid #1f1f22; }
  article code { background:#27272a; padding:.12em .4em; border-radius:4px; font-size:.88em; }
  article pre code { background:none; padding:0; }
  article table { border-collapse:collapse; }
  article th,article td { border:1px solid #27272a; padding:.4rem .6rem; }
  article details { margin:1rem 0; padding:.4rem .8rem; border:1px solid #1f1f22; border-radius:8px; background:#0f0f11; }
  article details summary { cursor:pointer; color:#a1a1aa; font-size:.85rem; list-style:none; }
  article details summary::-webkit-details-marker { display:none; }
  article details summary::before { content:"\25B6  "; color:#52525b; }
  article details[open] summary::before { content:"\25BC  "; }
  .mermaid { background:#141416; border-radius:8px; padding:.5rem; }
  .pn { display:flex; justify-content:space-between; gap:1rem; margin-top:3rem; padding-top:1rem; border-top:1px solid #1f1f22; }
  .pn a { display:flex; flex-direction:column; text-decoration:none; }
  .pn-next { align-items:flex-end; text-align:right; }
  .pn-k { font-size:.72rem; color:#71717a; }
  .pn-t { color:#60a5fa; font-size:.95rem; }
  aside.toc { position:fixed; top:var(--bar); right:0; bottom:0; width:var(--toc); overflow:auto; padding:1.5rem 1rem; }
  .toc-title { color:#71717a; font-size:.72rem; font-weight:700; text-transform:uppercase; letter-spacing:.05em; margin-bottom:.6rem; }
  .toc a { display:block; padding:.2rem 0; color:#a1a1aa; font-size:.82rem; }
  .toc a.toc-3 { padding-left:.8rem; font-size:.78rem; }
  @media (max-width:1100px) { main { margin-right:0; } aside.toc { display:none; } }
  @media (max-width:720px) { aside.side { display:none; } main { margin-left:0; padding-left:1.2rem; padding-right:1.2rem; } }
</style>
</head>
<body>
<header class="bar"><span class="crumb">__BREADCRUMB__</span>__GHLINK__</header>
<aside class="side">
  <div class="repolabel">__BREADCRUMB__</div>
  <input id="filter">
  <div id="nav"></div>
</aside>
<main><article id="content"></article></main>
<aside class="toc" id="toc"></aside>
<script src="__MARKED__"__MARKED_SRI__></script>
<script src="__MERMAID__"__MERMAID_SRI__></script>
<script src="__HLJS__"__HLJS_SRI__></script>
<script src="__DOMPURIFY__"__DOMPURIFY_SRI__></script>
<script>
const PAGES = __PAGES__, GROUPS = __GROUPS__, ORDER = __ORDER__, REPO = __REPO__, LABELS = __LABELS__;
if (window.mermaid) mermaid.initialize({ startOnLoad: false, theme: "dark", securityLevel: "strict" });
const navEl = document.getElementById("nav");
GROUPS.forEach(function (g) {
  const box = document.createElement("div"); box.className = "navgroup";
  const h = document.createElement("div"); h.className = "navhead"; h.textContent = (LABELS.groups && LABELS.groups[g.name]) || g.name; box.appendChild(h);
  g.slugs.forEach(function (slug) {
    const a = document.createElement("a"); a.className = "navlink"; a.textContent = PAGES[slug].title;
    a.href = "#" + slug; a.dataset.slug = slug; box.appendChild(a);
  });
  navEl.appendChild(box);
});
document.getElementById("filter").placeholder = LABELS.search;
document.getElementById("filter").addEventListener("input", function () {
  const q = this.value.toLowerCase();
  document.querySelectorAll(".navgroup").forEach(function (box) {
    let any = false;
    box.querySelectorAll(".navlink").forEach(function (a) {
      const ok = a.textContent.toLowerCase().indexOf(q) >= 0;
      a.style.display = ok ? "" : "none"; if (ok) any = true;
    });
    box.querySelector(".navhead").style.display = any ? "" : "none";
  });
});
function collapseSources(content) {
  // structural match: the sources section is the FIRST h2 and its body is a file list (ul);
  // wording varies by language/model, so never match on the heading text.
  content.querySelectorAll("h2").forEach(function (h, i) {
    if (i > 0) return;
    const sib = h.nextElementSibling;
    if (!sib || sib.tagName !== "UL") return;
    const label = h.textContent.trim();
    const det = document.createElement("details");
    const sum = document.createElement("summary"); sum.textContent = label; det.appendChild(sum);
    let n = h.nextElementSibling; const move = [];
    while (n && !/^H[1-6]$/.test(n.tagName)) { move.push(n); n = n.nextElementSibling; }
    move.forEach(function (el) { det.appendChild(el); });
    h.replaceWith(det);
  });
}
function buildToc(content) {
  const toc = document.getElementById("toc"); toc.innerHTML = "";
  const heads = content.querySelectorAll("h2, h3");
  if (!heads.length) { toc.style.display = "none"; return; }
  toc.style.display = "";
  const t = document.createElement("div"); t.className = "toc-title"; t.textContent = LABELS.toc; toc.appendChild(t);
  heads.forEach(function (h, i) {
    h.id = "sec-" + i;
    const a = document.createElement("a"); a.textContent = h.textContent; a.href = "#sec-" + i;
    a.className = h.tagName === "H3" ? "toc-3" : "toc-2";
    a.onclick = function (e) { e.preventDefault(); h.scrollIntoView({ behavior: "smooth" }); };
    toc.appendChild(a);
  });
}
function pageFooter(content, slug) {
  const i = ORDER.indexOf(slug);
  const prev = i > 0 ? ORDER[i - 1] : null, next = i < ORDER.length - 1 ? ORDER[i + 1] : null;
  const d = document.createElement("div"); d.className = "pn";
  const prevA = prev ? '<a class="pn-prev" href="#' + prev + '"><span class="pn-k">\u2190 ' + LABELS.prev
                     + '</span><span class="pn-t">' + PAGES[prev].title + '</span></a>' : '<span></span>';
  const nextA = next ? '<a class="pn-next" href="#' + next + '"><span class="pn-k">' + LABELS.next
                     + ' \u2192</span><span class="pn-t">' + PAGES[next].title + '</span></a>' : '<span></span>';
  d.innerHTML = DOMPurify.sanitize(prevA + nextA);
  content.appendChild(d);
}
function show(slug) {
  const p = PAGES[slug]; if (!p) return;
  const content = document.getElementById("content");
  if (!window.DOMPurify) {
    content.textContent = "Sanitizer unavailable (DOMPurify failed to load) -- refusing to render page content for safety.";
    document.querySelectorAll(".navlink").forEach(function (a) { a.classList.toggle("active", a.dataset.slug === slug); });
    document.title = p.title + " \u2014 " + REPO + " Wiki";
    if (location.hash !== "#" + slug) location.hash = slug;
    window.scrollTo(0, 0);
    return;
  }
  content.innerHTML = DOMPurify.sanitize(marked.parse(p.md), { ADD_ATTR: ["target"] });
  content.querySelectorAll("code.language-mermaid").forEach(function (code) {
    const dv = document.createElement("div"); dv.className = "mermaid"; dv.textContent = code.textContent;
    code.parentElement.replaceWith(dv);
  });
  collapseSources(content);
  if (window.hljs) content.querySelectorAll("pre code").forEach(function (b) { try { hljs.highlightElement(b); } catch (e) {} });
  if (window.mermaid) { try { mermaid.run({ nodes: content.querySelectorAll(".mermaid") }); } catch (e) {} }
  buildToc(content);
  pageFooter(content, slug);
  document.querySelectorAll(".navlink").forEach(function (a) { a.classList.toggle("active", a.dataset.slug === slug); });
  document.title = p.title + " \u2014 " + REPO + " Wiki";
  if (location.hash !== "#" + slug) location.hash = slug;
  window.scrollTo(0, 0);
}
const initial = location.hash.slice(1);
show(ORDER.indexOf(initial) >= 0 ? initial : ORDER[0]);
window.addEventListener("hashchange", function () { const s = location.hash.slice(1); if (PAGES[s]) show(s); });
</script>
</body>
</html>
"""


def _asset_sri_attr(vendor: bool, key: str) -> str:
    """`integrity`/`crossorigin` attribute text for a CDN <script>/<link> tag, or '' for
    vendored (local file) assets -- their bytes don't match the CDN hash and the browser
    would refuse to load them if tagged with it."""
    if vendor:
        return ""
    sri = SRI.get(key)
    return f' integrity="{sri}" crossorigin="anonymous"' if sri else ""


def render_html(breadcrumb: str, ghroot: str | None, data: dict,
                groups: list[dict], order: list[str], vendor: bool, labels: dict) -> str:
    a = VENDOR_ASSETS if vendor else CDN_ASSETS
    # breadcrumb/ghroot can come from a repo dir name or a configured remote slug --
    # untrusted text, so it's HTML-escaped before landing in the page (text nodes, and the
    # href/text of the GitHub link) or script-string-escaped before landing in JS below.
    safe_breadcrumb = html.escape(breadcrumb, quote=True)
    ghlink = (f'<a class="ghlink" href="{html.escape(ghroot, quote=True)}" target="_blank" '
              f'rel="noopener">{html.escape(labels["github"], quote=True)}</a>' if ghroot else "")
    # Replace __PAGES__ last so embedded page markdown can't clobber other tokens; escape </ for <script>.
    return (HTML_TEMPLATE
            .replace("__TITLE__", safe_breadcrumb)
            .replace("__BREADCRUMB__", safe_breadcrumb)
            .replace("__GHLINK__", ghlink)
            .replace("__MARKED__", a["marked"])
            .replace("__DOMPURIFY__", a["dompurify"])
            .replace("__MERMAID__", a["mermaid"])
            .replace("__HLJS__", a["hljs"])
            .replace("__HLJSCSS__", a["hljscss"])
            .replace("__MARKED_SRI__", _asset_sri_attr(vendor, "marked"))
            .replace("__DOMPURIFY_SRI__", _asset_sri_attr(vendor, "dompurify"))
            .replace("__MERMAID_SRI__", _asset_sri_attr(vendor, "mermaid"))
            .replace("__HLJS_SRI__", _asset_sri_attr(vendor, "hljs"))
            .replace("__HLJSCSS_SRI__", _asset_sri_attr(vendor, "hljscss"))
            .replace("__REPO__", json.dumps(breadcrumb).replace("</", "<\\/"))
            .replace("__LABELS__", json.dumps(labels))
            .replace("__GROUPS__", json.dumps(groups))
            .replace("__ORDER__", json.dumps(order))
            .replace("__PAGES__", json.dumps(data).replace("</", "<\\/")))


def build_html(repo: Path, out: Path, vendor: bool = False) -> Path:
    mds = sorted(p for p in out.glob("*.md") if p.name != "index.md")
    if not mds:
        die(f"no .md pages in {out}; run `repodocs generate {repo}` first", 1)
    titles, order = {}, []
    pj = out / "plan.json"
    if pj.is_file():
        try:
            for e in json.loads(pj.read_text()):
                if isinstance(e, dict) and e.get("slug"):
                    titles[e["slug"]] = e.get("title") or e["slug"]
                    order.append(e["slug"])
        except (OSError, json.JSONDecodeError):
            pass
    base = github_base(repo)
    slug = base.split("/blob/")[0].split("github.com/", 1)[1] if base else None
    breadcrumb = slug or repo.resolve().name
    ghroot = ("https://github.com/" + slug) if slug else None
    cite_base = base  # blob/<sha> citations only when the tree is clean AND HEAD is pushed
    if base:
        try:
            out_rel = out.resolve().relative_to(repo.resolve()).as_posix()
        except ValueError:
            out_rel = None  # out isn't inside repo; every untracked entry counts as dirty
        ok, why = citations_safe(_git_out(repo, "status", "--porcelain"),
                                 _git_out(repo, "branch", "-r", "--contains", "HEAD"),
                                 out_rel)
        if not ok:
            print(f"citations left relative: {why}", file=sys.stderr)
            cite_base = None
    data = {}
    for md in mds:
        s = md.stem
        text = md.read_text()
        data[s] = {"title": titles.get(s) or md_title(text) or s, "md": rewrite_citation_links(text, cite_base)}
    ordered = [s for s in order if s in data] + [s for s in sorted(data) if s not in order]
    groups = group_pages(ordered)
    flat = [s for g in groups for s in g["slugs"]]
    if vendor:
        try:
            vendor_assets(out)
        except OSError as ex:
            die(f"failed to download vendor assets for offline mode: {ex}\n"
                "check your network connection, or rerun `repodocs html --vendor` "
                "once connectivity is restored", 1)
    labels = lang_labels(out.name)  # ui language inferred from the out-dir name (e.g. .../pt)
    dest = out / "wiki.html"
    dest.write_text(render_html(breadcrumb, ghroot, data, groups, flat, vendor, labels))
    return dest


def md_title(text: str) -> str | None:
    for line in text.splitlines():
        m = re.match(r"^#\s+(.+)", line)
        if m:
            return m.group(1).strip()
    return None
