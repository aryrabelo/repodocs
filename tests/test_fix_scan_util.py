"""Regression tests for cubic review comments on scan.py / _util.py
(PR #2: dangling symlink / FIFO exclusion, nested --out pruning,
escaping metadata symlinks, sorted CI list, safe_repo_file symlink loop)."""

import os

import pytest

from repodocs._util import safe_repo_file
from repodocs.scan import scan


def test_dangling_symlink_excluded_from_src_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "real.py").write_text("print(1)\n")
    (repo / "dangling.py").symlink_to(repo / "missing_target.py")

    facts = scan(repo)

    assert "real.py" in facts["src_files"]
    assert "dangling.py" not in facts["src_files"]
    assert "dangling.py" not in facts["line_counts"]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="platform has no os.mkfifo")
def test_fifo_excluded_from_src_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    os.mkfifo(repo / "pipe.py")

    facts = scan(repo)

    assert "pipe.py" not in facts["src_files"]
    assert "pipe.py" not in facts["line_counts"]


def test_nested_out_prunes_only_out_subtree(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src" / "generated").mkdir(parents=True)
    (repo / "src" / "actual").mkdir(parents=True)
    (repo / "src" / "actual" / "code.py").write_text("x = 1\n")
    (repo / "src" / "generated" / "junk.py").write_text("y = 2\n")

    facts = scan(repo, out=repo / "src" / "generated")

    assert "src/actual/code.py" in facts["src_files"]
    assert "src/generated/junk.py" not in facts["src_files"]


def test_escaping_readme_symlink_dropped(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n")
    (repo / "README.md").symlink_to(outside)

    facts = scan(repo)

    assert facts["has_readme"] is False


def test_escaping_manifest_symlink_dropped(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "package.json"
    outside.write_text("{}\n")
    (repo / "package.json").symlink_to(outside)

    facts = scan(repo)

    assert "package.json" not in facts["manifests"]


def test_escaping_ci_workflow_symlink_dropped(tmp_path):
    repo = tmp_path / "repo"
    wf = repo / ".github" / "workflows"
    wf.mkdir(parents=True)
    outside = tmp_path / "evil.yml"
    outside.write_text("name: evil\n")
    (wf / "evil.yml").symlink_to(outside)
    (wf / "ci.yml").write_text("name: ci\n")

    facts = scan(repo)

    assert facts["ci"] == [".github/workflows/ci.yml"]


def test_ci_workflows_sorted(tmp_path):
    repo = tmp_path / "repo"
    wf = repo / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "zzz.yml").write_text("name: z\n")
    (wf / "aaa.yml").write_text("name: a\n")
    (wf / "mmm.yml").write_text("name: m\n")

    facts = scan(repo)

    assert facts["ci"] == [
        ".github/workflows/aaa.yml",
        ".github/workflows/mmm.yml",
        ".github/workflows/zzz.yml",
    ]


def test_safe_repo_file_returns_none_on_symlink_loop(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    loop = repo / "loop"
    loop.symlink_to(loop)  # self-referencing symlink -> ELOOP on resolve()

    assert safe_repo_file(repo, "loop") is None
