"""Regression tests for cubic review comments on plan.py (PR #2): unreadable
graph.json aborting planning, files=null crashing validate_pages, unvalidated/
corrupt cached plan.json, LLM plans missing mandatory slugs, and duplicate
slug allocation for distinct directory names."""

import json
from types import SimpleNamespace

from repodocs.plan import graph_digest, llm_plan, load_plan, plan_pages, validate_pages


def test_graph_digest_survives_invalid_utf8(tmp_path):
    repo = tmp_path / "repo"
    (repo / "graphify-out").mkdir(parents=True)
    (repo / "graphify-out" / "graph.json").write_bytes(b"\xff\xfe\xfd garbage, not utf-8 or json")
    assert graph_digest(repo) == ""


def test_validate_pages_drops_null_files_instead_of_crashing(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    raw = [{"slug": "overview", "title": "Overview", "purpose": "p", "files": None}]
    out = validate_pages(repo, raw)
    assert len(out) == 1
    assert out[0]["slug"] == "overview"
    assert out[0]["files"] == []


def test_load_plan_validates_cached_plan_rejecting_traversal_slug(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    cached = [
        {"slug": "../evil", "title": "Evil", "purpose": "p", "files": []},
        {"slug": "good", "title": "Good", "purpose": "p", "files": []},
    ]
    (out / "plan.json").write_text(json.dumps(cached))
    pages = load_plan(repo, out, allow_omp=False)
    slugs = [p["slug"] for p in pages]
    assert "../evil" not in slugs
    assert slugs == ["good"]


def test_load_plan_recovers_from_corrupt_cache(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    (out / "plan.json").write_text("{not valid json at all")
    pages = load_plan(repo, out, allow_omp=False)
    assert isinstance(pages, list)
    assert pages[0]["slug"] == "overview"


def test_llm_plan_falls_back_when_missing_mandatory_slug(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Hi\n")
    out = tmp_path / "out"

    # LLM omits the mandatory "installation" slug (repo has a README).
    llm_pages = [{"slug": "overview", "title": "Overview", "purpose": "p", "files": []}]
    monkeypatch.setattr(
        "repodocs.plan.run_llm",
        lambda repo, prompt: SimpleNamespace(returncode=0, stdout=json.dumps(llm_pages)),
    )

    pages = llm_plan(repo, out)
    slugs = [p["slug"] for p in pages]
    assert "installation" in slugs  # only the heuristic fallback includes it
    assert not (out / ".plan.hash").is_file()  # fallback is never cached as settled


def test_plan_pages_collision_safe_slugs_for_distinct_dirs(tmp_path):
    facts = {
        "src_files": ["dir_a/a1.py", "dir_a/a2.py", "dir_b/b1.py", "dir_b/b2.py"],
        "line_counts": {"dir_a/a1.py": 10, "dir_a/a2.py": 5, "dir_b/b1.py": 8, "dir_b/b2.py": 3},
        "manifests": [],
        "top_dirs": {
            "Foo Bar": ["dir_a/a1.py", "dir_a/a2.py"],
            "foo-bar": ["dir_b/b1.py", "dir_b/b2.py"],
        },
        "has_contributing": False,
        "tests": [],
        "ci": [],
        "has_changelog": False,
    }
    pages = plan_pages(tmp_path, facts)
    comp_slugs = [p["slug"] for p in pages if p["slug"].startswith("component-")]
    assert len(comp_slugs) == len(set(comp_slugs))
    assert "component-foo-bar" in comp_slugs
    assert "component-foo-bar-2" in comp_slugs
