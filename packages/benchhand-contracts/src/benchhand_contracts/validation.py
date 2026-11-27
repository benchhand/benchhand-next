# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

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
        """Where the failing keyword is, after following every ``$ref``: the ``$id`` of the schema that
        holds it and a JSON pointer, such as ``…/record/common.schema.json#/$defs/revision/pattern``.
        ``""`` for a NaN or Infinity."""
        self.message = message


class UnknownSchemaError(LookupError):
    """No packaged contract has this schema id, or its fragment doesn't resolve."""


def validate(schema_id: str, instance: Any) -> None:
    """Raise :class:`ContractViolation` unless ``instance`` matches the schema at ``schema_id``."""
    found = violations(schema_id, instance)
    if found:
        raise found[0]


def violations(schema_id: str, instance: Any) -> list[ContractViolation]:
    """Every way ``instance`` breaks the schema at ``schema_id``, the most relevant first; ``[]`` if none.

    A NaN or Infinity is the only violation reported, since the schema can't judge one."""
    validator = _validator(schema_id)
    pointer = _non_finite_number(instance)
    if pointer is not None:
        return [ContractViolation(schema_id, pointer, "", "NaN and Infinity are not JSON numbers")]
    errors = list(validator.iter_errors(instance))
    if not errors:
        return []
    first = best_match(errors)
    rest = [best_match([error]) for error in errors]
    rest.sort(key=lambda error: _pointer(error.absolute_path))
    found: dict[tuple[str, str, str], ContractViolation] = {}
    for error in [first, *rest]:  # best_match of a oneOf error and of its own best branch can agree
        violation = _violation(schema_id, error)
        found.setdefault((violation.pointer, violation.schema_path, violation.message), violation)
    return list(found.values())


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
        schema_path=_keyword_location(error),
        message=error.message,
    )


def _keyword_location(error: ValidationError) -> str:
    """The ``$id`` and JSON pointer of the failing keyword. jsonschema leaves ``$ref`` out of an error's
    schema path, so the subschema that failed is found by identity among the loaded contracts."""
    location = _schema_locations().get(id(error.schema))
    if location is None or not isinstance(error.validator, str):
        return ""
    return location + _pointer([error.validator])


@cache
def _schema_locations() -> dict[int, str]:
    """``id()`` of every subschema of the packaged contracts -> its ``$id#pointer``."""
    locations: dict[int, str] = {}
    for uri in _registry():
        _index_schema(_registry().contents(uri), f"{uri}#", locations)
    return locations


def _index_schema(node: Any, location: str, locations: dict[int, str]) -> None:
    if isinstance(node, dict):
        locations[id(node)] = location
        children: Iterable[tuple[str | int, Any]] = node.items()
    elif isinstance(node, list):
        children = enumerate(node)
    else:
        return
    for key, child in children:
        _index_schema(child, location + _pointer([key]), locations)


def _pointer(parts: Iterable[str | int]) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)
