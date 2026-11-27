# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""``python -m prototype_inventory [--write] [--reference DIR]``: check or write the prototype inventory."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from pathlib import Path
from typing import cast

from reference_map.cli import REFERENCE_ENV, REPO_ROOT, coverage_required
from reference_map.coverage import check_copy_commit
from reference_map.entries import MapError, ReferenceMap, load_map

from .build import (
    SCHEMA_VERSION,
    Inventory,
    InventoryError,
    build_inventory,
    check_joined,
    dump_json,
)
from .render import render_markdown

MAP_FILE = "docs/architecture/reference-map.yaml"
MARKDOWN_FILE = "docs/architecture/prototype-inventory.md"
JSON_FILE = "docs/architecture/prototype-inventory.json"
REGENERATE = "run `just inventory --write` with BENCHHAND_REFERENCE_DIR set"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prototype_inventory", description=__doc__)
    parser.add_argument("--write", action="store_true", help=f"regenerate {MARKDOWN_FILE} and {JSON_FILE}")
    parser.add_argument(
        "--reference",
        default=os.environ.get(REFERENCE_ENV),
        help=f"a read-only copy of the prototype at reference_commit (default: ${REFERENCE_ENV})",
    )
    arguments = parser.parse_args(argv)
    try:
        report = run(REPO_ROOT, Path(arguments.reference) if arguments.reference else None, arguments.write)
    except (MapError, InventoryError) as error:
        print("inventory: " + "\ninventory: ".join(error.problems), file=sys.stderr)
        return 1
    print(report)
    return 0


def run(repo_root: Path, reference_dir: Path | None, write: bool) -> str:
    """Write the inventory, or check the committed one; the report line says what was checked.

    With a copy of the prototype, the files are regenerated from it and must match byte for byte. Without one
    (a local check), the committed JSON must still agree with the reference map and the Markdown must be
    what the JSON renders to. CI requires the copy."""
    reference = load_map(repo_root / MAP_FILE)
    pinned = tomllib.loads((repo_root / "release.toml").read_text(encoding="utf-8"))["reference_commit"]
    if reference.reference_commit != pinned:
        raise InventoryError(
            [f"reference_commit {reference.reference_commit} is not release.toml's {pinned}"]
        )
    if reference_dir is None:
        if write or coverage_required():
            raise InventoryError(
                [
                    f"{'--write' if write else 'CI=true'}: set {REFERENCE_ENV} to a copy of the prototype at {pinned}"
                ]
            )
        data = _check_committed(repo_root, reference)
        return f"inventory: {_counts(data)}; prototype not re-read (no reference copy; set {REFERENCE_ENV})"
    verified = check_copy_commit(reference_dir, pinned)
    data = build_inventory(reference_dir, reference)
    expected = {MARKDOWN_FILE: render_markdown(data), JSON_FILE: dump_json(data)}
    if write:
        for name, text in expected.items():
            (repo_root / name).write_text(text, encoding="utf-8")
    else:
        stale = [name for name, text in expected.items() if _read(repo_root / name) != text]
        if stale:
            raise InventoryError([f"{name} is out of date; {REGENERATE}" for name in stale])
    commit = "its commit verified" if verified else "its commit not verified (no .git or stamp)"
    return f"inventory: {_counts(data)}; read from {reference_dir}, {commit}"


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _counts(data: Inventory) -> str:
    summary = data["summary"]
    return (
        f"{summary['files']} files, {summary['commands']} commands, {summary['classes']} classes, "
        f"{summary['functions']} functions, {summary['methods']} methods"
    )


def _check_committed(repo_root: Path, reference: ReferenceMap) -> Inventory:
    text = _read(repo_root / JSON_FILE)
    if text is None:
        raise InventoryError([f"{JSON_FILE} is missing; {REGENERATE}"])
    try:
        data = cast(Inventory, json.loads(text))
    except json.JSONDecodeError as error:
        raise InventoryError([f"{JSON_FILE} is not valid JSON: {error}; {REGENERATE}"]) from error
    if data.get("schema_version") != SCHEMA_VERSION:
        raise InventoryError([f"{JSON_FILE}: schema_version is not {SCHEMA_VERSION}; {REGENERATE}"])
    problems = check_joined(data, reference)
    if _read(repo_root / MARKDOWN_FILE) != render_markdown(data):
        problems.append(f"{MARKDOWN_FILE} is not what {JSON_FILE} renders to; {REGENERATE}")
    if text != dump_json(data):
        problems.append(f"{JSON_FILE} is not in the form the generator writes; {REGENERATE}")
    if problems:
        raise InventoryError([f"{problem}" for problem in problems])
    return data


if __name__ == "__main__":
    sys.exit(main())
