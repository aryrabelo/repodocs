"""Regression tests for the cubic-review fixes in repodocs.generate (PR #2)."""

import json
import subprocess

import repodocs.generate as gen
from repodocs.generate import _gitignore_notice, decide_page, page_prompt


def _fake_parallel_llm(repo, items, on_submit):
    """Stand-in for backend.parallel_llm: never spawns a real LLM subprocess."""
    for slug, _prompt in items:
        on_submit(slug)
        yield slug, subprocess.CompletedProcess(args=[], returncode=0, stdout=f"# {slug}\n")


# --- P0: unsafe slug from a hand-edited plan.json (commentId 3625776433) ---------------

def test_safe_page_rejects_traversal_slug(tmp_path, capsys):
    out = tmp_path / "out"
    out.mkdir()

    assert gen._safe_page({"slug": "../evil"}, out) is False
    assert "unsafe slug" in capsys.readouterr().err
    assert gen._safe_page({"slug": "good-page"}, out) is True


def test_reject_unsafe_slug_writes_nothing_outside_out(tmp_path, monkeypatch):
    # Bypass plan.py's own validate_pages by calling cmd_generate against a plan
    # list that already slipped an unsafe slug through -- generate.py must not
    # trust its input and must still refuse to write outside `out`.
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n")
    out = repo / "graphify-wiki"
    out.mkdir()
    monkeypatch.setattr(gen, "parallel_llm", _fake_parallel_llm)
    monkeypatch.setattr(gen, "load_plan", lambda repo, out, allow_omp=True: [
        {"slug": "../evil", "title": "Evil", "purpose": "p", "files": []},
        {"slug": "good-page", "title": "Good", "purpose": "p", "files": ["README.md"]},
    ])

    rc = gen.cmd_generate(repo, out, only=None, dry_run=False, force=True)

    assert rc == 0
    assert not (repo / "evil.md").exists()  # out/"../evil.md" normalizes to repo/evil.md
    assert not any(repo.rglob("evil.md"))
    assert (out / "good-page.md").is_file()


# --- P1: candidate path escaping the repo (commentId 3625776464) -----------------------

def test_decide_page_skips_escaping_candidate_before_hashing(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("x = 1\n")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "escape.py").symlink_to(outside / "secret.py")
    (repo / "real.py").write_text("y = 2\n")
    out = repo / "wiki"
    page = {"slug": "p", "files": ["escape.py", "../outside/secret.py", "real.py"]}

    action, _reason, current = decide_page(repo, out, page, {}, False)

    assert "escape.py" not in current
    assert "../outside/secret.py" not in current
    assert set(current) == {"real.py"}
    assert action == "generate"


# --- P1: graph hint must not follow an escaping symlink (commentId 3625776503) ---------

def test_page_prompt_omits_hint_for_escaping_graph_symlink(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "graph.json").write_text("{}")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "graphify-out").mkdir()
    (repo / "graphify-out" / "graph.json").symlink_to(outside / "graph.json")
    page = {"slug": "s", "title": "T", "purpose": "p", "files": []}

    prompt = page_prompt(page, repo)

    assert "graphify-out/graph.json" not in prompt


def test_page_prompt_includes_hint_for_real_in_repo_graph(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "graphify-out").mkdir()
    (repo / "graphify-out" / "graph.json").write_text("{}")
    page = {"slug": "s", "title": "T", "purpose": "p", "files": []}

    prompt = page_prompt(page, repo)

    assert "graphify-out/graph.json" in prompt


# --- P2: corrupt .hashes.json record must regenerate, not crash (commentId 3625776625) --

def test_decide_page_corrupt_hash_record_falls_back_to_regenerate(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("a = 1\n")
    out = repo / "wiki"
    out.mkdir()
    (out / "p.md").write_text("stale\n")
    page = {"slug": "p", "files": ["a.py"]}

    action, _reason, _current = decide_page(repo, out, page, {"p": "not-a-dict"}, False)
    assert action == "generate"

    action2, _reason2, _current2 = decide_page(repo, out, page, {"p": {"files": "not-a-dict"}}, False)
    assert action2 == "generate"


# --- P2: index.md must list the full plan, not a --pages subset (commentId 3625776569) --

def test_index_includes_full_plan_when_pages_filtered(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hi\n")
    out = repo / "wiki"
    out.mkdir()
    (out / "plan.json").write_text(json.dumps([
        {"slug": "alpha", "title": "Alpha", "purpose": "p", "files": ["README.md"]},
        {"slug": "beta", "title": "Beta", "purpose": "p", "files": ["README.md"]},
    ]))
    (out / "alpha.md").write_text("already generated in an earlier run\n")
    monkeypatch.setattr(gen, "parallel_llm", _fake_parallel_llm)

    rc = gen.cmd_generate(repo, out, only={"beta"}, dry_run=False, force=True)

    assert rc == 0
    assert (out / "beta.md").is_file()
    index = (out / "index.md").read_text()
    assert "Alpha" in index and "alpha.md" in index
    assert "Beta" in index and "beta.md" in index


# --- P2: out == repo must not IndexError (commentId 3625776604) ------------------------

def test_gitignore_notice_out_equals_repo_does_not_raise(tmp_path):
    _gitignore_notice(tmp_path, tmp_path)  # rel.parts is empty; must return, not crash
