# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""``python -m capability_catalogue [--write] [--reference DIR]``: check the catalogue or write its page."""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

from .catalogue import CatalogueError, load_catalogue
from .checks import check_catalogue
from .coverage import check_prototype_commands
from .render import render_page

REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOGUE_FILE = "docs/architecture/capabilities.yaml"
OUTPUT_FILE = "docs/architecture/capabilities.md"
REFERENCE_ENV = "BENCHHAND_REFERENCE_DIR"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="capability_catalogue", description=__doc__)
    parser.add_argument("--write", action="store_true", help=f"regenerate {OUTPUT_FILE}")
    parser.add_argument(
        "--reference",
        default=os.environ.get(REFERENCE_ENV),
        help=f"a read-only copy of the prototype at reference_commit (default: ${REFERENCE_ENV})",
    )
    arguments = parser.parse_args(argv)
    try:
        report = run(REPO_ROOT, Path(arguments.reference) if arguments.reference else None, arguments.write)
    except CatalogueError as error:
        print("capabilities: " + "\ncapabilities: ".join(error.problems), file=sys.stderr)
        return 1
    print(report)
    return 0


def run(repo_root: Path, reference_dir: Path | None, write: bool) -> str:
    """Check the catalogue, and write its page if asked; the report line says what was checked."""
    catalogue = load_catalogue(repo_root / CATALOGUE_FILE)
    problems = check_catalogue(catalogue, repo_root)
    if reference_dir is not None:
        problems += check_prototype_commands(catalogue, reference_dir)
    if problems:
        raise CatalogueError([f"{CATALOGUE_FILE}: {problem}" for problem in problems])
    rendered = render_page(catalogue)
    output = repo_root / OUTPUT_FILE
    if write:
        output.write_text(rendered, encoding="utf-8")
    elif not output.is_file() or output.read_text(encoding="utf-8") != rendered:
        raise CatalogueError([f"{OUTPUT_FILE} is out of date; run `just capabilities --write`"])
    statuses = Counter(item["status"] for item in catalogue.capabilities)
    by_status = ", ".join(f"{statuses[status]} {status}" for status in sorted(statuses))
    coverage = (
        f"prototype commands checked against {reference_dir}"
        if reference_dir
        else f"prototype commands not checked (no reference copy; set {REFERENCE_ENV})"
    )
    return (
        f"capabilities: {len(catalogue.capabilities)} capabilities ({by_status}), {len(catalogue.tools)} tools, "
        f"{len(catalogue.cli)} CLI commands; {coverage}"
    )


if __name__ == "__main__":
    sys.exit(main())
