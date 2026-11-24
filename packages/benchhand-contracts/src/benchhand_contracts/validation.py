"""Runtime validation against the packaged contracts (ADR-0017).

Schema ids are the ``$id`` of a contract, optionally with a JSON pointer fragment into it, e.g.
``https://benchhand.github.io/benchhand/contracts/provider/protocol.schema.json#/$defs/InitializeParams``.

The Python and the generated TypeScript (Ajv) validators agree: ``format`` is an annotation in both,
``pattern`` is an ECMAScript regular expression in both, and NaN and Infinity are never valid numbers.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Iterator
from functools import cache
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any

import regress
from jsonschema import Draft202012Validator, validators
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
    validator = _validator(schema_id)
    pointer = _non_finite_number(instance)
    if pointer is not None:
        raise ContractViolation(schema_id, pointer, "", "NaN and Infinity are not JSON numbers")
    error = best_match(validator.iter_errors(instance))
    if error is not None:
        raise _violation(schema_id, error)


@cache
def _ecmascript_regex(pattern: str) -> regress.Regex:
    # Ajv compiles patterns with the "u" flag.
    return regress.Regex(pattern, "u")


def _pattern(
    validator: Any, pattern: str, instance: Any, _schema: dict[str, Any]
) -> Iterator[ValidationError]:
    # Python's re lets ``$`` match before a trailing newline, so "kernel\n" would match ^[a-z]+$.
    if validator.is_type(instance, "string") and _ecmascript_regex(pattern).find(instance) is None:
        yield ValidationError(f"{instance!r} does not match {pattern!r}")


def _pattern_properties(
    validator: Any, patterns: dict[str, Any], instance: Any, _schema: dict[str, Any]
) -> Iterator[ValidationError]:
    if not validator.is_type(instance, "object"):
        return
    for pattern, subschema in patterns.items():
        for name, value in instance.items():
            if _ecmascript_regex(pattern).find(name) is not None:
                yield from validator.descend(value, subschema, path=name, schema_path=pattern)


ContractValidator = validators.extend(
    Draft202012Validator, {"pattern": _pattern, "patternProperties": _pattern_properties}
)
"""JSON Schema 2020-12 with ECMAScript regular expressions, as the TypeScript validators use."""


@cache
def _validator(schema_id: str) -> Any:
    registry = _registry()
    try:
        registry.resolver().lookup(schema_id)
    except Unresolvable as error:
        raise UnknownSchemaError(schema_id) from error
    return ContractValidator({"$ref": schema_id}, registry=registry)


def _non_finite_number(value: Any, pointer: str = "") -> str | None:
    """The pointer to the first NaN or infinity in ``value``: Python's json accepts them, JSON doesn't."""
    if isinstance(value, float) and not math.isfinite(value):
        return pointer
    children: Iterable[tuple[str | int, Any]] = ()
    if isinstance(value, dict):
        children = value.items()
    elif isinstance(value, list):
        children = enumerate(value)
    for key, child in children:
        found = _non_finite_number(child, pointer + _pointer([key]))
        if found is not None:
            return found
    return None


@cache
def _registry() -> Registry:
    root = files("benchhand_contracts") / "schemas"
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
