# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Render the Mermaid blocks of a Markdown file with mermaid-cli, so a block that doesn't render fails a test.

mermaid-cli (``mmdc``) is pinned in contracts/package.json. It drives a system Chrome; its own browser
download is switched off in contracts/pnpm-workspace.yaml. Locally a test that needs them is skipped
without them; with ``CI=true`` it runs and fails, so CI never passes without rendering.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from contracts_gen.sources import CONTRACTS_DIR, REPO_ROOT

MMDC = REPO_ROOT / CONTRACTS_DIR / "node_modules" / ".bin" / "mmdc"
CHROME_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")
CHROME_APP = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
RENDER_TIMEOUT_SECONDS = 300


def find_chrome() -> str | None:
    """The Chrome to render with: ``PUPPETEER_EXECUTABLE_PATH``, else one on PATH or the macOS app."""
    configured = os.environ.get("PUPPETEER_EXECUTABLE_PATH")
    if configured:
        return configured
    for name in CHROME_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return str(CHROME_APP) if CHROME_APP.is_file() else None


MERMAID_READY = MMDC.is_file() and Path(find_chrome() or "/nonexistent").is_file()
MERMAID_SKIP_REASON = "needs `pnpm install` in contracts/ and a Chrome (PUPPETEER_EXECUTABLE_PATH)"
IN_CI = os.environ.get("CI") == "true"
needs_mermaid = pytest.mark.skipif(not MERMAID_READY and not IN_CI, reason=MERMAID_SKIP_REASON)
"""Skip a render test locally when mmdc or Chrome is missing; in CI it runs, and fails without them."""


def mermaid_blocks(markdown: str) -> int:
    """The number of ```mermaid fences in ``markdown``."""
    return sum(1 for line in markdown.splitlines() if line.strip() == "```mermaid")


def render_markdown(markdown: str, work: Path) -> list[Path]:
    """Render every Mermaid block of ``markdown`` to an SVG in ``work``; raise if any block doesn't render."""
    if not MMDC.is_file():
        raise AssertionError(f"no mermaid-cli at {MMDC}: run `pnpm install` in contracts/")
    chrome = find_chrome()
    if chrome is None or not Path(chrome).is_file():
        raise AssertionError(f"no Chrome to render with ({chrome}): set PUPPETEER_EXECUTABLE_PATH")
    source = work / "page.md"
    source.write_text(markdown, encoding="utf-8")
    config = work / "puppeteer.json"
    config.write_text(f'{{"executablePath": "{chrome}", "args": ["--no-sandbox"]}}', encoding="utf-8")
    command = [str(MMDC), "--quiet", "-p", str(config), "-i", str(source), "-o", str(work / "out.md")]
    result = subprocess.run(
        [*command, "-e", "svg"], capture_output=True, text=True, timeout=RENDER_TIMEOUT_SECONDS, check=False
    )
    if result.returncode != 0:
        raise AssertionError(f"mermaid-cli failed:\n{result.stderr[-3000:]}")
    svgs = sorted(work.glob("out-*.svg"))
    if len(svgs) != mermaid_blocks(markdown):
        raise AssertionError(f"{mermaid_blocks(markdown)} Mermaid blocks, {len(svgs)} rendered")
    return svgs
