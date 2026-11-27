"""The D2 diagrams of docs/architecture: every ``.d2`` renders, with the pinned d2, to the bytes of its ``.svg``.

The SVG is committed beside its source, so the test fails when one changes without the other. d2 is pinned
because its layout is part of the output. Locally a render test is skipped without d2 on PATH; with
``CI=true`` it runs and fails, so CI never passes without rendering. CI installs d2 with mise.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from contracts_gen.sources import REPO_ROOT

ARCHITECTURE_DIR = REPO_ROOT / "docs" / "architecture"
D2_VERSION = "0.9.0"
D2_RENDER = ("d2", "--layout", "elk", "--pad", "40")
"""The command that rendered every committed SVG, followed by the source and the target."""
RENDER_TIMEOUT_SECONDS = 120
SOURCES = sorted(ARCHITECTURE_DIR.rglob("*.d2"))
IMAGE_LINK = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")

IN_CI = os.environ.get("CI") == "true"
needs_d2 = pytest.mark.skipif(
    shutil.which("d2") is None and not IN_CI,
    reason=f"d2 is not on PATH: install d2 {D2_VERSION} (`mise use d2@{D2_VERSION}`) to render the diagrams",
)
"""Skip a render test locally when d2 is missing; in CI it runs, and fails without it."""


def _relative(path: Path) -> str:
    return path.relative_to(ARCHITECTURE_DIR).as_posix()


def _embedded_images() -> set[Path]:
    """Every image that a page of docs/architecture embeds with ``![](...)``, resolved against the page."""
    found: set[Path] = set()
    for page in ARCHITECTURE_DIR.rglob("*.md"):
        for target in IMAGE_LINK.findall(page.read_text(encoding="utf-8")):
            found.add((page.parent / target).resolve())
    return found


def test_the_d2_sources_are_found() -> None:
    assert {"overview/layers.d2", "overview/deployment.d2"} <= {_relative(source) for source in SOURCES}


@pytest.mark.parametrize("source", SOURCES, ids=_relative)
def test_every_d2_source_has_its_svg_embedded_in_a_page(source: Path) -> None:
    svg = source.with_suffix(".svg")
    assert svg.is_file(), f"{_relative(source)} has no committed {svg.name}"
    assert svg.resolve() in _embedded_images(), f"no page of docs/architecture embeds {_relative(svg)}"


@needs_d2
def test_the_installed_d2_is_the_pinned_one() -> None:
    output = subprocess.run(
        ["d2", "--version"], capture_output=True, text=True, check=True, timeout=RENDER_TIMEOUT_SECONDS
    ).stdout
    assert output.strip().removeprefix("v") == D2_VERSION, (
        f"d2 {output.strip()} is installed, not {D2_VERSION}"
    )


@needs_d2
@pytest.mark.parametrize("source", SOURCES, ids=_relative)
def test_every_d2_source_renders_to_its_committed_svg(source: Path, tmp_path: Path) -> None:
    rendered = tmp_path / source.with_suffix(".svg").name
    result = subprocess.run(
        [*D2_RENDER, str(source), str(rendered)],
        capture_output=True,
        text=True,
        timeout=RENDER_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == 0, f"d2 failed on {_relative(source)}:\n{result.stderr}"
    command = " ".join([*D2_RENDER, source.name, rendered.name])
    assert rendered.read_bytes() == source.with_suffix(".svg").read_bytes(), (
        f"{_relative(source.with_suffix('.svg'))} differs from a fresh render: run `{command}` in "
        f"docs/architecture/{_relative(source.parent)} with d2 {D2_VERSION}"
    )
