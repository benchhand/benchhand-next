"""Every published contract is a valid JSON Schema 2020-12, every $ref resolves, and every example validates.

The published schemas are generated from contracts/*.tsp into the benchhand_contracts package (ADR-0017)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any

import pytest
import regress
from benchhand_contracts.validation import ContractValidator
from jsonschema import Draft202012Validator
from pydantic import Field, TypeAdapter
from referencing import Registry, Resource

CONTRACTS = (
    Path(__file__).resolve().parents[1] / "packages/benchhand-contracts/src/benchhand_contracts/schemas"
)
SCHEMAS = sorted(CONTRACTS.rglob("*.schema.json"))


def _registry() -> Registry:
    resources = []
    for path in SCHEMAS:
        doc = json.loads(path.read_text())
        resources.append((doc["$id"], Resource.from_contents(doc)))
    return Registry().with_resources(resources)


@pytest.mark.parametrize("path", SCHEMAS, ids=lambda p: str(p.relative_to(CONTRACTS)))
def test_schema_is_valid_and_versioned(path: Path) -> None:
    doc = json.loads(path.read_text())
    Draft202012Validator.check_schema(doc)
    assert doc["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert doc["$id"].endswith(str(path.relative_to(CONTRACTS)))
    assert "x-version" in doc


@pytest.mark.parametrize("path", SCHEMAS, ids=lambda p: str(p.relative_to(CONTRACTS)))
def test_examples_validate(path: Path) -> None:
    doc = json.loads(path.read_text())
    validator = ContractValidator(doc, registry=_registry())
    assert doc.get("examples"), "each contract carries at least one example"
    for example in doc["examples"]:
        validator.validate(example)


@pytest.mark.parametrize("path", SCHEMAS, ids=lambda p: str(p.relative_to(CONTRACTS)))
def test_every_def_resolves(path: Path) -> None:
    doc = json.loads(path.read_text())
    registry = _registry()
    for name in doc.get("$defs", {}):
        resolver = registry.resolver(base_uri=doc["$id"])
        resolver.lookup(f"#/$defs/{name}")


def test_every_protocol_message_shape_has_examples() -> None:
    """Each object shape gets valid and invalid conformance fixtures from its examples, which the
    TypeScript validators are checked against; a $def that is only a $ref is covered by its target."""
    doc = json.loads((CONTRACTS / "provider" / "protocol.schema.json").read_text())
    missing = [
        name
        for name, definition in doc["$defs"].items()
        if definition.get("type") == "object" and not definition.get("examples")
    ]
    assert missing == []


# --- portable patterns (docs/contract/versioning.md) -------------------------------------------------------

_SYNTAX_ESCAPES = frozenset("^$\\.*+?()[]{}|/") | frozenset("nrtfv")
_QUANTIFIER = re.compile(r"\{[0-9]+(,[0-9]*)?\}")
_CODE_POINT = re.compile(r"u[0-9A-Fa-f]{4}")


def _escape_end(pattern: str, start: int, in_class: bool) -> int:
    """The index after the escape at `start`, or ValueError for one the engines read differently."""
    escaped = pattern[start + 1 : start + 2]
    if escaped in _SYNTAX_ESCAPES or (in_class and escaped == "-"):
        return start + 2
    if _CODE_POINT.match(pattern, start + 1):
        return start + 6
    raise ValueError(f"escape \\{escaped} at {start}")


def _class_end(pattern: str, start: int) -> int:
    index = start + 2 if pattern.startswith("[^", start) else start + 1
    first = index
    while index < len(pattern) and pattern[index] != "]":
        if pattern[index] == "\\":
            index = _escape_end(pattern, index, in_class=True)
        elif pattern[index] == "[" or pattern[index : index + 2] in ("&&", "--", "~~"):
            raise ValueError(f"class set syntax {pattern[index : index + 2]!r} at {index}")
        else:
            index += 1
    if index == first or index == len(pattern):
        raise ValueError(f"empty or unterminated class at {start}")
    return index + 1


def portable_pattern_problem(pattern: str) -> str | None:
    """Why `pattern` is outside the portable dialect, or None: it means the same in ECMAScript with the u flag
    (Ajv, regress) and in the Rust regex engine pydantic uses for the generated models."""
    index = 0
    try:
        while index < len(pattern):
            char = pattern[index]
            if char == "\\":
                index = _escape_end(pattern, index, in_class=False)
            elif char == "[":
                index = _class_end(pattern, index)
            elif char == "(" and pattern.startswith("(?", index):
                if not pattern.startswith("(?:", index):
                    raise ValueError(f"group {pattern[index : index + 3]!r} at {index}")
                index += 3
            elif char == "{":
                quantifier = _QUANTIFIER.match(pattern, index)
                if quantifier is None:
                    raise ValueError(f"unescaped {{ at {index}")
                index = quantifier.end()
            elif char in ".}]":
                raise ValueError(f"unescaped {char} at {index}")
            else:
                index += 1
    except ValueError as error:
        return str(error)
    return None


def _patterns(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        if isinstance(node.get("pattern"), str):
            yield node["pattern"]
        yield from node.get("patternProperties", {})
        children = node.values()
    elif isinstance(node, list):
        children = node
    else:
        return
    for child in children:
        yield from _patterns(child)


@pytest.mark.parametrize("path", SCHEMAS, ids=lambda p: str(p.relative_to(CONTRACTS)))
def test_every_pattern_is_in_the_portable_dialect(path: Path) -> None:
    for pattern in _patterns(json.loads(path.read_text())):
        assert portable_pattern_problem(pattern) is None, (pattern, portable_pattern_problem(pattern))
        regress.Regex(pattern, "u")
        TypeAdapter(Annotated[str, Field(pattern=pattern)])  # compiles on pydantic's Rust regex engine


@pytest.mark.parametrize(
    "pattern", [r"^\S+$", r"^a.b$", r"^(?!/).+$", r"^(?<n>a)$", r"^[a[b]]$", r"^\-$", r"^a{$", r"^[]$"]
)
def test_a_pattern_the_engines_read_differently_is_outside_the_dialect(pattern: str) -> None:
    assert portable_pattern_problem(pattern) is not None
