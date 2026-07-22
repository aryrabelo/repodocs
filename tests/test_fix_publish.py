"""Regression tests for cubic review comments on publish.py (mostly PR #2, one
from PR #1): protected-branch normalization, an ENCRYPTED PRIVATE KEY gap in the
secret scan, repeat-publish orphan-branch collisions, symlink follows on both the
publish and publish-wiki paths, clone-failure misclassification, an index-only
wiki never reaching its documented Home fallback, citation checks reading through
a symlink before staging rejects it, and an unfinished translated subdir blocking
the base wiki's publish."""

import json
import subprocess

import pytest

import repodocs.publish as publish_mod
from repodocs.publish import (
    WikiNotInitialized,
    WikiPublishError,
    PUBLISH_SECRET_PATTERNS,
    _publishable_subdir_mds,
    _reject_symlink_dest,
    cmd_publish_wiki,
    publish_branch_safe,
    publish_push,
    publish_wiki_push,
    stage_wiki,
    staged_secret_findings,
)


def _git(*args, cwd):
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert r.returncode == 0, (args, r.stdout, r.stderr)
    return r


def _init_repo_with_commit(repo, monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t.com")
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    (repo / "f.txt").write_text("hello\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)


# -- publish_branch_safe -------------------------------------------------------

def test_publish_branch_safe_normalizes_refs_heads_prefix():
    assert publish_branch_safe("refs/heads/main") is False
    assert publish_branch_safe("refs/heads/Main") is False
    assert publish_branch_safe("MAIN") is False
    assert publish_branch_safe("docs") is True
    assert publish_branch_safe("refs/heads/docs") is True


# -- secret scan ----------------------------------------------------------------

def test_secret_scan_catches_encrypted_private_key(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "leak.md").write_text("-----BEGIN ENCRYPTED PRIVATE KEY-----\nabc\n-----END-----\n")
    findings = staged_secret_findings(staging)
    assert any(label == "private key" for _, _, label in findings), findings


def test_encrypted_private_key_pattern_matches_directly():
    _, pattern = PUBLISH_SECRET_PATTERNS[0]
    assert pattern.search("-----BEGIN ENCRYPTED PRIVATE KEY-----")


# -- publish_push: repeat publish to the same branch ---------------------------

def test_publish_push_repeat_same_branch_succeeds(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo_with_commit(repo, monkeypatch)

    bare = tmp_path / "bare.git"
    _git("init", "-q", "--bare", str(bare), cwd=tmp_path)

    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "index.html").write_text("hi\n")

    publish_push(repo, staging, "gh-pages", str(bare))
    # second publish to the SAME branch must not fail on a leftover local orphan ref
    publish_push(repo, staging, "gh-pages", str(bare))

    pushed = _git("show", "gh-pages:index.html", cwd=bare).stdout
    assert pushed == "hi\n"
    # the throwaway local orphan branches must not linger in the source repo
    branches = _git("branch", "--list", "repodocs-publish-*", cwd=repo).stdout
    assert branches.strip() == ""


# -- publish_wiki_push: symlinked clone destination ----------------------------

def test_reject_symlink_dest_rejects_symlinked_file(tmp_path):
    clone = tmp_path / "clone"
    clone.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("do not touch")
    (clone / "Evil.md").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        _reject_symlink_dest(clone, "Evil.md")


def test_reject_symlink_dest_rejects_symlinked_parent_dir(tmp_path):
    clone = tmp_path / "clone"
    clone.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (clone / "sub").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        _reject_symlink_dest(clone, "sub/page.md")


def test_publish_wiki_push_rejects_symlinked_clone_destination_before_copy(tmp_path, monkeypatch):
    clone_dir = tmp_path / "clone"
    clone_dir.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("must not be overwritten")
    (clone_dir / "Evil.md").symlink_to(outside)  # simulates a compromised/malicious wiki clone

    monkeypatch.setattr(publish_mod.tempfile, "mkdtemp", lambda prefix="": str(clone_dir))
    monkeypatch.setattr(
        publish_mod.subprocess, "run",
        lambda args, **kw: subprocess.CompletedProcess(args, 0, stdout="", stderr=""),
    )

    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "Evil.md").write_text("attacker content")

    with pytest.raises(ValueError, match="symlink"):
        publish_wiki_push("https://example.invalid/x.wiki.git", ["Evil.md"], staging)

    assert outside.read_text() == "must not be overwritten"


# -- stage_wiki: symlinked plan.json -------------------------------------------

def test_stage_wiki_rejects_symlinked_plan_json(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "overview.md").write_text("# Overview\n")
    evil_target = tmp_path / "evil_plan.json"
    evil_target.write_text(json.dumps([{"slug": "overview", "title": "HACKED TITLE"}]))
    (out / "plan.json").symlink_to(evil_target)

    staging = tmp_path / "staging"
    with pytest.raises(ValueError, match="plan.json"):
        stage_wiki(out, staging, None)


# -- publish_wiki_push: clone failure classification ---------------------------

def test_clone_auth_failure_is_wikipublisherror_not_uninitialized(monkeypatch, tmp_path):
    stderr = (
        "remote: Invalid username or token. Password authentication is not supported "
        "for Git operations.\nfatal: Authentication failed for "
        "'https://github.com/o/r.wiki.git/'\n"
    )
    monkeypatch.setattr(
        publish_mod.subprocess, "run",
        lambda args, **kw: subprocess.CompletedProcess(args, 128, stdout="", stderr=stderr),
    )
    with pytest.raises(WikiPublishError):
        publish_wiki_push("https://github.com/o/r.wiki.git", ["Home.md"], tmp_path)


def test_clone_missing_local_path_is_still_wikinotinitialized(tmp_path):
    # real (offline) git clone failure against a path that doesn't exist -- must
    # still classify as "wiki not initialized", not regress into WikiPublishError.
    missing = tmp_path / "does-not-exist"
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "Home.md").write_text("x\n")
    with pytest.raises(WikiNotInitialized):
        publish_wiki_push(str(missing), ["Home.md"], staging)


