"""The record contracts (contracts/record/*.schema.json) and validation against them.

Until the codegen lane lands, the schemas are read from the repository's contracts/ directory.
"""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError, best_match
from referencing import Registry, Resource

from benchhand_core.record.finding import pointer

MESSAGE_LIMIT = 300


@dataclass(frozen=True)
class SchemaViolation:
    """One place a document breaks its contract: a JSON Pointer into the document and into the schema."""

    pointer: str
    schema_path: str
    message: str


def contracts_root() -> Path:
    """The contracts/ directory that holds record/ and common/."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "contracts"
        if (candidate / "record").is_dir():
            return candidate
    raise FileNotFoundError("no contracts/record directory above " + str(Path(__file__).resolve()))


@functools.cache
def _registry() -> Registry:
    resources = []
    for path in sorted(contracts_root().rglob("*.schema.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        resources.append((document["$id"], Resource.from_contents(document)))
    return Registry().with_resources(resources)


@functools.cache
def schema(contract: str) -> dict[str, Any]:
    """The schema of a record contract, by file stem: `product`, `bom-row`, `decision`…"""
    path = contracts_root() / "record" / f"{contract}.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


@functools.cache
def _validator(contract: str) -> Draft202012Validator:
    return Draft202012Validator(schema(contract), registry=_registry())


def _clip(text: str) -> str:
    return text if len(text) <= MESSAGE_LIMIT else text[: MESSAGE_LIMIT - 1] + "…"


def _violation(contract: str, error: ValidationError) -> SchemaViolation:
    precise = best_match([error])
    return SchemaViolation(
        pointer=pointer(*precise.absolute_path),
        schema_path=f"{contract}.schema.json#{pointer(*precise.absolute_schema_path)}",
        message=_clip(precise.message),
    )


def violations(contract: str, instance: Any) -> tuple[SchemaViolation, ...]:
    """Every top-level violation of `contract` by `instance`, ordered by document pointer."""
    found = [_violation(contract, error) for error in _validator(contract).iter_errors(instance)]
    return tuple(sorted(found, key=lambda violation: (violation.pointer, violation.schema_path)))
