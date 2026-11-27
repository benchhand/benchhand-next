# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""``docs/architecture/prototype-inventory.md``: per area, a table of commands and a table of functions."""

from __future__ import annotations

import re

from reference_map.render import AREA_TITLES

from .build import GENERATED_NOTICE, FileRecord, Inventory, count_commands
from .commands import CommandRecord, OptionRecord

_PACKAGE_SOURCE = re.compile(r"^packages/([^/]+)/src/[^/]+/(.*)$")
_MARKDOWN_SPECIAL = re.compile(r"([\\|<>*\[\]`])")
COUNT_COLUMNS = ("files", "commands", "classes", "functions", "methods")


def render_markdown(data: Inventory) -> str:
    commit = data["reference_commit"][:7]
    lines = [
        "# Prototype inventory: functions and commands",
        "",
        GENERATED_NOTICE,
        "",
        f"Every public function, class and method, and every command line, of the prototype's scripts at "
        f"`{commit}`, read statically with `ast` (nothing is imported or run). Names that start with an "
        "underscore are private and left out. The summary is the first line of the docstring. "
        "Each file carries the home, phase and status of its entry in `reference-map.yaml`, and its "
        "functions inherit them: the map has no entries finer than a file. "
        "`prototype-inventory.json` holds the same data with more detail (decorators, line numbers, every "
        "option's keywords).",
        "",
        "A command is a parser or click command with no subcommand under it. An option whose flag is "
        "computed rather than written out is shown as its source text. A `*` after an option marks it "
        "required.",
        "",
        *_totals(data),
    ]
    for area in data["summary"]["by_area"]:
        files = [file for file in data["files"] if file["area"] == area]
        lines += [f"## {AREA_TITLES.get(area, area)}", "", *_command_table(area, files), *_function_table(area, files)]
    return "\n".join(lines).rstrip("\n") + "\n"


def _totals(data: Inventory) -> list[str]:
    header = ("Area", *(column.capitalize() for column in COUNT_COLUMNS))
    lines = ["| " + " | ".join(header) + " |", "|---|" + "---:|" * len(COUNT_COLUMNS)]
    for area, counts in data["summary"]["by_area"].items():
        cells = " | ".join(str(counts[column]) for column in COUNT_COLUMNS)  # type: ignore[literal-required]
        lines.append(f"| {AREA_TITLES.get(area, area)} | {cells} |")
    total = data["summary"]
    cells = " | ".join(f"**{total[column]}**" for column in COUNT_COLUMNS)  # type: ignore[literal-required]
    return [*lines, f"| **all** | {cells} |", ""]


def _plain(text: str) -> str:
    return _MARKDOWN_SPECIAL.sub(r"\\\1", " ".join(text.split())) or "–"


def _code(text: str) -> str:
    text = " ".join(text.split())
    fence = "``" if "`" in text else "`"
    padded = f" {text} " if "`" in text else text
    return f"{fence}{padded}{fence}".replace("|", "\\|")


def _short_home(home: str) -> str:
    found = _PACKAGE_SOURCE.match(home)
    return f"{found.group(1)}/{found.group(2)}" if found else home


def _homes(file: FileRecord) -> str:
    return "<br>".join(_code(_short_home(home)) for home in file["home"]) or "–"


def _phase(file: FileRecord) -> str:
    if file["phase"] is not None:
        return f"P{file['phase']}"
    return "–" if file["status"] == "dropped" else "open"


def _option(option: OptionRecord) -> str:
    flags = " ".join(option["flags"])
    shown = f"<{flags}>" if option["kind"] == "positional" else flags
    return _code(shown + ("*" if option.get("required") else ""))


def _command_cell(command: CommandRecord, has_subcommands: bool) -> str:
    if command["command"]:
        return _code(command["command"])
    return "(global)" if has_subcommands else "(script)"


def _has_subcommands(command: CommandRecord, commands: list[CommandRecord]) -> bool:
    prefix = command["command"] + " " if command["command"] else ""
    return any(other["command"] != command["command"] and other["command"].startswith(prefix) for other in commands)


def _command_rows(file: FileRecord, script: str) -> list[str]:
    commands = file["commands"]
    if not commands:
        entry = "; ".join(file["entry_points"])
        return [f"| {_code(script)} | – | {_plain(file['summary'])} | {_code(entry) if entry else '–'} |"]
    rows = []
    for command in commands:
        has_subcommands = _has_subcommands(command, commands)
        if has_subcommands and not command["options"] and not command["command"]:
            continue
        options = "<br>".join(_option(option) for option in command["options"]) or "–"
        summary = _plain(command["summary"]) + (" (hidden)" if command["hidden"] else "")
        rows.append(f"| {_code(script)} | {_command_cell(command, has_subcommands)} | {summary} | {options} |")
    return rows


def _command_table(area: str, files: list[FileRecord]) -> list[str]:
    rows = [row for file in files for row in _command_rows(file, _short_path(file["path"], area))]
    if not rows:
        return []
    counts = sum(count_commands(file["commands"]) for file in files)
    return [
        f"Commands: {counts} command lines. A script with no command line found is listed with its `__main__` block, if it has one.",
        "",
        "| Script | Command | Summary | Options |",
        "|---|---|---|---|",
        *rows,
        "",
    ]


def _short_path(path: str, area: str) -> str:
    return path.removeprefix(f"skills/{area}/")


def _function_table(area: str, files: list[FileRecord]) -> list[str]:
    rows: list[str] = []
    for file in files:
        tail = f"{_homes(file)} | {_phase(file)} | {file['status']} |"
        script = _code(_short_path(file["path"], area))
        rows += [
            f"| {script} | {_code(name)} | {_code(signature)} | {_plain(summary)} | {tail}"
            for name, signature, summary in _symbols(file)
        ]
    if not rows:
        return []
    return [
        "| File | Name | Signature | Summary | Home | Phase | Status |",
        "|---|---|---|---|---|---|---|",
        *rows,
        "",
    ]


def _symbols(file: FileRecord) -> list[tuple[str, str, str]]:
    """``(name, signature, summary)`` of each class followed by its methods, and of the functions, in source
    order."""
    methods: dict[str, list[tuple[str, str, str]]] = {}
    top: list[tuple[int, str, str, str]] = []
    for function in file["functions"]:
        owner = function["name"].rpartition(".")[0]
        row = (function["name"], function["signature"], function["summary"])
        if owner:
            methods.setdefault(owner, []).append(row)
        else:
            top.append((function["line"], *row))
    top += [(item["line"], item["name"], item["signature"], item["summary"]) for item in file["classes"]]
    found: list[tuple[str, str, str]] = []
    for _line, name, signature, summary in sorted(top):
        found.append((name, signature, summary))
        found += methods.get(name, [])
    return found
