# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Loading the specs: the YAML front matter of docs/specs/*.md, validated against its schema, and the
catalogue and issue register the specs are checked against."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import yaml

SPECS_DIR = "docs/specs"
INDEX_FILE = "docs/specs/README.md"
PAGE_FILE = "docs/specs/phase-2.md"
CATALOGUE_FILE = "docs/architecture/capabilities.yaml"
REGISTER_FILE = "docs/migration/issue-register.yaml"
SPEC_SCHEMA = Path(__file__).with_name("spec.schema.json")
INDEX_SCHEMA = Path(__file__).with_name("index.schema.json")
PHASE = 2
"""The phase whose capabilities the specs must cover and the page indexes."""

_REQUIREMENT = re.compile(r"^- \*\*(?P<id>REQ-[1-9][0-9]*)\.\*\*")
_BLOCK_HEADING = re.compile(r"^### (?P<id>[A-Z]+-[1-9][0-9]*)\b")


class SpecError(Exception):
    """The specs have problems; the message lists them all."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Requirement:
    id: str
    line: int
    text: str
    """The requirement's paragraph: its bullet line and the lines that continue it."""


@dataclass(frozen=True)
class Spec:
    path: str
    """The spec file, relative to the repository."""
    front: dict[str, Any]
    body: list[str]
    body_line: int
    """The file line of body[0], so a body problem names its line."""

    @property
    def id(self) -> str:
        return self.front["spec"]

    @property
    def capabilities(self) -> list[str]:
        return self.front["capabilities"]

    @property
    def blocks(self) -> list[dict[str, Any]]:
        return self.front["blocks"]

    @property
    def closes(self) -> list[dict[str, Any]]:
        return self.front["issues"]["closes"]

    @property
    def defers(self) -> list[dict[str, Any]]:
        return self.front["issues"]["defers"]

    def requirements(self) -> list[Requirement]:
        """The body's REQ bullets, each with the lines up to the next bullet, heading or blank line."""
        found: list[Requirement] = []
        current: list[str] = []
        current_id = ""
        start = 0
        for offset, line in enumerate([*self.body, ""]):
            match = _REQUIREMENT.match(line)
            if current and (match or not line.strip() or line.startswith(("- ", "#"))):
                found.append(Requirement(current_id, start, " ".join(current)))
                current = []
            if match:
                current, current_id, start = [line], match["id"], self.body_line + offset
            elif current:
                current.append(line.strip())
        return found

    def block_sections(self) -> dict[str, list[str]]:
        """Each `### <block id>` section of the body: its lines up to the next heading of level 3 or above."""
        sections: dict[str, list[str]] = {}
        current: list[str] | None = None
        for line in self.body:
            if line.startswith(("# ", "## ", "### ")):
                match = _BLOCK_HEADING.match(line)
                current = sections.setdefault(match["id"], []) if match else None
                if current is not None:
                    current.append(line)
            elif current is not None:
                current.append(line)
        return sections


@dataclass(frozen=True)
class Index:
    specs: list[str]
    not_yet_specced: list[str]


@dataclass(frozen=True)
class Sources:
    """What the specs cite: the catalogue's capabilities and open questions, and the register's entries."""

    capabilities: dict[str, dict[str, Any]]
    questions: dict[str, dict[str, Any]]
    issues: dict[str, dict[str, Any]]
    rules: set[str]

    def phase_capabilities(self) -> list[str]:
        return [key for key, item in self.capabilities.items() if item.get("phase") == PHASE]

    def phase_issues(self) -> list[str]:
        return [
            key
            for key, item in self.issues.items()
            if (item.get("benchhand_next") or {}).get("phase") == PHASE
        ]


def split_front_matter(text: str, where: str) -> tuple[Any, list[str], int]:
    """The parsed YAML between the leading `---` lines, the body lines after them, and the body's first line."""
    lines = text.splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        raise SpecError([f"{where}: no YAML front matter between --- lines at the top of the file"])
    end = lines.index("---", 1)
    try:
        front = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as error:
        raise SpecError([f"{where}: front matter is not valid YAML: {error}"]) from error
    return front, lines[end + 1 :], end + 2


def _schema_problems(data: Any, schema_file: Path, where: str) -> list[str]:
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    return [
        f"{where}: front matter /{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
        for error in sorted(validator.iter_errors(data), key=lambda error: list(error.absolute_path))
    ]


def load_index(repo_root: Path) -> Index:
    front, _, _ = split_front_matter((repo_root / INDEX_FILE).read_text(encoding="utf-8"), INDEX_FILE)
    problems = _schema_problems(front, INDEX_SCHEMA, INDEX_FILE)
    if problems:
        raise SpecError(problems)
    return Index(front["specs"], front["not_yet_specced"])


def load_spec(repo_root: Path, spec_id: str) -> Spec:
    path = f"{SPECS_DIR}/{spec_id}.md"
    if not (repo_root / path).is_file():
        raise SpecError([f"{INDEX_FILE}: lists spec {spec_id}, but {path} doesn't exist"])
    front, body, body_line = split_front_matter((repo_root / path).read_text(encoding="utf-8"), path)
    problems = _schema_problems(front, SPEC_SCHEMA, path)
    if problems:
        raise SpecError(problems)
    return Spec(path, front, body, body_line)


def load_specs(repo_root: Path, index: Index) -> list[Spec]:
    """Every spec the index lists, in its order; every schema problem of every spec is reported at once."""
    specs: list[Spec] = []
    problems: list[str] = []
    for spec_id in index.specs:
        try:
            specs.append(load_spec(repo_root, spec_id))
        except SpecError as error:
            problems += error.problems
    if problems:
        raise SpecError(problems)
    return specs


def load_sources(repo_root: Path) -> Sources:
    catalogue = yaml.safe_load((repo_root / CATALOGUE_FILE).read_text(encoding="utf-8"))
    register = yaml.safe_load((repo_root / REGISTER_FILE).read_text(encoding="utf-8"))
    return Sources(
        capabilities={item["id"]: item for item in catalogue["capabilities"]},
        questions={item["id"]: item for item in catalogue["open_questions"]},
        issues={item["id"]: item for item in register["issues"]},
        rules={item["id"] for item in register["design_rules"]},
    )
