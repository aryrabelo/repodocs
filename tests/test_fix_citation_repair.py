"""Regression test for repair_citations: a pure end-of-file overshoot is clamped
to the real file length; unrepairable citations are left for enforce_citations."""

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
