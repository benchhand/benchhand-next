# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Loading the catalogue: the YAML file, validated against capabilities.schema.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import yaml

SCHEMA_FILE = Path(__file__).with_name("capabilities.schema.json")
PHASE_OPEN = "no phase"
"""How a null phase is shown."""


class CatalogueError(Exception):
    """The catalogue has problems; the message lists them all."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Catalogue:
    """The catalogue's lists, as the schema shapes them, with the indexes the checks and the page use."""

    data: dict[str, Any]

    @property
    def capabilities(self) -> list[dict[str, Any]]:
        return self.data["capabilities"]

    @property
    def tools(self) -> list[dict[str, Any]]:
        return self.data["tools"]

    @property
    def cli(self) -> list[dict[str, Any]]:
        return self.data["cli"]

    @property
    def prototype_commands(self) -> list[dict[str, Any]]:
        return self.data["prototype_commands"]

    @property
    def open_questions(self) -> list[dict[str, Any]]:
        return self.data["open_questions"]

    def capability(self, capability_id: str) -> dict[str, Any]:
        return next(item for item in self.capabilities if item["id"] == capability_id)

    def tools_of(self, capability_id: str) -> list[dict[str, Any]]:
        return [tool for tool in self.tools if tool["capability"] == capability_id]

    def cli_of(self, capability_id: str) -> list[dict[str, Any]]:
        return [command for command in self.cli if command["capability"] == capability_id]


def load_catalogue(path: Path) -> Catalogue:
    """Read ``path`` and validate it against the schema; every schema violation is reported at once."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise CatalogueError([f"{path}: not valid YAML: {error}"]) from error
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    problems = [
        f"{path}: /{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
        for error in sorted(validator.iter_errors(data), key=lambda error: list(error.absolute_path))
    ]
    if problems:
        raise CatalogueError(problems)
    return Catalogue(data)


def phase_label(phase: int | None) -> str:
    return PHASE_OPEN if phase is None else f"P{phase}"
