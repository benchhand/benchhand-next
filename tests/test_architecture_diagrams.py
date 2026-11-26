"""The hand-written architecture pages: every Mermaid block of docs/architecture/*.md renders."""

from __future__ import annotations

from pathlib import Path

import pytest
from contracts_gen.sources import REPO_ROOT
from mermaid_render import mermaid_blocks, needs_mermaid, render_markdown
from reference_map.cli import OUTPUT_FILE

ARCHITECTURE_DIR = REPO_ROOT / "docs" / "architecture"
GENERATED = {Path(OUTPUT_FILE).name}
"""function-map.md has its own render test, beside its generator's."""
HAND_WRITTEN = sorted(page for page in ARCHITECTURE_DIR.glob("*.md") if page.name not in GENERATED)


def test_the_hand_written_pages_are_found() -> None:
    names = {page.name for page in HAND_WRITTEN}
    assert {"README.md", "context.md", "containers.md", "data-flow.md", "flow.md", "layers.md"} <= names


@needs_mermaid
@pytest.mark.parametrize("page", HAND_WRITTEN, ids=lambda page: page.name)
def test_every_block_of_a_hand_written_page_renders(page: Path, tmp_path: Path) -> None:
    text = page.read_text(encoding="utf-8")
    assert mermaid_blocks(text) > 0
    assert len(render_markdown(text, tmp_path)) == mermaid_blocks(text)
