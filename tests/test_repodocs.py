"""Test suite for repodocs (ported from the former in-module selftest)."""

import json
import os
import re
import shutil
import subprocess
import tempfile

from pathlib import Path

import repodocs.plan as plan_mod
import repodocs.render as render_mod
from repodocs import VERSION
from repodocs._util import safe_repo_file
from repodocs.backend import DEFAULT_CLAUDE_MODEL, backend_contract, backend_name, effective_model, jobs_count
from repodocs.citations import CITATION_RE, citation_error, citation_problems, requires_evidence, wiki_content_pages
from repodocs.cli import setup_install
from repodocs.generate import compute_file_hash, decide_page, generate_decision
from repodocs.gitlinks import _github_slug, citations_safe, rewrite_citation_links, wiki_remote_url
from repodocs.plan import graph_digest, llm_plan, parse_pages, plan_fingerprint, plan_pages, planner_prompt, validate_pages
from repodocs.publish import WikiNotInitialized, WikiPublishError, publish_branch_safe, publish_wiki_push, stage_publish, stage_wiki, staged_secret_findings
from repodocs.render import LANG_LABELS, THIRD_PARTY_NOTICES, build_html, group_pages, lang_labels
from repodocs.scan import scan, scan_inventory
from repodocs.translate import translate_prompt


def _raises(fn, *a):
    try:
        fn(*a)
    except ValueError:
        return True
    raise AssertionError("expected ValueError")


def _raises_exit(fn, *a):
    try:
        fn(*a)
    except SystemExit as e:
        return e.code != 0
    raise AssertionError("expected SystemExit")


