# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""``python -m capability_specs [--write]``: check the specs under docs/specs/ or write their Phase 2 page."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from .checks import check_specs
from .render import render_page
from .specs import PAGE_FILE, SpecError, load_index, load_sources, load_specs

REPO_ROOT = Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="capability_specs", description=__doc__)
    parser.add_argument("--write", action="store_true", help=f"regenerate {PAGE_FILE}")
    arguments = parser.parse_args(argv)
    try:
        report = run(REPO_ROOT, arguments.write)
    except SpecError as error:
        print("specs: " + "\nspecs: ".join(error.problems), file=sys.stderr)
        return 1
    print(report)
    return 0


def run(repo_root: Path, write: bool) -> str:
    """Check the specs, and write the page if asked; the report line says what was checked."""
    index = load_index(repo_root)
    specs = load_specs(repo_root, index)
    sources = load_sources(repo_root)
    problems = check_specs(index, specs, sources, repo_root)
    if problems:
        raise SpecError(problems)
    rendered = render_page(index, specs, sources)
    output = repo_root / PAGE_FILE
    if write:
        output.write_text(rendered, encoding="utf-8")
    elif not output.is_file() or output.read_text(encoding="utf-8") != rendered:
        raise SpecError([f"{PAGE_FILE} is out of date; run `just specs --write`"])
    sizes = Counter(block["size"] for spec in specs for block in spec.blocks)
    return (
        f"specs: {len(specs)} specs, {sum(sizes.values())} blocks ({sizes['S']} S, {sizes['M']} M, {sizes['L']} L); "
        f"{len(index.not_yet_specced)} Phase 2 capabilities not yet specced"
    )


if __name__ == "__main__":
    sys.exit(main())
