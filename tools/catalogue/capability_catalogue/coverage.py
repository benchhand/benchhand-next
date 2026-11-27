# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The check against the prototype's static command inventory (prototype-inventory.json, which tools/inventory
reads from the pin): every command line the pin can run has a prototype command, and every prototype command is
one the pin can run.

A prototype command is ``script.py``, then the subcommand words of one of its parsers, then any flags of that
parser. Without flags it names a command line, and each command line the pin can run needs one. With flags it
names a flag-only mode of that command line, such as ``stamp.py --verify``; each flag must be one that parser
declares. A parser with a mandatory switch, such as ``emit.py --sarif``, can't run without it: its command line
is the entry that has the mandatory switches, and an entry without them is wrong."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from prototype_inventory.cli import JSON_FILE as INVENTORY_FILE

from .catalogue import Catalogue

ENTRY_GLOBS = ("skills/*/scripts/*.py", "harness/*.py")
"""Where the prototype's commands are: a script here with a `__main__` block is one, tests left out."""


@dataclass(frozen=True)
class Script:
    """A runnable prototype script: its command lines, each as its subcommand words, with the flags it declares."""

    commands: dict[str, frozenset[str]]
    """Every parser, ``""`` for the script's own; a script with a `__main__` block and no parser has only ``""``."""
    mandatory: dict[str, frozenset[str]]
    """The switches each parser requires: flags that select a mode, not the values a mode takes, such as --hw."""
    leaves: frozenset[str]
    """The command lines that can be run: parsers with no subcommand below them."""


def load_inventory(repo_root: Path) -> dict[str, Any]:
    return json.loads((repo_root / INVENTORY_FILE).read_text(encoding="utf-8"))


def runnable_scripts(inventory: dict[str, Any]) -> dict[str, Script]:
    """The inventory's runnable scripts by prototype path."""
    return {
        file["path"]: _script(file)
        for file in inventory["files"]
        if any(fnmatchcase(file["path"], pattern) for pattern in ENTRY_GLOBS)
        and not Path(file["path"]).name.startswith("test_")
        and (file["entry_points"] or file["commands"])
    }


def _script(file: dict[str, Any]) -> Script:
    commands = {
        command["command"]: frozenset(
            flag for option in command["options"] if option["kind"] == "option" for flag in option["flags"]
        )
        for command in file["commands"]
    } or {"": frozenset()}
    mandatory = {
        command["command"]: frozenset(
            flag
            for option in command["options"]
            if option["kind"] == "option"
            and option.get("required")
            and "store_true" in str(option.get("action"))
            for flag in option["flags"]
        )
        for command in file["commands"]
    }
    leaves = frozenset(
        path
        for path in commands
        if not any(other != path and other.startswith(f"{path} " if path else "") for other in commands)
    )
    return Script(commands, mandatory, leaves)


def check_prototype_commands(catalogue: Catalogue, inventory: dict[str, Any]) -> list[str]:
    scripts = runnable_scripts(inventory)
    unknown = (_unknown(command, scripts) for command in catalogue.prototype_commands)
    return [*_unlisted(catalogue, scripts), *(problem for problem in unknown if problem)]


def _split(command: str) -> tuple[str, str, list[str]]:
    """``stamp.py --verify --committed`` as its script, its subcommand words and its flags."""
    script, *rest = command.split()
    words = " ".join(word for word in rest if not word.startswith("-"))
    return script, words, [word for word in rest if word.startswith("-")]


def _unlisted(catalogue: Catalogue, scripts: dict[str, Script]) -> Iterator[str]:
    split = [(command["path"], *_split(command["command"])) for command in catalogue.prototype_commands]
    listed = {
        (path, words)
        for path, name, words, flags in split
        if name == Path(path).name and path in scripts and _names_command_line(scripts[path], words, flags)
    }
    for path, script in sorted(scripts.items()):
        for words in sorted(script.leaves):
            if (path, words) not in listed:
                name = " ".join(
                    filter(None, (Path(path).name, words, *sorted(script.mandatory.get(words, []))))
                )
                yield f"{path}: the pin can run `{name}`, and prototype_commands has no entry for it"


def _names_command_line(script: Script, words: str, flags: list[str]) -> bool:
    """The entry is the command line itself: flagless, or with every mandatory switch when there are any."""
    mandatory = script.mandatory.get(words, frozenset())
    return words in script.leaves and mandatory <= set(flags) and bool(flags) == bool(mandatory)


def _unknown(command: dict[str, Any], scripts: dict[str, Script]) -> str | None:
    name, words, flags = _split(command["command"])
    where = f"prototype command {command['command']}"
    script = scripts.get(command["path"])
    if name != Path(command["path"]).name:
        return f"{where}: names {name}, and its path is {command['path']}"
    if script is None:
        return f"{where}: {command['path']} is not a runnable script in {INVENTORY_FILE}"
    if words not in script.leaves:
        return f"{where}: {command['path']} has no command line `{words}` at the pin"
    missing = [flag for flag in flags if flag not in script.commands[words]]
    if missing:
        return f"{where}: `{words or name}` declares no {', '.join(missing)} at the pin"
    absent = sorted(script.mandatory.get(words, frozenset()) - set(flags))
    return (
        f"{where}: `{' '.join(filter(None, (name, words)))}` needs {', '.join(absent)} at the pin"
        if absent
        else None
    )
