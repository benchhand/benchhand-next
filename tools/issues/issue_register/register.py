# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The register file: its schema check, and the checks that need the repository and the reference map."""

from __future__ import annotations

import json
import os
import re
import tomllib
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from reference_map.entries import MapError, ReferenceMap, load_map

REGISTER_FILE = "docs/migration/issue-register.yaml"
OUTPUT_FILE = "docs/migration/issue-register.md"
SCHEMA_FILE = "tools/issues/issue-register.schema.json"
MAP_FILE = "docs/architecture/reference-map.yaml"
SNAPSHOT_KEY = "ledger_snapshot"
_SNAPSHOT_LINE = re.compile(rf"^{SNAPSHOT_KEY}:", re.MULTILINE)
_TOP_LEVEL_KEY = re.compile(r"^[A-Za-z_]", re.MULTILINE)
_TOOL_ISSUE_SOURCE = re.compile(r"^test-project tool-issues #([0-9]+)$")
_ISSUE_MENTION = re.compile(r"\bIR-[0-9]{3}\b")
PRIVATE_PATTERNS_ENV = "BENCHHAND_PRIVATE_PATTERNS"
PRIVATE_PATTERNS_FILE = "tools/issues/private-patterns.txt"
_HOME_PATH = re.compile(r"/(Users|home)/[A-Za-z]")
"""The register is public: it never names a home directory, and never matches a local private pattern."""


class RegisterError(Exception):
    """The register has problems; the message lists them all."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Register:
    data: dict[str, Any]

    @property
    def issues(self) -> list[dict[str, Any]]:
        return self.data["issues"]

    @property
    def design_rules(self) -> list[dict[str, Any]]:
        return self.data["design_rules"]

    @property
    def bead_dispositions(self) -> list[dict[str, Any]]:
        return self.data["bead_dispositions"]

    @property
    def snapshot(self) -> dict[str, Any]:
        return self.data[SNAPSHOT_KEY]

    def bead_references(self) -> list[str]:
        """Every bead the register names, in order, once per mention."""
        named = [bead for issue in self.issues for bead in issue.get("beads", [])]
        return named + [entry["bead_id"] for entry in self.bead_dispositions]

    def cited_tool_issues(self) -> set[str]:
        """The test-project tool-issues numbers that some issue cites."""
        cited = (_TOOL_ISSUE_SOURCE.match(source) for issue in self.issues for source in issue["sources"])
        return {match.group(1) for match in cited if match}


def parse_register(text: str, where: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise RegisterError([f"{where}: not valid YAML: {error}"]) from error
    if not isinstance(data, dict):
        raise RegisterError([f"{where}: expected a mapping"])
    return data


def load_register(repo_root: Path, *, check_snapshot: bool = True) -> Register:
    """Read the register and run every check; all the problems are reported at once.

    ``check_snapshot=False`` leaves out the snapshot-coverage check, for `sync`, which rewrites the snapshot.
    """
    text = (repo_root / REGISTER_FILE).read_text(encoding="utf-8")
    return register_from_text(text, repo_root, check_snapshot=check_snapshot)


def register_from_text(text: str, repo_root: Path, *, check_snapshot: bool = True) -> Register:
    """Run every check on ``text`` as the register file, without reading or writing that file."""
    data = parse_register(text, REGISTER_FILE)
    schema = json.loads((repo_root / SCHEMA_FILE).read_text(encoding="utf-8"))
    problems = schema_problems(data, schema)
    if problems:
        raise RegisterError([f"{REGISTER_FILE}: {problem}" for problem in problems])
    register = Register(data)
    problems = [*text_problems(text, private_patterns(repo_root)), *cross_problems(register, repo_root)]
    if check_snapshot:
        problems += snapshot_problems(register)
    if problems:
        raise RegisterError([f"{REGISTER_FILE}: {problem}" for problem in problems])
    return register


def private_patterns(repo_root: Path) -> list[re.Pattern[str]]:
    """A home-directory path, and the private patterns of the local file, if there is one.

    The file is the one that BENCHHAND_PRIVATE_PATTERNS names, or else tools/issues/private-patterns.txt, which
    git ignores: one regular expression per line, `#` starts a comment line. It lists the tokens of private
    sources (project names, paths, part numbers) and never enters the repository. CI has no file, so it
    refuses home-directory paths only.
    """
    path = Path(os.environ.get(PRIVATE_PATTERNS_ENV) or repo_root / PRIVATE_PATTERNS_FILE)
    if not path.is_file():
        return [_HOME_PATH]
    patterns, problems = [_HOME_PATH], []
    lines = path.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            patterns.append(re.compile(line.strip()))
        except re.error as error:
            problems.append(f"{path} line {number}: not a regular expression: {error}")
    if problems:
        raise RegisterError(problems)
    return patterns


def schema_problems(data: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.absolute_path))
    return [f"{_json_path(error.absolute_path)}: {error.message}" for error in errors]


def _json_path(parts: Iterable[Any]) -> str:
    return "/".join(str(part) for part in parts) or "(top level)"


def text_problems(text: str, patterns: list[re.Pattern[str]]) -> list[str]:
    """The snapshot is the last top-level key, so `--update-snapshot` rewrites only it; no private tokens."""
    problems = []
    found = _SNAPSHOT_LINE.search(text)
    if found is None or _TOP_LEVEL_KEY.search(text, found.end()):
        problems.append(f"`{SNAPSHOT_KEY}` must be the last top-level key")
    for number, line in enumerate(text.splitlines(), start=1):
        problems += [
            f"line {number}: matches the private pattern {pattern.pattern!r}"
            for pattern in patterns
            if pattern.search(line)
        ]
    return problems


def cross_problems(register: Register, repo_root: Path) -> list[str]:
    pinned = tomllib.loads((repo_root / "release.toml").read_text(encoding="utf-8"))["reference_commit"]
    problems = []
    if register.data["reference_commit"] != pinned:
        problems.append(
            f"reference_commit {register.data['reference_commit']} is not release.toml's {pinned}"
        )
    problems += _unique_ids(register)
    problems += _dangling_mentions(register)
    problems += _bead_coverage(register)
    problems += _duplicate_targets(register)
    problems += _pointer_problems(register, repo_root)
    try:
        reference = load_map(repo_root / MAP_FILE)
    except MapError as error:
        return [*problems, *error.problems]
    return problems + _map_problems(register, reference)


def _repeated(values: Iterable[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def _unique_ids(register: Register) -> list[str]:
    ids = [issue["id"] for issue in register.issues] + [rule["id"] for rule in register.design_rules]
    return [f"id {value} is used more than once" for value in _repeated(ids)]


def _dangling_mentions(register: Register) -> list[str]:
    """Prose that names an issue (`IR-nnn`) names one the register has."""
    known = {issue["id"] for issue in register.issues}
    mentioned = set(_ISSUE_MENTION.findall(json.dumps(register.data)))
    return [f"{mention} is mentioned but is not an issue" for mention in sorted(mentioned - known)]


def _bead_coverage(register: Register) -> list[str]:
    return [f"{bead} is referenced more than once" for bead in _repeated(register.bead_references())]


def _duplicate_targets(register: Register) -> list[str]:
    known = {issue["id"] for issue in register.issues} | set(register.bead_references())
    return [
        f"{entry['bead_id']}: duplicate_of {entry['duplicate_of']} is not in the register"
        for entry in register.bead_dispositions
        if "duplicate_of" in entry and entry["duplicate_of"] not in known
    ]


def snapshot_problems(register: Register) -> list[str]:
    """The snapshot names exactly the register's beads, and every recorded tool issue is cited."""
    referenced = set(register.bead_references())
    recorded = set(register.snapshot["statuses"])
    problems = [f"{bead} has no {SNAPSHOT_KEY} status" for bead in sorted(referenced - recorded)]
    problems += [
        f"{SNAPSHOT_KEY} names {bead}, which the register doesn't" for bead in sorted(recorded - referenced)
    ]
    uncited = set(register.snapshot.get("tool_issue_hashes", {})) - register.cited_tool_issues()
    problems += [
        f"test-project tool-issues #{number}: no issue cites it" for number in sorted(uncited, key=int)
    ]
    return problems


