# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The check against a reference copy of the prototype: every script it can run has a prototype command,
and every subcommand a command names exists in its script."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from .catalogue import Catalogue

ENTRY_GLOBS = ("skills/*/scripts/*.py", "harness/*.py")
"""Where the prototype's commands are: a script here with a `__main__` block is one."""
MAIN_MARKER = "__main__"


def check_prototype_commands(catalogue: Catalogue, reference_dir: Path) -> list[str]:
    return [*_uncovered(catalogue, reference_dir), *_subcommands(catalogue, reference_dir)]


def runnable_scripts(reference_dir: Path) -> list[str]:
    """The prototype paths of its runnable scripts, tests left out."""
    found = {
        path.relative_to(reference_dir).as_posix()
        for pattern in ENTRY_GLOBS
        for path in reference_dir.glob(pattern)
        if not path.name.startswith("test_") and MAIN_MARKER in path.read_text(encoding="utf-8")
    }
    return sorted(found)


def _uncovered(catalogue: Catalogue, reference_dir: Path) -> Iterator[str]:
    listed = {command["path"] for command in catalogue.prototype_commands}
    for path in runnable_scripts(reference_dir):
        if path not in listed:
            yield f"{path} is a runnable prototype script with no entry in prototype_commands"


def _subcommands(catalogue: Catalogue, reference_dir: Path) -> Iterator[str]:
    """A command `script.py sub` needs the quoted `"sub"` in the script, as argparse declares it."""
    for command in catalogue.prototype_commands:
        script = reference_dir / command["path"]
        if not script.is_file():
            yield f"prototype command {command['command']}: {command['path']} is not in the reference copy"
            continue
        _, _, subcommand = command["command"].partition(" ")
        if subcommand and f'"{subcommand}"' not in script.read_text(encoding="utf-8"):
            yield f"prototype command {command['command']}: {command['path']} declares no {subcommand}"
