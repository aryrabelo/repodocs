"""Regression tests for the render.py / gitlinks.py / backend.py cubic review fixes."""

import json
import re
import subprocess

import repodocs.backend as backend_mod

from repodocs.gitlinks import _github_slug, citations_safe, rewrite_citation_links
from repodocs.render import CDN_ASSETS, SRI, VENDOR_ASSETS, lang_labels, render_html


# -- render.py: HTML/script-escaping of breadcrumb + GitHub link ---------------

def test_render_html_escapes_malicious_breadcrumb_in_title_and_script():
    breadcrumb = '</title><script>alert(1)</script>"repo'
    labels = lang_labels("en")
    out = render_html(breadcrumb, None, {}, [], [], False, labels)

    # <title>/<span class="crumb"> are ordinary HTML text nodes: no raw '<' may survive,
    # or the breadcrumb could close the tag early and open a real <script> element.
    title_inner = out.split("<title>", 1)[1].split("</title>", 1)[0]
    assert "<" not in title_inner, "breadcrumb must be HTML-escaped inside <title>"
    assert "</script>alert(1)</script>" not in out, "no raw script breakout in page text"

    # REPO is assigned inside the shared <script> block as a JSON string; '</' must be
    # escaped there too, or the breadcrumb could close that <script> element early.
    expected_repo_literal = json.dumps(breadcrumb).replace("</", "<\\/")
    assert f"REPO = {expected_repo_literal}" in out


def test_render_html_escapes_malicious_ghlink_href_and_text():
    ghroot = 'https://github.com/x/y"><script>alert(2)</script>'
    labels = lang_labels("en")
    out = render_html("repo", ghroot, {}, [], [], False, labels)

    assert "<script>alert(2)</script>" not in out, "ghroot must not inject a live <script> element"
    assert (
        'href="https://github.com/x/y&quot;&gt;&lt;script&gt;alert(2)&lt;/script&gt;"' in out
    ), "ghroot must be HTML-escaped as an attribute value"


# -- render.py: CDN_ASSETS pinning + Subresource Integrity ----------------------

def test_cdn_assets_are_exactly_pinned_with_sri():
    bare_major = re.compile(r"@\d+/")
    for name, url in CDN_ASSETS.items():
        assert not bare_major.search(url), f"{name} uses a floating major version: {url}"
        assert re.search(r"@\d+\.\d+\.\d+", url), f"{name} is not pinned to an exact semver: {url}"
        assert SRI.get(name, "").startswith("sha384-"), f"{name} has no sha384 SRI hash"

    labels = lang_labels("en")
    cdn_html = render_html("repo", None, {}, [], [], False, labels)
    for key in ("marked", "mermaid", "hljs", "dompurify"):
        assert (
            f'src="{CDN_ASSETS[key]}" integrity="{SRI[key]}" crossorigin="anonymous">' in cdn_html
        ), f"{key} CDN <script> is missing its integrity attribute"
    assert (
        f'href="{CDN_ASSETS["hljscss"]}" integrity="{SRI["hljscss"]}" crossorigin="anonymous">'
        in cdn_html
    )

    # Vendored (local file) assets must NOT carry the CDN integrity hash -- their bytes
    # were fetched once and saved locally, so the CDN hash would never match.
    vendor_html = render_html("repo", None, {}, [], [], True, labels)
    for key in VENDOR_ASSETS:
        assert f'integrity="{SRI[key]}"' not in vendor_html


# -- gitlinks.py: citation <a href> escaping + slug validation -----------------

def test_rewrite_citation_links_escapes_malicious_base():
    malicious_base = 'https://github.com/o/r/blob/deadbeef" onmouseover="alert(1)'
    md = "See [helper](src/a.py#L1-L2) for details."
    out = rewrite_citation_links(md, malicious_base)

    assert 'onmouseover="alert(1)"' not in out, "base must not add a live extra attribute"
    assert (
        '<a href="https://github.com/o/r/blob/deadbeef&quot; onmouseover=&quot;alert(1)'
        '/src/a.py#L1-L2" target="_blank" rel="noopener">helper</a>' in out
    )


def test_github_slug_rejects_html_metacharacters_in_repo_name():
    assert _github_slug('https://github.com/owner/repo"><script>alert(1)</script>') is None
    assert _github_slug("https://github.com/owner/repo.name-1_2") == "owner/repo.name-1_2"
    assert _github_slug("git@github.com:Owner-Name/Repo_Name.git") == "Owner-Name/Repo_Name"


# -- gitlinks.py: citations_safe untracked-cited-file rule ----------------------

def test_citations_safe_rejects_untracked_source_file_outside_output_dir():
    # An untracked SOURCE file could be exactly what a citation points at, and it would
    # not exist in the pushed commit -- that must NOT be treated as harmless.
    porcelain = "?? src/new_module.py\n"
    ok, why = citations_safe(porcelain, "origin/main", out_rel="docs/wiki")
    assert ok is False
    assert why == "working tree dirty"


def test_citations_safe_allows_untracked_entries_under_the_output_dir():
    porcelain = "?? docs/wiki/page.md\n?? docs/wiki/plan.json\n"
    ok, why = citations_safe(porcelain, "origin/main", out_rel="docs/wiki")
    assert (ok, why) == (True, None)


def test_citations_safe_defaults_to_dirty_for_untracked_without_out_rel():
    porcelain = "?? docs/wiki/page.md\n"
    ok, why = citations_safe(porcelain, "origin/main")
    assert ok is False
    assert why == "working tree dirty"


# -- backend.py: codex read-boundary warning ------------------------------------

def test_codex_backend_emits_read_boundary_warning_once(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("REPODOCS_BACKEND", "codex")
    monkeypatch.delenv("REPODOCS_MODEL", raising=False)
    monkeypatch.setattr(backend_mod, "_CODEX_READ_WARNING_SHOWN", False)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(backend_mod.subprocess, "run", fake_run)

    backend_mod.run_llm(tmp_path, "hello")
    err = capsys.readouterr().err
    assert "read-only" in err
    assert "does NOT restrict reads" in err
    assert "untrusted repositories" in err

    backend_mod.run_llm(tmp_path, "hello again")
    assert capsys.readouterr().err == "", "the warning must only print once per process"
