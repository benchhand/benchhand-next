"""Every contract is a valid JSON Schema 2020-12, every $ref resolves, and every example validates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"
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
    validator = Draft202012Validator(doc, registry=_registry())
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