def selftest():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        for rel, body in {
            "README.md": "# demo\n\n## Installation\nrun it\n", "pyproject.toml": "[project]\n",
            "CHANGELOG.md": "# Changelog\n", "src/core.py": "x=1\n" * 120, "src/util.py": "y=2\n" * 30,
            "tests/test_core.py": "def test_x():\n    assert True\n", ".github/workflows/ci.yml": "name: ci\n",
        }.items():
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(body)

        slugs = [p["slug"] for p in plan_pages(repo, scan(repo))]
        for expect in ("overview", "installation", "architecture", "development", "changelog"):
            assert expect in slugs, f"missing {expect} in {slugs}"
        assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION), VERSION
        assert slugs[0] == "overview" and any(s.startswith("component-") for s in slugs), slugs
        inv = scan_inventory(repo)
        assert "## Installation" in inv["readme_headings"] and inv["source_file_count"] == 3, inv

        raw = [
            {"slug": "overview", "title": "O", "files": ["README.md"]},
            {"slug": "Bad Slug", "files": []},  # bad slug -> drop
            "not a dict",                       # -> drop
            {"slug": "dup"}, {"slug": "dup"},   # dup -> one
            {"slug": "ghost", "files": ["nope.txt"]},  # kept, falls back to README
        ]
        vp = validate_pages(repo, raw)
        assert [p["slug"] for p in vp] == ["overview", "dup", "ghost"], vp
        assert vp[0]["files"] == ["README.md"] and vp[2]["files"] == ["README.md"], vp
        assert _raises(validate_pages, repo, {"not": "a list"})

    assert parse_pages('```json\n[{"slug":"a","title":"A","files":[]}]\n```')[0]["slug"] == "a"
    assert _raises(parse_pages, "no array here")

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "big.py").write_text("z=0\n" * 150)
        (repo / "small.py").write_text("z=0\n" * 5)
        slugs = [p["slug"] for p in plan_pages(repo, scan(repo))]
        assert "component-big" in slugs and "component-small" not in slugs, slugs

    m = list(CITATION_RE.finditer("[src/core.py:L1-L20](src/core.py#L1-L20) [a.py:L3-L3](a.py#L3-L3)"))
    assert len(m) == 2 and m[0].group(1) == "src/core.py", m
    assert not CITATION_RE.search("plain [link](foo.md)"), "should not match plain links"

    # hash helper: known content -> known sha256
    with tempfile.TemporaryDirectory() as td:
        fp = Path(td) / "h.txt"
        fp.write_bytes(b"hello")
        assert compute_file_hash(fp) == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    # generate_decision: pure skip/regenerate logic
    assert generate_decision(False, {}, {"a.py": "h"}) == ("generate", "new")
    assert generate_decision(True, {"a.py": "h"}, {"a.py": "h"}) == ("skip", "unchanged")
    assert generate_decision(True, {"a.py": "h"}, {"a.py": "H"})[0] == "generate"
    assert generate_decision(True, {}, {"a.py": "h"})[1].endswith("(added)")
    assert generate_decision(True, {"a.py": "h"}, {})[1].endswith("(removed)")

    # plan idempotency: skip on matching fingerprint, replan on change, never cache fallback
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "README.md").write_text("# X\n")
        (repo / "a.py").write_text("x = 1\n")
        out = repo / "repo-docs"
        out.mkdir()
        fp = plan_fingerprint(planner_prompt(repo, scan_inventory(repo)))
        (out / "plan.json").write_text('[{"slug":"overview","title":"O","purpose":"p","files":["README.md"]}]\n')
        (out / ".plan.hash").write_text(fp + "\n")
        real_run_llm, calls = plan_mod.run_llm, []
        def _planner_down(*a, **k):  # records the attempt; llm_plan catches this and falls back
            calls.append(1)
            raise FileNotFoundError("backend missing")
        plan_mod.run_llm = _planner_down
        try:
            pages = llm_plan(repo, out)  # unchanged inventory -> reuse plan.json, zero omp calls
            assert pages and pages[0]["slug"] == "overview" and not calls, (pages, calls)
            (repo / "b.py").write_text("y = 2\n")  # inventory changed -> planner attempted (down -> heuristic)
            pages = llm_plan(repo, out)
            assert calls == [1] and pages, (calls, pages)
            assert not (out / ".plan.hash").is_file(), "fallback must not cache a fingerprint"
            llm_plan(repo, out)  # post-fallback run must retry the LLM, not trust the fallback plan
            assert calls == [1, 1], f"expected planner retry after fallback, got {calls}"
        finally:
            plan_mod.run_llm = real_run_llm

    # graph_digest: optional graphify graph -> compact prompt block; "" when absent
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        assert graph_digest(repo) == "", "no graphify-out -> empty digest"
        gdir = repo / "graphify-out"
        gdir.mkdir()
        (gdir / "graph.json").write_text("not json")
        assert graph_digest(repo) == "", "corrupt graph.json -> empty digest"
        (gdir / "graph.json").write_text(json.dumps({
            "nodes": [
                {"id": "a", "label": "CoreThing", "source_file": "src/core.py"},
                {"id": "b", "label": "helper", "source_file": "src/util.py"},
            ],
            "links": [
                {"source": "a", "target": "b", "relation": "imports"},
                {"source": "a", "target": "b", "relation": "calls"},
            ],
        }))
        d = graph_digest(repo)
        assert "CoreThing" in d and "src/util.py (imported 1x)" in d, d
        assert "PREFER this over" in d

    # decide_page: memoizes file hashes across pages via shared hcache
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "shared.py").write_text("s = 1\n")
        out = repo / "repo-docs"
        out.mkdir()
        hcache: dict = {}
        p1 = {"slug": "one", "files": ["shared.py"]}
        p2 = {"slug": "two", "files": ["shared.py"]}
        a1 = decide_page(repo, out, p1, {}, False, hcache)
        assert a1[0] == "generate" and "shared.py" in a1[2], a1
        assert hcache["shared.py"] == a1[2]["shared.py"]
        (repo / "shared.py").write_text("s = 2\n")  # mutate AFTER caching: memoized value must win
        a2 = decide_page(repo, out, p2, {}, False, hcache)
        assert a2[2]["shared.py"] == a1[2]["shared.py"], "hcache must be reused across pages"

    # html builder: embeds page title, works from a generated output dir
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        (out / "overview.md").write_text("# Over\nbody\n")
        (out / "index.md").write_text("# nav\n")  # must be excluded
        (out / "plan.json").write_text('[{"slug":"overview","title":"Overview Page","files":[]}]')
        dest = build_html(Path(td), out)
        html = dest.read_text()
        assert "Overview Page" in html and '"md":' in html, "title/markdown not embedded"
        assert '"index":' not in html, "index.md leaked into viewer"
        assert _raises_exit(build_html, Path(td), Path(td) / "empty")

    # vendor_assets network failure -> friendly die(), not a raw traceback
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        (out / "overview.md").write_text("# Over\nbody\n")
        (out / "plan.json").write_text('[{"slug":"overview","title":"Overview Page","files":[]}]')
        real_vendor_assets = render_mod.vendor_assets
        def _vendor_down(_out):
            raise OSError("Name or service not known")
        render_mod.vendor_assets = _vendor_down
        try:
            assert _raises_exit(build_html, Path(td), out, True)
        finally:
            render_mod.vendor_assets = real_vendor_assets

    # github slug parsing (both remote forms, no subprocess)
    assert _github_slug("git@github.com:aryrabelo/planqueue.git") == "aryrabelo/planqueue"
    assert _github_slug("https://github.com/aryrabelo/planqueue.git") == "aryrabelo/planqueue"
    assert _github_slug("https://github.com/o/r") == "o/r"
    assert _github_slug("git@gitlab.com:o/r.git") is None

    # citation link rewrite to github blob URLs
    base = "https://github.com/o/r/blob/deadbeef"
    out_md = rewrite_citation_links("see [core.py:L1-L5](src/core.py#L1-L5)", base)
    assert 'href="https://github.com/o/r/blob/deadbeef/src/core.py#L1-L5"' in out_md and 'target="_blank"' in out_md
    assert rewrite_citation_links("[x](src/core.py#L1-L5)", None) == "[x](src/core.py#L1-L5)"
    assert rewrite_citation_links("[plain](foo.md)", base) == "[plain](foo.md)"

    # citation link rewrite: text/path are escaped so untrusted markdown
    # cannot inject attributes or tags into the generated <a>
    injected = rewrite_citation_links('[<b>bold</b>](evil"onmouseover="x.py#L1-L2)', base)
    assert "<b>bold</b>" not in injected and "&lt;b&gt;bold&lt;/b&gt;" in injected, injected
    assert '"onmouseover="' not in injected and "%22onmouseover%3D%22" in injected, injected

    # citation-safety guard (pure, no subprocess). Untracked ("??") entries are harmless
    # ONLY under out_rel (generated output); any other untracked path is dirty (fail-safe).
    assert citations_safe("", " origin/main\n") == (True, None)
    assert citations_safe("?? repo-docs/x.md\n", " origin/main\n", "repo-docs") == (True, None)
    assert citations_safe("?? new.md\n", " origin/main\n")[0] is False  # untracked, no out_rel -> dirty
    assert citations_safe(" M repodocs\n", " origin/main\n")[0] is False
    assert citations_safe("", "")[1] == "HEAD not pushed"
    assert citations_safe(" M x\n", "")[1] == "working tree dirty"
    assert citations_safe("?? only-untracked\n", "")[1] == "working tree dirty"

    # deterministic nav grouping
    g = group_pages(["overview", "prompt-queue", "architecture", "interop-x", "testing", "limitations"])
    gmap = {x["name"]: x["slugs"] for x in g}
    assert gmap["Overview"] == ["overview", "limitations"], gmap
    assert gmap["Features"] == ["prompt-queue"], gmap
    assert gmap["Reference"] == ["architecture", "interop-x"], gmap
    assert gmap["Development"] == ["testing"], gmap
    assert [x["name"] for x in g] == ["Overview", "Features", "Reference", "Development"], g

    # translation prompt preserves the input md verbatim + names the target language
    src = "# Title\n\nProse.\n\n```py\ncode\n```\n\nSources: [a.py:L1-L2](a.py#L1-L2)\n"
    tp = translate_prompt(src, "pt")
    assert src in tp and "Brazilian Portuguese" in tp, "prompt must embed md + target lang"
    assert "Sources:" in tp

    # ui label lookup by out-dir name (english fallback)
    assert lang_labels("pt")["github"] == "Ver no GitHub"
    assert lang_labels("pt")["groups"]["Overview"] == "Visão Geral"
    assert lang_labels("repo-docs") == LANG_LABELS["en"]
    assert lang_labels("zz")["toc"] == "On this page"

    # REPODOCS_JOBS parsing/clamping (default 4, 1..16, bad -> 4)
    _prev = os.environ.get("REPODOCS_JOBS")
    try:
        for val, want in [("6", 6), ("1", 1), ("0", 1), ("99", 16), ("abc", 4)]:
            os.environ["REPODOCS_JOBS"] = val
            assert jobs_count() == want, (val, jobs_count())
        os.environ.pop("REPODOCS_JOBS", None)
        assert jobs_count() == 4
    finally:
        if _prev is None:
            os.environ.pop("REPODOCS_JOBS", None)
        else:
            os.environ["REPODOCS_JOBS"] = _prev

    # backend selection + effective model resolution + vendored contract loading
    # (pure; no CLI calls)
    _prev_backend = os.environ.get("REPODOCS_BACKEND")
    _prev_model = os.environ.get("REPODOCS_MODEL")
    try:
        os.environ.pop("REPODOCS_BACKEND", None)
        os.environ.pop("REPODOCS_MODEL", None)
        assert backend_name() == "claude"  # no-env default
        assert effective_model() == DEFAULT_CLAUDE_MODEL

        for value in ("omp", "claude", "codex"):
            os.environ["REPODOCS_BACKEND"] = value
            assert backend_name() == value
        os.environ["REPODOCS_BACKEND"] = "invalid"
        assert _raises(backend_name)

        os.environ.pop("REPODOCS_MODEL", None)
        os.environ["REPODOCS_BACKEND"] = "omp"
        assert effective_model() is None  # omp never inherits the claude default
        os.environ["REPODOCS_BACKEND"] = "codex"
        assert effective_model() is None  # codex never inherits the claude default
        os.environ["REPODOCS_BACKEND"] = "claude"
        assert effective_model() == DEFAULT_CLAUDE_MODEL

        os.environ["REPODOCS_MODEL"] = "custom-model"
        for value in ("omp", "claude", "codex"):
            os.environ["REPODOCS_BACKEND"] = value
            assert effective_model() == "custom-model"  # explicit override always wins

        planner_contract = backend_contract("Plan the wiki pages for x")
        writer_contract = backend_contract("Write the wiki page `x`")
        assert "wiki-planner" in planner_contract and "wiki-writer" in writer_contract
    finally:
        if _prev_backend is None:
            os.environ.pop("REPODOCS_BACKEND", None)
        else:
            os.environ["REPODOCS_BACKEND"] = _prev_backend
        if _prev_model is None:
            os.environ.pop("REPODOCS_MODEL", None)
        else:
            os.environ["REPODOCS_MODEL"] = _prev_model

    # publish staging (pure fs; no git/network)
    with tempfile.TemporaryDirectory() as td:
        o = Path(td) / "repo-docs"
        (o / "assets").mkdir(parents=True)
        (o / "wiki.html").write_text("<html>")
        (o / "overview.md").write_text("# o")
        (o / "plan.json").write_text("[]")
        (o / "assets" / "marked.min.js").write_text("x")
        pt = o / "pt"
        (pt / "assets").mkdir(parents=True)
        (pt / "wiki.html").write_text("<html>")
        (pt / "overview.md").write_text("# o")
        (pt / "assets" / "m.js").write_text("x")
        st = Path(td) / "stage"
        staged = stage_publish(o, st)
        for expect in ("index.html", "pt/index.html", ".nojekyll",
                       "assets/marked.min.js", "pt/assets/m.js", "overview.md", "plan.json"):
            assert expect in staged, (expect, staged)
        assert not staged_secret_findings(st)
        (st / "leak.md").write_text("token: github_pat_" + "A" * 24)
        findings = staged_secret_findings(st)
        assert findings and findings[0][0] == "leak.md" and findings[0][2] == "GitHub token"
        assert publish_branch_safe("gh-pages")
        assert not publish_branch_safe("main") and not publish_branch_safe("MASTER")
        assert (st / "index.html").is_file() and (st / ".nojekyll").is_file()
    # wiki staging (pure fs; no git/network): Home mapping, Sidebar order/title,
    # absolute citation rewrite, index exclusion, secret-guard compatibility
    with tempfile.TemporaryDirectory() as td:
        o = Path(td) / "repo-docs"
        o.mkdir()
        (o / "overview.md").write_text("# Overview\nsee [core.py:L1-L2](src/core.py#L1-L2)\n")
        (o / "testing.md").write_text("# Testing\nbody\n")
        (o / "ghost.md").write_text("# Ghost\nbody\n")  # not in plan.json -> falls back to md_title
        (o / "index.md").write_text("# nav\n")  # never staged as a page
        (o / "plan.json").write_text(json.dumps([
            {"slug": "overview", "title": "Overview"},
            {"slug": "testing", "title": "Testing Guide"},
        ]))
        st = Path(td) / "wikistage"
        base = "https://github.com/o/r/blob/deadbeef"
        staged = stage_wiki(o, st, base)
        assert staged == sorted(["Home.md", "testing.md", "ghost.md", "_Sidebar.md"]), staged
        assert "index.md" not in staged and not (st / "index.md").exists()
        home = (st / "Home.md").read_text()
        assert 'href="https://github.com/o/r/blob/deadbeef/src/core.py#L1-L2"' in home, home
        sidebar = (st / "_Sidebar.md").read_text()
        assert sidebar.index("Home") < sidebar.index("Testing Guide") < sidebar.index("Ghost"), sidebar
        assert "[Testing Guide](testing)" in sidebar and "[Ghost](ghost)" in sidebar, sidebar
        assert not staged_secret_findings(st)
        (st / "leak.md").write_text("key: AKIA" + "A" * 16)
        findings = staged_secret_findings(st)
        assert findings and findings[0][0] == "leak.md" and findings[0][2] == "cloud/API key", findings

    # wiki staging: index.md is the fallback Home source when overview.md is absent
    with tempfile.TemporaryDirectory() as td:
        o = Path(td) / "repo-docs"
        o.mkdir()
        (o / "index.md").write_text("# nav-as-home\n")
        st = Path(td) / "wikistage2"
        staged = stage_wiki(o, st, None)
        assert staged == ["Home.md", "_Sidebar.md"], staged
        assert (st / "Home.md").read_text() == "# nav-as-home\n"

    # stage_publish / stage_wiki reject symlinked source files before any read or copy
    with tempfile.TemporaryDirectory() as td:
        outside = Path(td) / "outside.md"
        outside.write_text("top secret\n")

        o = Path(td) / "repo-docs"
        o.mkdir()
        (o / "wiki.html").write_text("<html>")
        (o / "plan.json").write_text("[]")
        (o / "overview.md").symlink_to(outside)
        st = Path(td) / "stage"
        try:
            stage_publish(o, st)
            raise AssertionError("expected symlink rejection")
        except ValueError as ex:
            assert "overview.md" in str(ex) and "top secret" not in str(ex), ex

        o2 = Path(td) / "repo-docs2"
        o2.mkdir()
        (o2 / "overview.md").symlink_to(outside)
        st2 = Path(td) / "stage2"
        try:
            stage_wiki(o2, st2, None)
            raise AssertionError("expected symlink rejection")
        except ValueError as ex:
            assert "Home.md" in str(ex) and "top secret" not in str(ex), ex

    # wiki remote URL: same scheme (ssh/https) as origin, github-only
    assert wiki_remote_url("git@github.com:aryrabelo/planqueue.git") == "git@github.com:aryrabelo/planqueue.wiki.git"
    assert wiki_remote_url("https://github.com/aryrabelo/planqueue.git") == "https://github.com/aryrabelo/planqueue.wiki.git"
    assert wiki_remote_url("https://github.com/o/r") == "https://github.com/o/r.wiki.git"
    assert wiki_remote_url("git@gitlab.com:o/r.git") is None

    # publish_wiki_push orchestration against a local bare git remote (no network)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        env_keys = ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL")
        _prev_git_env = {k: os.environ.get(k) for k in env_keys}
        os.environ.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})

        def _git(*args, cwd):
            r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
            assert r.returncode == 0, (args, r.stdout, r.stderr)
            return r

        def _seed_bare(name: str, content: str) -> Path:
            seed = tmp / f"{name}-seed"
            seed.mkdir()
            _git("init", cwd=seed)
            (seed / "Home.md").write_text(content)
            _git("add", "-A", cwd=seed)
            _git("commit", "-m", "seed", cwd=seed)
            bare = tmp / f"{name}.git"
            _git("clone", "--bare", str(seed), str(bare), cwd=tmp)
            return bare

        try:
            # 1. clone failure classification: no repo at the target path -> WikiNotInitialized
            missing = tmp / "does-not-exist"
            staging1 = tmp / "staging1"
            staging1.mkdir()
            (staging1 / "Home.md").write_text("x\n")
            try:
                publish_wiki_push(str(missing), ["Home.md"], staging1)
                raise AssertionError("expected WikiNotInitialized")
            except WikiNotInitialized:
                pass

            # 2. no-change: staged content identical to the wiki's -> None, nothing pushed
            bare2 = _seed_bare("nochange", "same\n")
            staging2 = tmp / "staging2"
            staging2.mkdir()
            (staging2 / "Home.md").write_text("same\n")
            assert publish_wiki_push(str(bare2), ["Home.md"], staging2) is None

            # 3. normal commit/push path: staged content differs -> commits, pushes, returns a sha
            bare3 = _seed_bare("normal", "old\n")
            staging3 = tmp / "staging3"
            staging3.mkdir()
            (staging3 / "Home.md").write_text("new\n")
            sha = publish_wiki_push(str(bare3), ["Home.md"], staging3)
            assert sha and re.fullmatch(r"[0-9a-f]{40,64}", sha), sha
            pushed = _git("show", f"{sha}:Home.md", cwd=bare3).stdout
            assert pushed == "new\n", pushed

            # 4. generic push failure (pre-receive hook rejects; still offline) -> WikiPublishError,
            #    bounded message, never a raw CalledProcessError with the command argv
            bare4 = _seed_bare("pushfail", "old\n")
            hook = bare4 / "hooks" / "pre-receive"
            hook.write_text("#!/bin/sh\nexit 1\n")
            hook.chmod(0o755)
            staging4 = tmp / "staging4"
            staging4.mkdir()
            (staging4 / "Home.md").write_text("new\n")
            try:
                publish_wiki_push(str(bare4), ["Home.md"], staging4)
                raise AssertionError("expected WikiPublishError")
            except WikiPublishError as ex:
                assert "push" in str(ex).lower(), ex
                assert "Command '" not in str(ex), "must not embed a raw CalledProcessError"
        finally:
            for k, v in _prev_git_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    # setup_install: fresh / identical / differs-kept / force-overwrite (tempdirs, no HOME)
    with tempfile.TemporaryDirectory() as td:
        src, dst = Path(td) / "src", Path(td) / "dst"
        (src / "agents").mkdir(parents=True)
        (src / "AGENTS.md").write_bytes(b"A\n")
        (src / "agents" / "w.md").write_bytes(b"W\n")
        acts = dict(setup_install(src, dst, force=False))
        assert acts == {"AGENTS.md": "installed", "agents/w.md": "installed"}, acts
        assert (dst / "AGENTS.md").read_bytes() == b"A\n"
        assert dict(setup_install(src, dst, force=False))["AGENTS.md"] == "up to date"
        (dst / "AGENTS.md").write_bytes(b"LOCAL\n")
        acts = dict(setup_install(src, dst, force=False))
        assert acts["AGENTS.md"].startswith("differs"), acts
        assert (dst / "AGENTS.md").read_bytes() == b"LOCAL\n", "must keep local without --force"
        acts = dict(setup_install(src, dst, force=True))
        assert acts["AGENTS.md"] == "overwritten", acts
        assert (dst / "AGENTS.md").read_bytes() == b"A\n", "--force must overwrite"

    # ---- security regressions ------------------------------------------------
    # safe_repo_file: rejects traversal/absolute/NUL/symlink-escape; accepts in-repo
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "in.py").write_text("x=1\n")
        assert safe_repo_file(repo, "in.py") == (repo / "in.py").resolve()
        assert safe_repo_file(repo, "../outside.py") is None
        assert safe_repo_file(repo, "/etc/passwd") is None
        assert safe_repo_file(repo, "nope.py") is None
        assert safe_repo_file(repo, "bad\x00.py") is None
        outside = Path(td + "-secret")
        outside.mkdir()
        (outside / "secret.txt").write_text("top secret\n")
        try:
            (repo / "escape.py").symlink_to(outside / "secret.txt")
            assert safe_repo_file(repo, "escape.py") is None, "symlink escape must be rejected"
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    # validate_pages drops a traversal file candidate (falls back to README)
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "README.md").write_text("# r\n")
        vp = validate_pages(repo, [{"slug": "x", "files": ["../../../etc/passwd"]}])
        assert vp[0]["files"] == ["README.md"], vp

    # scan self-ingestion: repo-docs/, graphify-out/, and the configured out dir
    # (any name) never appear in source_files; symlink escapes are dropped
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "real.py").write_text("x=1\n")
        for d in ("repo-docs", "graphify-out", "mydocs"):
            (repo / d / "assets").mkdir(parents=True)
            (repo / d / "assets" / "marked.min.js").write_text("VENDORED\n")
            (repo / d / "note.py").write_text("y=2\n")
        outside = Path(td + "-ext")
        outside.mkdir()
        (outside / "leak.py").write_text("secret\n")
        (repo / "link.py").symlink_to(outside / "leak.py")
        try:
            srcs = scan(repo, out=repo / "mydocs")["src_files"]
            assert "real.py" in srcs, srcs
            assert not any(s.startswith(("repo-docs/", "graphify-out/", "mydocs/")) for s in srcs), srcs
            assert "link.py" not in srcs, "symlink escape leaked into scan"
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    # citation gate: valid citation passes; every dishonest form is caught
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "core.py").write_text("z=0\n" * 20)
        assert citation_error(repo, "core.py", 1, 20, "core.py#L1-L20") is None
        assert citation_error(repo, "core.py", 1, 20, "core.py#L1-L19"), "range mismatch"
        assert citation_error(repo, "core.py", 1, 20, "other.py#L1-L20"), "path mismatch"
        assert citation_error(repo, "core.py", 0, 20, "core.py#L0-L20"), "zero start"
        assert citation_error(repo, "core.py", 5, 1, "core.py#L5-L1"), "reversed range"
        assert citation_error(repo, "core.py", 1, 999, "core.py#L1-L999"), "beyond eof"
        assert citation_error(repo, "gone.py", 1, 2, "gone.py#L1-L2"), "missing file"
        assert citation_error(repo, "../esc.py", 1, 2, "../esc.py#L1-L2"), "traversal"
        assert citation_error(repo, "core.py", 1, 20, "not a citation"), "bad href"

    # requires_evidence: prose needs a citation; heading + file list alone does not
    assert requires_evidence("# T\nSome prose.\n") is True
    assert requires_evidence("# T\n\n## Relevant source files\n\n- a.py\n") is False

    # citation_problems: unsourced/invalid content pages block; index.md excluded
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "m.py").write_text("q=1\n" * 10)
        out = repo / "repo-docs"
        out.mkdir()
        (out / "good.md").write_text("# Good\n\nProse.\n\nSources: [m.py:L1-L5](m.py#L1-L5)\n")
        (out / "bare.md").write_text("# Bare\n\nUnsourced prose paragraph.\n")
        (out / "bad.md").write_text("# Bad\n\nProse.\n\nSources: [m.py:L1-L99](m.py#L1-L99)\n")
        (out / "index.md").write_text("# nav\nprose\n")
        names = {p[0] for p in citation_problems(repo, wiki_content_pages(out))}
        assert "good.md" not in names, names
        assert "bare.md" in names and "bad.md" in names, names
        assert "index.md" not in names, "index.md must be excluded"

    # XSS wiring: the built viewer sanitizes markdown with DOMPurify + loads it
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        (out / "overview.md").write_text("# O\nbody\n")
        (out / "plan.json").write_text('[{"slug":"overview","title":"O","files":[]}]')
        html = build_html(Path(td), out).read_text()
        assert "DOMPurify.sanitize(marked.parse(" in html, "viewer must sanitize markdown"
        assert "__DOMPURIFY__" not in html and "purify.min.js" in html, "dompurify asset must be wired"
        assert 'securityLevel: "strict"' in html, "mermaid must run in strict security mode"
        assert "window.DOMPurify" in html and "refusing to render" in html, (
            "must fail closed (not render unsanitized) when the sanitizer fails to load")
        assert html.index("purify.min.js") < html.index("DOMPurify.sanitize("), (
            "DOMPurify must load before it is used by the viewer script")

    # third-party notices name every vendored lib and its real SPDX identifier
    for tok in ("marked", "Mermaid", "highlight.js", "DOMPurify",
                "MIT", "BSD-3-Clause", "Apache-2.0", "MPL-2.0"):
        assert tok in THIRD_PARTY_NOTICES, tok

    print("selftest: ok")


def test_repodocs():
    selftest()
