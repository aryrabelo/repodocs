"""Regression tests for the translate.py / citations.py cubic review fixes."""

import json
import subprocess

import pytest

import repodocs.citations as citations_mod
import repodocs.translate as translate_mod


# -- translate.py -------------------------------------------------------------

def test_localize_headings_skips_fenced_code_but_translates_real_h2():
    md = (
        "# Page\n"
        "```\n"
        "## Relevant source files\n"
        "```\n"
        "\n"
        "## Relevant source files\n"
        "\n"
        "- a.py\n"
    )
    result = translate_mod.localize_headings(md, "pt")
    lines = result.split("\n")
    assert lines[2] == "## Relevant source files", "heading text inside a fence must survive untouched"
    assert lines[5] == "## Arquivos-fonte relevantes", "the real H2 outside the fence must be translated"


def test_localize_headings_untouched_when_only_inside_fence():
    md = "```\n## Relevant source files\n```\n"
    assert translate_mod.localize_headings(md, "pt") == md


def test_translate_plan_file_rejects_non_list_json(tmp_path, monkeypatch):
    src = tmp_path / "plan.json"
    src.write_text("null")
    dest = tmp_path / "plan.pt.json"
    called = []
    monkeypatch.setattr(translate_mod, "run_llm", lambda *a, **k: called.append(1))
    ok = translate_mod.translate_plan_file(tmp_path, src, dest, "pt")
    assert ok is False, "a null plan.json must fall back, not crash"
    assert dest.read_text() == "null", "fallback must copy the untranslated (invalid) plan verbatim"
    assert not called, "a non-list plan.json must never reach the LLM call"


@pytest.mark.parametrize("bad_lang", ["..", ".", "../x", "a/b", "/etc"])
def test_cmd_translate_rejects_path_like_lang(tmp_path, bad_lang):
    repo = tmp_path / "repo"
    repo.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    (out / "page.md").write_text("# T\n\nProse.\n")
    with pytest.raises(SystemExit) as exc:
        translate_mod.cmd_translate(repo, out, bad_lang, None, False)
    assert exc.value.code == 1


def test_cmd_translate_propagates_plan_translation_failure(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    (out / "page.md").write_text("# T\n\nProse.\n")
    (out / "plan.json").write_text(
        json.dumps([{"slug": "page", "title": "T", "purpose": "p", "files": []}])
    )
    dest = out / "pt"
    dest.mkdir()
    # already translated -> phase-1 skip, so no page.md needs an LLM call at all
    (dest / "page.md").write_text("# T\n\nProse.\n")

    def failing_run_llm(repo_, prompt):
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(translate_mod, "run_llm", failing_run_llm)
    rc = translate_mod.cmd_translate(repo, out, "pt", None, False)
    assert rc == 1, "plan.json translation failure must make cmd_translate return nonzero"
    assert (dest / "plan.json").read_text() == (out / "plan.json").read_text(), "fallback copy still written"


def test_cmd_translate_blocks_dropped_citation(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    (out / "page.md").write_text("# T\n\nProse.\n\nSources: [a.py:L1-L1](a.py#L1-L1)\n")

    def fake_parallel_llm(repo_, items, on_submit):  # never calls a real LLM
        for name, _prompt in items:
            on_submit(name)
            yield name, subprocess.CompletedProcess(
                args=[], returncode=0, stdout="# T\n\nProse traduzida sem fonte.\n", stderr=""
            )

    monkeypatch.setattr(translate_mod, "parallel_llm", fake_parallel_llm)
    with pytest.raises(SystemExit) as exc:
        translate_mod.cmd_translate(repo, out, "pt", None, False)
    assert exc.value.code == 1, "a translation that dropped the Sources citation must block, not silently pass"


def test_cmd_translate_allows_translation_that_keeps_citation(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    (out / "page.md").write_text("# T\n\nProse.\n\nSources: [a.py:L1-L1](a.py#L1-L1)\n")

    def fake_parallel_llm(repo_, items, on_submit):
        for name, _prompt in items:
            on_submit(name)
            yield name, subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout="# T\n\nProse traduzida.\n\nSources: [a.py:L1-L1](a.py#L1-L1)\n", stderr="",
            )

    monkeypatch.setattr(translate_mod, "parallel_llm", fake_parallel_llm)
    rc = translate_mod.cmd_translate(repo, out, "pt", None, False)
    assert rc == 0
    assert "Sources: [a.py:L1-L1](a.py#L1-L1)" in (out / "pt" / "page.md").read_text()


# -- citations.py -------------------------------------------------------------

def test_requires_evidence_still_exempts_relevant_source_files_list():
    md = "# T\n\n## Relevant source files\n\n- a.py\n- b.py\n"
    assert citations_mod.requires_evidence(md) is False


def test_requires_evidence_flags_body_list_outside_relevant_source_files():
    md = "# T\n\n- item one\n- item two\n"
    assert citations_mod.requires_evidence(md) is True


def test_citation_problems_flags_all_bullets_page_with_no_citation(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    (out / "allbullets.md").write_text("# T\n\n- item one\n- item two\n")
    problems = citations_mod.citation_problems(repo, [out / "allbullets.md"])
    names = {p[0] for p in problems}
    assert "allbullets.md" in names, problems


def test_citation_problems_rejects_unlinked_citation_like_label(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x=1\n" * 5)
    out = tmp_path / "out"
    out.mkdir()
    md = (
        "# T\n\nProse.\n\n"
        "Sources: [a.py:L1-L2](a.py#L1-L2)\n\n"
        "See also [a.py:L3-L4] for more detail.\n"
    )
    (out / "page.md").write_text(md)
    problems = citations_mod.citation_problems(repo, [out / "page.md"])
    bad = [(c, why) for _page, c, why in problems if c == "[a.py:L3-L4]"]
    assert bad, problems
    assert "no linked href" in bad[0][1]


def test_citation_problems_ignores_citation_hidden_in_code_and_comments(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x=1\n" * 5)
    out = tmp_path / "out"
    out.mkdir()
    md = (
        "# T\n\nSome unsourced prose.\n\n"
        "<!-- Sources: [a.py:L1-L2](a.py#L1-L2) -->\n\n"
        "```\nSources: [a.py:L1-L2](a.py#L1-L2)\n```\n"
    )
    (out / "page.md").write_text(md)
    problems = citations_mod.citation_problems(repo, [out / "page.md"])
    names = {p[0] for p in problems}
    assert "page.md" in names, "a citation hidden in code/comments must not satisfy the citation gate"


def test_citation_problems_accepts_real_rendered_citation(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x=1\n" * 5)
    out = tmp_path / "out"
    out.mkdir()
    md = "# T\n\nProse.\n\nSources: [a.py:L1-L2](a.py#L1-L2)\n"
    (out / "page.md").write_text(md)
    problems = citations_mod.citation_problems(repo, [out / "page.md"])
    assert problems == []
