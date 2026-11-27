"""The D2 diagrams of docs/architecture: every ``.d2`` renders, with the d2 that mise.toml pins, to the bytes of its ``.svg``.

The SVG is committed beside its source, so the test fails when one changes without the other. The layout is part
of the output, so the render runs only on the pinned d2, with the flags and environment the domain-model
generator uses (``contracts_gen.domain_d2``). d2 comes from PATH: ``mise install`` locally, and in CI the
mise-action step that installs the tools of mise.toml. Locally a render test is skipped without d2; with
``CI=true`` it runs and fails, so CI never passes without rendering.
"""

from __future__ import annotations

import os
import re
import shutil
import tomllib
from pathlib import Path

import pytest
from contracts_gen.domain_d2 import D2_COMMAND, D2_LAYOUT, D2_PAD, check_d2_version, render_d2
from contracts_gen.sources import REPO_ROOT

ARCHITECTURE_DIR = REPO_ROOT / "docs" / "architecture"
PINNED_D2 = tomllib.loads((REPO_ROOT / "mise.toml").read_text(encoding="utf-8"))["tools"]["d2"]
SOURCES = sorted(ARCHITECTURE_DIR.rglob("*.d2"))
IMAGE_LINK = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")

IN_CI = os.environ.get("CI") == "true"
needs_d2 = pytest.mark.skipif(
    shutil.which(D2_COMMAND) is None and not IN_CI,
    reason=f"d2 is not on PATH: run `mise install` to get d2 {PINNED_D2}, as mise.toml pins it",
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
def test_the_installed_d2_is_the_one_mise_pins() -> None:
    check_d2_version()


@needs_d2
@pytest.mark.parametrize("source", SOURCES, ids=_relative)
def test_every_d2_source_renders_to_its_committed_svg(source: Path, tmp_path: Path) -> None:
    svg = source.with_suffix(".svg")
    rendered = render_d2(source, tmp_path / svg.name)
    command = f"{D2_COMMAND} --layout {D2_LAYOUT} --pad {D2_PAD} {source.name} {svg.name}"
    assert rendered == svg.read_bytes(), (
        f"{_relative(svg)} differs from a fresh render: run `{command}` in "
        f"docs/architecture/{_relative(source.parent)} with d2 {PINNED_D2}"
    )