# -- cmd_publish_wiki: index-only fallback + citation-scan ordering -----------

def _repo_with_origin(tmp_path, monkeypatch, name="repo"):
    repo = tmp_path / name
    _init_repo_with_commit(repo, monkeypatch)
    _git("remote", "add", "origin", "git@github.com:o/r.git", cwd=repo)
    return repo


def test_cmd_publish_wiki_index_only_reaches_home_fallback(tmp_path, monkeypatch, capsys):
    repo = _repo_with_origin(tmp_path, monkeypatch)
    out = tmp_path / "out"
    out.mkdir()
    (out / "index.md").write_text("# Index\n")

    rc = cmd_publish_wiki(repo, out, "origin", dry_run=True)
    assert rc == 0
    printed = capsys.readouterr().out
    assert "Home.md" in printed


def test_cmd_publish_wiki_stages_before_scanning_citations(tmp_path, monkeypatch):
    repo = _repo_with_origin(tmp_path, monkeypatch)
    secret = tmp_path / "secret.txt"
    # a fragment matching the citation-link shape so the (pre-fix) citation
    # scanner would echo it into its blocking die() message before any
    # symlink was ever rejected.
    secret.write_text("[leaked/path:L1-L2](bad#L1-L2) some secret content\n")

    out = tmp_path / "out"
    out.mkdir()
    (out / "overview.md").symlink_to(secret)

    with pytest.raises(ValueError, match="symlink"):
        cmd_publish_wiki(repo, out, "origin", dry_run=True)


# -- citation subdir scan skips unpublished translated dirs --------------------

def test_publishable_subdir_mds_skips_dir_without_rendered_html(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "overview.md").write_text("# Overview\n")

    finished = out / "es"
    finished.mkdir()
    (finished / "wiki.html").write_text("<html></html>")
    (finished / "overview.md").write_text("# Resumen\n")

    unfinished = out / "pt"
    unfinished.mkdir()
    (unfinished / "overview.md").write_text("# Visao geral\n")  # no wiki.html yet

    mds = _publishable_subdir_mds(out)
    assert any(p.name == "overview.md" and p.parent == out for p in mds)
    assert any(p.parent.name == "es" for p in mds)
    assert not any(p.parent.name == "pt" for p in mds)
