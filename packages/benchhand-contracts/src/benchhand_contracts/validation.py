"""Runtime validation against the packaged contracts (ADR-0017).

Schema ids are the ``$id`` of a contract, optionally with a JSON pointer fragment into it, e.g.
``https://benchhand.github.io/benchhand/contracts/provider/protocol.schema.json#/$defs/InitializeParams``.
``format`` is an annotation, as in the generated TypeScript validators.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from functools import cache
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError, best_match
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable

SCHEMA_SUFFIX = ".schema.json"


class ContractViolation(ValueError):
    """An instance doesn't match its contract."""

    def __init__(self, schema_id: str, pointer: str, schema_path: str, message: str) -> None:
        super().__init__(f"{schema_id}: {pointer or '/'}: {message}")
        self.schema_id = schema_id
        self.pointer = pointer
        """JSON pointer (RFC 6901) to the offending value in the instance; ``""`` is the whole instance."""
        self.schema_path = schema_path
        """Keyword path from the schema at ``schema_id`` to the failing keyword, through any ``$ref``."""
        self.message = message


class UnknownSchemaError(LookupError):
    """No packaged contract has this schema id, or its fragment doesn't resolve."""


def validate(schema_id: str, instance: Any) -> None:
    """Raise :class:`ContractViolation` unless ``instance`` matches the schema at ``schema_id``."""
    error = best_match(_validator(schema_id).iter_errors(instance))
    if error is not None:
        raise _violation(schema_id, error)


@cache
def _validator(schema_id: str) -> Draft202012Validator:
    registry = _registry()
    try:
        registry.resolver().lookup(schema_id)
    except Unresolvable as error:
        raise UnknownSchemaError(schema_id) from error
    return Draft202012Validator({"$ref": schema_id}, registry=registry)


@cache
def _registry() -> Registry:
    root = files("benchhand_contracts") / "_generated" / "schemas"
    resources = []
    for path in _schema_files(root):
        contents = json.loads(path.read_text(encoding="utf-8"))
        resources.append((contents["$id"], Resource.from_contents(contents)))
    return Registry().with_resources(resources)


def _schema_files(directory: Traversable) -> Iterable[Traversable]:
    for entry in directory.iterdir():
        if entry.is_dir():
            yield from _schema_files(entry)
        elif entry.name.endswith(SCHEMA_SUFFIX):
            yield entry


def _violation(schema_id: str, error: ValidationError) -> ContractViolation:
    return ContractViolation(
        schema_id=schema_id,
        pointer=_pointer(error.absolute_path),
        schema_path=_pointer(error.absolute_schema_path),
        message=error.message,
    )


def _pointer(parts: Iterable[str | int]) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)
