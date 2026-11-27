# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The reference map file: its entries, and the checks that need no reference copy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

STATUSES = ("planned", "in-progress", "partial", "ported", "dropped")
BUILT = ("partial", "ported")
"""The statuses whose home holds code on main."""
PHASES = range(0, 8)
ENTRY_KEYS = {"path", "home", "phase", "status", "reason", "note", "basis"}
SKILL_PREFIX = "skills/"


class MapError(Exception):
    """The map file, or the map against the reference copy, has problems; the message lists them all."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Entry:
    path: str
    """A file, a directory with a trailing ``/``, or a glob, relative to the prototype root."""
    status: str
    homes: tuple[str, ...] = ()
    phase: int | None = None
    reason: str = ""
    note: str = ""
    inferred: bool = False

    @property
    def area(self) -> str:
        """The skill a prototype path belongs to, ``examples``, or ``agents-and-harness``."""
        if self.path.startswith(SKILL_PREFIX):
            return self.path.split("/")[1]
        return "examples" if self.path.startswith("examples/") else "agents-and-harness"


@dataclass(frozen=True)
class ReferenceMap:
    reference_commit: str
    entries: tuple[Entry, ...]


def load_map(path: Path) -> ReferenceMap:
    """Read and validate ``path``; every problem in it is reported at once."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise MapError([f"{path}: not valid YAML: {error}"]) from error
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise MapError([f"{path}: expected a mapping with `reference_commit` and a list `entries`"])
    problems: list[str] = []
    entries = [_entry(item, index, problems) for index, item in enumerate(data["entries"])]
    kept = tuple(entry for entry in entries if entry is not None)
    problems += _duplicates(kept)
    if problems:
        raise MapError([f"{path}: {problem}" for problem in problems])
    return ReferenceMap(str(data.get("reference_commit", "")), kept)


def _entry(item: Any, index: int, problems: list[str]) -> Entry | None:
    where = f"entry {index + 1}"
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        problems.append(f"{where}: needs a string `path`")
        return None
    where = f"entry {index + 1} ({item['path']})"
    found = _entry_problems(item)
    problems += [f"{where}: {problem}" for problem in found]
    if found:
        return None
    homes = item.get("home", [])
    return Entry(
        path=item["path"],
        status=item["status"],
        homes=tuple([homes] if isinstance(homes, str) else homes),
        phase=item.get("phase"),
        reason=item.get("reason", ""),
        note=item.get("note", ""),
        inferred=item.get("basis") == "inferred",
    )


def _entry_problems(item: dict[str, Any]) -> list[str]:
    found = [f"unknown key `{key}`" for key in item if key not in ENTRY_KEYS]
    if item.get("status") not in STATUSES:
        return [*found, f"`status` must be one of {', '.join(STATUSES)}"]
    if item.get("basis", "inferred") != "inferred":
        found.append("`basis` can only be `inferred`")
    if item["status"] == "dropped":
        found += ["a dropped entry needs a `reason`"] if not item.get("reason") else []
        found += [f"a dropped entry has no `{key}`" for key in ("home", "phase") if key in item]
        return found
    homes = item.get("home")
    names = [homes] if isinstance(homes, str) else homes
    if not names or not all(isinstance(home, str) and home for home in names):
        found.append("`home` is a path or command, or a list of them")
    found += _phase_problems(item)
    if item["status"] == "partial" and not item.get("note"):
        found.append("a partial entry needs a `note` naming what is left out and which phase owns it")
    return found + (["only a dropped entry has a `reason`"] if "reason" in item else [])


def _phase_problems(item: dict[str, Any]) -> list[str]:
    """A phase from 0 to 7, or null for a planned entry whose home waits on an open question."""
    if "phase" in item and item["phase"] is None:
        if item["status"] != "planned":
            return ["only a planned entry may have no phase"]
        return [] if item.get("note") else ["an entry with no phase needs a `note` naming the open question"]
    return [] if item.get("phase") in PHASES else ["`phase` is a number from 0 to 7, or null"]


def _duplicates(entries: tuple[Entry, ...]) -> list[str]:
    seen: set[str] = set()
    problems = []
    for entry in entries:
        if entry.path in seen:
            problems.append(f"{entry.path} has two entries")
        seen.add(entry.path)
    return problems


def pattern_regex(pattern: str) -> re.Pattern[str]:
    """A glob as a regex over ``/``-separated paths: ``*`` stays in a segment, ``**`` crosses them, and a
    trailing ``/`` matches everything below the directory."""
    if pattern.endswith("/"):
        pattern += "**"
    parts = re.split(r"(\*\*/|\*\*|\*|\?)", pattern)
    translated = {"**/": "(?:.*/)?", "**": ".*", "*": "[^/]*", "?": "[^/]"}
    return re.compile("".join(translated.get(part, re.escape(part)) for part in parts) + r"\Z")
