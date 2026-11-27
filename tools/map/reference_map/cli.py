# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""``python -m reference_map [--write] [--reference DIR]``: check the function map or write its diagrams."""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from pathlib import Path

from .coverage import check_copy_commit, check_coverage, check_homes
from .entries import MapError, load_map
from .render import render_function_map, status_counts

REPO_ROOT = Path(__file__).resolve().parents[3]
MAP_FILE = "docs/architecture/reference-map.yaml"
OUTPUT_FILE = "docs/architecture/function-map.md"
REFERENCE_ENV = "BENCHHAND_REFERENCE_DIR"
REPO_REFERENCE = "reference"
"""The prototype's tests and fixtures as imported here; it also holds the agent sources the copy lacks."""


def coverage_required() -> bool:
    """CI must check coverage against a copy; locally the check may go without one."""
    return os.environ.get("CI") == "true"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reference_map", description=__doc__)
    parser.add_argument("--write", action="store_true", help=f"regenerate {OUTPUT_FILE}")
    parser.add_argument(
        "--reference",
        default=os.environ.get(REFERENCE_ENV),
        help=f"a read-only copy of the prototype at reference_commit (default: ${REFERENCE_ENV})",
    )
    arguments = parser.parse_args(argv)
    try:
        report = run(REPO_ROOT, Path(arguments.reference) if arguments.reference else None, arguments.write)
    except MapError as error:
        print("reference-map: " + "\nreference-map: ".join(error.problems), file=sys.stderr)
        return 1
    print(report)
    return 0


def run(repo_root: Path, reference_dir: Path | None, write: bool) -> str:
    """Check the map, and write the diagrams if asked; the report line says what was and wasn't checked."""
    reference = load_map(repo_root / MAP_FILE)
    pinned = tomllib.loads((repo_root / "release.toml").read_text(encoding="utf-8"))["reference_commit"]
    if reference.reference_commit != pinned:
        raise MapError([f"reference_commit {reference.reference_commit} is not release.toml's {pinned}"])
    check_homes(reference, repo_root)
    verified = False
    if reference_dir is not None:
        verified = check_copy_commit(reference_dir, pinned)
        check_coverage(reference, [reference_dir, repo_root / REPO_REFERENCE])
    elif coverage_required():
        raise MapError([f"CI=true: set {REFERENCE_ENV} to a copy of the prototype at {pinned}"])
    rendered = render_function_map(reference)
    output = repo_root / OUTPUT_FILE
    if write:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    elif not output.is_file() or output.read_text(encoding="utf-8") != rendered:
        raise MapError([f"{OUTPUT_FILE} is out of date; run `just reference-map --write`"])
    counts = status_counts(reference)
    by_status = ", ".join(f"{counts[status]} {status}" for status in sorted(counts))
    commit = "its commit verified" if verified else "its commit not verified (no .git or stamp)"
    coverage = (
        f"coverage checked against {reference_dir}, {commit}"
        if reference_dir
        else f"coverage not checked (no reference copy; set {REFERENCE_ENV})"
    )
    return f"reference-map: {len(reference.entries)} entries ({by_status}); {coverage}"


if __name__ == "__main__":
    sys.exit(main())
