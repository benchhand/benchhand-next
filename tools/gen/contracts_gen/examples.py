"""Valid and invalid conformance fixtures from the ``examples`` in each contract (plan section 6a).

Each example at a schema root or in a ``$defs`` entry is a valid fixture. Each invalid fixture is a
valid example with one mutation applied. A mutation is kept only when the schema rejects the result,
so every invalid fixture is known to be invalid.
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
        cases = [_case(target, examples, registry) for target, examples in _targets(contract)]
        if not cases:
            continue
        document = {"$comment": f"{GENERATED_NOTICE} Source: {contract.source}", "cases": cases}
        path = out_dir / f"{contract.stem}{EXAMPLES_SUFFIX}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _targets(contract: Contract) -> Iterator[tuple[str, list[Any]]]:
    if contract.schema.get("examples"):
        yield contract.schema_id, contract.schema["examples"]
    for name, definition in contract.schema.get("$defs", {}).items():
        if isinstance(definition, dict) and definition.get("examples"):
            yield f"{contract.schema_id}#/$defs/{name}", definition["examples"]


def _case(schema_id: str, examples: list[Any], registry: Registry) -> dict[str, Any]:
    validator = ContractValidator({"$ref": schema_id}, registry=registry)
    invalid: list[dict[str, Any]] = []
    for index, example in enumerate(examples):
        if not validator.is_valid(example):
            raise ExampleError(f"{schema_id}: examples[{index}] doesn't validate")
        for fixture in _invalid_variants(example, validator):
            if all(fixture["instance"] != seen["instance"] for seen in invalid):
                invalid.append({"example": index, **fixture})
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


# Each mutation yields (JSON pointer of the change, mutated instance) candidates in a fixed order.
MUTATIONS: tuple[tuple[str, Callable[[Any], Iterator[tuple[str, Any]]]], ...] = (
    ("remove-property", _remove_property),
    ("add-unknown-property", _add_unknown_property),
    ("wrong-type", _wrong_type),
)
