"""Regression tests for repodocs.diagrams: mermaid blocks are swapped for image
embeds on a successful render and kept verbatim on failure. The Bun renderer is
stubbed so the tests need no Bun/playwright."""

import repodocs.diagrams as dg


def test_process_page_swaps_rendered_block(tmp_path, monkeypatch):
    md = tmp_path / "arch.md"
    md.write_text("# Arch\n\nintro\n\n```mermaid\nflowchart TD\n  A-->B\n```\n\nmore\n")

    def fake_render(tool, out, stem, i, yaml_text):
        (out / f"{stem}-diagram-{i}.png").write_bytes(b"PNG")
        return True

    monkeypatch.setattr(dg, "_render_png", fake_render)
    assert dg.process_page(md, tmp_path, tmp_path / "tool.ts") == (1, 0)
    body = md.read_text()
    assert "```mermaid" not in body
    assert "![Arch diagram](arch-diagram-1.png)" in body


def test_process_page_keeps_block_on_render_failure(tmp_path, monkeypatch):
    md = tmp_path / "arch.md"
    md.write_text("# Arch\n\n```mermaid\nflowchart TD\n  A-->B\n```\n")
    monkeypatch.setattr(dg, "_render_png", lambda *a: False)
    assert dg.process_page(md, tmp_path, tmp_path / "tool.ts") == (0, 1)
    assert "```mermaid" in md.read_text()  # unrendered block stays honest


def test_process_page_numbers_multiple_blocks(tmp_path, monkeypatch):
    md = tmp_path / "p.md"
    md.write_text("# P\n\n```mermaid\nflowchart TD\n  A-->B\n```\n\n```mermaid\nflowchart LR\n  C-->D\n```\n")
    monkeypatch.setattr(dg, "_render_png",
                        lambda tool, out, stem, i, y: bool((out / f"{stem}-diagram-{i}.png").write_bytes(b"P")) or True)
    assert dg.process_page(md, tmp_path, tmp_path / "tool.ts") == (2, 0)
    body = md.read_text()
    assert "![P — diagram 1](p-diagram-1.png)" in body
    assert "![P — diagram 2](p-diagram-2.png)" in body
    assert "```mermaid" not in body


def test_poster_yaml_indents_mermaid_and_numbers_multi(tmp_path):
    y = dg._poster_yaml("Title", "slug", "flowchart TD\n  A-->B", 2, 3)
    assert "DIAGRAM 2/3" in y
    assert "mermaid: |\n  flowchart TD\n    A-->B\n" in y
