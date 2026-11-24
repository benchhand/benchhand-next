"""Valid and invalid conformance fixtures from the ``examples`` in each contract (plan section 6a).

Each example at a schema root or in a ``$defs`` entry is a valid fixture. Each invalid fixture is a
valid example with one mutation applied. A mutation is kept only when the schema rejects the result,
so every invalid fixture is known to be invalid, and every fixture case has at least one. An
``examples`` block anywhere else in a schema isn't a fixture, but it must validate too.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from benchhand_contracts.validation import ContractValidator
from referencing import Registry, Resource

from .sources import GENERATED_NOTICE, Contract

EXAMPLES_SUFFIX = ".examples.json"
UNKNOWN_PROPERTY = "x-conformance-unknown"
SCHEMA_MAPS = ("properties", "patternProperties", "$defs", "dependentSchemas")
DATA_KEYWORDS = ("const", "enum", "examples", "default", "required", "dependentRequired")
NON_VALIDATING = frozenset(
    ("$schema", "$id", "$defs", "$comment", "title", "description", "examples", "default", "deprecated")
    + ("readOnly", "writeOnly", "format")
)


class ExampleError(Exception):
    """An ``examples`` entry doesn't validate against its own schema."""


def contract_registry(contracts: list[Contract]) -> Registry:
    return Registry().with_resources(
        (contract.schema_id, Resource.from_contents(contract.schema)) for contract in contracts
    )


def write_examples(contracts: list[Contract], out_dir: Path) -> None:
    """Write ``<stem>.examples.json`` into ``out_dir`` for each contract that has examples."""
    registry = contract_registry(contracts)
    for contract in contracts:
        cases = []
        for pointer, examples in _examples_blocks(contract.schema):
            schema_id = f"{contract.schema_id}#{pointer}" if pointer else contract.schema_id
            if _is_fixture_target(pointer):
                cases.append(_case(schema_id, examples, registry, _constrains(contract.schema, pointer)))
            else:
                _check_examples(schema_id, examples, _validator(schema_id, registry))
        if not cases:
            continue
        document = {"$comment": f"{GENERATED_NOTICE} Source: {contract.source}", "cases": cases}
        path = out_dir / f"{contract.stem}{EXAMPLES_SUFFIX}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _examples_blocks(node: Any, pointer: str = "") -> Iterator[tuple[str, list[Any]]]:
    """``(JSON pointer, examples)`` for every subschema of ``node`` that has an ``examples`` list."""
    if isinstance(node, list):
        for index, item in enumerate(node):
            yield from _examples_blocks(item, f"{pointer}/{index}")
        return
    if not isinstance(node, dict):
        return
    if isinstance(node.get("examples"), list) and node["examples"]:
        yield pointer, node["examples"]
    for key, value in node.items():
        if key in DATA_KEYWORDS or key.startswith("x-"):
            continue
        if key in SCHEMA_MAPS and isinstance(value, dict):
            for name, schema in value.items():
                yield from _examples_blocks(schema, f"{pointer}/{key}/{_escape(name)}")
        else:
            yield from _examples_blocks(value, f"{pointer}/{_escape(key)}")


def _is_fixture_target(pointer: str) -> bool:
    """The contract root or a ``$defs`` entry: the schemas with a TypeScript validator of their own."""
    parts = pointer.split("/")
    return pointer == "" or (len(parts) == 3 and parts[1] == "$defs")


def _validator(schema_id: str, registry: Registry) -> ContractValidator:
    return ContractValidator({"$ref": schema_id}, registry=registry)


def _check_examples(schema_id: str, examples: list[Any], validator: ContractValidator) -> None:
    for index, example in enumerate(examples):
        if not validator.is_valid(example):
            raise ExampleError(f"{schema_id}: examples[{index}] doesn't validate")


def _constrains(schema: dict[str, Any], pointer: str) -> bool:
    """Whether the fixture target has a validation keyword, so that some instance must fail it."""
    target = schema if pointer == "" else schema["$defs"][_unescape(pointer.split("/")[2])]
    if not isinstance(target, dict):
        return target is False
    return any(key not in NON_VALIDATING and not key.startswith("x-") for key in target)


def _case(schema_id: str, examples: list[Any], registry: Registry, constrained: bool) -> dict[str, Any]:
    validator = _validator(schema_id, registry)
    _check_examples(schema_id, examples, validator)
    invalid: list[dict[str, Any]] = []
    for index, example in enumerate(examples):
        for fixture in _invalid_variants(example, validator):
            if all(fixture["instance"] != seen["instance"] for seen in invalid):
                invalid.append({"example": index, **fixture})
    if constrained and not invalid:
        raise ExampleError(
            f"{schema_id}: no mutation of its examples is rejected, so it has no invalid fixture"
        )
    return {"schema_id": schema_id, "valid": examples, "invalid": invalid}


def _invalid_variants(example: Any, validator: ContractValidator) -> Iterator[dict[str, Any]]:
    """At most one fixture per mutation kind: the first candidate the schema rejects."""
    for name, mutation in MUTATIONS:
        for pointer, instance in mutation(example):
            if not validator.is_valid(instance):
                yield {"mutation": name, "pointer": pointer, "instance": instance}
                break


def _remove_property(example: Any) -> Iterator[tuple[str, Any]]:
    if isinstance(example, dict):
        for key in example:
            yield f"/{_escape(key)}", {k: v for k, v in example.items() if k != key}


def _add_unknown_property(example: Any) -> Iterator[tuple[str, Any]]:
    if isinstance(example, dict) and UNKNOWN_PROPERTY not in example:
        yield f"/{UNKNOWN_PROPERTY}", {**example, UNKNOWN_PROPERTY: True}


def _wrong_type(example: Any) -> Iterator[tuple[str, Any]]:
    if isinstance(example, dict):
        for key, value in example.items():
            mutated = copy.deepcopy(example)
            mutated[key] = _other_type(value)
            yield f"/{_escape(key)}", mutated
    yield "", _other_type(example)


def _other_type(value: Any) -> Any:
    """A value of a different JSON type than ``value``."""
    if isinstance(value, str):
        return 12345
    if isinstance(value, bool):
        return "not-a-boolean"
    if isinstance(value, int | float):
        return "not-a-number"
    if value is None:
        return "not-null"
    if isinstance(value, list):
        return {"not": "an-array"}
    return ["not-an-object"]


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


# Each mutation yields (JSON pointer of the change, mutated instance) candidates in a fixed order.
MUTATIONS: tuple[tuple[str, Callable[[Any], Iterator[tuple[str, Any]]]], ...] = (
    ("remove-property", _remove_property),
    ("add-unknown-property", _add_unknown_property),
    ("wrong-type", _wrong_type),
)