def _pointers(register: Register) -> Iterator[tuple[str, str]]:
    for issue in register.issues:
        if "pointer" in issue:
            yield issue["id"], issue["pointer"]
    for rule in register.design_rules:
        if "pointer" in rule:
            yield rule["id"], rule["pointer"]
    for entry in register.bead_dispositions:
        if "pointer" in entry:
            yield entry["bead_id"], entry["pointer"]


def _pointer_problems(register: Register, repo_root: Path) -> list[str]:
    problems = []
    for owner, pointer in _pointers(register):
        file = pointer.split(" §", 1)[0]
        if not (repo_root / file).exists():
            problems.append(f"{owner}: pointer {file} does not exist")
    return problems


def _map_problems(register: Register, reference: ReferenceMap) -> list[str]:
    paths = {entry.path for entry in reference.entries}
    areas = {entry.area for entry in reference.entries}
    problems = []
    for issue in register.issues:
        problems += [
            f"{issue['id']}: prototype path {path} is not in {MAP_FILE}"
            for path in issue.get("prototype_paths", [])
            if path not in paths
        ]
    owners = [(issue["id"], issue["area"]) for issue in register.issues]
    owners += [(entry["bead_id"], entry["area"]) for entry in register.bead_dispositions]
    problems += [
        f"{owner}: area {area} is not a {MAP_FILE} area" for owner, area in owners if area not in areas
    ]
    return problems
