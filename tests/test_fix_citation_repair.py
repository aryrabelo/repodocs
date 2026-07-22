"""Regression test for repair_citations: a pure end-of-file overshoot is clamped
to the real file length; unrepairable citations are left for enforce_citations."""

import subprocess

from repodocs.citations import citation_error, repair_citations


def _repo(tmp_path, name="f.py", lines=5):
    (tmp_path / name).write_text("\n".join(f"line{i}" for i in range(1, lines + 1)) + "\n")
    return tmp_path


def test_repair_clamps_end_of_file_overshoot(tmp_path):
    repo = _repo(tmp_path, lines=5)  # 5-line file cited to L6 (the model's +1)
    out = repair_citations(repo, "Sources: [f.py:L2-L6](f.py#L2-L6)")
    assert out == "Sources: [f.py:L2-L5](f.py#L2-L5)"
    assert citation_error(repo, "f.py", 2, 5, "f.py#L2-L5") is None  # now honest


def test_repair_leaves_valid_citation_untouched(tmp_path):
    repo = _repo(tmp_path, lines=5)
    text = "Sources: [f.py:L1-L5](f.py#L1-L5)"
    assert repair_citations(repo, text) == text


def test_repair_leaves_missing_file_untouched(tmp_path):
    repo = _repo(tmp_path, lines=5)  # hallucinated path -- can't be salvaged
    text = "Sources: [nope.py:L1-L3](nope.py#L1-L3)"
    assert repair_citations(repo, text) == text
    assert citation_error(repo, "nope.py", 1, 3, "nope.py#L1-L3") is not None


def test_repair_leaves_start_past_eof_untouched(tmp_path):
    repo = _repo(tmp_path, lines=5)  # start itself past EOF -- not a clamp case
    text = "Sources: [f.py:L9-L12](f.py#L9-L12)"
    assert repair_citations(repo, text) == text

def _git_repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    sub = tmp_path / "src" / "pkg"
    sub.mkdir(parents=True)
    (sub / "mod.py").write_text("\n".join(f"line{i}" for i in range(1, 9)) + "\n")  # 8 lines
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def test_repair_resolves_dropped_prefix_via_unique_tracked_suffix(tmp_path):
    repo = _git_repo(tmp_path)  # model dropped 'src/pkg/', cited bare 'mod.py'
    out = repair_citations(repo, "Sources: [mod.py:L2-L5](mod.py#L2-L5)")
    assert out == "Sources: [src/pkg/mod.py:L2-L5](src/pkg/mod.py#L2-L5)"


def test_repair_resolves_prefix_and_clamps_overshoot_together(tmp_path):
    repo = _git_repo(tmp_path)  # mod.py has 8 lines; cite drops prefix AND overshoots
    out = repair_citations(repo, "Sources: [mod.py:L2-L9](mod.py#L2-L9)")
    assert out == "Sources: [src/pkg/mod.py:L2-L8](src/pkg/mod.py#L2-L8)"

def test_repair_adds_missing_L_prefix_on_label(tmp_path):
    repo = _repo(tmp_path, lines=5)  # href already L-formed; label dropped the L
    out = repair_citations(repo, "Sources: [f.py:2-4](f.py#L2-L4)")
    assert out == "Sources: [f.py:L2-L4](f.py#L2-L4)"


def test_repair_normalizes_single_line_citation_to_range(tmp_path):
    repo = _repo(tmp_path, lines=5)
    out = repair_citations(repo, "Sources: [f.py:3](f.py#L3)")
    assert out == "Sources: [f.py:L3-L3](f.py#L3-L3)"


def test_repair_leaves_label_href_path_mismatch_untouched(tmp_path):
    repo = _repo(tmp_path, lines=5)  # label path != href path -- ambiguous, don't guess
    text = "Sources: [g.py:L1-L2](f.py#L1-L2)"
    assert repair_citations(repo, text) == text
